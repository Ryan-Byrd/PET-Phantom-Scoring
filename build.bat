@echo off
REM Build script for PET QA Toolkit
REM Compiles PET_GUI.py into a standalone Windows executable

setlocal enabledelayedexpansion

echo.
echo ========================================
echo PET QA Toolkit - Build Script
echo ========================================
echo.

REM Get the script directory
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

echo [*] Workspace: %SCRIPT_DIR%
echo.

REM Check if PyInstaller is installed
echo [*] Checking for PyInstaller...
python -m pip list | findstr /i "pyinstaller" >nul
if errorlevel 1 (
    echo [!] PyInstaller not found. Installing...
    python -m pip install pyinstaller
)
echo [OK] PyInstaller found
echo.

REM Check if build directory exists and clean it
if exist "build" (
    echo [*] Cleaning old build artifacts...
    rmdir /s /q "build" 2>nul
    rmdir /s /q "dist" 2>nul
    del "*.spec.bak" 2>nul
)
echo.

REM Run PyInstaller
echo [*] Building executable...
echo [*] Command: pyinstaller PET_QA_Toolkit.spec --onefile --distpath ./build/dist --workpath ./build --specpath ./build
echo.

pyinstaller PET_QA_Toolkit.spec ^
    --onefile ^
    --distpath "./build/dist" ^
    --workpath "./build" ^
    --specpath "./build" ^
    --noconfirm

if errorlevel 0 (
    echo.
    echo ========================================
    echo [OK] BUILD SUCCESSFUL!
    echo ========================================
    echo.
    echo Location: %SCRIPT_DIR%build\dist\PET_QA_Toolkit.exe
    echo.
    echo To run the application:
    echo   .\build\dist\PET_QA_Toolkit.exe
    echo.
) else (
    echo.
    echo ========================================
    echo [ERROR] BUILD FAILED
    echo ========================================
    echo.
    echo Check the output above for error details.
    echo.
    exit /b 1
)

endlocal
pause
