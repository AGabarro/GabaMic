@echo off
setlocal enabledelayedexpansion

echo ================================================
echo   GabaMic Setup
echo ================================================
echo.

:: ── 1. Locate Python ─────────────────────────────────────────────────────
set PYTHON=
for %%P in (python py) do (
    if not defined PYTHON (
        where %%P >nul 2>&1
        if !errorlevel! equ 0 set PYTHON=%%P
    )
)

if not defined PYTHON (
    echo Python was not found on this machine.
    echo.
    echo Please install Python 3.10 or newer from:
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANT: on the installer's first page, tick
    echo   "Add Python to PATH"
    echo before clicking Install.
    echo.
    echo After installing Python, run this script again.
    pause
    exit /b 1
)

:: ── 2. Check Python version ≥ 3.10 ───────────────────────────────────────
%PYTHON% -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo Python 3.10 or newer is required.
    echo.
    for /f "tokens=*" %%V in ('%PYTHON% --version 2^>^&1') do echo Installed: %%V
    echo.
    echo Download a newer version from https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=*" %%V in ('%PYTHON% --version 2^>^&1') do echo Found: %%V
echo.

:: ── 3. Create virtual environment ────────────────────────────────────────
if exist ".venv\Scripts\python.exe" (
    echo Virtual environment already exists — skipping creation.
) else (
    echo Creating virtual environment...
    %PYTHON% -m venv .venv
    if %errorlevel% neq 0 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: ── 4. Install dependencies ───────────────────────────────────────────────
echo Installing dependencies (this may take a few minutes)...
.venv\Scripts\pip install --upgrade pip --quiet
.venv\Scripts\pip install -r requirements_win.txt
if %errorlevel% neq 0 (
    echo.
    echo Dependency installation failed.
    echo Check your internet connection and try again.
    pause
    exit /b 1
)

:: ── 5. Success ────────────────────────────────────────────────────────────
echo.
echo ================================================
echo   Setup complete!
echo ================================================
echo.
echo To start GabaMic:
echo   Double-click  GabaMic.bat
echo.
echo Usage:
echo   Hold Alt+S anywhere to record.
echo   Release to transcribe.
echo   Text is typed into whatever app is focused.
echo   Right-click the pill to quit.
echo.
echo Note: the first launch downloads the speech model
echo (~150 MB). After that GabaMic works fully offline.
echo.

set /p LAUNCH="Launch GabaMic now? (Y/N): "
if /i "%LAUNCH%"=="Y" (
    start "" ".venv\Scripts\pythonw.exe" app_win.py
)

endlocal
