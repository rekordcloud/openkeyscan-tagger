@echo off
REM Build script for OpenKeyScan Tagger (Windows)
REM Builds the standalone executable using PyInstaller

echo ======================================================================
echo Building OpenKeyScan Tagger Standalone Application
echo ======================================================================
echo.

REM Check if pipenv is available
where pipenv >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Error: pipenv not found
    echo Install it with: pip install pipenv
    exit /b 1
)

REM Clean previous build artifacts (optional, PyInstaller will handle this)
if exist "build" (
    echo Cleaning build\ directory...
    rmdir /s /q build
)

echo Starting PyInstaller build...
echo.

REM Run PyInstaller with --noconfirm to skip prompts using pipenv
pipenv run pyinstaller --noconfirm openkeyscan_tagger.spec

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
echo   Executable: dist\openkeyscan-tagger\openkeyscan-tagger.exe
echo   Archive:    dist\openkeyscan-tagger.zip
echo.
echo Test the build:
echo   dist\openkeyscan-tagger\openkeyscan-tagger.exe
echo.
echo Or extract and distribute the zip file:
echo   dist\openkeyscan-tagger.zip
echo.

set DEST_DIR=%USERPROFILE%\workspace\openkeyscan\OpenKeyScan-app\build\lib\win\x64

echo ======================================================================
echo Moving build to library directory
echo ======================================================================
echo.
echo Architecture: x64
echo Destination:  %DEST_DIR%
echo.

REM Create destination directory if it doesn't exist
if not exist "%DEST_DIR%" mkdir "%DEST_DIR%"

REM Copy the zip file to the destination, replacing any existing file
copy /Y dist\openkeyscan-tagger.zip "%DEST_DIR%\"

echo.
echo Build successfully moved to:
echo   %DEST_DIR%\openkeyscan-tagger.zip
echo.
