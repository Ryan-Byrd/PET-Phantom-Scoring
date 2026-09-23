@echo off
REM Dual Series Overlay — Windows batch launcher
REM Provides an easy way to run dual_series_overlay.py with common options

setlocal enabledelayedexpansion

REM Get the directory of this script
set SCRIPT_DIR=%~dp0
set PYTHON_SCRIPT=%SCRIPT_DIR%dual_series_overlay.py

REM Check if Python script exists
if not exist "%PYTHON_SCRIPT%" (
    echo Error: dual_series_overlay.py not found in %SCRIPT_DIR%
    pause
    exit /b 1
)

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found. Please ensure Python is installed and added to PATH.
    pause
    exit /b 1
)

REM Display menu
cls
echo.
echo ============================================================
echo   Dual Series Overlay — Windows Launcher
echo ============================================================
echo.
echo This tool overlays two DICOM image series with independent
echo color scales, preserving spatial coordinates from DICOM data.
echo.
echo.
echo Select mode:
echo   1) Quick Overlay (default colormaps, save to output folder)
echo   2) Custom Colormaps and Opacity
echo   3) Interactive Viewer Only (no save)
echo   4) Full Debug Mode
echo   5) Exit
echo.

set /p choice="Enter choice (1-5): "

if "%choice%"=="1" goto quick
if "%choice%"=="2" goto custom
if "%choice%"=="3" goto interactive
if "%choice%"=="4" goto debug
if "%choice%"=="5" goto end
echo Invalid choice. Exiting.
goto end

:quick
echo.
echo Quick Overlay Mode
echo ------------------
set /p series1="Enter path to Series 1 folder: "
set /p series2="Enter path to Series 2 folder: "

if not exist "!series1!" (
    echo Error: !series1! does not exist.
    pause
    goto end
)
if not exist "!series2!" (
    echo Error: !series2! does not exist.
    pause
    goto end
)

echo.
echo Running overlay... This may take a minute.
python "%PYTHON_SCRIPT%" --series1 "!series1!" --series2 "!series2!"
goto success

:custom
echo.
echo Custom Mode
echo -----------
set /p series1="Enter path to Series 1 folder: "
set /p series2="Enter path to Series 2 folder: "

if not exist "!series1!" (
    echo Error: !series1! does not exist.
    pause
    goto end
)
if not exist "!series2!" (
    echo Error: !series2! does not exist.
    pause
    goto end
)

set /p cmap1="Colormap for Series 1 (viridis/hot/plasma/gray) [viridis]: "
if "!cmap1!"=="" set cmap1=viridis

set /p cmap2="Colormap for Series 2 (viridis/hot/plasma/gray) [hot]: "
if "!cmap2!"=="" set cmap2=hot

set /p alpha1="Opacity of Series 1 (0.0-1.0) [0.5]: "
if "!alpha1!"=="" set alpha1=0.5

set /p alpha2="Opacity of Series 2 (0.0-1.0) [0.5]: "
if "!alpha2!"=="" set alpha2=0.5

set /p output="Output folder [overlay_output]: "
if "!output!"=="" set output=overlay_output

echo.
echo Running overlay with custom settings...
python "%PYTHON_SCRIPT%" ^
  --series1 "!series1!" ^
  --series2 "!series2!" ^
  --cmap1 !cmap1! ^
  --cmap2 !cmap2! ^
  --alpha1 !alpha1! ^
  --alpha2 !alpha2! ^
  --output "!output!"
goto success

:interactive
echo.
echo Interactive Viewer Mode
echo -----------------------
set /p series1="Enter path to Series 1 folder: "
set /p series2="Enter path to Series 2 folder: "

if not exist "!series1!" (
    echo Error: !series1! does not exist.
    pause
    goto end
)
if not exist "!series2!" (
    echo Error: !series2! does not exist.
    pause
    goto end
)

echo.
echo Launching interactive viewer...
echo Use arrow keys (UP/DOWN or Page Up/Page Down) to navigate slices.
echo.
python "%PYTHON_SCRIPT%" ^
  --series1 "!series1!" ^
  --series2 "!series2!" ^
  --interactive ^
  --no-save
goto success

:debug
echo.
echo Debug Mode
echo ----------
set /p series1="Enter path to Series 1 folder: "
set /p series2="Enter path to Series 2 folder: "

if not exist "!series1!" (
    echo Error: !series1! does not exist.
    pause
    goto end
)
if not exist "!series2!" (
    echo Error: !series2! does not exist.
    pause
    goto end
)

set /p debug_dir="Debug output folder [debug_output]: "
if "!debug_dir!"=="" set debug_dir=debug_output

echo.
echo Running with full debug output...
python "%PYTHON_SCRIPT%" ^
  --series1 "!series1!" ^
  --series2 "!series2!" ^
  --debug "!debug_dir!"
goto success

:success
echo.
echo ============================================================
echo Done!
echo.
pause
goto end

:end
endlocal
