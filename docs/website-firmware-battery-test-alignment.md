# Website setup alignment with Museum battery testing

Reviewed 13 October 2026 against [builder issue #3](https://github.com/TheReverendCard/open-transit-display/issues/3), its hardware observations and the alpha branch handoff.  This records next-version work; it does not enable untested firmware features.

## Current website and device are separate test paths

The hosted website offers a USB framebuffer renderer test.  Its installation replaces the current device firmware, uses full refresh for each uploaded image, and stores the preview for restart.  It does not receive OTD1, automatically fetch transit data, run the Museum gateway or implement overnight polling.  Keep that status explicit.  Do not install the USB renderer during an ongoing Museum battery endurance test.

Museum v0.3 is a separate direct-LoRa alpha.  The local battery diagnostic variant has compiled, uploaded and rendered on hardware; successful OTD1 reception in this build, refresh reliability and power measurements remain separate checks.  Continuous LoRa receive remains enabled and overnight deep sleep disabled in the reference alpha.  The original branch README's uncompiled statement predates the local test and does not establish that the committed source was compiled unchanged.

## Website setup steps for the next firmware version

1. Select agency, stop, routes/direction and review the whole day's preview.  Preserve selection when opening the designer.  Distinguish same-day previous departure from a previous day's last service; do not show yesterday's time beside tomorrow's first service without its date.
2. Select the exact hardware target and transport.  Pin XIAO ESP32-S3 Plus, EE04 UC8179 800x480 and optional Wio-SX1262 B2B.  Direct OTD1 LoRa, Wi-Fi and future MeshCore are different capabilities.  Preserve shared SPI and GPIO38 coordination from the hardware handoff.
3. Select a version-labelled build and display implemented capabilities from its manifest.  Record board/display, firmware commit, supported configuration/layout/payload schemas, font/layout hashes, partition size, refresh validation and power features.  Reject incompatible custom layout schemas or transport choices.  Current site exports schema 1.0 configuration and schema 2.0 custom layouts; Museum does not yet consume these as a complete provisioning contract.
4. Include generated Nimbus Sans arrays at native sizes, UTF-8/macrons, clipping and fitting, licence notices and the font manifest.  Full default font data currently needs about 3.5 MB plus firmware; check actual partition and linked size.  Font conversion CI is delivered; device integration is pending in PR #5.
5. Offer overnight check-in settings only in builds that implement them.  Proposed test defaults are 15-minute polls, optional 5 minutes for shorter alert latency and 30 minutes in conservation mode.  Wake at the earlier of the next poll and 15–20 minutes before the next valid service.  Rounded nighttime clock updates must not independently wake the device.  Choose the final pre-service value with the hardware agent and version it.
6. Explain that messages arrive during check-ins, not immediately.  Gateway must queue scoped alerts/cancellations and timetable revisions with generation/expiry timestamps, sequence, ACK/retry and clock synchronisation.  OTD1 currently lacks acknowledgement, authentication and routing; do not present it as authenticated public emergency signage.
7. Provision persistent per-stop static timetable and historical fallback, service-date range, timezone/DST and expiry handling.  Refresh expired snapshots; never continue yesterday's date-scoped departures.  Show LIVE/CACHED/EST/SCHED honestly when gateway or upstream feed is unavailable.
8. Install only after matching target/build checks.  Package gateway script, dependencies and instructions together; commands must run from the folder actually containing museum_gateway.py.  Show selected stop ID and sender COM port.  Configuration download alone does not flash or activate settings on the alpha.
9. Confirm a received packet, refresh, reconnect/restart and offline fallback before beginning a battery-only test.  An unchanged e-paper image is not proof that the device is running.  Keep voltage-derived percentage and assumed runtime out of public builds until calibrated.

## Hardware-dependent release checks

- [ ] Resolve overlapping nighttime clock digits: clear and clip the full aligned update window, preserve framebuffer, investigate controller waveform/temperature and compare with full refresh.  Do not mark partial refresh validated yet.
- [ ] Confirm packet reception after screen refresh and shared GPIO/SPI recovery.
- [ ] Integrate fonts, UTF-8 gateway text and same-day/date-aware departure context.
- [ ] Implement periodic overnight TX/poll/RX, queued replies, missed-poll recovery, RTC/DST and pre-service wake.
- [ ] Measure assembled active RX, poll TX/RX, full/partial refresh and sleep current, including radio CS/NSS leakage and charger losses.
- [ ] Validate persistent timetable recovery after power loss, coverage expiry and gateway outage.
- [ ] Establish battery/solar thresholds and cloudy-day energy budget from measurements; no nominal-capacity runtime promises.
- [ ] Compile reproducible target-specific binaries and expose alpha/beta status from evidence.

## Ownership and next review

Website/layout conversation owns builder guidance, schema compatibility checks, fonts and export contracts.  Hardware conversation owns radio/panel/power implementation and physical validation.  Update issue #3 and this document when battery observations change a capability or default.  No background monitoring is configured by this document.
