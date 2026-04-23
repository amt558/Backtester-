@echo off
REM Double-click this file to launch the tradelab environment.
REM It runs tradelab-launch.ps1 in the same folder with execution policy
REM bypassed (so Windows doesn't refuse to run an unsigned local script).
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tradelab-launch.ps1"
echo.
pause
