# Dated CityLink stop timetable snapshots

Nightly publication writes compact static schedules alongside the same verified GTFS ZIP on the feed-data branch.

Example URL:
https://raw.githubusercontent.com/TheReverendCard/open-transit-display/feed-data/citylink/stops/11000262/6.json

Discovery and capacity report:
https://raw.githubusercontent.com/TheReverendCard/open-transit-display/feed-data/citylink/stops/index.json

## Contract

- schema: otd-stop-schedule-v1.  Source is GTFS_STATIC, never live predictions.
- stop_id and route select a stop/public route number.  departures is a sorted, unique array of UTC Unix seconds.  Display in the provided Pacific/Auckland timezone.
- covered_dates lists only the explicitly imported service dates, including dates with no departures for this route.  No weekly repetition is inferred.  Reject stale coverage and show an unavailable state after expiry.
- revision is the uppercase 8-character CRC32 of the ASCII comma-separated departure epochs, with no trailing comma or newline.  This preserves the OTDL1 cache checksum.
- content_revision is a SHA-256 of the complete payload before this field is added, serialized as UTF-8 JSON with sorted keys and compact separators.  Use it to detect changes to names, coverage and provenance even if departure times are unchanged.
- static_feed_sha256 identifies the GTFS ZIP from which the snapshot was generated.  Fetching static GTFS and this file separately can cross a publication boundary; compare hashes or pin the feed-data commit when fetching companion files.
- stop_name and destination are passenger-facing metadata.  Museum Route 6 uses the verified Rose Street / CBD label and Whangārei spelling.  When trips disagree on destination the shared destination is empty, rather than choosing a misleading label.
- A file has at most 160 departure epochs.  Over-capacity stop/routes are absent and listed in index.json with device_capacity_exceeded and actual entry count; the exporter never truncates and calls the result complete.  Inspect the index before treating a missing file as no service.
- Only ordinary boarding events are included.  No-pickup and reservation-only boarding events and terminal rows are excluded.

## Scope and limitations

This exporter accepts the project's explicit date-scoped derived CityLink feed, not arbitrary GTFS calendar.txt feeds.  It validates current, contiguous date coverage and supports GTFS times over 24:00 and the noon-minus-12-hours DST time origin.

The v1 firmware cache stores times, not full trip records.  It combines directions sharing a public route number and does not supply per-departure trip identity, next-stop metadata, alerts or predictions.  Do not use a departure epoch alone as a live trip-ID match.  Direction-specific provisioning and compact live updates need a versioned extension agreed with the firmware agent.

More than 160 events currently makes a stop/route unavailable for this small cache.  A later schema can split by service date/direction with an explicit coverage manifest; until then do not silently shorten coverage to make a file fit.

## Publication and recovery

The workflow tests adapters, stages fresh validated GTFS, generates all stop files and index, and replaces the previous stops directory only when the new index exists.  A failed CityLink import retains the previous static feed and stop files.  A failed exporter prevents publication.  The worktree commit publishes GTFS, trip-map, metadata, stop files and index together.

The sign must retain its last validated snapshot until a replacement is fully downloaded and its schema, stop/route, date coverage and CRC are checked.  Commit the replacement cache only after validation.  A failed download must not erase a still-valid cache; expired data must not masquerade as future service.

Wi-Fi commissioning, nightly sync and NVS persistence are firmware integration work under issue #10.  This PR publishes schedule data and does not change the running FULL24/HYBRID5 tests or enable deep sleep.

## Verification

Seven exporter regression tests cover CRC compatibility, metadata revisions, 160/161 capacity boundary, stale/gapped coverage, unsupported generic calendars, explicit no-service output and overnight/DST epochs.

On the published GTFS downloaded 17 October 2026 (NZ), deterministic export for 2026-10-17 produced 312 stop/route files.  Museum 11000262/6 had 80 departures over 2026-10-17 through 2026-10-24.  Two Route 4 stop/routes exceeded 160 entries and were explicitly reported.  Counts change as the rolling source feed changes.
