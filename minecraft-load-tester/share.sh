#!/usr/bin/env bash
#
# share.sh
# ========
#
# Публичный доступ к Minecraft Load Tester с телефона из любой сети.
#
# Скрипт запускает локальный веб-сервер (web_server.py) и открывает к нему
# бесплатный HTTPS-туннель Cloudflare Quick Tunnel (регистрация не нужна).
# В консоли появится готовая ссылка вида
#   https://<случайное-имя>.trycloudflare.com/?token=<токен>
# которую можно открыть на телефоне откуда угодно.
#
# Если cloudflared не установлен, скрипт САМ скачает подходящий бинарник в
# папку ./.cloudflared/ (ничего ставить вручную не нужно) -- требуется лишь
# curl или wget и доступ в интернет.
#
# Через туннель и страница, и API отдаются с одного HTTPS-адреса, поэтому
# проблем с mixed-content и CORS нет.
#
# Использование:
#   ./share.sh                       # порт 8000, токен сгенерируется автоматически
#   PORT=8080 ./share.sh             # другой порт
#   TOKEN=мой_секрет ./share.sh      # свой токен доступа
#
# Альтернатива без cloudflared -- ngrok (см. README, раздел про туннель).

set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8000}"
# Токен по умолчанию генерируется случайно -- без него публичной ссылкой смог бы
# воспользоваться любой, кто её узнает.
TOKEN="${TOKEN:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(9))')}"

CF_DIR="./.cloudflared"
CF=""   # путь к бинарнику cloudflared (заполняется resolve_cloudflared)


# --- Загрузка файла: curl или wget ------------------------------------------
fetch() {  # fetch <URL> <OUTPUT>
  local url="$1" out="$2"
  echo "Скачиваю cloudflared: $url" >&2
  if command -v curl >/dev/null 2>&1; then
    curl -fSL --retry 3 -o "$out" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$out" "$url"
  else
    echo "Для автозагрузки нужен curl или wget." >&2
    return 1
  fi
}


# --- Автоматическая загрузка cloudflared под текущую ОС/архитектуру ----------
download_cloudflared() {
  local os arch base
  os="$(uname -s)"
  arch="$(uname -m)"

  case "$arch" in
    x86_64|amd64)          arch="amd64" ;;
    aarch64|arm64)         arch="arm64" ;;
    armv7l|armv6l|armhf|arm) arch="arm" ;;
    i686|i386)             arch="386" ;;
    *) echo "Неизвестная архитектура: $arch" >&2; return 1 ;;
  esac

  base="https://github.com/cloudflare/cloudflared/releases/latest/download"
  mkdir -p "$CF_DIR"

  case "$os" in
    Linux)
      fetch "$base/cloudflared-linux-$arch" "$CF_DIR/cloudflared" || return 1
      chmod +x "$CF_DIR/cloudflared"
      CF="$CF_DIR/cloudflared"
      ;;
    Darwin)
      # Для macOS релизы упакованы в .tgz.
      fetch "$base/cloudflared-darwin-$arch.tgz" "$CF_DIR/cf.tgz" || return 1
      tar -xzf "$CF_DIR/cf.tgz" -C "$CF_DIR"
      rm -f "$CF_DIR/cf.tgz"
      chmod +x "$CF_DIR/cloudflared"
      CF="$CF_DIR/cloudflared"
      ;;
    MINGW*|MSYS*|CYGWIN*)
      fetch "$base/cloudflared-windows-$arch.exe" "$CF_DIR/cloudflared.exe" || return 1
      CF="$CF_DIR/cloudflared.exe"
      ;;
    *)
      echo "Неизвестная ОС: $os" >&2
      return 1
      ;;
  esac
}


# --- Найти готовый cloudflared или загрузить его ----------------------------
resolve_cloudflared() {
  # 1) установлен в системе
  if command -v cloudflared >/dev/null 2>&1; then
    CF="$(command -v cloudflared)"
    return 0
  fi
  # 2) уже скачан ранее в ./.cloudflared/
  if [[ -x "$CF_DIR/cloudflared" ]]; then
    CF="$CF_DIR/cloudflared"
    return 0
  fi
  if [[ -x "$CF_DIR/cloudflared.exe" ]]; then
    CF="$CF_DIR/cloudflared.exe"
    return 0
  fi
  # 3) автозагрузка
  echo "cloudflared не найден -- пробую скачать автоматически..." >&2
  if download_cloudflared; then
    echo "cloudflared загружен: $CF" >&2
    return 0
  fi
  return 1
}


if ! resolve_cloudflared; then
  echo >&2
  echo "ОШИБКА: не удалось получить cloudflared автоматически." >&2
  echo "Установите его вручную (https://pkg.cloudflare.com/ или менеджером пакетов)" >&2
  echo "либо используйте ngrok:  ngrok http ${PORT}   (см. README)." >&2
  exit 1
fi

# 1) Запускаем веб-сервер только на localhost -- наружу его выставит туннель.
python3 web_server.py --host 127.0.0.1 --port "$PORT" --token "$TOKEN" &
SERVER_PID=$!

# Гарантированно гасим сервер при выходе/Ctrl+C.
cleanup() { kill "$SERVER_PID" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM

sleep 1
echo
echo "Токен доступа: ${TOKEN}"
echo "Запускаю Cloudflare-туннель, ждём публичную ссылку..."
echo

# 2) Открываем туннель и, поймав выданный URL, печатаем готовую ссылку с токеном.
"$CF" tunnel --url "http://127.0.0.1:${PORT}" 2>&1 | while IFS= read -r line; do
  echo "$line"
  if [[ "$line" =~ https://[a-zA-Z0-9.-]+\.trycloudflare\.com ]]; then
    url="${BASH_REMATCH[0]}"
    echo
    echo "==================================================================="
    echo " Открывайте на телефоне (из любой сети):"
    echo "   ${url}/?token=${TOKEN}"
    echo "==================================================================="
    echo
  fi
done
