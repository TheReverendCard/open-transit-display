#!/usr/bin/env python3
"""Build a public-route departure-time to Ride Guide trip-ID map.

Input is ``routes_trips.csv`` produced by ``extract_history_db.py``.  Rows with a
stable schedule-based first time are converted into a compact mapping suitable
for matching against a passenger-facing timetable.

This does not claim the Ride Guide schedule-based time is independently
published.  It records the machine trip ID and its derived scheduled departure
so an external published timetable can confirm it.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build route/departure to Ride Guide trip map.")
    parser.add_argument("--routes-trips", required=True, help="routes_trips.csv from extract_history_db.py")
    parser.add_argument("--output", default="data/derived_schedule/departure_trip_map.csv")
    return parser.parse_args()


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_local_datetime(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def write_csv(path: Path, rows: Iterable[Dict[str, Any]], fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    rows = read_csv(Path(args.routes_trips))
    output: List[Dict[str, Any]] = []

    for row in rows:
        dt = parse_local_datetime(row.get("schedule_first_time_nz", ""))
        if dt is None:
            continue

        schedule_rows = int(float(row.get("schedule_stop_rows") or 0))
        stable_rows = int(float(row.get("schedule_exact_stable_rows") or 0))
        if schedule_rows <= 0:
            continue

        stable_fraction = stable_rows / schedule_rows
        if stable_fraction >= 0.98:
            confidence = "high"
        elif stable_fraction >= 0.90:
            confidence = "medium"
        else:
            confidence = "low"

        output.append(
            {
                "service_date": dt.date().isoformat(),
                "public_route": row.get("public_route", ""),
                "route_name": row.get("route_name", ""),
                "rideguide_route_id": row.get("route_id", ""),
                "rideguide_trip_id": row.get("trip_id", ""),
                "derived_departure_time": dt.strftime("%H:%M:%S"),
                "derived_departure_minutes": dt.hour * 60 + dt.minute,
                "schedule_stop_rows": schedule_rows,
                "stable_schedule_rows": stable_rows,
                "stable_fraction": f"{stable_fraction:.4f}",
                "confidence": confidence,
                "source": "rideguide_schedule_based",
                "published_confirmed": "false",
            }
        )

    def sort_key(row: Dict[str, Any]) -> tuple:
        route = str(row["public_route"])
        digits = "".join(ch for ch in route if ch.isdigit())
        suffix = route[len(digits):]
        return (int(digits) if digits else 9999, suffix, int(row["derived_departure_minutes"]), str(row["rideguide_trip_id"]))

    output.sort(key=sort_key)
    fields = [
        "service_date",
        "public_route",
        "route_name",
        "rideguide_route_id",
        "rideguide_trip_id",
        "derived_departure_time",
        "derived_departure_minutes",
        "schedule_stop_rows",
        "stable_schedule_rows",
        "stable_fraction",
        "confidence",
        "source",
        "published_confirmed",
    ]
    write_csv(Path(args.output), output, fields)
    print(f"Wrote {len(output)} departure/trip rows to {args.output}")


if __name__ == "__main__":
    main()
