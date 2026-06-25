@echo off
echo ====================================
echo  Building J.A.R.V.I.S. Application
echo ====================================
echo.

cd /d "%~dp0"

echo [1/2] Building React frontend...
cd jarvis_ui
call npm run build
if %errorlevel% neq 0 (
    echo Frontend build failed!
    pause
    exit /b 1
)
cd ..

echo [2/2] Building EXE with PyInstaller...
python build_exe.py
if %errorlevel% neq 0 (
    echo EXE build failed!
    pause
    exit /b 1
)

echo.
echo ====================================
echo  Build complete!
echo  Output: dist\JARVIS
echo ====================================
pause
