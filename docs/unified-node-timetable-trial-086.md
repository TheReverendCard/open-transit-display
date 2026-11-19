# Unified timetable trial 0.8.6

## Current candidate:  0.8.6-trial3, status updated 20 November 2026

### Standalone gateway fetch and offline cache restore passed, 20 November 2026

The 8 MB XIAO ESP32-S3 spare booted as a headless gateway after rebuilding under the standard S3 board profile. The Plus image had failed flash initialization because it expected 16 MB. Trial3 also rejected valid HTTPS timetables because it reused the published CRC of comma-separated timestamps as the binary CRC expected by the LoRa snapshot validator. The bench sketch was patched in `nodeSaveWifiSchedule` to calculate the binary CRC from the copied timestamps before committing. The published checksum validation is still in place.

The patched spare fetched and saved 82 departures. The published revision was `BD264D2C` and the LoRa snapshot revision was `05FE9B0B`. With the hotspot off, a commanded reboot logged `NODE schedule restored revision=05FE9B0B` before `WIFI connect timed out` and `NODE UPSTREAM timetable=FAILED clock=0`. The cache survived the reboot. The restored clock estimate was provisional, so this does not establish offline serving with a trusted clock after reboot. Earlier successful online logs showed a peer request and metadata transmission. Complete LoRa page delivery and missing-page repair remain to be verified. This result applies to the locally patched bench sketch.

### Overnight sleep and display check passed, 20 November 2026

The owner supplied five fresh gateway OTDP1 records from 07:55:11 through 08:15:11 NZDT and reports:  "Sign is updating and displaying correctly."  All five retain boot nonce `0BED394C`, matching the 19 November 20:07:03 report.  Uptime and sleep counters increase consistently.  This supports uninterrupted operation in the same session overnight and passes the initial overnight light-sleep/recovery and observed display check for the installed trial3 candidate.

| Report NZDT | Uptime seconds | Sleep events | Total sleep seconds | GPIO wakes | Timer wakes | Sleep errors |
| --- | --- | --- | --- | --- | --- | --- |
| 07:55:11 | 42522 | 20869 | 41194 | 32 | 20837 | 0 |
| 08:00:11 | 42822 | 21008 | 41466 | 37 | 20971 | 0 |
| 08:05:11 | 43123 | 21147 | 41738 | 42 | 21105 | 0 |
| 08:10:11 | 43423 | 21286 | 42011 | 47 | 21239 | 0 |
| 08:15:11 | 43723 | 21425 | 42283 | 53 | 21372 | 0 |

Every report has stop=11000262, sleep_enabled=1 and sleep_supported=1.  Final uptime is 12 h 8 m 43 s; accumulated light sleep is 11 h 44 m 43 s, approximately 96.7% of uptime.  Between the first and last morning samples, 1089 of 1201 uptime seconds were asleep (90.7%), with 556 additional sleep events, 21 GPIO wakes, 535 timer wakes and no reported sleep errors.  This demonstrates continued sleep/wake operation during morning updates, not just accumulated overnight sleep.  The wake counts sum to the event counts in these samples.  Received RSSI is -31 to -33 dBm and SNR 10.2-11.5 dB.

Raw owner-supplied records:

```text
2026-11-20 07:55:11 2026-11-20 07:55:11 <- radio: RX_OTHER:OTDP1|11000262|0BED394C|42522|1|1|20869|41194|32|20837|0 RSSI=-32.0 SNR=11.2
2026-11-20 08:00:11 2026-11-20 08:00:11 <- radio: RX_OTHER:OTDP1|11000262|0BED394C|42822|1|1|21008|41466|37|20971|0 RSSI=-31.0 SNR=11.2
2026-11-20 08:05:11 2026-11-20 08:05:11 <- radio: RX_OTHER:OTDP1|11000262|0BED394C|43123|1|1|21147|41738|42|21105|0 RSSI=-31.0 SNR=10.2
2026-11-20 08:10:11 2026-11-20 08:10:11 <- radio: RX_OTHER:OTDP1|11000262|0BED394C|43423|1|1|21286|42011|47|21239|0 RSSI=-32.0 SNR=11.5
2026-11-20 08:15:11 2026-11-20 08:15:11 <- radio: RX_OTHER:OTDP1|11000262|0BED394C|43723|1|1|21425|42283|53|21372|0 RSSI=-33.0 SNR=10.8
```

Evidence scope:  these are supplied gateway excerpts plus the owner's physical observation, not a direct audit of Windows logs.  They show no restart in the continuing overnight session and no reported sleep-call errors.  The boot nonce's USB-reset reason describes the session's original startup, not a new reset on each report.  The earlier setup resets are not retrospectively classified as intentional.  The excerpts do not measure complete ACK delivery rate, exact first-service wake timing, battery current, battery-only endurance or energy saving; percentage asleep is elapsed MCU sleep time, not percentage energy saved.

The initial overnight observation gate is complete; no reflash or repeated identical overnight test is required for this result.  Continue ordinary use while the next development milestone is the standalone timetable-only gateway on a spare node, followed by capable-peer transfer/missing-page repair and combined gateway/display validation.  Multi-day endurance and those gateway/peer capabilities remain separate tests.  Firmware, artifacts and the owner's running installation were not changed for this documentation update.

### Initial physical display check, 19 November 2026

After receiving the trial3 fix, the owner reports:  "It is now displaying correctly."  The initial physical rendering check is passed on that report.  No new startup log or photograph accompanied this confirmation, so the exact flashed build banner, new geometry diagnostic, post-fix ACK rate and uninterrupted uptime are not independently verified in this update.

At that stage the next check was a short observation with the existing gateway running and the sign's Serial Monitor closed, allowing the baseline USB guard to permit light sleep.  The later wireless records above now pass the initial overnight sleep/display check without requiring a USB reconnection.  Battery endurance remains a separate test.

Standalone timetable gateway operation, capable-peer page repair and combined gateway/display field checks remain separate milestones.  The corrected screen alone does not pass those tests.

### Initial wireless sleep telemetry, 19 November 2026

The owner supplied these five OTDP1 reports spanning setup/uploads.  The first byte of the boot nonce stores esp_reset_reason(); the pinned ESP-IDF enum identifies 1 as power-on, 3 as software restart, and 11 (hex 0B) as USB-peripheral reset.

| Receiver report NZ time | Boot nonce | Uptime seconds | Reported reset reason |
| --- | --- | --- | --- |
| 19:44:42 | 012020EB | 51 | Power-on (1) |
| 19:51:10 | 039856FB | 24 | Software restart (3) |
| 19:59:24 | 0B5E35D5 | 26 | USB peripheral (11) |
| 20:01:50 | 0138DF00 | 19 | Power-on (1) |
| 20:07:03 | 0BED394C | 24 | USB peripheral (11) |

All reports have sleep_enabled=1 and supported=1, but zero sleep events, accumulated seconds, wake counts and sleep errors.  Four are inside the 30-second startup grace; an open USB Serial Monitor also suppresses light sleep.  These early-boot samples do not establish sleep operation or failure.  None reports a panic, watchdog or brownout cause, but the samples are not an uninterrupted history and do not prove all resets were intentional.

At this stage it was not established whether the reported power/USB resets coincided with uploads or deliberate reconnections, especially the last estimated startup around 20:06:39.  Their intentionality remains unconfirmed, but the later 20 November data above establishes a continuing overnight session after that startup.

The subsequent check used existing wireless OTDP1 records instead of reconnecting USB merely to obtain counters.  The 20 November evidence above supplies the sought same boot nonce with longer uptime, increasing sleep counters and zero errors.  Telemetry is ACK-triggered, rate-limited to one attempt per five minutes; overnight quiet mode can suppress the triggering exchanges entirely, so no new report after 20-30 minutes is inconclusive.  A later scheduled exchange can provide the accumulated evidence.  The full node configuration report remains serial-only and Wi-Fi diagnostics are not implemented.

### Observed trial2 display failure

The owner successfully flashed trial2.  First-start hardware=0 left the screen untouched until `node hardware trmnl` and `node reboot` were entered.  The resulting log confirms hardware=1, role=stop, RadioLib 8.0.0, completed EPD FULL calls, restored 82-event cache BD264D2C, and reception of OTD2 session 776523039/N429 with TX_ACK status=0.  The photograph shows four miniature sign layouts across the upper screen and severe corruption below.  Display acceptance therefore FAILED.  Successful refresh calls and radio ACKs do not establish correct physical rendering.

This was the owner's screen-equipped unit running trial2, not a headless-only trial.  Earlier statements that the Museum baseline was unchanged describe actions of the build session; the owner has now installed the candidate on this unit.  Preserve original v0.8.4e as the rollback/reference version.

### Diagnosed regression and trial3 correction

The UC8179/800x480/one-bit panel selection matches the working baseline.  The change from a global static `EPaper` to ordinary heap `new EPaper` exposed an omitted initializer in the pinned Seeed_GFX 2.0.3 constructor:  its private `_grayLevel` field is not initialized.  The static baseline object began with zero storage.  Nonzero heap storage can instead select the grayscale update path while the sprite buffer is still one-bit monochrome.

An instrumented host regression compiles the actual upstream EPaper header/implementation with mocked base-sprite allocation and transport.  Nonzero object storage reproduces a grayscale transfer-read request of 192,000 bytes against a 48,000-byte monochrome buffer.  This is a concrete code defect consistent with the photo; the test does not reproduce the physical panel waveform.

Trial3 adds `OTDDisplayStorage.h` with a function-local static display object.  Its storage is zero-initialized, and construction/framebuffer allocation still occurs only when the display profile requests it.  Headless builds reserve the small control object's static storage but skip its constructor and framebuffer allocation.  The test confirms one-time on-demand construction and repeated monochrome transfers bounded to 48,000 bytes.  Startup also validates 800x480 and 1 bpp before enabling output, and reports:

```text
EPD CONFIG width=800 height=480 bpp=1 storage=static-zeroed
```

The RadioLib 7/8 adapter, fonts, protocol, persistent settings, and transmission policy remain as in trial2.  All five checked baseline sleep/IRQ/ACK/clock functions remain byte-identical.

### Validation and delivery

| RadioLib | Program bytes | Static RAM bytes | Result |
| --- | --- | --- | --- |
| 7.3.0 | 1,439,239 | 51,984 | ESP32-S3 Plus compile/link passed |
| 8.0.0 | 1,446,731 | 51,832 | ESP32-S3 Plus compile/link passed |

The actual-library display regression, existing ASan/UBSan protocol tests and baseline-function hashes passed.  In-place repair tests passed from both trial1 and trial2, including backup, repeat execution, rejection of local edits and rollback after an injected write failure.  Tests ran on Linux; there was no Windows execution or physical upload by this session.

Refreshed `OTD_Unified_086_Trial.zip`:  43 files, 17,013,066 bytes, SHA-256 `1692a7698f63e7c8268681c0cd6e9a9d18b3e9c4f1d3b690d99ff7e65202e771`.  The matching source, both builds, receipt, display regression harness and `Apply_OTD_086_Trial3_Fix.py` are included.

The installer targets the previously supplied Documents/OTD sketch folder, saves backups under Documents/OTD/backups, and updates source only.  Reopen the sketch and Verify/Upload with Erase All Flash disabled.  Saved hardware selection should persist.  Original trial1/trial2 binaries/receipts outside a source-only repaired sketch are not updated; use the complete refreshed package for matching artifacts.

**Acceptance status, updated 20 November:** correct physical rendering is reported by the owner and the initial overnight sleep/recovery check has passed on the continuing-session telemetry above.  Multi-day endurance, standalone timetable gateway and capable-peer transfer/repair remain pending.  Exact first-service transition timing and a complete ACK delivery rate were not collected.  Host tests alone are not field acceptance.

The supplied `reset_reason=3` follows the explicit `node reboot` and denotes a software restart.  The core-dump checksum warning reports invalid stored dump data; it alone does not establish a new panic or identify its origin.  No core-dump erase or NVS reset is part of this correction.

Upstream source inspected:  https://github.com/Seeed-Studio/Seeed_GFX/tree/0dfdd7135425be82b5bb4b4b58d74dd51ab29a59/Extensions

## Historical trial2 record

## Candidate 0.8.6-trial2, 19 November 2026

The owner reported missing `setPacketReceivedAction`/`clearPacketReceivedAction` methods and an eight-argument `SX1262::begin` compile failure.  Those errors match RadioLib 8.0's breaking API changes.  Trial1 was verified only with RadioLib 7.3.0; its dependency validation did not cover the owner's installed API.

Trial2 adds `OTDRadioCompat.h`.  It selects the installed major version at compile time, leaving the 7.x initialization intact.  The 8.x branch uses `ConfigLoRa_t` with 915,000,000 Hz carrier and 125,000 Hz bandwidth, SF9, CR7, sync 0x12, 10 dBm and 8-symbol preamble.  It sets `tcxoVoltage=RadioLibTCXOVoltage_t::Voltage1V8` and `useRegulatorLDO=false` before initialization.  Receive-action aliases call the same rising-edge DIO1 attach/detach functions used by 7.3.0.  No installed Arduino library is edited or downgraded.  The firmware identifies itself as trial2 and reports its RadioLib version.

All five checked v0.8.4e sleep/IRQ/ACK/clock function bodies remain byte-identical.  The timetable protocol, layout, font assets, NVS behavior and duty/transmission schedules are unchanged from trial1.  RadioLib internals themselves differ between releases, so hardware validation is still required.

Two actual ESP32-S3 Plus builds passed with core 3.3.2 and the same board options and other dependencies as below:

| RadioLib | Program bytes | Static RAM bytes | Result |
| --- | --- | --- | --- |
| 7.3.0 | 1,438,951 | 51,568 | Compile/link passed |
| 8.0.0 | 1,446,495 | 51,416 | Compile/link passed |

The existing ASan/UBSan host protocol tests and all five baseline function hashes passed.  The complete refreshed `OTD_Unified_086_Trial.zip` contains 38 files, 17,003,253 bytes, SHA-256 `fb1ef3d809d0619f8ea027472a9df108643e93c0bef570a94ac8545832c9affd`.  It contains separate build artifacts for both RadioLib versions, a refreshed receipt, changelog and the in-place installer.

### Owner's existing Windows installation

The owner prefers all future gateway/sign deliveries under `Documents/OTD`, with versioned folders and shared settings.  The existing trial sketch is under `Documents/OTD/OTD_Unified_086_Trial/OTD_Unified_086_Trial/OTDUnified_v086`.  This cloud session has no direct access to that Windows drive.

`Apply_OTD_086_Trial2_Fix.py` defaults to that sketch folder beneath the current user's home.  It checks the complete original source against known original/corrected hashes, backs up the affected files under `Documents/OTD/backups`, and installs the updated .ino, version label and compatibility header plus a repair note.  It stops on local edits, is idempotent, and attempts rollback if a write fails.  It does not open serial, flash firmware, install libraries, read credentials, stop the gateway or change Task Scheduler.  Close/reopen the Arduino sketch around the repair, then Verify and Upload to the bench device.

The in-place installer changes source only.  Any original trial1 binaries/receipt outside the sketch remain trial1.  The corrected full ZIP supplies matching trial2 binaries and receipts.  Installer tests on temporary original-sketch copies passed for apply/exact compiled source, backup, repeat run, rejection of edits, and injected mid-write failure rollback.  Tests ran on Linux Python; no Windows execution or hardware upload was performed.

Bench sequence remains standalone headless timetable fetch, then capable-peer transfer/missing-page repair.  Production Museum installation remains unchanged by this session.

Upstream change reference:  https://github.com/jgromes/RadioLib/releases/tag/8.0.0

## Historical trial1 record

Prepared 19 November 2026.  Status: compiled and host-tested, awaiting physical bench tests.  The Museum field baseline remains sign v0.8.4e, receiver v0.8.5 and PC gateway 0.8.5.1.  No installed device or Windows task was changed.

## Owner package and build

Owner package: `OTD_Unified_086_Trial.zip`, 8,695,481 bytes, 30 files.
SHA-256: `f23709e1a2b6069bcaf00302e8681e1023f0341e116f1d9bc2f5eec6fb7292b2`.

The package contains the complete candidate sketch, embedded outline-font sources/licences, compiled Plus application and ELF, build receipt and source hashes, host tests, setup/acceptance instructions, and the original v0.8.4e display and v0.8.5 receiver sources for rollback.  As with the preceding Museum hardware packages, the complete owner bench bundle is delivered separately rather than publishing the owner's earlier diagnostic firmware archive here.

The verified target is `esp32:esp32:XIAO_ESP32S3_Plus:PSRAM=opi,CDCOnBoot=default`, ESP32 core 3.3.2, Arduino CLI 1.6.0, RadioLib 7.3.0, ArduinoJson 7.3.2 and Seeed_GFX 2.0.3 at commit `0dfdd7135425be82b5bb4b4b58d74dd51ab29a59`.  In this core, `CDCOnBoot=default` means Enabled.  The default Plus partition layout has a 2 MiB application partition.  The application uses 1,438,575 bytes and static RAM uses 51,568 bytes.  Runtime allocation and hardware stability remain to be measured.

No font-generation step is required.  The same sketch supports headless gateway, EE04/TRMNL display stop and combined gateway/display through persistent runtime configuration.  Other ESP32 board definitions require their own verified builds; the supplied Plus binary is not universal.

## Implemented scope

This is a direct, single-gateway, single-capable-peer Museum stop 11000262 / route 6 trial.  It is not the multi-stop mesh milestone and is not MeshCore compatible.

- New hardware starts in commissioning mode.  `node hardware headless|trmnl`, `node role gateway|stop`, and `node power mains|battery` select the installation.  Hardware/role changes require `node reboot`.  The sketch probes the supported SX1262 pins after commissioning.
- Gateway eligibility requires responding LoRa, configured Wi-Fi and the installer's persisted mains declaration.  Removing that declaration suspends coordinator work and permits receiver/local-timetable operation.  Automatic USB detection and solar sufficiency decisions are not implemented.
- Wi-Fi acquires NTP time and the existing published `otd-stop-schedule-v1` snapshot.  It validates stop, route, source, epoch bounds, strict event order, CRC and contiguous covered dates including today and tomorrow.  HTTPS response storage is bounded to 16 KiB.  It disconnects between fetches; successful checks are six hours apart, failed attempts retry at least five minutes apart, and `sync` can request an immediate attempt.
- A complete schedule envelope is committed as one NVS blob in `otd-node`.  Invalid, incomplete or unsuccessfully stored revisions do not replace the active revision.  Existing network and legacy cache namespaces are retained.
- A peer requests the explicitly versioned trial format.  Metadata and pages are addressed to its node ID.  Missing-page bitmaps coalesce repair work.  The gateway leaves at least three seconds after each transmission before its next transmission and services only one peer job at a time.
- A peer requests repair every 45 seconds until complete; completed peers check revision and time every 15 minutes.  An active peer job expires after two minutes.  A recently heard coordinator session is pinned for two minutes.  There is no coordinator election.
- The legacy Museum OTD2/OTDA2 path is separately enabled by `node legacy on`.  Its default is off.  It sends SCHED information only, uses the existing 20-minute active window and 15-minute idle interval, suppresses routine next-day quiet traffic, and responds to matching BOOT/STALE requests.  Matching ACKs and timeouts are logged.
- The candidate does not implement the v0.8.5 USB bridge command interface.  Restore the bridge before reconnecting the PC sender if its production receiver was used in the trial.

## Trial frames

These are bench protocol identifiers, separate from any later multi-stop mesh protocol.  Stop/route scope is fixed to Museum in this candidate.

| Frame | Fields after identifier |
| --- | --- |
| OTNQ1 | stop ID, route, peer ID (8 hex), cached revision (8 hex), incoming revision (8 hex), received-page bitmap (8 hex) |
| OTNM1 | coordinator session (decimal), destination peer (8 hex), stop ID, route, current epoch, revision (8 hex), event count, coverage start, coverage end (exclusive) |
| OTNP1 | coordinator session, destination peer (8 hex), revision (8 hex), zero-based page index, count in this page, comma-separated departure epochs |

Limits are 220 bytes per frame, 160 events, ten events per page and sixteen pages.  Revision is CRC32 over little-endian 32-bit departure epochs.  The assembler rejects invalid metadata, out-of-range or unsorted values, wrong session/revision, changed duplicate pages and a complete set with a bad CRC.  A successful cached-revision request transfers metadata/time without repeating the complete timetable.

Radio time follows the existing trusted-installation model, not cryptographic authentication.  Trial frames do not establish general mesh security or multi-coordinator correctness.  No source-age semantics for live forwarding are claimed because this trial carries only static departures and clock metadata.

## Regression protection and tests

The following v0.8.4e functions are byte-identical in the candidate: `restoreRadioInterruptAfterSleep`, `maybeLightSleep`, `sendAcknowledgement`, `restoreProvisionalClock`, and `rememberTrustedClock`.  Deep sleep remains disabled.  The display is allocated/initialised only for the TRMNL hardware profile, and headless nodes do not use the TRMNL battery ADC pins.  The candidate uses an uncalibrated 1.0 battery multiplier; no owner-specific calibration is used for gateway eligibility.

Both C++ test executables pass with AddressSanitizer and UndefinedBehaviorSanitizer.  Leak detection is disabled because the build environment does not support it.  Coverage includes:

- Missing-page repair, reordered and duplicate pages, conflicting duplicates, maximum-size and short final pages, epoch/count bounds and numeric overflow.
- Changed coordinator/revision, full-set corruption and retention of the previous complete revision.
- The actual trial adapter with deterministic radio/NVS/time mocks: destination/route isolation before setting time, a deliberately dropped page, failed NVS commit and retry, restart restore, coordinator pinning, selective retransmission, legacy-transmission gating and withdrawal of mains power eligibility.
- Hash checks for the five unchanged recovery/ACK functions above.
- An actual ESP32-S3 Plus compile/link, with build receipt and ELF retained.

These checks do not establish physical Wi-Fi connectivity, RF delivery, display correctness, runtime memory margin or sleep stability.

## Next bench evidence

1. Fetch and restore the timetable on a spare headless node powered without the Windows sender.  Record upstream success, trusted clock, revision, count and coverage.
2. On a freshly configured radio-only peer, enter `trial drop page 2` before its first transfer, then start the candidate gateway.  Verify the one-time drop, missing-page request, selective repair and complete commit.  Use page 0 for a schedule with fewer than three pages.
3. Interrupt a transfer with a deliberate peer reset.  Test gateway/Wi-Fi loss after a complete commit.  Check cached service and explicitly provisional time after an offline reset.
4. Run the same firmware as combined gateway/display and inspect physical updates plus radio delivery.
5. Separately stop the existing Windows Museum sender before enabling candidate legacy transmission.  Confirm Museum ACKs and correct scheduled departures.  Disable candidate legacy traffic before resuming the stable sender.
6. Change the gateway declaration to battery and verify coordinator transmissions stop while local service continues.

Preserve the current Museum installation as the comparison baseline.  Record intentional resets separately.  No candidate hardware upload or field test has yet been performed.  Live upstream acquisition on the MCU, forwarding, negotiated multi-stop schedules, solar trends and automated duty selection remain subsequent development.
