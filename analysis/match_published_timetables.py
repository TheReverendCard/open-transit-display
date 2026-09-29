#!/usr/bin/env python3
"""Match BusLink passenger-facing routes/trips to Ride Guide machine IDs.

Route identity is taken first from BusLink's current timetable links, which
contain Ride Guide route IDs directly (for example ``#/route/1102``). That is
stronger evidence than geometry or timing similarity.

If published timetable rows and derived Ride Guide schedule rows are available,
this script then performs trip-level timing matching *within the already-known
route mapping*.

Inputs:
  published_routes.csv
  published_timetable.csv
  derived_schedule.csv

Outputs:
  route_matches.csv
  trip_matches.csv
  match_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


WEEKDAY_INDEX = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Match BusLink routes and timetables to Ride Guide IDs.")
    parser.add_argument("--routes", required=True, help="published_routes.csv")
    parser.add_argument("--published", required=True, help="published_timetable.csv")
    parser.add_argument("--derived", required=True, help="derived_schedule.csv")
    parser.add_argument("--output-dir", default="data/timetable_matches")
    parser.add_argument("--start-tolerance", type=float, default=6.0)
    parser.add_argument("--trip-top", type=int, default=5)
    return parser.parse_args()


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[Dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def safe_int(value: Any) -> Optional[int]:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def circular_minute_diff(a: int, b: int) -> int:
    diff = abs(a - b) % 1440
    return min(diff, 1440 - diff)


def best_clock_diff(published_minutes: int, derived_minutes: int, confidence: str) -> int:
    candidates = [published_minutes]
    if confidence == "ambiguous_12h":
        candidates.extend([(published_minutes + 720) % 1440, (published_minutes - 720) % 1440])
    return min(circular_minute_diff(candidate, derived_minutes) for candidate in candidates)


def parsed_service_days(value: str) -> set[int]:
    result: set[int] = set()
    for token in (value or "").split(";"):
        token = token.strip()
        if token in WEEKDAY_INDEX:
            result.add(WEEKDAY_INDEX[token])
    return result


def group_published(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str, str], List[Dict[str, str]]]:
    grouped: Dict[Tuple[str, str, str], List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = (row.get("route_public", ""), row.get("table_index", ""), row.get("trip_index", ""))
        grouped[key].append(row)
    for group in grouped.values():
        group.sort(key=lambda row: safe_int(row.get("timing_point_sequence")) or 999999)
    return grouped


def group_derived(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str, int], List[Dict[str, str]]]:
    grouped: Dict[Tuple[str, str, int], List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        weekday = safe_int(row.get("weekday"))
        if weekday is None:
            continue
        key = (row.get("route_id", ""), row.get("trip_id", ""), weekday)
        grouped[key].append(row)
    for group in grouped.values():
        group.sort(key=lambda row: safe_int(row.get("stop_sequence")) or 999999)
    return grouped


def first_published_time(group: List[Dict[str, str]]) -> Optional[Tuple[int, str]]:
    for row in group:
        minutes = safe_int(row.get("published_minutes"))
        if minutes is not None:
            return minutes, row.get("time_parse_confidence", "")
    return None


def first_derived_time(group: List[Dict[str, str]]) -> Optional[int]:
    for row in group:
        seconds = safe_int(row.get("inferred_seconds_since_midnight"))
        if seconds is not None:
            return int(round(seconds / 60.0)) % 1440
    return None


def published_offsets(group: List[Dict[str, str]]) -> List[int]:
    values: List[int] = []
    first: Optional[int] = None
    for row in group:
        minutes = safe_int(row.get("published_minutes"))
        if minutes is None:
            continue
        if first is None:
            first = minutes
        delta = minutes - first
        if delta < -360:
            delta += 720
        elif delta > 720:
            delta -= 720
        values.append(delta)
    return values


def derived_offsets(group: List[Dict[str, str]]) -> List[int]:
    values: List[int] = []
    first: Optional[int] = None
    for row in group:
        seconds = safe_int(row.get("inferred_seconds_since_midnight"))
        if seconds is None:
            continue
        minutes = seconds // 60
        if first is None:
            first = minutes
        delta = minutes - first
        if delta < -720:
            delta += 1440
        values.append(delta)
    return values


def sequence_shape_error(public: List[int], derived: List[int]) -> Optional[float]:
    if len(public) < 2 or len(derived) < 2:
        return None
    cursor = 0
    errors: List[float] = []
    for offset in public:
        best_index: Optional[int] = None
        best_error: Optional[int] = None
        for index in range(cursor, len(derived)):
            error = abs(derived[index] - offset)
            if best_error is None or error < best_error:
                best_error = error
                best_index = index
        if best_index is None or best_error is None:
            break
        errors.append(float(best_error))
        cursor = best_index
    if len(errors) < 2:
        return None
    return sum(errors) / len(errors)


def score_trip(public_group: List[Dict[str, str]], derived_group: List[Dict[str, str]], weekday: int, tolerance: float) -> Dict[str, Any]:
    public_start = first_published_time(public_group)
    derived_start = first_derived_time(derived_group)
    if public_start is None or derived_start is None:
        return {"score": 0.0, "start_error_minutes": "", "shape_error_minutes": "", "weekday_ok": False}

    allowed_days: set[int] = set()
    for row in public_group:
        allowed_days.update(parsed_service_days(row.get("service_days", "")))
    weekday_ok = not allowed_days or weekday in allowed_days

    published_minutes, time_confidence = public_start
    start_error = best_clock_diff(published_minutes, derived_start, time_confidence)
    shape_error = sequence_shape_error(published_offsets(public_group), derived_offsets(derived_group))

    start_score = max(0.0, 1.0 - start_error / max(1.0, tolerance * 3.0))
    shape_score = 0.35 if shape_error is None else max(0.0, 1.0 - shape_error / 12.0)
    weekday_score = 1.0 if weekday_ok else 0.0
    score = 100.0 * (0.65 * start_score + 0.25 * shape_score + 0.10 * weekday_score)

    return {
        "score": round(score, 2),
        "start_error_minutes": start_error,
        "shape_error_minutes": "" if shape_error is None else round(shape_error, 2),
        "weekday_ok": weekday_ok,
    }


def main() -> None:
    args = parse_args()
    route_rows = read_csv(Path(args.routes))
    published_rows = read_csv(Path(args.published))
    derived_rows = read_csv(Path(args.derived))

    direct_routes: Dict[str, Dict[str, str]] = {}
    route_matches: List[Dict[str, Any]] = []
    for row in route_rows:
        public = row.get("route_public", "")
        rideguide = row.get("rideguide_route_id", "")
        if not public or not rideguide:
            continue
        direct_routes[public] = row
        route_matches.append(
            {
                "route_public": public,
                "route_name": row.get("route_name", ""),
                "rideguide_route_id": rideguide,
                "mapping_source": row.get("mapping_source", "buslink_current_timetable_link"),
                "confidence": "direct",
                "evidence_url": row.get("url", ""),
            }
        )

    published_groups = group_published(published_rows)
    derived_groups = group_derived(derived_rows)
    trip_matches: List[Dict[str, Any]] = []

    for (route_public, table_index, trip_index), public_group in published_groups.items():
        route_mapping = direct_routes.get(route_public)
        if not route_mapping:
            continue
        rideguide_route_id = route_mapping.get("rideguide_route_id", "")
        candidates: List[Dict[str, Any]] = []

        for (route_id, trip_id, weekday), derived_group in derived_groups.items():
            if route_id != rideguide_route_id:
                continue
            result = score_trip(public_group, derived_group, weekday, args.start_tolerance)
            candidates.append(
                {
                    "route_public": route_public,
                    "route_name": route_mapping.get("route_name", ""),
                    "rideguide_route_id": rideguide_route_id,
                    "published_table_index": table_index,
                    "published_trip_index": trip_index,
                    "rideguide_trip_id": trip_id,
                    "weekday": weekday,
                    "weekday_name": derived_group[0].get("weekday_name", ""),
                    "section_context": public_group[0].get("section_context", ""),
                    **result,
                }
            )

        candidates.sort(key=lambda row: (-float(row["score"]), float(row["start_error_minutes"] or 99999)))
        for rank, candidate in enumerate(candidates[: args.trip_top], start=1):
            candidate["candidate_rank"] = rank
            if rank == 1 and float(candidate["score"]) >= 85:
                candidate["confidence"] = "high"
            elif rank == 1 and float(candidate["score"]) >= 65:
                candidate["confidence"] = "medium"
            else:
                candidate["confidence"] = "low"
            trip_matches.append(candidate)

    output_dir = Path(args.output_dir)
    route_fields = [
        "route_public",
        "route_name",
        "rideguide_route_id",
        "mapping_source",
        "confidence",
        "evidence_url",
    ]
    trip_fields = [
        "route_public",
        "route_name",
        "rideguide_route_id",
        "published_table_index",
        "published_trip_index",
        "rideguide_trip_id",
        "weekday",
        "weekday_name",
        "section_context",
        "score",
        "start_error_minutes",
        "shape_error_minutes",
        "weekday_ok",
        "candidate_rank",
        "confidence",
    ]

    write_csv(output_dir / "route_matches.csv", route_matches, route_fields)
    write_csv(output_dir / "trip_matches.csv", trip_matches, trip_fields)

    summary = {
        "direct_route_mappings": len(route_matches),
        "published_timetable_rows": len(published_rows),
        "published_trip_patterns": len(published_groups),
        "derived_schedule_rows": len(derived_rows),
        "derived_trip_patterns": len(derived_groups),
        "trip_candidates_written": len(trip_matches),
        "high_confidence_trip_matches": sum(1 for row in trip_matches if row["confidence"] == "high"),
        "medium_confidence_trip_matches": sum(1 for row in trip_matches if row["confidence"] == "medium"),
        "note": (
            "Route mappings are direct from current BusLink timetable links. "
            "Trip matching is only attempted inside those known route mappings."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "match_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"Wrote {output_dir / 'route_matches.csv'}")
    print(f"Wrote {output_dir / 'trip_matches.csv'}")
    print(f"Wrote {output_dir / 'match_summary.json'}")


if __name__ == "__main__":
    main()
