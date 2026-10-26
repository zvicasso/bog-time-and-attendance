@echo off
REM ==========================================================================
REM  Start the application without opening a browser (for Windows Server /
REM  scheduled task / service use). Address and port: .streamlit\config.toml
REM ==========================================================================
cd /d "%~dp0"
".venv\Scripts\python.exe" -m streamlit run app.py
