@echo off
setlocal
cd /d "%~dp0"
start "" /b wscript.exe "%CD%\LeonDL.vbs"
exit /b 0
