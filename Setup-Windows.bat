@echo off
setlocal
cd /d "%~dp0"
echo Pencil Video Studio - setup Python 3.12 x64
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo Please install Python 3.12 x64 from https://www.python.org/downloads/windows/
  echo Include the Python launcher and Tcl/Tk during installation.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" model_assets.py
if errorlevel 1 goto fail
echo Setup complete. Open Start-Windows.bat to use the application.
pause
exit /b 0
:fail
echo Setup failed. See the error above. Check your internet connection and disk space.
pause
exit /b 1
