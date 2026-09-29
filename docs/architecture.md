# Architecture

## Principle

Transit service to the passenger is the mandatory function. Everything else is opportunistic and must never make the display less reliable.

## Display data priority

Every display keeps enough local data to remain useful without network access.

1. Current live prediction from the shared backend.
2. Current live prediction received through LoRa mesh, if fitted.
3. Recently cached live response while still within its freshness limit.
4. Weekly historical fallback profile stored locally.
5. Published static timetable stored locally.

A Wi-Fi-only shop-window display includes levels 3 through 5 even when no LoRa hardware is installed.

## Power-aware roles

The same firmware should be able to choose behaviour from observed power conditions.

### Mains

- Frequent Wi-Fi/API refresh.
- Mesh gateway/repeater role allowed.
- Normal display refresh rate.
- Stop-request beacon can use generous timeout.

### Healthy solar

- Normal passenger-facing service.
- Mesh forwarding allowed when battery trend is healthy.
- Timetable-aware sleeping between relevant services.

### Solar conserve

- Reduce Wi-Fi wake frequency.
- Stop forwarding non-essential mesh traffic.
- Preserve passenger display, button wake and emergency alerts.

### Low battery / survival

- Deep sleep for long periods.
- Wake shortly before scheduled services.
- Wake immediately on stop-request button.
- Retain static/historical fallback on the e-paper panel.
- Avoid mesh repeater duty.

A future reference PCB should expose external-power presence, solar-input presence, battery voltage and preferably charge/discharge current or state-of-charge.

## Suggested node roles

### Display / leaf

Aggressively sleeps. Passenger-facing display remains visible because e-paper consumes no power to hold the image. LoRa receive windows can be scheduled around useful periods.

### Repeater

LoRa listening most or all of the time. Best suited to mains-powered or generously solar-powered locations.

### Gateway

Internet/Wi-Fi plus LoRa. Injects signed/validated transit and emergency updates into the local mesh.

## Passenger stop-request beacon

A weatherproof button can wake the device from deep sleep and activate a visible night beacon. The beacon should extinguish when the relevant bus is inferred or confirmed to have departed, or after a conservative timeout.

An optional second press when the bus arrives can be stored as rider-supplied arrival feedback. It is useful training/validation data but must never be required for the display to work.

## Mesh transport

Prefer an existing open LoRa mesh implementation such as MeshCore or Meshtastic rather than inventing a new routing stack. Transit messages should use a small project-owned application payload so the transport can be replaced later without redesigning the prediction/API layer.

Example logical payload fields:

```text
type: departure_update
agency: northland
stop: 11000155
route: 1102
eta: unix_timestamp
confidence_seconds: 90
generated: unix_timestamp
```

## Emergency information

The backend should eventually ingest official geographically targeted emergency alert feeds and assign them a priority above routine transit information. Critical alerts may take over most or all of the display; lower-severity alerts may share the screen.

## Prediction strategy

The agency realtime estimate is the incumbent. Challenger models should include simple interpretable baselines before complex machine learning:

- static schedule
- recent segment travel time
- same route/time/day historical performance
- buses ahead on the same segment
- rolling short/medium/long windows
- optional weather and calendar features
- later, a tree-based model or ensemble if justified

Evaluation should be split by ETA horizon. If a challenger is not materially better than the agency estimate, keep the agency estimate for live use and use learned timings mainly to improve offline fallback.
