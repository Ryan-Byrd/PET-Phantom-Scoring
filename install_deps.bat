@echo off
REM ============================================================
REM  install_deps.bat
REM  Purpose: Install Python dependencies from requirements.txt
REM  Uses the script's own directory as working directory
REM ============================================================

setlocal enabledelayedexpansion
echo.
echo [INFO] ===================================================
echo [INFO]  Dependency Installer Started
echo [INFO] ===================================================

REM -- Always use the directory where this script resides --
set "WORK_DIR=%~dp0"
echo [INFO] Using script directory:
echo [INFO] %WORK_DIR%
cd /d "%WORK_DIR%"

REM ============================================================
REM  Check Python
REM ============================================================
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo [HINT] Please install Python and add it to PATH, then rerun this script.
    pause
    exit /b 1
)

REM ============================================================
REM  Check and install pip if missing
REM ============================================================
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] pip not found. Attempting to install pip...
    powershell -Command "Invoke-WebRequest https://bootstrap.pypa.io/get-pip.py -OutFile get-pip.py"
    python get-pip.py
    del get-pip.py
    if errorlevel 1 (
        echo [ERROR] pip installation failed.
        pause
        exit /b 1
    )
    echo [INFO] pip successfully installed.
)

REM ============================================================
REM  Upgrade pip
REM ============================================================
python -m pip install --upgrade pip

REM ============================================================
REM  Install requirements.txt
REM ============================================================
if exist "requirements.txt" (
    echo [INFO] Installing dependencies from requirements.txt...
    python -m pip install -r "requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. Check messages above.
        pause
        exit /b 1
    )
) else (
    echo [WARN] No requirements.txt found in "%WORK_DIR%".
)

echo [INFO] ===================================================
echo [INFO]  Dependency Installation Complete
echo [INFO] ===================================================
pause
endlocal
