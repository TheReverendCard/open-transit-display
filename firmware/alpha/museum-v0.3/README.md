# Museum LoRa e-paper alpha v0.3 (reference source)

**Status: DEVELOPMENT / ALPHA. Not a production firmware release.**
The earlier basic LoRa text sender/receiver successfully transferred and displayed five packets and ran from battery on actual XIAO ESP32-S3 Plus / Wio-SX1262 / 7.5" TRMNL hardware. **This Museum-specific v0.3 source has NOT been compiled or verified on the user's hardware yet.** It addresses two compiler errors reported for v0.2.

## Device and source of truth

- 800 x 480 black-and-white UC8179, XIAO ESP32-S3 Plus, Seeed EE04 e-paper board, Wio-SX1262 B2B.
- Seeed_GFX + RadioLib. Shared SPI instance: **use the e-paper library's SPI instance**, not a second instance reassigning the same pins. LoRa GPIO38 RF switch HIGH for receive, LOW for transmit; GPIO38 also resets the e-paper panel. Display work must be coordinated with radio activity.
- Site layout authoritative: [site-default.json](../../layouts/site-default.json). In particular, prefer rendering.single.regions and rendering.single separators to the older generic single rectangles.
- Font conversion owned by website/layout conversation. Integrate its generated Nimbus Sans bitmap font assets when published. Preserve correct licence notices; do not copy proprietary or unverified font assets into firmware.
- Current built-in fonts approximate the layout; this is NOT yet visual parity with the website.
- Current protocol is **OTD1**, a test application payload sent over direct RadioLib LoRa. It is NOT MeshCore or Meshtastic. Separate application payload from transport in future refactoring.

## v0.3 source and dependencies

- MuseumLoRaDisplay/MuseumLoRaDisplay.ino + MuseumLoRaDisplay/MuseumTypes.h + MuseumLoRaDisplay/driver.h
- MuseumLoRaSender/MuseumLoRaSender.ino
- gateway/museum_gateway.py (requires pyserial and tzdata on Windows)
- Board: XIAO_ESP32S3_PLUS; Tools -> PSRAM -> OPI PSRAM; USB CDC On Boot -> Enabled.
- Install Seeed_GFX and RadioLib. **Two LoRa antennas attached before TX.**

## Fixed from v0.2

1. The auto-generated Arduino forward declarations referred to Rect and TransitData before the struct definitions. Both types now live in MuseumTypes.h included before function bodies. This is intended to remove the "'Rect' does not name a type" / "'TransitData' does not name a type" errors.
2. Some ESP32 newlib toolchains omit tm_gmtoff. Sunrise/sunset logic now uses tm_isdst with the explicitly configured NZST/NZDT timezone.
3. Museum stop ID is 11000262. The string YOUR_STOP_ID is not a valid argument.

## Running on Windows

In Arduino IDE, flash the display sketch to the e-paper board and the sender sketch to the USB-connected Wio board. Leave the display on USB during initial tests and open its Serial Monitor at 115200. Close the sender's Serial Monitor.

From gateway/:

    py -m pip install pyserial tzdata
    py museum_gateway.py --list-stops museum
    py museum_gateway.py --stop-id 11000262 --dry-run
    py museum_gateway.py --port COM5 --stop-id 11000262

Use the actual sender COM port instead of COM5. Museum was the only Route 6 stop matching "museum" in the referenced 2026-10-13 snapshot, at approximately -35.74277, 174.26968.

The gateway checks current service-date coverage in the generated feed-data/citylink/gtfs.zip and refuses to send an expired date. **The date-specific, provider-derived GTFS is not an official permanent schedule.** The gateway sends SCHED, not live ETAs. Production firmware must maintain persistent static and historical fallback data across battery loss.

## Expected display/clock logic (not yet field validated)

- Day: clock changes at most once per minute.
- After local calculated sunset: display approximate clock "~HH:MM", rounding down to 5-minute multiples.
- Clock updates never wake a sleeping device.
- Draw static fields using the authoritative layout; change dynamic regions without repainting unchanged fields where possible.
- UC8179 Seeed_GFX method is updataPartial(x,y,w,h) (exact spelling). **Partial refresh remains enabled for a controlled experiment**, not yet panel validated. Set ENABLE_PARTIAL=false in source if ghosting occurs.
- Full refresh after 30 partials, 45 minutes, or a major layout change.
- Overnight deep sleep flag is deliberately FALSE. The proposed 20-minute pre-service wake requires tests of correct next-day service, fresh-date validation, RTC wake, fallback, and full morning refresh.
- Version currently retains the previous drawn e-paper image while asleep; RAM is not durable across power loss.

## Test plan

- [ ] Compile v0.3 receiver and sender with matching board/library versions.
- [ ] Load actual Museum stop 11000262 and confirm packet on receiver serial.
- [ ] Confirm single, repeated, and concurrent clock/ETA partial refresh.
- [ ] Check full refresh and observe 30 partial / 45-minute maintenance.
- [ ] Validate approximate local sunrise/sunset and NZ DST changeovers.
- [ ] Battery-only reception after screen refresh.
- [ ] Independent measured current draw: active RX, full refresh, partial refresh, deep sleep.
- [ ] Validate fallback data and wake before enabling overnight deep sleep.
- [ ] Migrate Nimbus Sans fonts when website pipeline publishes generated arrays.
- [ ] Publish builder-compatible reproducible flash images after hardware testing.

## Battery diagnostics

**Not committed to this repository/reference.** A local-only diagnostic variant of this test measures battery voltage using Seeed TRMNL OG GPIO1 (ADC) and GPIO6 (enable) and labels voltage-derived percentage and illustrative runtime assuming a configurable 20 mA average draw. That estimate is not accurate enough for public signage and must not enter released builds without measured calibration.
