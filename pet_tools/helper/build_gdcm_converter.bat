@echo off
REM Build script for native GDCM converter on Windows
REM
REM Prerequisites:
REM   - Visual Studio or MinGW with CMake
REM   - GDCM source in ..\..\build\gdcm-3.0.24
REM
REM Usage: build_gdcm_converter.bat

setlocal enabledelayedexpansion

echo ========================================
echo Building GDCM 3.0.24
echo ========================================

REM Get current directory
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Set GDCM path
set "GDCM_SOURCE_DIR=%SCRIPT_DIR%..\..\build\gdcm-3.0.24"
set "GDCM_BUILD_DIR=%SCRIPT_DIR%..\..\build\gdcm-3.0.24-build"

REM Build GDCM if not already built
if not exist "%GDCM_BUILD_DIR%" (
    echo Building GDCM...
    mkdir "%GDCM_BUILD_DIR%"
    cd /d "%GDCM_BUILD_DIR%"
    cmake -G "Ninja" "%GDCM_SOURCE_DIR%"
    if !errorlevel! neq 0 (
        echo ERROR: GDCM CMake configuration failed
        exit /b 1
    )
    ninja
    if !errorlevel! neq 0 (
        echo ERROR: GDCM build failed
        exit /b 1
    )
)

echo GDCM build complete at: %GDCM_BUILD_DIR%

REM Now build gdcm_converter
echo.
echo ========================================
echo Building native GDCM converter
echo ========================================

cd /d "%SCRIPT_DIR%"

REM Create build directory
if exist gdcm_converter_build rmdir /s /q gdcm_converter_build
if not exist gdcm_converter_build mkdir gdcm_converter_build
cd gdcm_converter_build

REM Run CMake with GDCM path
echo.
echo Configuring with CMake...
cmake -G "Ninja" -DGDCM_DIR="%GDCM_BUILD_DIR%" ..

if !errorlevel! neq 0 (
    echo ERROR: CMake configuration failed
    exit /b 1
)

REM Build
echo.
echo Building...
ninja

if !errorlevel! neq 0 (
    echo ERROR: Build failed
    exit /b 1
)

REM Copy DLL to bin directory
echo.
echo Copying DLL to bin directory...
if exist "gdcm_converter.dll" (
    if not exist "..\bin" mkdir ..\bin
    copy "gdcm_converter.dll" "..\bin\gdcm_converter.dll"
    echo Successfully built and installed gdcm_converter.dll
) else (
    echo ERROR: DLL not found in build directory
    echo Checking for .dll files...
    dir *.dll
    exit /b 1
)

echo.
echo ========================================
echo Build completed successfully!
echo ========================================
endlocal
