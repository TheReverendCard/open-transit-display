#!/usr/bin/env python3
"""Generate compact per-stop fallback JSON from the derived static dataset.

The files are intended for low-power displays. They contain only the schedule
needed at one physical Ride Guide stop, grouped by route, and remain explicit
that the current seed calendar covers observed dates rather than a proven
weekly service pattern.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build compact per-stop fallback JSON.")
    parser.add_argument("--derived-dir", default="data/derived_static")
    parser.add_argument("--output-dir", default="data/display_fallback")
    return parser.parse_args()


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def route_sort_key(route: str) -> Tuple[int, str]:
    route = text(route)
    digits = "".join(ch for ch in route if ch.isdigit())
    suffix = route[len(digits):]
    return (int(digits) if digits else 9999, suffix)


def main() -> None:
    args = parse_args()
    derived = Path(args.derived_dir)
    out = Path(args.output_dir)
    stop_dir = out / "stops"
    stop_dir.mkdir(parents=True, exist_ok=True)

    stops = {row["stop_id"]: row for row in read_csv(derived / "stops.csv")}
    trips = {(row["route_id"], row["trip_id"]): row for row in read_csv(derived / "trips.csv")}
    stop_times = read_csv(derived / "stop_times.csv")
    service_patterns = read_csv(derived / "service_patterns.csv")

    by_stop: Dict[str, Dict[Tuple[str, str, str], List[Dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for row in stop_times:
        # Terminal arrivals at loop origins are not departures a rider can board.
        # Keep only rows whose reconstructed source is explicitly departure.
        if text(row.get("time_source")).lower() != "departure":
            continue
        stop_id = text(row.get("stop_id"))
        route_id = text(row.get("route_id"))
        trip_id = text(row.get("trip_id"))
        trip = trips.get((route_id, trip_id), {})
        key = (
            text(row.get("service_date")),
            text(row.get("public_route")),
            text(trip.get("destination_label")),
        )
        by_stop[stop_id][key].append(row)

    index: List[Dict[str, Any]] = []
    for stop_id in sorted(stops):
        stop = stops[stop_id]
        services = []
        for (service_date, public_route, destination), rows in sorted(
            by_stop.get(stop_id, {}).items(),
            key=lambda item: (item[0][0], route_sort_key(item[0][1]), item[0][2]),
        ):
            departures = sorted({text(row.get("scheduled_time")) for row in rows if text(row.get("scheduled_time"))})
            route_ids = sorted({text(row.get("route_id")) for row in rows if text(row.get("route_id"))})
            trip_ids = sorted({text(row.get("trip_id")) for row in rows if text(row.get("trip_id"))})
            confidence_values = {text(row.get("confidence")) for row in rows}
            confidence = "high" if confidence_values == {"high"} else "medium" if "low" not in confidence_values else "low"
            services.append(
                {
                    "service_date": service_date,
                    "route": public_route,
                    "rideguide_route_ids": route_ids,
                    "destination": destination,
                    "departures": departures,
                    "trip_ids": trip_ids,
                    "confidence": confidence,
                }
            )

        payload = {
            "schema_version": 1,
            "stop_id": stop_id,
            "stop_name": text(stop.get("stop_name")),
            "latitude": text(stop.get("latitude")),
            "longitude": text(stop.get("longitude")),
            "name_source": text(stop.get("name_source")),
            "source": "derived_static_transit",
            "official_gtfs": False,
            "calendar_scope": "observed_seed_dates_only",
            "services": services,
        }
        path = stop_dir / f"{stop_id}.json"
        path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
        index.append(
            {
                "stop_id": stop_id,
                "stop_name": text(stop.get("stop_name")),
                "service_groups": len(services),
                "file": f"stops/{stop_id}.json",
            }
        )

    manifest = {
        "schema_version": 1,
        "stop_files": len(index),
        "service_patterns": service_patterns,
        "official_gtfs": False,
        "calendar_scope": "observed_seed_dates_only",
        "index": index,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(index)} per-stop fallback files to {stop_dir}")


if __name__ == "__main__":
    main()
