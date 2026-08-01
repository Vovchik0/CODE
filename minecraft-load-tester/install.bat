@echo off
REM install.bat -- установщик Minecraft Load Tester для Windows.
REM Создаёт .venv, устанавливает приложение и лаунчеры run-web.bat / run-gui.bat.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py") else (set "PY=python")

echo ==^> Создаю виртуальное окружение (.venv)
%PY% -m venv .venv
if errorlevel 1 (
  echo ОШИБКА: Python 3 не найден. Установите с https://www.python.org/
  exit /b 1
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul

echo ==^> Устанавливаю приложение
pip install -e ".[gui]"
if errorlevel 1 (
  echo PyQt5 не установился -- ставлю только веб-версию.
  pip install -e .
)

> run-web.bat echo @echo off
>> run-web.bat echo cd /d "%%~dp0"
>> run-web.bat echo .venv\Scripts\mc-load-tester-web %%*
> run-gui.bat echo @echo off
>> run-gui.bat echo cd /d "%%~dp0"
>> run-gui.bat echo .venv\Scripts\mc-load-tester %%*

echo.
echo ================================================================
echo  Готово!
echo    Веб (для телефона):  run-web.bat
echo    Десктопный GUI:      run-gui.bat
echo    Обновить позже:      update.bat
echo ================================================================
endlocal
