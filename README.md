# Open Transit Display

Open Transit Display is an open-source project for inexpensive public e-paper transit signs that continue to provide useful information when internet connectivity or upstream realtime services fail.

The first deployment target is Whangārei, Aotearoa New Zealand. The software is deliberately structured so other agencies can later be added through standard public transit feeds such as GTFS and GTFS-Realtime.

## Design goals

- Large, readable e-paper displays for shop windows and outdoor stops.
- Simple setup: enter an address, choose the suggested stop/route/direction, flash the device, connect Wi-Fi, and install it.
- One shared backend aggregates realtime data so individual signs do not repeatedly query the transit provider.
- Every display, including the simplest Wi-Fi shop-window unit, retains a local static fallback.
- Weekly fallback data combines the published timetable with historically observed running times where useful.
- Realtime prediction experiments are treated as challengers, not assumptions. If the agency ETA is already as accurate as our alternatives within a practically narrow margin, the project will use the agency ETA for live operation and retain our model primarily for fallback and resilience.
- Optional LoRa mesh connectivity for resilient distribution of small updates.
- Power-aware behaviour for mains, solar, and battery operation.
- Optional passenger stop-request button and night beacon, with an optional second press on vehicle arrival as useful ground-truth feedback.
- Future support for geographically relevant official emergency alerts.

## Resilience ladder

A display should degrade gracefully rather than go blank:

1. Live backend prediction over Wi-Fi.
2. Live update received through LoRa mesh, where fitted.
3. Recently cached live data while still fresh.
4. Weekly generated historical/fallback timetable stored locally.
5. Published static timetable stored locally.

The Wi-Fi-only reference unit always includes levels 3-5.

## Initial architecture

```text
Transit provider realtime feed
           |
           v
      Collector
           |
           +---- raw short-term observations
           |
           v
  Reliability analysis
           |
           +---- agency ETA benchmark
           +---- schedule benchmark
           +---- challenger predictors
           |
           v
   Weekly fallback model
           |
           v
     Public API / cache
        /         \
       v           v
 Wi-Fi display   LoRa gateway
                    |
                    v
                LoRa nodes
```

## Current status

The first provider adapter targets the Ride Guide GTFS-Realtime WebSocket used by the Whangārei CityLink tracker. The collector is intentionally polite: one shared collector receives the network-wide feed rather than having every display connect upstream.

The repository starts by collecting and preserving short-run observations as GitHub Actions artifacts so we can measure prediction reliability before choosing a long-term data store. Static GTFS discovery/import is the next required data step because it provides route names, stop names, scheduled stop times, service calendars and destinations.

## Prototype path

1. **Shop-window reference unit**: 7.5-inch-class black-and-white e-paper, ESP32-class controller, USB-C/mains, Wi-Fi, cached live data, weekly historical fallback, and local static timetable.
2. **Solar Wi-Fi unit**: battery/solar power telemetry and timetable-aware sleeping.
3. **LoRa leaf unit**: receives compact updates from nearby gateways while retaining all local fallbacks.
4. **Gateway/repeater unit**: mains or generously powered node that bridges internet data to the mesh.
5. **Full roadside unit**: solar, LoRa-dependent operation, stop-request button, night beacon, emergency information, and aggressive power management.

## Repository layout

```text
collector/       provider adapters and realtime collection
analysis/        arrival inference and prediction benchmarking
fallback/        weekly static fallback generation
firmware/        reference display firmware and hardware profiles
docs/            architecture and protocol notes
.github/         scheduled collection and analysis workflows
```

## Data and prediction philosophy

The project will compare the provider ETA with simple, interpretable alternatives first: schedule, recent segment travel time, same route/time/day history, buses ahead on the same segment, and rolling adaptive estimates. More complex models are only justified if held-out evaluation shows a material improvement.

Accuracy should be reported by prediction horizon (for example 0-2, 2-5, 5-10, 10-20 and 20+ minutes), because the best method may differ depending on how far away the vehicle is.

If a challenger model is only marginally different from the agency estimate, the project should prefer the agency estimate for live operation and preserve our own learned timing mainly as a local/offline fallback.

## Licensing

This repository is licensed under the GNU General Public License v3.0. Hardware documentation may later use an appropriate open-hardware licence once the reference PCB and enclosure exist.
