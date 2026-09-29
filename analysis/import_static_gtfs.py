#!/usr/bin/env python3
"""Import a static GTFS feed and build a normalized daily schedule.

Inputs
------
A GTFS ZIP file or extracted GTFS directory containing, at minimum:
    routes.txt
    trips.txt
    stops.txt
    stop_times.txt
and at least one of:
    calendar.txt
    calendar_dates.txt

Outputs
-------
The importer writes normalized CSV files plus a date-specific schedule CSV
that can be consumed by analysis/schedule_monitor.py.

Example
-------
python analysis/import_static_gtfs.py \
    --gtfs citylink_gtfs.zip \
    --date 2026-09-29 \
    --timezone Pacific/Auckland \
    --output-dir data/static
"""

from __future__ import annotations

import argparse
import csv
import io
import shutil
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo


REQUIRED_CORE = ("routes.txt", "trips.txt", "stops.txt", "stop_times.txt")
CALENDAR_FILES = ("calendar.txt", "calendar_dates.txt")


@dataclass
class FeedFiles:
    root: Path
    temporary_root: Optional[Path] = None

    def close(self) -> None:
        if self.temporary_root and self.temporary_root.exists():
            shutil.rmtree(self.temporary_root, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import static GTFS and build a date-specific transit schedule."
    )
    parser.add_argument(
        "--gtfs",
        required=True,
        help="Path to a GTFS .zip file or an extracted GTFS directory.",
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Service date to build, YYYY-MM-DD. Defaults to today.",
    )
    parser.add_argument(
        "--timezone",
        default="Pacific/Auckland",
        help="IANA timezone used to expand GTFS service times.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/static",
        help="Directory for normalized CSVs and generated schedule files.",
    )
    parser.add_argument(
        "--route-id",
        action="append",
        default=[],
        help="Optional route_id filter. Repeat for multiple routes.",
    )
    return parser.parse_args()


def open_feed(path: Path) -> FeedFiles:
    if path.is_dir():
        return FeedFiles(root=path)

    if not path.is_file():
        raise FileNotFoundError(f"GTFS source not found: {path}")

    if path.suffix.lower() != ".zip":
        raise ValueError("GTFS input must be a directory or .zip file")

    temp_root = Path(tempfile.mkdtemp(prefix="gtfs_import_"))
    with zipfile.ZipFile(path, "r") as archive:
        archive.extractall(temp_root)

    root = locate_gtfs_root(temp_root)
    return FeedFiles(root=root, temporary_root=temp_root)


def locate_gtfs_root(root: Path) -> Path:
    if all((root / name).exists() for name in REQUIRED_CORE):
        return root

    candidates = []
    for child in root.rglob("stop_times.txt"):
        candidate = child.parent
        if all((candidate / name).exists() for name in REQUIRED_CORE):
            candidates.append(candidate)

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError("Could not locate required GTFS files in archive")
    raise ValueError("Archive contains multiple possible GTFS roots")


def validate_feed(root: Path) -> None:
    missing = [name for name in REQUIRED_CORE if not (root / name).exists()]
    if missing:
        raise ValueError("Missing required GTFS files: " + ", ".join(missing))

    if not any((root / name).exists() for name in CALENDAR_FILES):
        raise ValueError(
            "Feed must contain calendar.txt and/or calendar_dates.txt to build a daily schedule"
        )


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_optional_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    return read_csv(path)


def write_csv(path: Path, rows: Iterable[Dict[str, object]], fields: List[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def parse_gtfs_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def active_service_ids(root: Path, service_date: date) -> Set[str]:
    active: Set[str] = set()

    calendar_rows = read_optional_csv(root / "calendar.txt")
    weekday_name = service_date.strftime("%A").lower()

    for row in calendar_rows:
        service_id = row.get("service_id", "").strip()
        if not service_id:
            continue

        try:
            start_date = parse_gtfs_date(row.get("start_date", ""))
            end_date = parse_gtfs_date(row.get("end_date", ""))
        except ValueError:
            continue

        if start_date <= service_date <= end_date and row.get(weekday_name) == "1":
            active.add(service_id)

    exception_rows = read_optional_csv(root / "calendar_dates.txt")
    service_date_text = service_date.strftime("%Y%m%d")

    for row in exception_rows:
        if row.get("date") != service_date_text:
            continue
        service_id = row.get("service_id", "").strip()
        exception_type = row.get("exception_type", "").strip()
        if not service_id:
            continue
        if exception_type == "1":
            active.add(service_id)
        elif exception_type == "2":
            active.discard(service_id)

    return active


def parse_gtfs_time(value: str) -> Optional[timedelta]:
    value = (value or "").strip()
    if not value:
        return None

    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid GTFS time: {value}")

    hours, minutes, seconds = (int(part) for part in parts)
    if minutes < 0 or minutes > 59 or seconds < 0 or seconds > 59 or hours < 0:
        raise ValueError(f"Invalid GTFS time: {value}")

    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def local_datetime(service_date: date, offset: timedelta, timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    midnight = datetime(
        service_date.year,
        service_date.month,
        service_date.day,
        0,
        0,
        0,
        tzinfo=tz,
    )
    return midnight + offset


def normalize_routes(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    fields = [
        "route_id",
        "agency_id",
        "route_short_name",
        "route_long_name",
        "route_desc",
        "route_type",
        "route_url",
        "route_color",
        "route_text_color",
        "route_sort_order",
    ]
    return [{field: row.get(field, "") for field in fields} for row in rows]


def normalize_stops(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    fields = [
        "stop_id",
        "stop_code",
        "stop_name",
        "stop_desc",
        "stop_lat",
        "stop_lon",
        "zone_id",
        "stop_url",
        "location_type",
        "parent_station",
        "platform_code",
    ]
    return [{field: row.get(field, "") for field in fields} for row in rows]


def normalize_trips(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    fields = [
        "route_id",
        "service_id",
        "trip_id",
        "trip_headsign",
        "trip_short_name",
        "direction_id",
        "block_id",
        "shape_id",
        "wheelchair_accessible",
        "bikes_allowed",
    ]
    return [{field: row.get(field, "") for field in fields} for row in rows]


def normalize_stop_times(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    fields = [
        "trip_id",
        "arrival_time",
        "departure_time",
        "stop_id",
        "stop_sequence",
        "stop_headsign",
        "pickup_type",
        "drop_off_type",
        "shape_dist_traveled",
        "timepoint",
    ]
    return [{field: row.get(field, "") for field in fields} for row in rows]


def build_daily_schedule(
    routes: List[Dict[str, str]],
    trips: List[Dict[str, str]],
    stops: List[Dict[str, str]],
    stop_times: List[Dict[str, str]],
    active_services: Set[str],
    service_date: date,
    timezone_name: str,
    route_filter: Set[str],
) -> List[Dict[str, object]]:
    route_by_id = {row.get("route_id", ""): row for row in routes}
    stop_by_id = {row.get("stop_id", ""): row for row in stops}

    active_trip_by_id: Dict[str, Dict[str, str]] = {}
    for trip in trips:
        if trip.get("service_id") not in active_services:
            continue
        route_id = trip.get("route_id", "")
        if route_filter and route_id not in route_filter:
            continue
        trip_id = trip.get("trip_id", "")
        if trip_id:
            active_trip_by_id[trip_id] = trip

    schedule: List[Dict[str, object]] = []

    for stop_time in stop_times:
        trip_id = stop_time.get("trip_id", "")
        trip = active_trip_by_id.get(trip_id)
        if not trip:
            continue

        arrival_offset = parse_gtfs_time(stop_time.get("arrival_time", ""))
        departure_offset = parse_gtfs_time(stop_time.get("departure_time", ""))
        event_offset = arrival_offset or departure_offset
        if event_offset is None:
            continue

        scheduled_at = local_datetime(service_date, event_offset, timezone_name)
        departure_at = (
            local_datetime(service_date, departure_offset, timezone_name)
            if departure_offset is not None
            else scheduled_at
        )

        route_id = trip.get("route_id", "")
        route = route_by_id.get(route_id, {})
        stop_id = stop_time.get("stop_id", "")
        stop = stop_by_id.get(stop_id, {})

        schedule.append(
            {
                "service_date": service_date.isoformat(),
                "service_id": trip.get("service_id", ""),
                "route_id": route_id,
                "route_short_name": route.get("route_short_name", ""),
                "route_long_name": route.get("route_long_name", ""),
                "trip_id": trip_id,
                "trip_headsign": trip.get("trip_headsign", ""),
                "direction_id": trip.get("direction_id", ""),
                "shape_id": trip.get("shape_id", ""),
                "stop_id": stop_id,
                "stop_name": stop.get("stop_name", ""),
                "stop_lat": stop.get("stop_lat", ""),
                "stop_lon": stop.get("stop_lon", ""),
                "stop_sequence": stop_time.get("stop_sequence", ""),
                "scheduled_at": scheduled_at.isoformat(timespec="seconds"),
                "scheduled_departure_at": departure_at.isoformat(timespec="seconds"),
                "gtfs_arrival_time": stop_time.get("arrival_time", ""),
                "gtfs_departure_time": stop_time.get("departure_time", ""),
            }
        )

    schedule.sort(
        key=lambda row: (
            str(row["scheduled_at"]),
            str(row["route_id"]),
            str(row["trip_id"]),
            int(row["stop_sequence"]) if str(row["stop_sequence"]).isdigit() else 999999,
        )
    )
    return schedule


def compare_id_samples(
    trips: List[Dict[str, str]], routes: List[Dict[str, str]], stops: List[Dict[str, str]]
) -> Dict[str, List[str]]:
    return {
        "route_ids": sorted({row.get("route_id", "") for row in routes if row.get("route_id")})[:25],
        "trip_ids": sorted({row.get("trip_id", "") for row in trips if row.get("trip_id")})[:25],
        "stop_ids": sorted({row.get("stop_id", "") for row in stops if row.get("stop_id")})[:25],
    }


def main() -> None:
    args = parse_args()

    try:
        service_date = date.fromisoformat(args.date)
    except ValueError as exc:
        raise SystemExit(f"Invalid --date value {args.date!r}; expected YYYY-MM-DD") from exc

    try:
        ZoneInfo(args.timezone)
    except Exception as exc:
        raise SystemExit(f"Unknown timezone: {args.timezone}") from exc

    source = Path(args.gtfs)
    output_dir = Path(args.output_dir)
    route_filter = set(args.route_id)

    feed = open_feed(source)
    try:
        validate_feed(feed.root)

        routes_raw = read_csv(feed.root / "routes.txt")
        trips_raw = read_csv(feed.root / "trips.txt")
        stops_raw = read_csv(feed.root / "stops.txt")
        stop_times_raw = read_csv(feed.root / "stop_times.txt")

        routes = normalize_routes(routes_raw)
        trips = normalize_trips(trips_raw)
        stops = normalize_stops(stops_raw)
        stop_times = normalize_stop_times(stop_times_raw)

        active_services = active_service_ids(feed.root, service_date)
        if not active_services:
            print(
                f"WARNING: no active service_ids found for {service_date}. "
                "Check calendar/calendar_dates and the requested date."
            )

        output_dir.mkdir(parents=True, exist_ok=True)

        route_fields = list(routes[0].keys()) if routes else ["route_id"]
        trip_fields = list(trips[0].keys()) if trips else ["trip_id"]
        stop_fields = list(stops[0].keys()) if stops else ["stop_id"]
        stop_time_fields = list(stop_times[0].keys()) if stop_times else ["trip_id", "stop_id"]

        route_count = write_csv(output_dir / "normalized_routes.csv", routes, route_fields)
        trip_count = write_csv(output_dir / "normalized_trips.csv", trips, trip_fields)
        stop_count = write_csv(output_dir / "normalized_stops.csv", stops, stop_fields)
        stop_time_count = write_csv(
            output_dir / "normalized_stop_times.csv", stop_times, stop_time_fields
        )

        daily_schedule = build_daily_schedule(
            routes=routes,
            trips=trips,
            stops=stops,
            stop_times=stop_times,
            active_services=active_services,
            service_date=service_date,
            timezone_name=args.timezone,
            route_filter=route_filter,
        )

        schedule_fields = [
            "service_date",
            "service_id",
            "route_id",
            "route_short_name",
            "route_long_name",
            "trip_id",
            "trip_headsign",
            "direction_id",
            "shape_id",
            "stop_id",
            "stop_name",
            "stop_lat",
            "stop_lon",
            "stop_sequence",
            "scheduled_at",
            "scheduled_departure_at",
            "gtfs_arrival_time",
            "gtfs_departure_time",
        ]
        schedule_path = output_dir / f"schedule-{service_date.isoformat()}.csv"
        schedule_count = write_csv(schedule_path, daily_schedule, schedule_fields)

        sample_ids = compare_id_samples(trips, routes, stops)
        sample_path = output_dir / "id_samples.txt"
        with sample_path.open("w", encoding="utf-8") as handle:
            handle.write("Static GTFS sample IDs for realtime compatibility checks\n\n")
            for key, values in sample_ids.items():
                handle.write(f"{key}:\n")
                for value in values:
                    handle.write(f"  {value}\n")
                handle.write("\n")

        print("Static GTFS import complete.")
        print(f"Source root: {feed.root}")
        print(f"Service date: {service_date}")
        print(f"Timezone: {args.timezone}")
        print(f"Active service IDs: {len(active_services)}")
        print(f"Routes: {route_count}")
        print(f"Trips: {trip_count}")
        print(f"Stops: {stop_count}")
        print(f"Stop times: {stop_time_count}")
        print(f"Daily schedule rows: {schedule_count}")
        print(f"Daily schedule: {schedule_path}")
        print(f"ID samples: {sample_path}")

    finally:
        feed.close()


if __name__ == "__main__":
    main()
