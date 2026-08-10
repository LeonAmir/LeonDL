@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title LeonDL Diagnostics

echo ============================================================
echo  LeonDL diagnostics
echo ============================================================
echo.
echo [Python launcher]
where py 2>nul
py -3 --version 2>nul
echo.
echo [Python]
where python 2>nul
python --version 2>nul
echo.
echo [Virtual environment]
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" --version
  ".venv\Scripts\python.exe" -m pip --version
  ".venv\Scripts\python.exe" -c "import PySide6, yt_dlp; print('PySide6:', PySide6.__version__); print('yt-dlp:', yt_dlp.version.__version__)" 2>&1
  echo.
  ".venv\Scripts\python.exe" bootstrap.py --check --strict
  echo.
  echo [Qt paint smoke test]
  set "QT_QPA_PLATFORM=offscreen"
  ".venv\Scripts\python.exe" qt_paint_smoke.py 2^>^&1
  set "QT_QPA_PLATFORM="
  echo.
  echo [Download Later storage smoke test]
  ".venv\Scripts\python.exe" later_store_smoke.py 2^>^&1
) else (
  echo .venv does not exist.
)
echo.
echo [FFmpeg]
where ffmpeg 2>nul
ffmpeg -version 2>&1 | findstr /b /c:"ffmpeg version"
echo.
echo [FFprobe]
where ffprobe 2>nul
ffprobe -version 2>&1 | findstr /b /c:"ffprobe version"
echo.
echo [Deno]
where deno 2>nul
deno --version 2>nul
echo.
echo Logs:
echo   %CD%\leon_setup.log
echo   %CD%\leon_runtime.log
echo.
pause
