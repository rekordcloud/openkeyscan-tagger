@echo off
REM Build script for OpenKeyScan Tagger (Windows)
REM Builds the standalone executable using PyInstaller

echo ======================================================================
echo Building OpenKeyScan Tagger Standalone Application
echo ======================================================================
echo.

REM Check if pyinstaller is available
where pyinstaller >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Error: pyinstaller not found
    echo Install it with: pipenv install --dev
    exit /b 1
)

REM Clean previous build artifacts (optional, PyInstaller will handle this)
if exist "build" (
    echo Cleaning build\ directory...
    rmdir /s /q build
)

echo Starting PyInstaller build...
echo.

REM Run PyInstaller with --noconfirm to skip prompts
pyinstaller --noconfirm tag_keys_server.spec

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ======================================================================
    echo Build Failed!
    echo ======================================================================
    exit /b 1
)

echo.
echo ======================================================================
echo Build Complete!
echo ======================================================================
echo.
echo Output:
echo   Executable: dist\tag_keys\tag_keys_server.exe
echo   Archive:    dist\tag_keys.zip
echo.
echo Test the build:
echo   dist\tag_keys\tag_keys_server.exe
echo.
echo Or extract and distribute the zip file:
echo   dist\tag_keys.zip
echo.
