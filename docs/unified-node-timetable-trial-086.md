# Unified timetable trial 0.8.6-trial1

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
