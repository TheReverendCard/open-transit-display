@echo off
setlocal
cd /d "%~dp0"
py -3 bench_flash.py restore --node 495F0C7C
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo Restore stopped. Keep the recovery ZIP.
pause
exit /b 1
