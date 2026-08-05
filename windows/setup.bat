@echo off
cd /d "%~dp0.."
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
echo Setup complete. Run windows\start.bat to launch the dashboard.
pause
