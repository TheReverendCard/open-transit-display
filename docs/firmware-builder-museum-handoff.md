# Website firmware builder handoff: Museum LoRa / e-paper alpha (13 October 2026)

This document is the cross-conversation handoff for the firmware builder on the Open Transit Display website. A separate Website/layout conversation owns the Nimbus Sans asset licence and conversion pipeline. The device/hardware conversation owns the reference XIAO + EE04 + Wio-SX1262 sketch and consumes the generated font output.

## Canonical sources

- Display **geometry, badges, separators, conditions, refresh regions**: firmware/layouts/site-default.json, specifically rendering.single.regions / rendering.single.route_badge / rendering.single.separators.
- Font provenance, hashes and licence: docs/site-fonts-and-layout.md; the font pipeline is owned by the website/layout conversation.
- Hardware behaviour & offline fallback: docs/architecture.md; firmware/README.md.
- Current hardware-alpha reference: firmware/alpha/museum-v0.3/README.md and sketch subfolders.
- Current direct-LoRa application packet: OTD1|unix|route|direction|stop|scheduled_unix|predicted_unix|source|previous_unix|following_unix|next_service_unix.

## Builder requirements

1. Offer distinct **hardware targets** instead of treating all devices as one:
   - XIAO ESP32-S3 Plus + Seeed EE04 7.5-inch UC8179 + optional Wio-SX1262 B2B.
   - Mains/Wi-Fi-only or other future reference devices once supported and hardware-tested.
2. Export **prebuilt, reproducible firmware binary** after firmware compilation and hardware checks exist. Require board-specific options: PSRAM OPI, USB CDC on boot, selected display variant, installed firmware version, and revision/commit SHA.
3. Export a **per-stop configuration** separate from the code where feasible: agency, GTFS stop ID, public route number and direction, timezone, display profile, feed URL and fallback model ID. The Museum Route 6 test uses stop 11000262, but must NOT hardcode that into all user builds.
4. Preserve display data state labels LIVE / CACHED / EST / SCHED. Static schedules are not live predictions. Clock is never labelled SCHED. Use freshness expiry and provenance; prevent date-specific GTFS service times from being rendered after their covered service date.
5. Keep local static timetable and weekly historical fallback independent of the internet and radio, including resilience across loss of battery power. Current v0.3 alpha does **not** yet do this; it is a gap, not a completed builder feature.
6. Generate and include Nimbus Sans converted font arrays from the pipeline maintained by the website conversation. Preserve Māori macrons. Verify applicable Artifex/URW AGPL-3 font licence terms for distributing embedded derivatives; no assumption that the PostScript/PDF exception covers firmware. Do not require end users to convert fonts locally.
7. For the EE04/Wio combination, **coordinate shared SPI** and GPIO38 display-reset/radio-RF-switch use. Use the screen library's SPIClass in RadioLib and preserve the verified antenna/pin configuration. Do not overwrite the XIAO pin map with generic ESP32 defaults.
8. Keep transport modular: OTD1 is a current **direct LoRa test**; it is not MeshCore. A future transit-organisations branch may provide direct managed LoRa; a future resilient mesh branch may adopt MeshCore integration with an explicit app-message envelope, addressing, retries, and power policy.
9. Gate advanced options on hardware proof: UC8179 partial refresh must be physically validated; 30 partials / 45-minute full refresh policy; clock minute intervals; 5-minute night "~" clock; deep sleep before first service and the full morning refresh. Deep sleep is **OFF** in alpha.
10. Avoid bundling the local test's voltage-derived battery percentage/runtime estimator into the public firmware builder. It is experimental only and assumes 20 mA current, not measured consumption.

## Compatibility contract between builder and firmware (proposed, NOT yet implemented)

A versioned manifest should describe board_id, display_id, firmware_version, layout_schema, supported transports, source modes, configurable stop fields, generated-font asset version, RTC/DST handling, deep-sleep availability, partial-refresh validation status, and Git commit. The builder should pin the manifest revision and reject unknown layout or payload schema versions rather than silently producing mismatched firmware.

For transit data packets, keep the logical arrival payload transport-independent. Future schema should include stop_id, service_date, route_id, trip_id, departure_epoch, prediction_epoch, source, generated_epoch, expiry_epoch, sequence, network scope, and authenticity markers. The current OTD1 payload is **only** an alpha interoperability test, with no acknowledgement, security or routing.

## Validation and release gates

- Alpha v0.3: sources in a review branch; reported v0.2 compile errors patched, compilation on Arduino 2.x still unverified.
- Prior basic demonstration: five LoRa packets successfully received and displayed; battery-only operation confirmed.
- Beta requirements: confirmed compilation + successful Museum stop message on real display + repeat partial refresh + power measurement + persistent offline fallback + testable recovery.
- Website builder should show alpha status, not advertise a production firmware download, until gate checks are complete.
- Website agent should use this document and the associated issue/PR to track builder/firmware divergence, and update handoff on future firmware changes.
