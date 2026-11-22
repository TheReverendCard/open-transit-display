@echo off
setlocal
cd /d "%~dp0"
set "CLOCK_CLI=%ProgramFiles%\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
if not exist "%CLOCK_CLI%" set "CLOCK_CLI=arduino-cli"
set "CLOCK_OUT=%TEMP%\OTD-ClockBench-%RANDOM%-%RANDOM%"
mkdir "%CLOCK_OUT%" || exit /b 1
"%CLOCK_CLI%" compile --jobs 4 --fqbn "esp32:esp32:XIAO_ESP32S3_Plus:USBMode=hwcdc,CDCOnBoot=default,FlashMode=qio,FlashSize=16M,PartitionScheme=fatflash,PSRAM=disabled,EraseFlash=none" --output-dir "%CLOCK_OUT%" ClockRefreshBench
if errorlevel 1 exit /b 1
py -3 -c "import hashlib,pathlib,sys; d=pathlib.Path(sys.argv[1]).read_bytes(); pathlib.Path('ClockRefreshBench.bin').write_bytes(d); pathlib.Path('ClockRefreshBench.sha256').write_text(hashlib.sha256(d).hexdigest()+'  ClockRefreshBench.bin\n')" "%CLOCK_OUT%\ClockRefreshBench.ino.bin"
exit /b %errorlevel%
