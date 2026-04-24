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

:: ── 2. Check Python version is 3.10, 3.11, or 3.12 ──────────────────────
:: Python 3.13+ is not supported yet: pywebview depends on pythonnet,
:: which has no pre-built wheel for Python 3.13/3.14. Building it from
:: source requires .NET SDK + NuGet which most users don't have.
%PYTHON% -c "import sys; exit(0 if (3,10) <= sys.version_info < (3,13) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    for /f "tokens=*" %%V in ('%PYTHON% --version 2^>^&1') do echo Installed: %%V
    echo.
    echo GabaMic requires Python 3.10, 3.11, or 3.12.
    echo Python 3.13 and 3.14 are not supported yet.
    echo.
    echo Please install Python 3.12 from:
    echo   https://www.python.org/downloads/release/python-3128/
    echo.
    echo IMPORTANT: on the installer's first page, tick
    echo   "Add Python to PATH"
    echo before clicking Install.
    echo.
    echo After installing Python 3.12, run this script again.
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

:: ── 5. Create GabaMic.lnk shortcut with the GabaMic icon ─────────────────
:: .bat files always show the CMD icon in Explorer; a .lnk shortcut lets us
:: attach GabaMic.ico so users have a branded launcher to double-click.
if exist "%~dp0GabaMic.ico" (
    powershell -NoProfile -Command ^
        "$s=New-Object -ComObject WScript.Shell;" ^
        "$l=$s.CreateShortcut('%~dp0GabaMic.lnk');" ^
        "$l.TargetPath='%~dp0GabaMic.bat';" ^
        "$l.IconLocation='%~dp0GabaMic.ico';" ^
        "$l.WorkingDirectory='%~dp0';" ^
        "$l.Save()"
)

:: ── 6. Success ────────────────────────────────────────────────────────────
echo.
echo ================================================
echo   Setup complete!
echo ================================================
echo.
echo To start GabaMic:
echo   Double-click  GabaMic.lnk  (GabaMic icon)
echo   or            GabaMic.bat  (same thing, CMD icon)
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
