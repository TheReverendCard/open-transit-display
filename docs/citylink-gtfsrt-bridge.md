# CityLink canonical GTFS-Realtime bridge

**Development code only. Not a deployed public service.**

CityLink's date-specific, derived static GTFS is already published at
https://github.com/TheReverendCard/open-transit-display/tree/feed-data/citylink
with a matching trip-map.json. Ride Guide's upstream protobuf feed uses
provider trip IDs. The bridge rewrites those IDs to exactly match the public
static GTFS, exposing conventional GTFS-Realtime HTTP endpoints.

## Running

Install with: python -m pip install gtfs-realtime-bindings websockets

Fetch citylink/gtfs.zip and citylink/trip-map.json from the **same**
validated feed-data revision. Then:

    python collector/citylink_gtfsrt_bridge.py --gtfs ./citylink/gtfs.zip --trip-map ./citylink/trip-map.json --host 127.0.0.1 --port 8787

This process subscribes once to the Ride Guide WebSocket (organisation 104).
It must run continuously on a NAS, dedicated gateway or cloud server behind
a trusted HTTPS reverse proxy. GitHub hosts **nightly static timetables** and
the bridge code, not a 30-second real-time streaming service. Check provider
redistribution terms before exposing the feed publicly.

## HTTP interface

- /gtfs-realtime/tripupdates.pb : standard GTFS-RT TripUpdates protobuf
- /gtfs-realtime/vehiclepositions.pb : standard GTFS-RT VehiclePositions protobuf
- /gtfs-realtime/alerts.pb : standard GTFS-RT ServiceAlerts protobuf
- /v1/stops/11000262/arrivals.json : simplified, source-labelled departure times
- /health.json : source timestamps, matched/unmatched counts and feed status

All raw protobuf IDs must reference the **same static GTFS snapshot** a
consumer downloads. A trip that cannot be uniquely matched is dropped rather
than falsely mapped. Stale upstream TripUpdates/VehiclePositions (older than
90 seconds) return HTTP 503, not an apparently healthy frozen feed. Schedule
only fallbacks remain available in the JSON endpoint when realtime goes stale.

## Intermediate stops

The existing static GTFS contains scheduled stop_times for intermediate stops.
GTFS-RT is allowed to omit intermediate StopTimeUpdates. A known delay is
propagated to later omitted stops until overridden by a newer update or a
NO_DATA boundary. A downstream consumer does not need our own prediction
model to apply that standard rule.

The simple stop JSON labels:
- LIVE: direct, fresh, vehicle-assigned prediction for this stop.
- PROPAGATED: fresh vehicle-backed delay from an earlier stop in the trip.
- PROVIDER_ESTIMATE and PROPAGATED_ESTIMATE: provider predictions with no
  verified vehicle assignment, including schedule-based pseudo-vehicles.
- CANCELED: upstream confirmed trip cancellation.
- SCHED: explicit published timetable where no fresh prediction exists.

The bridge does **not** invent intermediate arrival times from GPS position
or assume a missing TripUpdate means a bus is on time. A separately evaluated
segment-time/interpolation model might improve this later, but must be labelled
MODELLED rather than LIVE.

## Continuous host and observability

The optional [systemd unit](../ops/citylink-gtfsrt.service.example) keeps the
existing single-subscription bridge running on a trusted, always-on host.
It is an **example only**: update paths, create a restricted service account,
install `gtfs-realtime-bindings` and `websockets` in the local virtual
environment, and place the same-revision `gtfs.zip` and `trip-map.json` at
the configured paths. Test locally before enabling the service. It listens
only on `127.0.0.1:8787`, does not expose a public endpoint, and does not
publish any data to GitHub. A proxy and provider redistribution permission
are separate requirements.

Useful commands on the host:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now citylink-gtfsrt.service
sudo journalctl -u citylink-gtfsrt.service -f
curl --fail --silent http://127.0.0.1:8787/health.json
```

`/health.json` reports WebSocket connection state and connection/reconnection
counts; decode/connection errors; packets seen; accepted, unmatched, missing-date,
unmapped, empty-update and stale entity counts, by feed kind where meaningful;
source and receipt ages separately; per-feed freshness; active TripUpdate
provenance; and *instantaneous* direct future-stop prediction coverage.
The latter denominator is **only stops on currently accepted mapped trips**
whose *scheduled* departure has not passed by more than two minutes. It
is not an all-day passenger availability metric. Source ages are distinct
from transport packet arrival ages.

Alert if the WebSocket is disconnected during service hours or the TripUpdates
feed remains stale; keep a separate zero-vehicle/no-current-trip warning
because the network can legitimately have no active vehicles after hours.
When a provider packet is fresh but contains no usable live entities, the
standard protobuf endpoint can return an empty `FULL_DATASET` while passenger
arrivals fall back to `SCHED`. Never call that live ETA availability.

When the static timetable changes, **verify and atomically replace both**
`gtfs.zip` and `trip-map.json` from one revision, then restart the bridge;
the example unit deliberately does not automatically load partial updates.
For validation, run the host for two complete weekdays and a Saturday,
save periodic `/health.json` snapshots plus restricted application logs,
and calculate service-window / per-stop percentages of fresh vehicle-backed,
provider-estimated and timetable-only arrivals. Include stop `11000262`
(Route 6 Whangārei Museum) in those metrics. Do not persist credentials,
precise vehicle-location history or passenger-identifying information in
public artifacts.

## Before production

1. Verify real Ride Guide trip IDs, route IDs, start dates and stop sequences
   match the derived source mapping. Health endpoint exposes unmatched entities.
2. Quantify how many intermediate stops receive direct TripUpdate predictions.
   Compare stop IDs in recorded upstream StopTimeUpdates with the full public
   stop_times.txt, distinguishing vehicle-assigned versus schedule-based.
3. Update static GTFS and trip-map.json **atomically** on service-date changes;
   restart the adapter only after both files are verified and current.
4. Validate cancellations, skipped stops, NO_DATA and early departure edge
   cases on recorded real provider messages before using in passenger signs.
5. Integrate the stop JSON adapter into the Wi-Fi/LoRa sender; choose profile
   and source freshness independently. Shared provider collection is one
   backend connection, never one WebSocket per sign.
6. Provision reliable TLS, restart/supervision, upstream outage alerts and
   provider redistribution permissions before public hosting.

The HTTP reference server is intentionally bound to 127.0.0.1 by default.

Official specification:
https://gtfs.org/documentation/realtime/feed-entities/trip-updates/
