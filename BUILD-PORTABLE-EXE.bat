@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
  echo.
  echo Build failed with code %CODE%.
  pause
  exit /b %CODE%
)
echo.
echo EXE build completed successfully.
pause
exit /b 0
