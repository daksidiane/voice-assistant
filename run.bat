@echo off
rem =========================================================
rem  SPUTNIK Voice Assistant - Launch Script
rem =========================================================
setlocal

if not exist .venv goto NO_VENV

set PYTHONIOENCODING=utf-8

echo =========================================================
echo  [SPUTNIK] Voice Assistant is starting...
echo  - Control Panel window is active.
echo  - Tray icon is active in the Windows notification area.
echo  - Emergency hotkey: Right Shift + Enter
echo =========================================================
echo.

.venv\Scripts\python.exe main.py %*
if errorlevel 1 goto RUN_ERROR
goto END_OK

:NO_VENV
echo.
echo [ERROR] Virtual environment (.venv) not found!
echo Please run install.bat first to set up the environment.
echo.
pause
exit /b 1

:RUN_ERROR
echo.
echo [ERROR] SPUTNIK process terminated with an error.
echo Check sputnik.log for details.
echo.
pause
exit /b 1

:END_OK
echo.
echo [SPUTNIK] Assistant execution finished. Press any key to close this window.
pause
endlocal
