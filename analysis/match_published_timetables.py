#!/usr/bin/env python3
"""Match BusLink's published passenger timetable against inferred Ride Guide trips.

Inputs:
  published_timetable.csv from scrape_buslink_timetables.py
  derived_schedule.csv from infer_schedule_from_realtime.py

The matcher deliberately starts with timing fingerprints rather than route geometry.
It scores public route/trip candidates against Ride Guide machine route/trip IDs using
published timing-point times, inferred stop times, weekday overlap, and sequence shape.

Outputs:
  route_matches.csv
  trip_matches.csv
  match_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
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
    parser = argparse.ArgumentParser(description="Match published BusLink timetable to Ride Guide IDs.")
    parser.add_argument("--published", required=True, help="published_timetable.csv")
    parser.add_argument("--derived", required=True, help="derived_schedule.csv")
    parser.add_argument("--output-dir", default="data/timetable_matches")
    parser.add_argument("--start-tolerance", type=float, default=6.0, help="Minutes for a strong trip-start match")
    parser.add_argument("--route-top", type=int, default=5, help="Route candidates retained per public route")
    parser.add_argument("--trip-top", type=int, default=5, help="Trip candidates retained per published trip")
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


def safe_int(value: Any) -> Optional[int]:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def circular_minute_diff(a: int, b: int) -> int:
    diff = abs(a - b) % 1440
    return min(diff, 1440 - diff)


def best_clock_diff(published_minutes: int, derived_minutes: int, confidence: str) -> int:
    """Allow a 12-hour ambiguity only when the published page did not establish AM/PM."""
    candidates = [published_minutes]
    if confidence == "ambiguous_12h":
        candidates.extend([(published_minutes + 720) % 1440, (published_minutes - 720) % 1440])
    return min(circular_minute_diff(candidate, derived_minutes) for candidate in candidates)


def parsed_service_days(value: str) -> set[int]:
    result = set()
    for token in (value or "").split(";"):
        token = token.strip()
        if token in WEEKDAY_INDEX:
            result.add(WEEKDAY_INDEX[token])
    return result


def group_published(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str, str], List[Dict[str, str]]]:
    grouped: Dict[Tuple[str, str, str], List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = (
            row.get("route_public", ""),
            row.get("table_index", ""),
            row.get("trip_index", ""),
        )
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


def first_time_published(group: List[Dict[str, str]]) -> Optional[Tuple[int, str]]:
    for row in group:
        minutes = safe_int(row.get("published_minutes"))
        if minutes is not None:
            return minutes, row.get("time_parse_confidence", "")
    return None


def first_time_derived(group: List[Dict[str, str]]) -> Optional[int]:
    for row in group:
        seconds = safe_int(row.get("inferred_seconds_since_midnight"))
        if seconds is not None:
            return int(round(seconds / 60.0)) % 1440
    return None


def published_offsets(group: List[Dict[str, str]]) -> List[int]:
    values: List[int] = []
    first = None
    for row in group:
        minutes = safe_int(row.get("published_minutes"))
        if minutes is None:
            continue
        if first is None:
            first = minutes
        # Timetable rows are short enough that 12h-wrap is not expected within one trip.
        delta = minutes - first
        if delta < -360:
            delta += 720
        elif delta > 720:
            delta -= 720
        values.append(delta)
    return values


def derived_offsets(group: List[Dict[str, str]]) -> List[int]:
    values: List[int] = []
    first = None
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
    """Compare relative timing shape without requiring stop-name identity.

    Published timetables often expose only major timing points while Ride Guide has
    every stop.  We therefore align each published offset to its nearest derived
    offset while preserving order.
    """
    if len(public) < 2 or len(derived) < 2:
        return None

    cursor = 0
    errors: List[float] = []
    for offset in public:
        best_index = None
        best_error = None
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


def weekday_overlap(public_group: List[Dict[str, str]], derived_weekday: int) -> Tuple[bool, str]:
    days: set[int] = set()
    raw_values = []
    for row in public_group:
        raw = row.get("service_days", "")
        if raw:
            raw_values.append(raw)
            days.update(parsed_service_days(raw))
    if not days:
        return True, "published_weekday_unknown"
    return derived_weekday in days, ";".join(sorted(set(raw_values)))


def score_trip(
    public_group: List[Dict[str, str]],
    derived_group: List[Dict[str, str]],
    derived_weekday: int,
    start_tolerance: float,
) -> Dict[str, Any]:
    public_start = first_time_published(public_group)
    derived_start = first_time_derived(derived_group)
    if public_start is None or derived_start is None:
        return {"score": 0.0, "start_error_minutes": "", "shape_error_minutes": "", "weekday_ok": False}

    published_minutes, confidence = public_start
    start_error = best_clock_diff(published_minutes, derived_start, confidence)
    weekday_ok, _ = weekday_overlap(public_group, derived_weekday)
    shape_error = sequence_shape_error(published_offsets(public_group), derived_offsets(derived_group))

    start_score = max(0.0, 1.0 - start_error / max(1.0, start_tolerance * 3.0))
    if shape_error is None:
        shape_score = 0.35
    else:
        shape_score = max(0.0, 1.0 - shape_error / 12.0)
    weekday_score = 1.0 if weekday_ok else 0.0

    # Timing is the strongest evidence.  Relative trip shape and weekday are corroboration.
    score = 100.0 * (0.60 * start_score + 0.25 * shape_score + 0.15 * weekday_score)
    return {
        "score": round(score, 2),
        "start_error_minutes": start_error,
        "shape_error_minutes": "" if shape_error is None else round(shape_error, 2),
        "weekday_ok": weekday_ok,
    }


def main() -> None:
    args = parse_args()
    published_rows = read_csv(Path(args.published))
    derived_rows = read_csv(Path(args.derived))

    published_groups = group_published(published_rows)
    derived_groups = group_derived(derived_rows)

    trip_candidates: List[Dict[str, Any]] = []
    for (route_public, table_index, trip_index), public_group in published_groups.items():
        public_name = public_group[0].get("route_name", "") if public_group else ""
        context = public_group[0].get("section_context", "") if public_group else ""
        allowed_days = set()
        for row in public_group:
            allowed_days.update(parsed_service_days(row.get("service_days", "")))

        candidates: List[Dict[str, Any]] = []
        for (route_id, trip_id, weekday), derived_group in derived_groups.items():
            if allowed_days and weekday not in allowed_days:
                continue
            result = score_trip(public_group, derived_group, weekday, args.start_tolerance)
            candidates.append(
                {
                    "route_public": route_public,
                    "route_name": public_name,
                    "published_table_index": table_index,
                    "published_trip_index": trip_index,
                    "section_context": context,
                    "rideguide_route_id": route_id,
                    "rideguide_trip_id": trip_id,
                    "weekday": weekday,
                    "weekday_name": derived_group[0].get("weekday_name", ""),
                    **result,
                }
            )

        candidates.sort(key=lambda row: (-float(row["score"]), float(row["start_error_minutes"] or 99999)))
        for rank, candidate in enumerate(candidates[: args.trip_top], start=1):
            candidate["candidate_rank"] = rank
            trip_candidates.append(candidate)

    # Aggregate top trip evidence into route-level confidence.
    evidence: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    matched_trip_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    for row in trip_candidates:
        if row["candidate_rank"] != 1:
            continue
        key = (row["route_public"], row["rideguide_route_id"])
        evidence[key].append(float(row["score"]))
        if float(row["score"]) >= 70:
            matched_trip_counts[key] += 1

    public_routes = sorted({row.get("route_public", "") for row in published_rows if row.get("route_public")})
    rideguide_routes = sorted({row.get("route_id", "") for row in derived_rows if row.get("route_id")})

    route_candidates: List[Dict[str, Any]] = []
    for public_route in public_routes:
        candidates = []
        public_name = next((row.get("route_name", "") for row in published_rows if row.get("route_public") == public_route), "")
        for rideguide_route in rideguide_routes:
            scores = evidence.get((public_route, rideguide_route), [])
            if scores:
                mean_score = sum(scores) / len(scores)
                strong = matched_trip_counts.get((public_route, rideguide_route), 0)
            else:
                # There may be no winning top-ranked trips for this route pair.
                pair_scores = [
                    float(row["score"])
                    for row in trip_candidates
                    if row["route_public"] == public_route and row["rideguide_route_id"] == rideguide_route
                ]
                mean_score = sum(pair_scores) / len(pair_scores) if pair_scores else 0.0
                strong = sum(1 for score in pair_scores if score >= 70)

            candidates.append(
                {
                    "route_public": public_route,
                    "route_name": public_name,
                    "rideguide_route_id": rideguide_route,
                    "mean_trip_match_score": round(mean_score, 2),
                    "strong_trip_matches": strong,
                    "evidence_trip_count": len(scores),
                }
            )

        candidates.sort(key=lambda row: (-row["strong_trip_matches"], -row["mean_trip_match_score"], row["rideguide_route_id"]))
        for rank, candidate in enumerate(candidates[: args.route_top], start=1):
            candidate["candidate_rank"] = rank
            if rank == 1 and candidate["strong_trip_matches"] >= 2 and candidate["mean_trip_match_score"] >= 80:
                candidate["confidence"] = "high"
            elif rank == 1 and candidate["mean_trip_match_score"] >= 65:
                candidate["confidence"] = "medium"
            else:
                candidate["confidence"] = "low"
            route_candidates.append(candidate)

    output_dir = Path(args.output_dir)
    trip_fields = [
        "route_public",
        "route_name",
        "published_table_index",
        "published_trip_index",
        "section_context",
        "rideguide_route_id",
        "rideguide_trip_id",
        "weekday",
        "weekday_name",
        "score",
        "start_error_minutes",
        "shape_error_minutes",
        "weekday_ok",
        "candidate_rank",
    ]
    route_fields = [
        "route_public",
        "route_name",
        "rideguide_route_id",
        "mean_trip_match_score",
        "strong_trip_matches",
        "evidence_trip_count",
        "candidate_rank",
        "confidence",
    ]

    write_csv(output_dir / "trip_matches.csv", trip_candidates, trip_fields)
    write_csv(output_dir / "route_matches.csv", route_candidates, route_fields)

    top_routes = [row for row in route_candidates if row["candidate_rank"] == 1]
    summary = {
        "published_rows": len(published_rows),
        "published_trip_patterns": len(published_groups),
        "derived_rows": len(derived_rows),
        "derived_trip_patterns": len(derived_groups),
        "public_routes": len(public_routes),
        "rideguide_routes": len(rideguide_routes),
        "high_confidence_route_matches": sum(1 for row in top_routes if row["confidence"] == "high"),
        "medium_confidence_route_matches": sum(1 for row in top_routes if row["confidence"] == "medium"),
        "low_confidence_route_matches": sum(1 for row in top_routes if row["confidence"] == "low"),
        "note": "Candidate matching only. Confirm top mappings before treating them as canonical machine-ID links.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "match_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"Wrote {output_dir / 'route_matches.csv'}")
    print(f"Wrote {output_dir / 'trip_matches.csv'}")
    print(f"Wrote {output_dir / 'match_summary.json'}")


if __name__ == "__main__":
    main()
