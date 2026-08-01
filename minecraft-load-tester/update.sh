#!/usr/bin/env bash
#
# update.sh -- обновить установленную копию из git и переустановить зависимости.
#
#   ./update.sh
#
# Безопасно: применяет только «перемотку» (--ff-only). Если были локальные
# правки, конфликтующие с обновлением, git об этом сообщит.

set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .git ]; then
  echo "Это не git-репозиторий -- обновление через git недоступно." >&2
  echo "Переустановите из GitHub: git clone ... и ./install.sh" >&2
  exit 1
fi

echo "==> Получаю обновления (git pull --ff-only)"
git pull --ff-only

if [ -d .venv ]; then
  echo "==> Обновляю зависимости"
  # shellcheck disable=SC1091
  . .venv/bin/activate
  pip install -e . >/dev/null
fi

echo "==> Готово. Текущая версия: $(git rev-parse --short HEAD)"
