"""
Build Script for J.A.R.V.I.S. Desktop Application
==================================================
This script uses PyInstaller to create a standalone .exe file
that includes both the Python backend and the React frontend.

Usage:
    python build_exe.py

This will produce a 'JARVIS' folder in the 'dist' directory containing
the complete application, plus a JARVIS.exe launcher.
"""

import os
import sys
import shutil
import subprocess
import platform

# Configuration
APP_NAME = "JARVIS"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")
BUILD_DIR = os.path.join(BASE_DIR, "build")
VOICES_DIR = os.path.join(BASE_DIR, "voices")
DOTENV_FILE = os.path.join(BASE_DIR, ".env")


def build_pyinstaller():
    """Run PyInstaller to create the executable."""
    print("=" * 60)
    print(f"  Building {APP_NAME} Application with PyInstaller")
    print("=" * 60)

    # Clean previous builds
    for dir_path in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(dir_path):
            print(f"  Cleaning: {dir_path}")
            shutil.rmtree(dir_path)

    # Build command for PyInstaller
    main_script = os.path.join(BASE_DIR, "main.py")
    icon_path = None  # Add icon path if you have one

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",  # One folder for easier debugging
        "--console",  # Console mode (no GUI)
        "--add-data", f"{BASE_DIR}/api_server.py{os.pathsep}.",
        "--add-data", f"{BASE_DIR}/jarvis.py{os.pathsep}.",
        "--add-data", f"{BASE_DIR}/professional_presentation.py{os.pathsep}.",
        "--add-data", f"{BASE_DIR}/creative_presentation.py{os.pathsep}.",
        "--add-data", f"{BASE_DIR}/pexels_integration.py{os.pathsep}.",
        "--add-data", f"{BASE_DIR}/voice_assistant.py{os.pathsep}.",
        "--add-data", f"{BASE_DIR}/.env{os.pathsep}.",
        "--add-data", f"{VOICES_DIR}{os.pathsep}voices",
        "--hidden-import", "groq",
        "--hidden-import", "flask",
        "--hidden-import", "flask_cors",
        "--hidden-import", "dotenv",
        "--hidden-import", "psutil",
        "--hidden-import", "pyperclip",
        "--hidden-import", "jarvis",
        "--hidden-import", "api_server",
        "--hidden-import", "professional_presentation",
        "--hidden-import", "creative_presentation",
        "--hidden-import", "pexels_integration",
        "--hidden-import", "voice_assistant",
        "--hidden-import", "docx",
        "--hidden-import", "pptx",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL._imaging",
        "--hidden-import", "numpy",
        "--hidden-import", "pygame",
        "--collect-all", "flask",
        "--collect-all", "flask_cors",
        "--collect-all", "groq",
        "--collect-all", "docx",
        "--collect-all", "pptx",
        "--distpath", DIST_DIR,
        "--workpath", BUILD_DIR,
        "--specpath", BASE_DIR,
        main_script,
    ]

    if icon_path and os.path.exists(icon_path):
        cmd.extend(["--icon", icon_path])

    print("\n  Running PyInstaller...")
    print(f"  Command: {' '.join(cmd[:4])} ...")
    print()

    try:
        subprocess.run(cmd, check=True)
        print(f"\n  ✅ Build complete!")
        print(f"  📁 Output: {os.path.join(DIST_DIR, APP_NAME)}")
        print(f"  🚀 Executable: {os.path.join(DIST_DIR, APP_NAME, APP_NAME)}.exe")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n  ❌ Build failed: {e}")
        return False
    except Exception as e:
        print(f"\n  ❌ Unexpected error: {e}")
        return False


def create_build_bat():
    """Create a convenient .bat file for building."""
    bat_content = """@echo off
echo ====================================
echo  Building J.A.R.V.I.S. Application
echo ====================================
echo.

cd /d "%~dp0"

echo Building EXE with PyInstaller...
python build_exe.py
if %errorlevel% neq 0 (
    echo EXE build failed!
    pause
    exit /b 1
)

echo.
echo ====================================
echo  Build complete!
echo  Output: dist\\JARVIS
echo ====================================
pause
"""
    bat_path = os.path.join(BASE_DIR, "build_app.bat")
    with open(bat_path, "w") as f:
        f.write(bat_content)
    print(f"  📝 Created build script: {bat_path}")
    return bat_path


if __name__ == "__main__":
    print()
    print(f"  Platform: {platform.system()} {platform.release()}")
    print(f"  Python: {sys.version}")
    print(f"  Directory: {BASE_DIR}")
    print()

    success = build_pyinstaller()

    if success:
        exe_path = os.path.join(DIST_DIR, APP_NAME, f"{APP_NAME}.exe")
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"\n  Executable size: {size_mb:.1f} MB")
        
        create_build_bat()
        
        print()
        print("=" * 60)
        print(f"  {APP_NAME} Application built successfully!")
        print(f"  Location: {os.path.join(DIST_DIR, APP_NAME)}")
        print("=" * 60)
    else:
        print("\n  Build failed. Check the errors above.")
        sys.exit(1)