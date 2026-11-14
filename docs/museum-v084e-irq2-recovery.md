# Museum sign v0.8.4e radio wake recovery

13 November 2026. This corrects the v0.8.4b/c/d handoffs. Their sleep checks established that sleep, timer wake and GPIO39 wake were enabled. They missed the separate IRQ2 recovery implementation from the archived MuseumDisplay_v08_4a_LS_IRQ2_Diagnostics.ino. The endurance record contains the matching OTDP1 format. The exact field binary was not available for hash comparison.

Six ordinary gateway transmissions N564 through N574 (even numbers) went unacknowledged, each followed by a different BOOT nonce 13–16 seconds after submission. Each subsequent post-boot reply was acknowledged with RX=1. This occurs without a STALE HELLO. A missing GPIO interrupt restoration on wake is the leading explanation. The random v0.8.4c nonce carries no reset reason.

The private owner package OTD_v084e_IRQ2_Recovery.zip restores the archived IRQ2 mask-before-wake, per-pin wake disable and positive-edge ISR restore on wake, abort and setup failure, and level sampling in the normal receive loop. The ACK and rate-limited OTDP1 diagnostics are restored from that source. The v0.8.4d nonce still encodes reset reason. Nimbus outline fonts, clock checkpoint and passenger labels are retained. No gateway change or font generation is required.

Verified exact source equality for the mask/sleep/cleanup block, restore helper, ACK and power telemetry functions against the archived diagnostic sketch. Checked the asserted-pin receive fallback, 17 firmware invariants and host status/cadence checks. Arduino ESP32 core 3.3.5, RadioLib 7.4.0, Seeed_GFX 2.0.3 and ArduinoJson 7.4.2 compiled for XIAO ESP32S3 Plus with OPI PSRAM and USB CDC. Application 1,414,683 bytes, static RAM 50,564 bytes.

Initial field test criteria follow. With sign USB disconnected, look for five consecutive active-period packets acknowledged after the 30-second startup grace, increasing sign RX count, and a second OTDP1 under the same nonce with increasing uptime and sleep counters. Subsequently check an idle-to-active transition. Record unexpected BOOT reason and surrounding gateway traffic. For future releases, use this recovered sketch as the integration base and compare the actual interrupt lifecycle, not just the sleep enable flags.

## First-hour field result, 13 November 2026 NZDT

Passed the short-term reboot regression check. The gateway received all 28 ACKs for N614–N641, including 25 consecutive minute transmissions N616–N640. Boot ID 0B336F4A held across the initial idle heartbeat, the 11:55:08 STALE request and its successful reply, active service and the 12:34 idle heartbeat. At 12:34:10 the sign reported 3,653 seconds uptime, 3,349 seconds asleep, 28 GPIO wakes, 1,661 timer wakes and zero sleep errors. The gateway timeout count stayed at 36 throughout. Overnight stability and endurance remain open.

## Next-morning observation, 14 November 2026 NZDT

The operator reported that the sign appeared stable and was behaving properly the following morning. Together with the first-hour receiver measurements, this supports using v0.8.4e as the working Museum firmware baseline. Overnight boot-ID continuity and the first-service ACK were not independently verified from a receiver transcript. Battery endurance on this build remains unmeasured.
