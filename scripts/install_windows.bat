@echo off
setlocal
set "SCRIPT=%~dp0install_windows.ps1"
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
if errorlevel 1 exit /b %errorlevel%
