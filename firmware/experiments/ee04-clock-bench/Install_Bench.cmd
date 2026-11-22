@echo off
setlocal
cd /d "%~dp0"
if not exist ClockRefreshBench.bin (
  call Build_Bench.cmd
  if errorlevel 1 goto failed
)
py -3 bench_flash.py install --node 495F0C7C
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo Installation stopped. Check the message above.
pause
exit /b 1
