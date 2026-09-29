#!/usr/bin/env python3

import argparse
import csv
import io
import json
import shutil
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


REQUIRED_FILES = {"routes.txt", "stops.txt", "trips.txt", "stop_times.txt"}
WEEKDAY_FIELDS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Import a standard GTFS Static feed and build display-ready timetable files."
    )
    parser.add_argument("--source", required=True, help="GTFS ZIP URL or local ZIP path")
    parser.add_argument("--output-dir", required=True, help="Directory for normalized output")
    parser.add_argument(
        "--route-short-names",
        default="",
        help="Comma-separated route_short_name values to import. Empty means all routes.",
    )
    parser.add_argument("--start-date", default="", help="YYYY-MM-DD; defaults to today")
    parser.add_argument("--days", type=int, default=7, help="Number of service dates to materialize")
    parser.add_argument("--agency-label", default="", help="Optional human-readable agency label")
    return parser.parse_args()


def parse_yyyymmdd(value):
    return datetime.strptime(value, "%Y%m%d").date()


def gtfs_time_seconds(value):
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = (int(part) for part in parts)
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


def fetch_zip(source, target):
    if source.startswith("http://") or source.startswith("https://"):
        request = urllib.request.Request(
            source,
            headers={
                "User-Agent": "open-transit-display/1.0 (+https://github.com/TheReverendCard/open-transit-display)"
            },
        )
        with urllib.request.urlopen(request, timeout=120) as response, open(target, "wb") as out:
            shutil.copyfileobj(response, out)
    else:
        shutil.copyfile(source, target)


def read_csv_from_zip(zf, name):
    with zf.open(name, "r") as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(text))


def iter_csv_from_zip(zf, name):
    raw = zf.open(name, "r")
    text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
    reader = csv.DictReader(text)
    try:
        for row in reader:
            yield row
    finally:
        text.close()


def active_services(zf, service_dates):
    active = {d: set() for d in service_dates}

    if "calendar.txt" in zf.namelist():
        for row in iter_csv_from_zip(zf, "calendar.txt"):
            try:
                start = parse_yyyymmdd(row["start_date"])
                end = parse_yyyymmdd(row["end_date"])
            except (KeyError, ValueError):
                continue
            service_id = row.get("service_id", "")
            if not service_id:
                continue
            for d in service_dates:
                if start <= d <= end and row.get(WEEKDAY_FIELDS[d.weekday()], "0") == "1":
                    active[d].add(service_id)

    if "calendar_dates.txt" in zf.namelist():
        for row in iter_csv_from_zip(zf, "calendar_dates.txt"):
            try:
                d = parse_yyyymmdd(row["date"])
            except (KeyError, ValueError):
                continue
            if d not in active:
                continue
            service_id = row.get("service_id", "")
            exception_type = row.get("exception_type", "")
            if exception_type == "1":
                active[d].add(service_id)
            elif exception_type == "2":
                active[d].discard(service_id)

    return active


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    start_date = date.fromisoformat(args.start_date) if args.start_date else date.today()
    service_dates = [start_date + timedelta(days=i) for i in range(args.days)]
    requested_short_names = {
        value.strip() for value in args.route_short_names.split(",") if value.strip()
    }

    with tempfile.TemporaryDirectory(prefix="gtfs-import-") as temp_dir:
        zip_path = Path(temp_dir) / "feed.zip"
        fetch_zip(args.source, zip_path)

        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            missing = sorted(REQUIRED_FILES - names)
            if missing:
                raise RuntimeError(f"GTFS feed is missing required files: {', '.join(missing)}")

            routes = read_csv_from_zip(zf, "routes.txt")
            if requested_short_names:
                selected_routes = [
                    row for row in routes if row.get("route_short_name", "") in requested_short_names
                ]
                found = {row.get("route_short_name", "") for row in selected_routes}
                missing_routes = sorted(requested_short_names - found)
                if missing_routes:
                    print(f"Warning: requested routes not found: {', '.join(missing_routes)}")
                if not selected_routes:
                    raise RuntimeError("None of the requested route_short_name values were present in the feed.")
            else:
                selected_routes = routes

            selected_route_ids = {row.get("route_id", "") for row in selected_routes}
            selected_route_ids.discard("")

            active_by_date = active_services(zf, service_dates)
            active_service_ids = set().union(*active_by_date.values()) if active_by_date else set()

            trips = []
            for row in iter_csv_from_zip(zf, "trips.txt"):
                if row.get("route_id", "") not in selected_route_ids:
                    continue
                if active_service_ids and row.get("service_id", "") not in active_service_ids:
                    continue
                trips.append(row)

            selected_trip_ids = {row.get("trip_id", "") for row in trips}
            selected_trip_ids.discard("")
            selected_service_ids = {row.get("service_id", "") for row in trips}

            stop_times = []
            selected_stop_ids = set()
            for row in iter_csv_from_zip(zf, "stop_times.txt"):
                if row.get("trip_id", "") not in selected_trip_ids:
                    continue
                stop_times.append(row)
                if row.get("stop_id"):
                    selected_stop_ids.add(row["stop_id"])

            stops = [
                row for row in iter_csv_from_zip(zf, "stops.txt")
                if row.get("stop_id", "") in selected_stop_ids
            ]

            route_by_id = {row.get("route_id", ""): row for row in selected_routes}
            trip_by_id = {row.get("trip_id", ""): row for row in trips}
            stop_by_id = {row.get("stop_id", ""): row for row in stops}
            stop_times_by_trip = defaultdict(list)
            for row in stop_times:
                stop_times_by_trip[row.get("trip_id", "")].append(row)

            for rows in stop_times_by_trip.values():
                rows.sort(key=lambda r: int(r.get("stop_sequence") or 0))

            service_date_rows = []
            display_rows = []
            for d in service_dates:
                active_services_for_date = active_by_date.get(d, set())
                for service_id in sorted(selected_service_ids):
                    if service_id in active_services_for_date:
                        service_date_rows.append(
                            {"service_date": d.isoformat(), "service_id": service_id}
                        )

                for trip in trips:
                    if trip.get("service_id", "") not in active_services_for_date:
                        continue
                    route = route_by_id.get(trip.get("route_id", ""), {})
                    for st in stop_times_by_trip.get(trip.get("trip_id", ""), []):
                        stop = stop_by_id.get(st.get("stop_id", ""), {})
                        display_rows.append(
                            {
                                "service_date": d.isoformat(),
                                "route_id": trip.get("route_id", ""),
                                "route_short_name": route.get("route_short_name", ""),
                                "route_long_name": route.get("route_long_name", ""),
                                "trip_id": trip.get("trip_id", ""),
                                "trip_headsign": trip.get("trip_headsign", ""),
                                "direction_id": trip.get("direction_id", ""),
                                "stop_id": st.get("stop_id", ""),
                                "stop_name": stop.get("stop_name", ""),
                                "stop_lat": stop.get("stop_lat", ""),
                                "stop_lon": stop.get("stop_lon", ""),
                                "stop_sequence": st.get("stop_sequence", ""),
                                "arrival_time": st.get("arrival_time", ""),
                                "departure_time": st.get("departure_time", ""),
                                "departure_seconds": gtfs_time_seconds(st.get("departure_time", "")),
                            }
                        )

            display_rows.sort(
                key=lambda r: (
                    r["service_date"],
                    r["stop_id"],
                    r["departure_seconds"] if r["departure_seconds"] is not None else 10**9,
                    r["route_short_name"],
                )
            )

            route_fields = list(routes[0].keys()) if routes else ["route_id", "route_short_name", "route_long_name"]
            trip_fields = list(trips[0].keys()) if trips else ["route_id", "service_id", "trip_id"]
            stop_fields = list(stops[0].keys()) if stops else ["stop_id", "stop_name", "stop_lat", "stop_lon"]
            stop_time_fields = list(stop_times[0].keys()) if stop_times else ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"]

            write_csv(output_dir / "routes.csv", selected_routes, route_fields)
            write_csv(output_dir / "trips.csv", trips, trip_fields)
            write_csv(output_dir / "stops.csv", stops, stop_fields)
            write_csv(output_dir / "stop_times.csv", stop_times, stop_time_fields)
            write_csv(output_dir / "service_dates.csv", service_date_rows, ["service_date", "service_id"])

            display_fields = [
                "service_date",
                "route_id",
                "route_short_name",
                "route_long_name",
                "trip_id",
                "trip_headsign",
                "direction_id",
                "stop_id",
                "stop_name",
                "stop_lat",
                "stop_lon",
                "stop_sequence",
                "arrival_time",
                "departure_time",
                "departure_seconds",
            ]
            write_csv(output_dir / "display_departures.csv", display_rows, display_fields)

            by_stop_dir = output_dir / "display_stops"
            by_stop_dir.mkdir(exist_ok=True)
            grouped = defaultdict(list)
            for row in display_rows:
                grouped[row["stop_id"]].append(row)
            for stop_id, rows in grouped.items():
                payload = {
                    "schema_version": 1,
                    "stop_id": stop_id,
                    "stop_name": rows[0].get("stop_name", ""),
                    "stop_lat": rows[0].get("stop_lat", ""),
                    "stop_lon": rows[0].get("stop_lon", ""),
                    "departures": rows,
                }
                (by_stop_dir / f"{stop_id}.json").write_text(
                    json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                    encoding="utf-8",
                )

            manifest = {
                "schema_version": 1,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "source": args.source,
                "agency_label": args.agency_label,
                "start_date": start_date.isoformat(),
                "days": args.days,
                "requested_route_short_names": sorted(requested_short_names),
                "imported_route_short_names": sorted(
                    {row.get("route_short_name", "") for row in selected_routes if row.get("route_short_name", "")}
                ),
                "routes": len(selected_routes),
                "trips": len(trips),
                "stops": len(stops),
                "stop_times": len(stop_times),
                "service_date_rows": len(service_date_rows),
                "display_departure_rows": len(display_rows),
                "display_stop_files": len(grouped),
                "required_gtfs_files_present": True,
                "optional_calendar_present": "calendar.txt" in names,
                "optional_calendar_dates_present": "calendar_dates.txt" in names,
            }
            (output_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
