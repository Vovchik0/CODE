@echo off
REM update.bat -- обновить установленную копию из git (Windows).
setlocal
cd /d "%~dp0"

if not exist ".git" (
  echo Это не git-репозиторий -- обновление через git недоступно.
  echo Переустановите: git clone ... и install.bat
  exit /b 1
)

echo ==^> Получаю обновления (git pull --ff-only)
git pull --ff-only

if exist ".venv" (
  call .venv\Scripts\activate.bat
  echo ==^> Обновляю зависимости
  pip install -e . >nul
)

echo ==^> Готово.
endlocal
