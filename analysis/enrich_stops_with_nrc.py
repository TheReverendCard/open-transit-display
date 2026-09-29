#!/usr/bin/env python3
"""Join Ride Guide-derived stop IDs to NRC CityLink stop names.

Inputs:
  stops.csv from extract_history_db.py or stop_catalogue.csv from
  build_realtime_catalogue.py
  nrc_citylink_stops.csv from import_nrc_stops.py

The primary join is exact ``stop_id`` equality.  For unmatched rows, if the
Ride Guide input contains coordinates, the nearest NRC stop is reported as a
review candidate with its distance.  Geographic candidates are deliberately
NOT promoted to confirmed names automatically.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich Ride Guide stops with NRC stop names.")
    parser.add_argument("--rideguide-stops", required=True)
    parser.add_argument("--nrc-stops", required=True)
    parser.add_argument("--output", default="data/derived_schedule/stops_enriched.csv")
    parser.add_argument(
        "--candidate-max-meters",
        type=float,
        default=1000.0,
        help="Maximum nearest-stop distance to retain as a review candidate.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[Dict[str, Any]], fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_stop_id(value: str) -> str:
    value = (value or "").strip()
    if value.endswith(".0") and value[:-2].isdigit():
        return value[:-2]
    return value


def safe_float(value: Any) -> Optional[float]:
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def rideguide_coordinates(row: Dict[str, str]) -> Tuple[Optional[float], Optional[float]]:
    candidates = [
        ("latitude_median", "longitude_median"),
        ("median_latitude", "median_longitude"),
        ("latitude", "longitude"),
        ("lat", "lon"),
    ]
    for lat_key, lon_key in candidates:
        lat = safe_float(row.get(lat_key))
        lon = safe_float(row.get(lon_key))
        if lat is not None and lon is not None:
            return lat, lon
    return None, None


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * radius * math.asin(math.sqrt(a))


def nearest_candidate(
    lat: float,
    lon: float,
    nrc_points: List[Tuple[float, float, Dict[str, str]]],
) -> Tuple[Optional[Dict[str, str]], Optional[float]]:
    best_row: Optional[Dict[str, str]] = None
    best_distance: Optional[float] = None
    for nrc_lat, nrc_lon, row in nrc_points:
        distance = haversine_meters(lat, lon, nrc_lat, nrc_lon)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_row = row
    return best_row, best_distance


def blank_confirmed_fields(result: Dict[str, Any]) -> None:
    result.update(
        {
            "nrc_stop_name": "",
            "nrc_latitude": "",
            "nrc_longitude": "",
            "nrc_shelter": "",
            "nrc_seat": "",
            "nrc_signage": "",
            "nrc_roadmarking": "",
            "nrc_timetable": "",
            "nrc_comment": "",
        }
    )


def apply_confirmed_fields(result: Dict[str, Any], match: Dict[str, str]) -> None:
    result.update(
        {
            "nrc_stop_name": match.get("stop_name", ""),
            "nrc_latitude": match.get("latitude", ""),
            "nrc_longitude": match.get("longitude", ""),
            "nrc_shelter": match.get("Shelter", ""),
            "nrc_seat": match.get("Seat", ""),
            "nrc_signage": match.get("Signage", ""),
            "nrc_roadmarking": match.get("Roadmarking", ""),
            "nrc_timetable": match.get("Timetable", ""),
            "nrc_comment": match.get("Comment", ""),
        }
    )


def candidate_confidence(distance: Optional[float]) -> str:
    if distance is None:
        return ""
    if distance <= 25:
        return "strong_candidate"
    if distance <= 75:
        return "possible_candidate"
    if distance <= 150:
        return "weak_candidate"
    return "review_only"


def main() -> None:
    args = parse_args()
    rideguide = read_csv(Path(args.rideguide_stops))
    nrc = read_csv(Path(args.nrc_stops))

    nrc_by_id: Dict[str, Dict[str, str]] = {}
    nrc_points: List[Tuple[float, float, Dict[str, str]]] = []
    for row in nrc:
        stop_id = normalize_stop_id(row.get("stop_id", ""))
        if stop_id:
            nrc_by_id[stop_id] = row
        lat = safe_float(row.get("latitude"))
        lon = safe_float(row.get("longitude"))
        if lat is not None and lon is not None:
            nrc_points.append((lat, lon, row))

    output: List[Dict[str, Any]] = []
    exact = 0
    unmatched = 0
    with_candidate = 0
    strong_candidates = 0

    for row in rideguide:
        stop_id = normalize_stop_id(row.get("stop_id", ""))
        match = nrc_by_id.get(stop_id)
        result: Dict[str, Any] = dict(row)
        result.update(
            {
                "nrc_candidate_stop_id": "",
                "nrc_candidate_stop_name": "",
                "nrc_candidate_distance_m": "",
                "nrc_candidate_confidence": "",
            }
        )

        if match:
            exact += 1
            result["nrc_match_type"] = "exact_stop_id"
            apply_confirmed_fields(result, match)
        else:
            unmatched += 1
            result["nrc_match_type"] = "unmatched"
            blank_confirmed_fields(result)

            lat, lon = rideguide_coordinates(row)
            if lat is not None and lon is not None and nrc_points:
                candidate, distance = nearest_candidate(lat, lon, nrc_points)
                if (
                    candidate is not None
                    and distance is not None
                    and distance <= args.candidate_max_meters
                ):
                    confidence = candidate_confidence(distance)
                    with_candidate += 1
                    if confidence == "strong_candidate":
                        strong_candidates += 1
                    result.update(
                        {
                            "nrc_candidate_stop_id": normalize_stop_id(candidate.get("stop_id", "")),
                            "nrc_candidate_stop_name": candidate.get("stop_name", ""),
                            "nrc_candidate_distance_m": f"{distance:.1f}",
                            "nrc_candidate_confidence": confidence,
                        }
                    )

        output.append(result)

    base_fields = list(rideguide[0].keys()) if rideguide else ["stop_id"]
    extra_fields = [
        "nrc_match_type",
        "nrc_stop_name",
        "nrc_latitude",
        "nrc_longitude",
        "nrc_shelter",
        "nrc_seat",
        "nrc_signage",
        "nrc_roadmarking",
        "nrc_timetable",
        "nrc_comment",
        "nrc_candidate_stop_id",
        "nrc_candidate_stop_name",
        "nrc_candidate_distance_m",
        "nrc_candidate_confidence",
    ]
    write_csv(Path(args.output), output, base_fields + extra_fields)

    print(f"Ride Guide stops: {len(rideguide)}")
    print(f"Exact NRC stop_id matches: {exact}")
    print(f"Unmatched: {unmatched}")
    print(f"Unmatched with geographic review candidate: {with_candidate}")
    print(f"Strong geographic candidates (<=25 m): {strong_candidates}")
    print("Geographic candidates remain unconfirmed and do not populate nrc_stop_name.")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
