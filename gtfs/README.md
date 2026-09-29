# Standard GTFS import template

This directory is the agency-neutral path for bringing a normal GTFS Static feed into Open Transit Display.

The goal is that another city should not require custom code before a display can show a timetable.  If an agency publishes a standards-compliant GTFS ZIP, the same importer should produce the same display-facing files regardless of whether the feed came from Auckland, Christchurch, Wellington, or somewhere else.

## What the importer consumes

A normal GTFS Static ZIP.  At minimum it expects:

- `routes.txt`
- `stops.txt`
- `trips.txt`
- `stop_times.txt`

For correct date-specific service it also uses `calendar.txt` and/or `calendar_dates.txt` when present.

## What it produces

`import_gtfs.py` normalizes a selected date window into:

- `routes.csv`
- `stops.csv`
- `trips.csv`
- `stop_times.csv`
- `service_dates.csv`
- `display_departures.csv`
- `display_stops/<stop_id>.json`
- `manifest.json`

The per-stop JSON files are deliberately compact and display-facing.  A display does not need to understand the agency's original GTFS ZIP.  It only needs its configured stop ID, route selection if desired, and the normalized departures for that stop.

## Auckland reference test

Auckland Transport publishes a public GTFS ZIP at:

`https://gtfs.at.govt.nz/gtfs.zip`

The workflow `.github/workflows/test_gtfs_auckland.yml` downloads that official feed and runs the generic importer against a small set of Auckland route numbers.  This is our compatibility/reference test for a conventional GTFS agency.

The Auckland test is not a separate Auckland implementation.  It exists to prove that the generic importer works against a real, comparatively large GTFS feed without any Ride Guide or Northland-specific assumptions.

## Adding another agency

For another agency with a public GTFS ZIP, the expected onboarding work should be configuration rather than programming:

1. Point `--source` at the agency GTFS ZIP.
2. Optionally supply one or more `route_short_name` values for a test subset.
3. Run the importer.
4. Verify the manifest and a few generated `display_stops/*.json` files.
5. If the agency also publishes GTFS-Realtime, connect that feed separately and join it using the GTFS `trip_id`, `route_id`, and stop identifiers.

If a standards-compliant GTFS feed requires new agency-specific parsing code here, that should be treated as a bug or a clearly documented agency quirk rather than the normal onboarding process.

## Local example

```bash
python gtfs/import_gtfs.py \
  --source https://gtfs.at.govt.nz/gtfs.zip \
  --route-short-names 18,70,NX1 \
  --days 7 \
  --agency-label "Auckland Transport" \
  --output-dir data/gtfs_auckland
```

Leaving `--route-short-names` empty imports every route in the feed.
