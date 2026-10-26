@echo off
REM ==========================================================================
REM  Time & Attendance Processor - one-time setup (Windows 11 / Server 2022)
REM  Creates a private Python environment in .venv and installs the libraries.
REM ==========================================================================
setlocal
cd /d "%~dp0"
echo.
echo  Time ^& Attendance Processor - setup
echo  ------------------------------------

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo  [X] Python was not found.
    echo      Install Python 3.12 or 3.13 from https://www.python.org/downloads/windows/
    echo      and tick "Add python.exe to PATH". On servers choose "Install for all users".
    goto :fail
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
    echo  [X] Python 3.11 or newer is required. Found:
    %PY% --version
    goto :fail
)
for /f "delims=" %%v in ('%PY% --version') do echo  [OK] %%v

if not exist ".venv\Scripts\python.exe" (
    echo  Creating virtual environment in .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)

set "VPY=.venv\Scripts\python.exe"
if exist "wheels\" (
    echo  Installing from the local wheels folder ^(offline mode^) ...
    "%VPY%" -m pip install --no-index --find-links wheels -r requirements.txt
) else (
    echo  Installing libraries from the internet ^(PyPI^) ...
    "%VPY%" -m pip install --upgrade pip >nul
    "%VPY%" -m pip install -r requirements.txt
)
if errorlevel 1 (
    echo  [X] Library installation failed. See README.md - Troubleshooting.
    goto :fail
)

if not exist "logs" mkdir logs
"%VPY%" -c "import tap, streamlit, pdfplumber, pypdfium2, pandas, openpyxl; print('  [OK] All components installed')"
if errorlevel 1 goto :fail

echo.
echo  Setup complete. Double-click start_app.bat to run the application.
echo.
pause
exit /b 0

:fail
echo.
echo  Setup did not complete.
pause
exit /b 1
