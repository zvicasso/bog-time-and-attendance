@echo off
REM ==========================================================================
REM  Start the Time & Attendance Processor and open it in the default browser.
REM  Keep this window open while using the app; close it to stop the app.
REM ==========================================================================
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo The application is not installed yet. Run setup.bat first.
    pause
    exit /b 1
)
for /f "delims=" %%u in ('".venv\Scripts\python.exe" -m tap.urlinfo') do set "APPURL=%%u"
echo.
echo  Time ^& Attendance Processor
echo  Open in your browser: %APPURL%
echo  Close this window to stop the application.
echo.
REM open the browser a few seconds after the server starts
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start "" %APPURL%"
".venv\Scripts\python.exe" -m streamlit run app.py
if errorlevel 1 (
    echo.
    echo  The application stopped with an error. See logs\app.log and README.md - Troubleshooting.
    pause
)
