#!/usr/bin/env python3
"""Build a compact, explicitly-derived static transit dataset.

This script converts the stable Ride Guide schedule reconstruction plus NRC stop
name enrichment into normalized CSV files. The result resembles the useful
parts of GTFS, but is deliberately not labelled official GTFS.

Inputs:
  trip_stop_patterns_named.csv
  stops_enriched.csv
  departure_trip_map.csv

Outputs:
  routes.csv
  trips.csv
  stops.csv
  stop_times.csv
  service_patterns.csv
  confidence.csv
  manifest.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build derived static transit dataset.")
    parser.add_argument("--trip-stops", required=True)
    parser.add_argument("--stops", required=True)
    parser.add_argument("--departures", required=True)
    parser.add_argument("--output-dir", default="data/derived_static")
    return parser.parse_args()


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[Dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def bool_text(value: Any) -> str:
    return "true" if text(value).lower() in {"1", "true", "yes", "y"} else "false"


def parse_dt(value: str) -> datetime | None:
    value = text(value)
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def hhmmss(value: str) -> str:
    dt = parse_dt(value)
    return dt.strftime("%H:%M:%S") if dt else ""


def route_sort_key(route: str) -> Tuple[int, str]:
    route = text(route)
    digits = "".join(ch for ch in route if ch.isdigit())
    suffix = route[len(digits):]
    return (int(digits) if digits else 9999, suffix)


def pattern_id(rows: List[Dict[str, str]]) -> str:
    material = "|".join(
        f"{text(row.get('stop_sequence'))}:{text(row.get('stop_id'))}"
        for row in sorted(rows, key=lambda r: int(float(text(r.get("stop_sequence")) or 0)))
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]


def confidence_for_trip(rows: List[Dict[str, str]], departure: Dict[str, str] | None) -> Tuple[str, float]:
    if not rows:
        return "low", 0.0
    exact = sum(bool_text(row.get("stable_exact")) == "true" for row in rows)
    fraction = exact / len(rows)
    dep_conf = text((departure or {}).get("confidence")).lower()
    if fraction >= 0.98 and dep_conf == "high":
        return "high", fraction
    if fraction >= 0.90 and dep_conf in {"high", "medium"}:
        return "medium", fraction
    return "low", fraction


def main() -> None:
    args = parse_args()
    trip_stop_rows = read_csv(Path(args.trip_stops))
    stop_rows = read_csv(Path(args.stops))
    departure_rows = read_csv(Path(args.departures))
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    departures_by_trip = {
        (text(row.get("rideguide_route_id")), text(row.get("rideguide_trip_id"))): row
        for row in departure_rows
    }

    grouped: Dict[Tuple[str, str], List[Dict[str, str]]] = defaultdict(list)
    for row in trip_stop_rows:
        route_id = text(row.get("route_id"))
        trip_id = text(row.get("trip_id"))
        if route_id and trip_id:
            grouped[(route_id, trip_id)].append(row)

    route_meta: Dict[str, Dict[str, str]] = {}
    for row in trip_stop_rows:
        route_id = text(row.get("route_id"))
        if not route_id:
            continue
        route_meta.setdefault(
            route_id,
            {
                "route_id": route_id,
                "public_route": text(row.get("public_route")),
                "route_name": text(row.get("route_name")),
            },
        )

    routes_out: List[Dict[str, Any]] = []
    for route_id, meta in sorted(route_meta.items(), key=lambda item: route_sort_key(item[1]["public_route"])):
        trips_for_route = [key for key in grouped if key[0] == route_id]
        patterns = {pattern_id(grouped[key]) for key in trips_for_route}
        routes_out.append(
            {
                **meta,
                "trip_count": len(trips_for_route),
                "distinct_patterns": len(patterns),
                "source": "rideguide_schedule_based+buslink_route_mapping",
            }
        )

    stops_out: List[Dict[str, Any]] = []
    for row in stop_rows:
        match_type = text(row.get("nrc_match_type"))
        stop_name = text(row.get("stop_name"))
        if not stop_name:
            stop_name = f"Stop {text(row.get('stop_id'))}"
        stops_out.append(
            {
                "stop_id": text(row.get("stop_id")),
                "stop_name": stop_name,
                "name_source": "nrc_exact_stop_id" if match_type == "exact_stop_id" else "machine_id_fallback",
                "nrc_match_type": match_type,
                "latitude": text(row.get("latitude_median")),
                "longitude": text(row.get("longitude_median")),
                "route_ids": text(row.get("route_ids")),
                "route_count": text(row.get("route_count")),
                "candidate_stop_id": text(row.get("candidate_stop_id")),
                "candidate_stop_name": text(row.get("candidate_stop_name")),
                "candidate_distance_m": text(row.get("candidate_distance_m")),
                "candidate_confidence": text(row.get("candidate_confidence")),
            }
        )

    trips_out: List[Dict[str, Any]] = []
    stop_times_out: List[Dict[str, Any]] = []
    confidence_out: List[Dict[str, Any]] = []
    service_dates = set()

    for (route_id, trip_id), rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda r: int(float(text(r.get("stop_sequence")) or 0)))
        departure = departures_by_trip.get((route_id, trip_id))
        service_date = text((departure or {}).get("service_date"))
        if service_date:
            service_dates.add(service_date)
        public_route = text(rows[0].get("public_route"))
        route_name = text(rows[0].get("route_name"))
        patt = pattern_id(rows)
        conf, stable_fraction = confidence_for_trip(rows, departure)

        named_rows = [row for row in rows if text(row.get("stop_name"))]
        first_named = text(named_rows[0].get("stop_name")) if named_rows else ""
        last_named = text(named_rows[-1].get("stop_name")) if named_rows else ""
        origin_stop_id = text(rows[0].get("stop_id"))
        terminal_stop_id = text(rows[-1].get("stop_id"))

        trips_out.append(
            {
                "route_id": route_id,
                "public_route": public_route,
                "route_name": route_name,
                "trip_id": trip_id,
                "service_date": service_date,
                "departure_time": text((departure or {}).get("derived_departure_time")),
                "pattern_id": patt,
                "stop_count": len(rows),
                "origin_stop_id": origin_stop_id,
                "terminal_stop_id": terminal_stop_id,
                "first_named_stop": first_named,
                "last_named_stop": last_named,
                "destination_label": route_name,
                "confidence": conf,
                "published_confirmed": bool_text((departure or {}).get("published_confirmed")),
            }
        )

        confidence_out.append(
            {
                "route_id": route_id,
                "trip_id": trip_id,
                "pattern_id": patt,
                "stable_stop_rows": sum(bool_text(row.get("stable_exact")) == "true" for row in rows),
                "stop_rows": len(rows),
                "stable_fraction": f"{stable_fraction:.4f}",
                "departure_confidence": text((departure or {}).get("confidence")),
                "overall_confidence": conf,
                "published_confirmed": bool_text((departure or {}).get("published_confirmed")),
            }
        )

        for row in rows:
            stop_times_out.append(
                {
                    "route_id": route_id,
                    "public_route": public_route,
                    "trip_id": trip_id,
                    "service_date": service_date,
                    "stop_sequence": text(row.get("stop_sequence")),
                    "stop_id": text(row.get("stop_id")),
                    "stop_name": text(row.get("stop_name")) or f"Stop {text(row.get('stop_id'))}",
                    "scheduled_time": hhmmss(text(row.get("canonical_time_nz"))),
                    "scheduled_datetime_nz": text(row.get("canonical_time_nz")),
                    "time_source": text(row.get("time_source")),
                    "observations": text(row.get("observations")),
                    "stable_exact": bool_text(row.get("stable_exact")),
                    "stop_name_match_type": text(row.get("stop_name_match_type")),
                    "confidence": conf,
                }
            )

    service_patterns = []
    for service_date in sorted(service_dates):
        try:
            dt = datetime.strptime(service_date, "%Y-%m-%d")
            weekday = dt.strftime("%A")
        except ValueError:
            weekday = ""
        service_patterns.append(
            {
                "service_date": service_date,
                "weekday": weekday,
                "status": "observed_seed_date_only",
                "recurrence_inferred": "false",
                "note": "One captured service day is insufficient to infer a recurring calendar.",
            }
        )

    write_csv(out / "routes.csv", routes_out, [
        "route_id", "public_route", "route_name", "trip_count", "distinct_patterns", "source"
    ])
    write_csv(out / "trips.csv", trips_out, [
        "route_id", "public_route", "route_name", "trip_id", "service_date", "departure_time",
        "pattern_id", "stop_count", "origin_stop_id", "terminal_stop_id", "first_named_stop",
        "last_named_stop", "destination_label", "confidence", "published_confirmed"
    ])
    write_csv(out / "stops.csv", stops_out, [
        "stop_id", "stop_name", "name_source", "nrc_match_type", "latitude", "longitude",
        "route_ids", "route_count", "candidate_stop_id", "candidate_stop_name",
        "candidate_distance_m", "candidate_confidence"
    ])
    write_csv(out / "stop_times.csv", stop_times_out, [
        "route_id", "public_route", "trip_id", "service_date", "stop_sequence", "stop_id",
        "stop_name", "scheduled_time", "scheduled_datetime_nz", "time_source", "observations",
        "stable_exact", "stop_name_match_type", "confidence"
    ])
    write_csv(out / "service_patterns.csv", service_patterns, [
        "service_date", "weekday", "status", "recurrence_inferred", "note"
    ])
    write_csv(out / "confidence.csv", confidence_out, [
        "route_id", "trip_id", "pattern_id", "stable_stop_rows", "stop_rows", "stable_fraction",
        "departure_confidence", "overall_confidence", "published_confirmed"
    ])

    manifest = {
        "dataset_type": "derived_static_transit",
        "official_gtfs": False,
        "source_service_dates": sorted(service_dates),
        "routes": len(routes_out),
        "trips": len(trips_out),
        "stops": len(stops_out),
        "stop_times": len(stop_times_out),
        "named_stops_exact_nrc": sum(row["name_source"] == "nrc_exact_stop_id" for row in stops_out),
        "unresolved_stop_names": sum(row["name_source"] != "nrc_exact_stop_id" for row in stops_out),
        "service_calendar_inferred": False,
        "note": "Derived from Ride Guide schedule-based observations and NRC stop metadata. Not an official GTFS feed.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
