@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup-Windows.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" model_assets.py
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean PencilVideoStudio.spec
if errorlevel 1 goto fail
echo Build complete: dist\PencilVideoStudio\PencilVideoStudio.exe
echo Copy the WHOLE PencilVideoStudio folder, not just the exe.
pause
exit /b 0
:fail
echo Build failed. See errors above.
pause
exit /b 1
