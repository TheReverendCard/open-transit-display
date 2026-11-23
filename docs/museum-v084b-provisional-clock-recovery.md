# Museum sign v0.8.4b: provisional clock recovery (private firmware candidate)

**Status on 6 November 2026:** candidate package built and software tests passed; **not Arduino-compiled or field-verified**. This document is an architecture and test handoff, not a declaration of a production release. Firmware with local battery calibration remains private to the owner and is deliberately not committed to this repository.

## Verified field context

- The v0.8.4a-plus-light-sleep Museum sign operated for almost eight days on its 2000 mAh battery. A 3.90 V to 3.40 V voltage segment lasted about 4.26 times longer than the earlier no-light-sleep build. LoRa, minute display, and GPIO39 timer wake remained functional in the run.
- With the gateway disconnected overnight (6 November), the sign still correctly showed 07:37, previous scheduled 07:15, next 08:15 and following 09:16. Light sleep retained the running software clock.
- After manual sign RESET while the gateway was still disconnected, the display correctly showed `CLOCK NOT SET`, `TIME UNSYNCED`, and saved **date-labelled** departures. It had lost authoritative time.
- Restarting the gateway caused the sign to recover its time immediately and choose the correct departure, with no sign reboot. This validates the LoRa time bootstrap path, not independent cold-boot timekeeping.

## Candidate change (v0.8.4b)

1. Continue storing the authoritative Unix epoch in the existing NVS `Preferences("otd-sched")` key `lastclock`. Previously saved at most hourly when a timestamped packet arrived; now checkpoint **approximately once per 60 seconds** while the sign's already-synchronized software clock advances, including during a prolonged gateway outage.
2. On boot with no authoritative time, read the checkpoint as an **approximate lower-bound anchor** and advance it by `esp_timer_get_time()`, which remains monotonic through light sleep. Display `~HH:MM` with **TIME ESTIMATED / SYNC PENDING** and `TIME APPROXIMATE` instead of an empty clock.
3. **Do not call `settimeofday()` from the NVS estimate and do not set `clockValid=true`.** The estimate never authorizes live ETA, DUE, NEXT, accurate countdown, service-day inference, nor actual timetable selection. Display only saved **dated** departures while untrusted. Long power outages can leave even the approximate time hours or days wrong; this is explicitly disclosed on the display.
4. A validated OTD1/OTD2/OTD3 gateway packet or successfully synchronized NTP restores the real clock and clears the provisional label immediately. An untrusted saved value must never trick the existing Wi-Fi bootstrap logic into reporting successful NTP.
5. After estimated-time reboot, preserve light sleep using the estimated monotonic clock for timer scheduling; preserve GPIO39/DIO1 RX wake, shared GPIO38 radio/panel handoff, existing USB Serial Monitor guard, full 800x480 refresh policy, existing OTDQ1 HELLO/retry and date-specific cached timetable. Deep sleep stays disabled.
6. Add USB diagnostic command `clock status` to print `trusted`, `provisional`, `persisted` and `estimated` epochs. Keep `sleep status`.

The change is confined to sign source and one tiny pure C++ clock helper. **Gateway firmware, Windows gateway, on-air protocol, cloud service, batteries, NVS timetable data and credentials are not changed.**

## Durability and safety

60-second NVS saves mean up to ~525,600 small writes/year. ESP32 NVS has wear levelling and page compaction, but actual lifetime and energy impact depend on hardware flash allocation. Verify under realistic use; the interval is a compile-time constant, not a commitment to unlimited writes. Never store guessed time as though it were synchronized. Firmware upgrades should use **Erase All Flash OFF** to retain `lastclock` and timetable cache.

The validated approximately week-long battery run was for the predecessor light-sleep build, **not** an endurance test of v0.8.4b. A second extended power test is premature until reset/time recovery and USB reflashing are verified.

## Release artifacts and rollback

Private owner delivery contains:
- a full source ZIP with `MuseumDisplay_v08_4b_FULL_FONT` and existing Python gateway;
- a Windows PowerShell patch that creates a **new sibling Arduino sketch folder** from the owner's light-sleep-patched v0.8.4a and copies existing generated font headers, battery constants and configuration code untouched;
- a pure C++ checkpoint helper, 21 host-side assertions, 18 integration/static checks, and detailed README.

The patch checks source revision and anchor uniqueness; it refuses to overwrite the old working sketch or the new folder. Existing font bitmaps and font files are **not** distributed or published. Restore the original v0.8.4a sketch if hardware validation fails.

## Completed checks

- Existing v0.8.3/v0.8.4/v0.8.4a gateway and calendar Python suites: **36 tests pass**.
- New C++ clock checkpoint/restore helper: **21 assertions pass**, compiled with `g++ -std=c++17 -Wall -Wextra -Werror`.
- New static firmware safety checks: **18 pass**.
- Patch manifest reconstructed the exact v0.8.4b sketch and OTDConnectivity header from the prior v0.8.4a source with the field-used light-sleep patch.
- ZIP CRC and Python syntax verified.

**Not yet run:** PowerShell on Windows, Arduino IDE Verify/Upload, direct ESP32-S3 hard-reset test, long-offline trial, NVS wear measurement or verification of USB CDC attach/detach behavior. These remain release blockers.

## Hardware acceptance matrix

1. Upload on a charged sign with the gateway available. Verify synchronized `HH:MM`, correct next cached departure, LoRa ACK, and `clock status` `trusted=1`.
2. With gateway offline, run >2 minutes; confirm minute checkpoints while trusted and continued timetable updates.
3. Reset sign with gateway still offline. Verify `~HH:MM`, `TIME ESTIMATED`, dated saved departures and NO live/accurate departure countdown. The estimate must advance and light sleep must remain functional.
4. Let the sign remain completely without power for a much longer period; confirm estimate is **still marked tentative** and never claims a current countdown.
5. Start gateway without touching the sign. Verify time snaps to actual, estimate warning clears, scheduled next departure and LoRa ACK resume.
6. Validate NTP backup where configured. Verify USB Serial Monitor and normal BOOT/RESET firmware upload; inspect `esp_reset_reason()` if resets recur.
7. Continue to keep a printed schedule at passenger-facing test stops until no-gateway cold-boot behavior and display labels are understood.

Related: issue #10 (network and power integration), issue #9 (clock/refresh policy), issue #13 (ETA freshness and reconnection). The external battery-backed RTC remains an optional later hardware enhancement for truly accurate time through arbitrary unpowered intervals.
