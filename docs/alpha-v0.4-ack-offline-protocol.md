# OTD v0.4 alpha: numbered ACK and date-scoped offline timetable

**Status:** Test protocol, not production, MeshCore, a relay, or live ETA. The hardware-tested sign/sender image remains v0.3.2 until the user verifies the separate local candidate. No sleep is enabled in this stage.

## Physical radio guardrail

Both radios: SX1262, 915 MHz, BW 125 kHz, SF9, CR 4/7, sync 0x12, 10 dBm, preamble 8, 1.8 V TCXO, antenna installed. The EE04 board shares GPIO38 between e-paper reset and the Wio's RF path. Never transmit while driving the panel. Read RX payload completely, radio standby, await USB bridge RX turn-around, RF switch GPIO38 LOW, transmit, return GPIO38 HIGH, startReceive. During full-screen 800x480 refresh, stop radio RX; only resume after panel sleep. Hardware v0.3.2 had 91/91 received six-minute telemetry messages across nine battery-only hours with no missing telemetry seq.

## OTD2 live gateway test envelope

`OTD2|session|seq|unix|route|direction|stop|scheduled|predicted|source|previous|following|nextService`

Each gateway process creates a random nonzero session; seq counts every minute from 1. Sign must validate the packet and answer after received data is consumed:

`OTDA2|session|Nseq|11000262|battery_mV_or_0|received_count|inferred_seq_gaps`

The battery reading is carried approximately every five minutes; other ACKs carry zero millivolts. The gateway matches session and message ID to sent messages and logs ACK RTT and timeouts. Count source packet sequence gaps separately; missing ACKs are *not* direct proof of a missing inbound frame. USB bridge must return to RX before sign ACK TX starts.

## OTDL1 complete timetable pages

`OTDL1|session|11000262|CRC32_HEX|page|totalPages|entriesOnPage|epoch,epoch,...`

A page carries at most 10 POSIX epoch seconds for real, explicitly covered GTFS service dates. Maximum 160 entries in at most 16 pages. The 8-digit checksum is CRC32 over a comma-separated, strictly ascending ASCII list of ALL event timestamps, `zlib.crc32(joined.encode("ascii"))`. The sign accepts pages from one revision, never combines revisions, validates time range and count, and commits one NVS blob **only after all pages and the overall CRC succeed**. On reboot, it validates the same checksum and ordering before accepting stored bytes. Keep the previous valid schedule until the next full revision has been received. Never project a date-specific derived GTFS feed forward as an indefinite weekday timetable.

Page ACK uses:

`OTDA2|session|Pindex-CRC32_HEX|11000262|0|received_count|inferred_seq_gaps`

This ACK means only that the page passed immediate validation; a complete persisted schedule requires sign-side `OFFLINE COMMITTED` evidence. Resend pages at intervals until the full revision is complete. In the test implementation, hold initial pages eight seconds after the first OTD2 packet to avoid the sign's ~3.4s full-screen refresh, and space pages 4.5 seconds apart.

## Acceptance sequence

1. **Arduino Verify both sign and sender** on the exact XIAO ESP32-S3 Plus / Seeed_GFX / RadioLib toolchain. Candidate has not yet had physical or Arduino compilation verification. PC-side Python syntax and isolated protocol-format/CRC tests pass.
2. Gateway prints numbered OTD2 ACKs, gap/timeout totals and sporadic actual battery millivolts; verify sign continues after bidirectional mode switching.
3. See `OFFLINE COMMITTED` once pages are complete; interrupt gateway, observe the clock continue and date-correct stored departures progress beyond the old one-packet horizon.
4. Restart gateway, confirm sign resets the sequence gap counter for a new session and sees fresh ACKs.
5. Conduct a full 24-hour cycle (first/last service, midnight, planned outages) **only** when feed coverage includes the next day and steps 1–4 pass. Preserve acknowledgements CSV, battery telemetry CSV and photos.
6. Add coordinated gateway wake/listen windows as a *separate power test*. Do not enable deep sleep while investigating ACK or schedule faults. Scheduled relaying will need explicit third SX1262 node and origin+TTL dedupe.

## UI and safety

Use full-screen UC8179 refresh as the selected legibility-first policy. For Museum stop 11000262 / Route 6, passenger-facing destination is Rose Street / CBD, not “Clockwise”. The native Nimbus Sans renderer is a separate workstream; scaled built-in fonts remain temporary. `SCHED` is timetable-only, not live tracking. Stale gateway status must not erase date-valid locally stored departures. Do not announce a bus has departed from elapsed timetable alone. The local diagnostic battery ADC percentage/runtime estimate is **not calibrated and must not be committed to public firmware**.
