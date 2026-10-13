# Reference firmware

The first hardware test target is the TRMNL OG 7.5-inch kit with XIAO ESP32-S3 Plus and EE04 UC8179 800x480 display.  The website USB renderer and Museum direct-LoRa alpha are separate test paths.  This directory defines required behaviour; implemented capabilities must be checked against the selected build.

## Current font and firmware responsibilities

See the [responsibility assignment and handoff contract](../docs/site-fonts-and-layout.md#responsibility-assignment-13-october-2026).

- **Website/layout conversation** owns source font assets, licensing/provenance documentation, automated font conversion and the reusable GitHub Actions font-generation step.
- **Hardware-testing conversation** (Museum-stop display and LoRa testing) owns consuming the generated fonts in Seeed_GFX, compiling ready-to-flash firmware, and validating the display on hardware.
- The hardware-testing conversation continues Museum-stop rendering, structured LoRa arrivals, regional refresh, daytime/nighttime clock behaviour and timetable-aware sleep/wake.
- Font conversion and its reusable GitHub Actions job are delivered and tested: [font package and integration guide](fonts/README.md), [successful build](https://github.com/TheReverendCard/open-transit-display/actions/runs/38363649629). The hardware conversation now integrates the generated package into its next firmware version and validates physical rendering. Neither conversation should hand the conversion task back.

## Website setup and battery-test coordination

See [website firmware battery-test alignment](../docs/website-firmware-battery-test-alignment.md) for current capabilities, next-version setup steps and release checks.  Do not replace the Museum battery-test firmware with the website USB renderer during an endurance test.  Overnight periodic check-ins are a next-version requirement, not implemented in the current Museum alpha.

## Non-negotiable fallback behaviour

Even the simplest Wi-Fi-only unit must retain locally stored data so loss of Wi-Fi, the backend, GitHub-hosted assets, DNS, or the upstream realtime feed does not blank the sign.

The device should retain:

- the published static timetable for its configured stop/route/direction
- the latest weekly historical fallback profile
- the most recent successful live response, with a timestamp and expiry
- configuration identifying agency, stop, route, direction and display profile

## Display source states

Suggested source labels:

- `LIVE` - current backend/mesh prediction
- `CACHED` - recent live response still considered useful
- `EST` - weekly historical fallback prediction
- `SCHED` - static timetable only

The label should be visible but secondary to the route and departure time.

## Power state machine

```text
MAINS
  -> frequent Wi-Fi refresh
  -> mesh gateway/repeater allowed

SOLAR_HEALTHY
  -> normal passenger service
  -> timetable-aware sleep
  -> mesh forwarding allowed

SOLAR_CONSERVE
  -> reduced network wakes
  -> no non-essential repeating

LOW_BATTERY
  -> wake near relevant services
  -> preserve display/button/emergency functions

SURVIVAL
  -> deep sleep almost continuously
  -> wake on button or scheduled service window
  -> static/historical display remains visible
```

Exact voltage/state-of-charge thresholds will be chosen after battery chemistry and power hardware are selected.

## Timetable-aware wake strategy

A sparse stop should not wake at the same rate all day.

Example policy:

```text
next service > 60 min      long sleep
20-60 min                  wake every 10-15 min
5-20 min                   wake every 2-5 min
< 5 min                    wake every 30-60 sec
service passed             return to long sleep
no more services today     periodic overnight check-ins + pre-service wake
```

Proposed overnight policy:  poll every 15 minutes, optionally 5 minutes for shorter alert latency, or 30 minutes in low-battery conservation.  Wake at the earlier of the next poll and 15–20 minutes before the next valid service.  These values require hardware testing.  Clock updates alone must not wake the device.  Queue timetable changes, cancellations and alerts at the gateway until the next check-in; delivery latency depends on the poll interval and retries.

Mains-powered nodes may choose to remain awake because they can contribute gateway/repeater capacity to the mesh.

## Stop-request button

The button should be wired to a wake-capable GPIO so it works from deep sleep.

First press:

- wake immediately
- mark rider waiting
- activate night beacon when appropriate
- report request through Wi-Fi or LoRa when available

Optional second press:

- record rider-confirmed arrival timestamp
- extinguish beacon
- upload/relay feedback when possible

If no second press occurs, the beacon should shut down after the bus is inferred to have departed or after a conservative timeout.

## Hardware profiles

Planned profiles:

1. USB-C/mains + Wi-Fi shop-window display
2. solar/battery + Wi-Fi display
3. low-power LoRa leaf display
4. mains/solar LoRa gateway/repeater display
5. fully independent solar roadside display with request button and beacon
