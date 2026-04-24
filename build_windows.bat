@echo off
setlocal
cd /d "%~dp0"

echo ================================================
echo   Building GabaMic.exe
echo ================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Run setup_windows.bat first to create the virtual environment.
    pause
    exit /b 1
)

echo Installing PyInstaller...
.venv\Scripts\pip install pyinstaller pyinstaller-hooks-contrib --quiet
if %errorlevel% neq 0 (
    echo Failed to install PyInstaller.
    pause
    exit /b 1
)

echo Building...
.venv\Scripts\pyinstaller GabaMic.spec --noconfirm
if %errorlevel% neq 0 (
    echo Build failed. See output above for details.
    pause
    exit /b 1
)

echo.
echo ================================================
echo   Build complete!
echo ================================================
echo.
echo Executable:  dist\GabaMic\GabaMic.exe
echo.
echo Distribute the entire dist\GabaMic\ folder (zip it).
echo Users just extract and double-click GabaMic.exe.
echo.
pause
endlocal
