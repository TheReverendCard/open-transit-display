# CityLink / Ride Guide GTFS-Realtime validation, 20 October 2026

## Scope and evidence

This is a **retrospective, sampled validation**, not an assertion that the realtime bridge has been deployed. Dates and service days are Pacific/Auckland unless otherwise noted.

Sources:
- Collector [workflow](../.github/workflows/collect.yml), retained workflow artifacts and [20 October collector run](https://github.com/TheReverendCard/open-transit-display/actions/runs/39338476524).
- [Collection analysis run](https://github.com/TheReverendCard/open-transit-display/actions/runs/39325780426) and its `collection-analysis-39325780426` artifact (76 archives processed).
- [Ride Guide timetable importer](https://github.com/TheReverendCard/open-transit-display/actions/runs/39328305207) and `rideguide-timetables-39328305207` artifact, for 19 and 20 October service dates.
- `feed-data/citylink/trip-map.json` and the [draft bridge](../collector/citylink_gtfsrt_bridge.py).
- [Prediction benchmark run](https://github.com/TheReverendCard/open-transit-display/actions/runs/39321361539).

The review independently read 31 compressed collector artifacts spanning 16 through 20 October, including the latest completed collector run at about 11:57 NZDT on 20 October. The 19–20 October stop checks used the provider's date-specific timetable artifact as the reference for stop sequences, and the published derived trip-map as the reference for source-to-derived trip identity. A byte-level comparison against `gtfs.zip` and raw original websocket protobuf replay remains outstanding.

## Historical data collection

The existing analysis successfully downloaded **76 of 76** available collector archives, with no skipped archives, covering 6–20 October NZDT. It reported **418,893 JSONL rows**: **376,488 TripUpdate rows**, **38,002 vehicle rows** and **4,403 empty-feed rows**, plus 0 invalid JSON rows. It identified **14 source routes**, **176 source trip IDs**, **184 vehicle IDs** and **272 stop IDs**. Its heartbeat-based continuous-span coverage was just **5.27%** across 332.31 hours. It found 75 gaps above 30 seconds; the longest was **32,204 seconds** (8.95 hours). This gap measure reflects collector scheduling and archive availability, not necessarily any upstream outage.

For 16–20 October, 31 archives were independently inspected: 6 on Friday, 7 on Saturday, 8 on Sunday, 7 on Monday and 3 on Tuesday through midday NZDT. The 31 archives contained **139,060 TripUpdate rows**, **13,053 vehicle rows**, **2,094 empty-feed rows** and **587,708 individual StopTimeUpdates**. The Sunday archives carried zero TripUpdates, consistent with no scheduled regular CityLink service. Of the 31 archive health summaries, 30 said `healthy` and 1 said `degraded`; none listed hard validation failures. Degraded/empty feeds should be distinguished from data corruption and service-off hours.

The configured cron expression is `*/15 * * * *`, but observed starts were often hours apart. With a 600-second run duration, the retained samples are **not** a continuous observation of the day's service. A successful GitHub Actions job is not evidence of continuous feed coverage.

## Trip-ID match to published derived CityLink GTFS

For **19 and 20 October** the sampled upstream data contained **72,471 TripUpdate rows**: **66,381 CityLink records for routes 1102–1110** and **6,090 records from routes 1201, 1202, 1204, 1205 and 1206**, which are outside the CityLink derived feed.

**All 66,381 CityLink records had source route/trip pairs present in the relevant date-specific timetable and in the derived trip-map.** The all-route record-weighted matching figure, **66,381 / 72,471 = 91.6%**, is therefore not evidence of a CityLink ID mapping failure. All **271,506 StopTimeUpdate entries** counted for CityLink matched a stop ID and sequence in the corresponding Ride Guide timetable snapshot. This is a provider-timetable structural check, not a raw-protobuf-to-published-GTFS-byte comparison.

The draft bridge additionally requires a populated `TripDescriptor.start_date` and rejects TripUpdate entities with their own timestamp older than 90 seconds. Its effective intake must be measured using both requirements, not just source trip-ID existence.

## Freshness and provenance, 19–20 October

Of 72,471 raw TripUpdate rows:
- **41,342 unknown-source** rows (57.0%) had no StopTimeUpdates; they are not useful arrival forecasts.
- **23,884 vehicle-assigned** rows (33.0%).
- **7,245 schedule-based** rows (10.0%), recognised from pseudo-vehicle IDs containing `schedBasedVehicle`.
- **9,726** rows supplied a `start_date`.
- **2,554** rows had a source entity timestamp between -60 and +90 seconds of receipt.
- **2,472** rows simultaneously mapped to CityLink, had the correct service date, had a fresh source timestamp, and contained valid stop updates. Of these, **2,456 were vehicle-assigned** and **16 were schedule-based**.

The source **feed header** was very fresh (0-second median, 3-second p99, 9-second maximum receipt age for the 16–20 October TripUpdate sample). In contrast, individual TripUpdate timestamps were often hours old. A fresh envelope must **not** refresh an old vehicle/prediction. This is a good reason to retain entity-level freshness checks. Low accepted-to-raw ratios are also expected when the provider broadcasts many inactive, zero-update and precomputed schedule entries; they are **not**, on their own, a stop availability or live-uptime percentage.

From **5,965 VehiclePosition records** on 19–20 October, **2,480** contained a trip ID, route ID, service date and stop ID, all with fresh vehicle timestamps in this sample. Other records frequently contained parked or unassigned vehicles and should not be falsely associated with a passenger trip. A separate replay is required to confirm final VehiclePositions protobuf output.

## Intermediate stops and Route 6 Whangārei Museum

For **all 2,472 fresh, dated, mapped TripUpdate records** examined, every scheduled stop from the *first predicted future stop through the terminus* had an explicit provider StopTimeUpdate. This is **100% within accepted observed updates**, **not** coverage of every trip/departure throughout the day.

For Route 6 (upstream route `1106`, Maunu), the 19 October static timetable contains **12 trips and 37 stop IDs**, including **Whangārei Museum (`11000262`, sequence 23)**. Across the observed 19 October runs:
- There were directly provider-supplied future predictions for **357 distinct trip/stop pairs**, including **116 distinct fresh vehicle-backed pairs**.
- Fresh vehicle-backed direct predictions covered **36 of 37 stop IDs** across **four observed trips**.
- Whangārei Museum appeared in **185 repeated fresh vehicle-backed future-stop observations** on 19 October, representing trips **92, 94, 96 and 97**. There were an additional **392 schedule-based observations** at that stop.
- The 20 October partial-day sample added **72 fresh vehicle-backed** and **183 schedule-based** future observations at Whangārei Museum, with fresh vehicle-backed trips **94 and 97**.

Repeats at roughly ten-second sampling intervals must never be reported as distinct bus arrivals. The unobserved trips are predominantly a consequence of sampling gaps, not proved provider omissions.

### Propagation decision

**Do not build a separate arrival propagation model yet.** Fresh assigned trips already provide explicit estimates for all remaining downstream stops in the sampled updates. Keep GTFS-Realtime's standard delay propagation semantics as a compatible fallback if sparse cases eventually occur, honouring `NO_DATA`, `SKIPPED`, cancelled trips and missing data. A missing live entity must degrade to an openly labelled **SCHED** fallback, not to a fabricated LIVE ETA.

## Independent prediction benchmark

The 19 October benchmark workflow processed 76 archives and reported **624 benchmark samples** with observed stop arrivals. It estimated an overall provider prediction mean absolute error of **109.9 s**, versus **231.7 s** for static schedules. A simple hold-last-delay baseline had **114.4 s** MAE on its **306 available samples**, which is a different sample set. Horizon 5-minute samples (n=461) yielded provider MAE **97.6 s** versus schedule MAE **232.1 s**. The 15-minute (n=13) and 30-minute (n=2) bins are too small to support dependable claims. These statistics should not be treated as a fair same-sample comparison for all models or as validation of Route 6 in isolation.

## Gaps before standard GTFS-Realtime publication

1. **Collection coverage:** The earlier 15-minute schedule did not execute reliably. The chosen first distribution target is rights-gated approximately five-minute GitHub Actions snapshots, **not** an always-on host as a precondition. Monitor actual scheduled runs, queue times, CDN lag, and source ages over two weekdays and one Saturday; an optional supervised bridge remains available for lower-latency deployments.
2. **Live replay:** Replay original *protobuf* frames (not only collector JSONL records) against the bridge using the exact published `gtfs.zip` plus `trip-map.json` revision. Verify protobuf parsing, service dates, sequence/stop identity, entity freshness, zero-update behaviour, cancellation, `NO_DATA`, `SKIPPED`, and header semantics.
3. **Published GTFS parity:** Check `trip-map.json` and `gtfs.zip` from the identical commit; compare generated `stop_times.txt` against current provider snapshots and enforce an atomic refresh.
4. **Arrival availability:** With continuous observations, measure per-stop and per-trip *time-weighted* direct vehicle-backed ETA availability, provider-estimate availability, static fallback, source age, and downtime, especially Route 6 stop `11000262`.
5. **Quality/rights:** Validate actual arrival error against independently observed stop events and obtain permission to redistribute provider-sourced realtime data before advertising a public feed.
6. **Publication:** The draft now contains a five-minute GitHub Actions snapshot workflow, but scheduled publication is explicitly disabled unless `CITYLINK_RT_PUBLICATION_AUTHORIZED` is set to `true`. GitHub snapshots can remain useful estimated arrival observations up to a provisional maximum of 600 seconds, **not 90-second live tracking**; consumer labels must explicitly downgrade using original entity age, show data age, and use SCHED after expiry. A separately hosted HTTPS/WebSocket bridge remains an optional advanced mode.

**Implementation decision (reconciled with issue #10):** Trip identities and direct intermediate-stop predictions pass sampled validation for 19–20 October, but live-protobuf replay and end-to-end publication reliability remain unverified. The next deployment stage is the separately gated `realtime-data` GitHub publisher and field monitoring. A continuously running server is **optional**, not the default prerequisite. No new inferred arrival model is justified by the sampled data.
