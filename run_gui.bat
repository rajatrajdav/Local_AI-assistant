@echo off
cd /d "%~dp0"
echo Starting J.A.R.V.I.S Desktop GUI...

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" jarvis_gui.py
    goto :eof
)
where python >nul 2>nul
if %errorlevel%==0 (
    python jarvis_gui.py
) else (
    echo Python not found on PATH. Trying py launcher...
    py jarvis_gui.py
)
pause