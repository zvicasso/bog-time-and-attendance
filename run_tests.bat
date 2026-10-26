@echo off
REM Install test tools (first run only) and run the automated tests.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -q -r requirements-dev.txt
".venv\Scripts\python.exe" -m pytest -v
pause
