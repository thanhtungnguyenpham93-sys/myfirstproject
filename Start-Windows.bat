@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup-Windows.bat first, or use the portable Windows release.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" pencil_video_studio.py %*
if errorlevel 1 pause
