@echo off
cd /d "%~dp0.."
if not exist "venv\Scripts\python.exe" (
    echo venv not found -- run windows\setup.bat first.
    pause
    exit /b 1
)
echo Starting Brad's Agent Stack Creator...
echo Closing this window will stop the dashboard. The session daemon
echo (your Claude Code sessions) keeps running independently of it.
echo.
venv\Scripts\python app.py
pause
