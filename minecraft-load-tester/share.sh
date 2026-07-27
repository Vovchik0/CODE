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
# Через туннель и страница, и API отдаются с одного HTTPS-адреса, поэтому
# проблем с mixed-content и CORS нет.
#
# Использование:
#   ./share.sh                       # порт 8000, токен сгенерируется автоматически
#   PORT=8080 ./share.sh             # другой порт
#   TOKEN=мой_секрет ./share.sh      # свой токен доступа
#
# Требуется установленный cloudflared:
#   Linux (deb) : https://pkg.cloudflare.com/  (пакет cloudflared)
#   macOS       : brew install cloudflared
#   Windows     : winget install --id Cloudflare.cloudflared
#   Termux      : pkg install cloudflared   (или скачайте arm64-бинарник)
#
# Альтернатива без cloudflared -- ngrok (см. README, раздел про туннель).

set -euo pipefail

PORT="${PORT:-8000}"
# Токен по умолчанию генерируется случайно -- без него публичной ссылкой смог бы
# воспользоваться любой, кто её узнает.
TOKEN="${TOKEN:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(9))')}"

cd "$(dirname "$0")"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "ОШИБКА: не найден cloudflared." >&2
  echo "Установите его (см. комментарий в начале share.sh) и запустите снова." >&2
  echo "Либо используйте ngrok: ngrok http ${PORT}  (см. README)." >&2
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
cloudflared tunnel --url "http://127.0.0.1:${PORT}" 2>&1 | while IFS= read -r line; do
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
