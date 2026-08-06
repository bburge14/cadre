@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0relocate.ps1"
if errorlevel 2 (
    REM Relocated to a stable location and re-launched setup from there --
    REM that copy is handling everything now, stop here.
    exit /b 0
)
if errorlevel 1 (
    echo Relocation failed -- see the error above.
    pause
    exit /b 1
)
echo Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo.
    echo Failed to create the virtual environment. Is Python installed and on PATH?
    pause
    exit /b 1
)
echo Installing dependencies...
venv\Scripts\pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo pip install failed -- see the error above.
    pause
    exit /b 1
)
echo.
echo Creating Desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0make-shortcut.ps1"
if errorlevel 1 (
    echo Could not create a Desktop shortcut automatically -- you can still run windows\start.bat directly.
)
echo.
echo Setup complete. Run windows\start.bat (or the Desktop shortcut) to launch the dashboard.
pause
