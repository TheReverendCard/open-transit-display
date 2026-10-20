# CityLink standard GTFS-Realtime via GitHub snapshots

**Draft / opt-in / NOT publishing at present.** This document reconciles the
16 October owner decisions in [issue #10](https://github.com/TheReverendCard/open-transit-display/issues/10)
with the 20 October [validation](citylink-gtfsrt-validation-2026-10-20.md).
The earlier conclusion that a continuously hosted WebSocket bridge was required
for an initial release was **incorrect**. GitHub is the preferred first
distribution channel for ordinary public signs; a continuously hosted endpoint
remains an optional lower-latency advanced mode.

## Components and flow

1. Nightly **verified static** `feed-data/citylink/gtfs.zip` and
   `feed-data/citylink/trip-map.json`, retrieved by **one exact Git commit**.
2. A small single-connection Ride Guide WebSocket capture by
   `collector/publish_citylink_gtfsrt_snapshot.py` (default 40 seconds).
   Its `StaticIndex` verifies each source route/trip/date against the date-
   specific static feed. Its `Bridge` filters >90-second-old trip/vehicle
   entities and unmapped descriptors. Standard protobuf keeps the provider's
   explicit StopTimeUpdates; no new GPS-based ETA model is introduced.
3. `.github/workflows/publish_citylink_realtime.yml` proposes staggered
   `2-59/5 * * * *` scheduled collection, only inside actual static GTFS
   service windows. The static branch remains untouched. Approved snapshots
   would be pushed to the independent `realtime-data` branch:
   - `citylink/tripupdates.pb` (standard FULL_DATASET GTFS-RT)
   - `citylink/vehiclepositions.pb`
   - `citylink/alerts.pb`
   - `citylink/stops/11000262/6.json` (optional stop-level convenience)
   - `citylink/manifest.json` (metadata + file hashes)
4. Future Wi-Fi / LoRa gateways consume the same canonical, timestamped
   snapshots, matched against locally cached **date-valid** static schedules.
   The gateway transmits the original source observation time as distinct from
   gateway send time and device packet-receipt time. An original scheduled
   departure never changes when its ETA is updated.

## Publication is disabled by default

Scheduled jobs are skipped unless the repository variable
`CITYLINK_RT_PUBLICATION_AUTHORIZED` is exactly `true`. **Do not set this
without verifying NRC/Ride Guide redistribution permission**, retention
conditions and acceptable rate limits. The workflow is currently on the
draft feature branch, and GitHub schedules only run for workflows on the
default branch; it will not schedule on this draft by itself.

A manual `workflow_dispatch` with `publish: false` is a no-publication
smoke run. The candidate files are not uploaded as a public artifact. To
publish requires **both** the authorization repository variable **and**
`publish: true` on a manual run, or an authorized scheduled run after merge.
This is deliberately separate from the optional systemd bridge.

## Manifest / freshness contract

Manifest schema: `otd-citylink-gtfsrt-snapshot-v1`.

- `static_feed_commit`: exact revision of the published static GTFS and
  trip-map used to map all source IDs.
- `service_dates`: valid service dates from its `calendar_dates.txt`.
- `generated_at_utc`: snapshot assembly time.
- `publication_started_at_utc`: time publication was *attempted* just before
  the git commit/push; **not** proof that CDN users can already fetch it.
- Each feed has `path`, `sha256`, `entities`,
  `source_observation_at` (upstream header timestamp),
  `latest_packet_received_at`, `oldest_included_entity_at`,
  and age counters at generation.
- `max_consumer_age_seconds: 600` is a **provisional ceiling**, not a claim
  of freshness or the recommended lifetime for a LIVE label.

Every consuming sign/gateway **must** check current time and original
entity/stop observation age, ensure matching route/trip/stop/service date,
confirm `static_feed_commit` is compatible with cached static files,
and downgrade expired data regardless of the freshness of the downloaded
GitHub URL or LoRa packet. Recommended initial rule (subject to field testing):
- **LIVE:** verified vehicle-backed direct estimate with observation age
  <=90 seconds, if otherwise valid.
- **ESTIMATED with observation age:** previously valid provider prediction
  at >90 and <=600 seconds, avoiding false precision and preserving source.
- **SCHED:** >600 seconds, missing/unmatched prediction or failed/cached
  network fetch, provided the locally stored *original* schedule is valid.
  If the schedule itself is expired, display `SYNC REQUIRED`.
- Pseudo-vehicles named `schedBasedVehicle...` must **never** be shown
  as vehicle-confirmed LIVE; their predictions remain provider estimates.
- `CANCELED`, `SKIPPED`, `NO_DATA` and early departures need explicit
  client handling. Never fabricate a future ETA from a missing vehicle.

An HTTP 200 from GitHub or a recent commit is not evidence that a prediction
is live. Five-minute workflow cadence plus queueing, run duration and CDN
caching produces additional lag. No latency/availability SLA is asserted.
Caches should use validation/ETag where supported; the client must
degrade to SCHED after expiry even without a subsequent publication.

## Smoke test and release acceptance

1. Run offline CI `test_citylink_gtfsrt*.py` and `py_compile` on the
   feature branch. Tests verify canonical protobuf trip IDs, stale
   exclusion, valid empty feeds, exact static revision and stop JSON timestamps.
2. Manually run the new workflow in **no-publication** mode and confirm
   fetching static snapshot plus trip-map from the same feed-data commit,
   provider access, source ages, no decoded errors, correct protobuf entities
   and that the Museum stop JSON includes original observation times.
   **Not performed in CI; tests use synthetic protobuf.**
3. Check Actions cron scheduling over at least two complete weekdays and
   Saturday: missed/delayed jobs, zero-vehicle periods, relation of source
   age to service windows, static-revision changes and commit growth.
4. Before authorizing public publication, confirm provider redistribution
   rights and how URL consumers handle cache headers, source age, 5–10-minute
   expiration, and mismatched static revisions.
5. Test real Museum sign Wi-Fi/LoRa bridge, including reboot, loss of Wi-Fi,
   stopped Windows PC, skipped/cancelled trips, and a source prediction
   older than 90 seconds but newer than the LoRa receive packet.
6. Preserve local owner-specific battery calibration/diagnostic firmware
   outside this public GitHub branch. Do not claim new ESP32 code has
   been physically verified.

## CI failure review (20 October)

Three intermediate revisions of PR #12 failed the same test:
`test_health_counts_only_upcoming_direct_stop_predictions`,
`AssertionError: 3 != 2`. The test used a simulated observation at
08:02 where the 08:00 stop was still inside the intentional
two-minute grace window. Commit `fa1a428` advanced the simulated time
to 08:02:01, beyond the inclusive cutoff. CI run
[39346751433](https://github.com/TheReverendCard/open-transit-display/actions/runs/39346751433)
passed 17/17 bridge tests; the failures were from stale intermediate
commits, not evidence of three independent processing defects.

Snapshot publication code is deliberately **not deployed** by the commit
itself. Existing `main` collector and previously working LoRa display
are unchanged. The publisher needs separate no-publication source validation
and explicit authorization before its first public GitHub push.
