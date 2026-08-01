#!/usr/bin/env bash
#
# install.sh -- установщик Minecraft Load Tester (Linux / macOS / Termux).
#
# Создаёт изолированное окружение (.venv), устанавливает приложение и
# формирует удобные лаунчеры run-web.sh / run-gui.sh.
#
#   ./install.sh              # установка (с GUI, если PyQt5 поставится)
#   PYTHON=python3.12 ./install.sh
#
# Веб-версия работает всегда (только стандартная библиотека). GUI требует
# PyQt5 -- если он не собирается на вашей платформе, установщик продолжит без
# него, и останется рабочая веб-версия.

set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ОШИБКА: Python 3 не найден (задайте PYTHON=/путь/к/python3)." >&2
  exit 1
fi

echo "==> Создаю виртуальное окружение (.venv)"
"$PY" -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate

echo "==> Обновляю pip"
pip install --upgrade pip >/dev/null

echo "==> Устанавливаю приложение"
if pip install -e ".[gui]"; then
  echo "    Установлено вместе с десктопным GUI (PyQt5)."
else
  echo "    PyQt5 не установился -- ставлю только веб-версию (GUI будет недоступен)."
  pip install -e .
fi

# Удобные лаунчеры.
cat > run-web.sh <<'EOS'
#!/usr/bin/env bash
cd "$(dirname "$0")"
exec .venv/bin/mc-load-tester-web "$@"
EOS
cat > run-gui.sh <<'EOS'
#!/usr/bin/env bash
cd "$(dirname "$0")"
exec .venv/bin/mc-load-tester "$@"
EOS
chmod +x run-web.sh run-gui.sh

echo
echo "================================================================"
echo " Готово!"
echo "   Веб (для телефона):   ./run-web.sh"
echo "   Публичная ссылка:     ./share.sh"
echo "   Десктопный GUI:       ./run-gui.sh"
echo "   Обновить позже:       ./update.sh"
echo "================================================================"
