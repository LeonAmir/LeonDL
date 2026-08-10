@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title LeonDL Core Setup

set "VENV_DIR=%CD%\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "PYEXE="
set "PYARGS="
set "PIP_DEFAULT_TIMEOUT=45"
set "PIP_RETRIES=2"
set "PIP_NO_INPUT=1"

call :FIND_PYTHON
if defined PYEXE goto :PYTHON_READY

echo Python 3.10 or newer was not found.
where winget >nul 2>nul
if errorlevel 1 goto :FAILED

echo Installing Python 3.12...
winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
if errorlevel 1 goto :FAILED
call :FIND_PYTHON
if not defined PYEXE goto :FAILED

:PYTHON_READY
if not exist "%VENV_PY%" (
    echo Creating .venv...
    "%PYEXE%" %PYARGS% -m venv "%VENV_DIR%"
    if errorlevel 1 goto :FAILED
)

echo Installing and verifying the core application packages...
echo This step installs only PySide6, yt-dlp, yt-dlp-ejs, and curl-cffi.
echo FFmpeg, Deno, spotDL, gallery-dl, and other optional tools are managed inside Leon.
"%VENV_PY%" bootstrap.py --skip-external
if errorlevel 1 goto :FAILED

REM Mark the core runtime ready so normal startup does not repeat setup.
"%VENV_PY%" -c "import runpy; ns=runpy.run_path('launcher.pyw'); ns['_write_environment_stamp']()"
if errorlevel 1 goto :FAILED

echo.
echo Core setup completed successfully.
echo Open LeonDL, then use Packages and Tools for optional external tools.
echo.
pause
exit /b 0

:FIND_PYTHON
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "PYEXE=py"
        set "PYARGS=-3"
        exit /b 0
    )
)
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "PYEXE=python"
        set "PYARGS="
        exit /b 0
    )
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        set "PYARGS="
        exit /b 0
    )
)
exit /b 0

:FAILED
echo.
echo Setup failed. Read the messages above and leon_setup.log.
echo The window will remain open.
pause
exit /b 1
