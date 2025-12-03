@echo off
REM ============================================================
REM  RunAllPETFolders.bat
REM  Purpose:
REM    - Process all PET unit folders inside the ACR Overlay Validation directory
REM    - Skip rename_folder_from_dicom.py (hardcoded directory instead)
REM    - Generate one MASTER_SPLASH.png from all SUV_overlay.png files
REM ============================================================

setlocal enabledelayedexpansion
set MPLBACKEND=Agg
chcp 65001 >nul

REM --- Path to Python executable ---
set "PYTHON_EXE=C:\Users\RyanByrd\AppData\Local\Programs\Python\Python313\python.exe"

REM --- Hardcoded path to validation directory ---
set "VALIDATION_DIR=C:\Users\RyanByrd\OneDrive - ONE Physics\General - Radcom Files\PET Python Scripts\Validation Files\ACR Overlay Validation"

REM --- Path to PET analysis script ---
set "SCRIPT_PATH=C:\Users\RyanByrd\OneDrive - ONE Physics\General - Radcom Files\PET Python Scripts\test.py"

REM --- Verify paths ---
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python not found at "%PYTHON_EXE%"
    pause
    exit /b 1
)
if not exist "%SCRIPT_PATH%" (
    echo [ERROR] test.py not found at "%SCRIPT_PATH%"
    pause
    exit /b 1
)
if not exist "%VALIDATION_DIR%" (
    echo [ERROR] Validation directory not found at "%VALIDATION_DIR%"
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Starting PET Batch Processor (Silent + Headless)
echo  Validation Directory:
echo  %VALIDATION_DIR%
echo ============================================================
echo.

REM --- Process each subfolder in the validation directory ---
cd /d "%VALIDATION_DIR%"
for /D %%F in (*) do (
    echo [INFO] Running analysis on: %%F
    "%PYTHON_EXE%" -X utf8 -W ignore "%SCRIPT_PATH%" --input "%VALIDATION_DIR%\%%F" --output "%VALIDATION_DIR%\%%F" >nul 2>&1

    if errorlevel 1 (
        echo [WARN] Error encountered in %%F
    ) else (
        echo [OK] Completed: %%F
    )
    echo ------------------------------------------------------------
)

REM --- Create the master splash after all units processed ---
echo [INFO] Creating master splash view from all SUV_overlay.png files...
"%PYTHON_EXE%" -X utf8 -W ignore "%VALIDATION_DIR%\make_master_splash.py" "%VALIDATION_DIR%" >nul 2>&1

if errorlevel 1 (
    echo [WARN] Failed to create MASTER_SPLASH.png
) else (
    echo [OK] MASTER_SPLASH.png created successfully.
)

echo.
echo ============================================================
echo  All folders processed and MASTER_SPLASH generated.
echo ============================================================
pause
endlocal
