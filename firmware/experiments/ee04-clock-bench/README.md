# EE04 differential clock bench

This standalone experiment for the Museum sign alternates 08:08 and 11:11 against static text, a border and contrast patches.  It compares the GxEPD2 GDEY075T7 full waveform, a differential update with explicit previous and current images, and the same differential update after the Wio has transmitted.  While the bench firmware is installed, the sign shows the test clock and the ordinary passenger display is offline.

## Run it on Windows

1. Extract the entire package into a folder.  Plug in the **Museum EE04 sign** (node `495F0C7C`) by USB.  Close Arduino Serial Monitor.  The Windows launchers target this node and ask for its COM port.
2. Double-click **Install_Bench.cmd**.  If no prebuilt binary is present, it builds the sketch using the installed Arduino IDE tools first.  The installer reads the board MAC, validates the partition table and OTA selection, and saves the original sectors before writing the test app.  Wait for “Bench application verified” and “Board restarted”.
3. Open Serial Monitor at **115200 baud**, with a newline line ending.  The first screen is a full 08:08 baseline.  The default `diff` phase starts automatically.  Send `next` to see 11:11 immediately, or leave the sign for one change per minute.  Each phase stops after 12 changes, leaving the last image visible for a photo.  Send `status` if you missed the startup log.
4. Send `full` to repeat with the GxEPD2 full waveform.  Every phase starts with a fresh full baseline.  Compare both directions of the transition and look for pale leftover segments, faded black strokes, or changes outside the clock.  This full control uses GxEPD2's default fast full waveform; the October 3.433 s measurement was made with Seeed_GFX.
5. For the Wio test attach the **915 MHz antenna** and send `radio`, then `next`.  On the next OTD1, OTD2, OTD3 or OTDXQ1 frame the sign sends a diagnostic acknowledgement and performs the differential update.  If the gateway is away or quiet, `probe` sends one real test packet and updates immediately.  A gateway is optional for this path.  The log distinguishes `diagnostic_ack` from `local_probe`.  Watch for `status=0`, `tx_before=1`, `result=ready` and clean digits.  The diagnostic reply uses its own prefix; a normal production gateway can ignore it.  Receiver-side delivery of the reply requires a second receiver to verify.
6. Send `stop` to pause.  To return to service, close Serial Monitor, double-click **Restore_Sign.cmd**, and select the sign's current COM port.  Wait for the original bytes to verify and the board to restart.  Check for the normal trial3 startup, schedule and clock.  Manual `next` and `probe` commands advance the bench on demand; the automatic timing runs one minute after completion.

## Recovery

The recovery ZIP is private to the PC, under `Documents/OTD/backups/clock-refresh-bench/<board-mac>/`.  Keep it until the sign is back in service.  It contains exactly the old sectors spanned by the bench application and a hash receipt.  The updater targets only the currently selected application slot.  Bootloader, partition table, OTA selection, NVS, filesystem and application bytes beyond that span are outside its write range.  Install and Restore both perform flash read-back checks.  Downloaded schedules and node settings stay in place.

After an interrupted install, use Restore with the saved ZIP.  If the app cannot start, hold BOOT, tap RESET, release BOOT and select the download-mode COM port.  The recovery prompt requires the sign ID before overwriting an unrecognised image.  A successful restore archives the backup for reference.  Normal Arduino IDE Upload writes additional boot and partition files; use the supplied launchers for this reversible test.

## Implementation and build

The sketch reconstructs the old and new 48,000-byte monochrome frames from deterministic artwork on each transition.  It writes the previous image to controller RAM 0x10 and the current image to 0x13.  The GxEPD2 driver selects the panel's built-in differential waveform.  Its default GDEY075T7 configuration drives the full frame; static marks help reveal any effects outside the digits.  After physical TX on GPIO38, the sketch releases reset, reinitialises the driver and restores both complete frames from the host.  Panel power is turned off between updates.  This bench sketch stays awake and timings alone do not establish energy use.

The log separates preparation, display drive, and total time through panel power-off.  Radio TX time is outside these display timings.  `busy_seen` records whether the active-low BUSY signal was observed; visual quality must be checked on the glass.  Reset starts a clean differential phase.  A refresh fault halts the phase.

Match the local Museum build using XIAO ESP32S3 Plus, 16 MB, FAT flash layout, hardware USB CDC, and PSRAM disabled.  The sketch uses ESP32 Arduino 4.0.0, GxEPD2 1.6.9, RadioLib 8.0.0, and Adafruit GFX 1.13.0.  Arduino CLI 1.6.0 and esptool 5.x were used in preparing this trial.  Windows scripts require Python 3 with the `py` launcher.  Build_Bench.cmd uses the Arduino IDE's CLI or the CLI on PATH.  The existing installation already has the required libraries.

| Connection | ESP32-S3 GPIO |
| --- | --- |
| Shared SCK, MISO, MOSI | 7, 8, 9 |
| EE04 CS, DC, BUSY, power enable | 44, 10, 4, 43 |
| Panel reset / Wio RF switch | 38 |
| Wio CS, DIO1, reset, BUSY | 41, 39, 42, 40 |

The Museum tune and shared SPI configuration reuse the trial3 RadioLib adapter.  The display-only phases keep the radio deselected.  Radio runs at 915 MHz, BW 125 kHz, SF9, CR 4/7, 10 dBm.

GreatScott's Inkplate 10 desktop dashboard inspired the comparison.  Its Arduino code redraws a frame on the host and uses Inkplate's differential refresh for changing data.  This experiment uses Jean-Marc Zingg's panel-specific GxEPD2 driver.  See [the Patreon project](https://www.patreon.com/GreatScott/posts/desktop-files-176056546), [the GDEY075T7 driver](https://github.com/ZinggJM/GxEPD2/tree/1.6.9/src/gdey), [the EE04 schematic](https://files.seeedstudio.com/wiki/Epaper/EE04/XIAO_ePaper_Display_Board_EE04_SCH_V1.2.pdf), and [Museum bench measurements](https://github.com/TheReverendCard/open-transit-display/issues/7#issuecomment-6154013808).
