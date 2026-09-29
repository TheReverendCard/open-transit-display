# Reference firmware

The first firmware target will be a Wi-Fi shop-window display. Hardware selection is not final yet, so this directory currently defines required behaviour rather than tying the project to one board.

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
no more services today     sleep until pre-service window tomorrow
```

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
