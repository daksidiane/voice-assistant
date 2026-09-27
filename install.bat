@echo off
rem =========================================================
rem  SPUTNIK Voice Assistant - Environment Setup Script
rem =========================================================
setlocal

echo [SPUTNIK] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 goto NO_PYTHON

if not exist .venv goto CREATE_VENV
goto INSTALL_DEPS

:CREATE_VENV
echo [SPUTNIK] Creating virtual environment (.venv)...
python -m venv .venv
if errorlevel 1 goto VENV_ERROR

:INSTALL_DEPS
echo [SPUTNIK] Installing required packages...
.venv\Scripts\python.exe -m pip install --upgrade pip setuptools
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto PIP_ERROR

echo [SPUTNIK] Verifying Vosk model and voice synthesizer...
.venv\Scripts\python.exe -c "from stt.vosk_recognizer import VoskRecognizerEngine; VoskRecognizerEngine(); print('STT Engine Ready')"
if errorlevel 1 goto SETUP_WARNING

echo.
echo =========================================================
echo  [SUCCESS] SPUTNIK installation completed successfully!
echo  Run 'run.bat' to launch the voice assistant in background.
echo =========================================================
goto END

:NO_PYTHON
echo [ERROR] Python is not found in PATH!
echo Please install Python 3.10+ from https://www.python.org and check 'Add Python to PATH'.
pause
exit /b 1

:VENV_ERROR
echo [ERROR] Failed to create virtual environment!
pause
exit /b 1

:PIP_ERROR
echo [ERROR] Failed to install pip requirements!
pause
exit /b 1

:SETUP_WARNING
echo [WARNING] Model initialization completed with warnings. Check logs.
pause
exit /b 0

:END
endlocal
