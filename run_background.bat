@echo off
rem =========================================================
rem  SPUTNIK Voice Assistant - Silent Background Launch Script
rem =========================================================
setlocal

if not exist .venv goto NO_VENV

set PYTHONIOENCODING=utf-8

start "" .venv\Scripts\pythonw.exe main.py %*
goto END

:NO_VENV
echo [ERROR] Virtual environment not found! Run install.bat first.
pause
exit /b 1

:END
endlocal
