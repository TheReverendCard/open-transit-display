#!/usr/bin/env python3
"""Infer a provisional static schedule from collected Ride Guide GTFS-RT data.

This script mines collector JSONL/JSONL.GZ files for schedule-based TripUpdates
(`prediction_source == "schedule_based"`) and estimates stable stop times for
route/trip/stop combinations.  It is intentionally labelled DERIVED, not
official GTFS.

Outputs:
  derived_schedule.csv
  derived_trips.csv
  inference_summary.json

Example:
  python analysis/infer_schedule_from_realtime.py \
      --input data/artifacts \
      --output-dir data/derived_schedule \
      --timezone Pacific/Auckland
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from zoneinfo import ZoneInfo


WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Infer a provisional schedule from Ride Guide realtime data.")
    parser.add_argument("--input", required=True, help="Collector file or directory containing .jsonl/.jsonl.gz files")
    parser.add_argument("--output-dir", default="data/derived_schedule")
    parser.add_argument("--timezone", default="Pacific/Auckland")
    parser.add_argument("--min-days", type=int, default=2, help="Minimum distinct service dates before confidence can exceed low")
    return parser.parse_args()


def iter_files(source: Path) -> Iterable[Path]:
    if source.is_file():
        yield source
        return
    for pattern in ("*.jsonl.gz", "*.jsonl"):
        yield from sorted(source.rglob(pattern))


def iter_rows(path: Path) -> Iterable[Dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def event_epoch(stop: Dict[str, Any]) -> int | None:
    for key in ("arrival", "departure"):
        event = stop.get(key)
        if isinstance(event, dict) and event.get("time"):
            try:
                return int(event["time"])
            except (TypeError, ValueError):
                pass
    return None


def sec_of_day(dt: datetime) -> int:
    return dt.hour * 3600 + dt.minute * 60 + dt.second


def fmt_hms(seconds: int) -> str:
    seconds %= 24 * 3600
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def circular_diff_seconds(a: int, b: int) -> int:
    diff = abs(a - b) % 86400
    return min(diff, 86400 - diff)


def circular_median(values: List[int]) -> int:
    if not values:
        raise ValueError("no values")
    # For transit schedules clustered within minutes, minimizing total circular
    # absolute distance is robust and avoids midnight wrap issues.
    return min(values, key=lambda candidate: sum(circular_diff_seconds(candidate, v) for v in values))


def confidence_label(distinct_days: int, spread_seconds: float, observations: int, min_days: int) -> str:
    if distinct_days >= max(4, min_days) and observations >= 8 and spread_seconds <= 60:
        return "high"
    if distinct_days >= min_days and observations >= 4 and spread_seconds <= 180:
        return "medium"
    return "low"


def write_csv(path: Path, rows: List[Dict[str, Any]], fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    tz = ZoneInfo(args.timezone)
    source = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    observations: Dict[Tuple[str, str, str, int, int], List[Tuple[int, str]]] = defaultdict(list)
    trip_meta: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    files_read = 0
    trip_updates_seen = 0
    schedule_updates_seen = 0
    stop_predictions_seen = 0

    for path in iter_files(source):
        files_read += 1
        for row in iter_rows(path):
            if row.get("kind") != "trip_update":
                continue
            trip_updates_seen += 1
            if row.get("prediction_source") != "schedule_based":
                continue
            schedule_updates_seen += 1

            route_id = str(row.get("route_id") or "")
            trip_id = str(row.get("trip_id") or "")
            vehicle_id = str(row.get("vehicle_id") or "")
            if not trip_id:
                continue

            for stop in row.get("stop_updates") or []:
                epoch = event_epoch(stop)
                if not epoch:
                    continue
                stop_id = str(stop.get("stop_id") or "")
                if not stop_id:
                    continue
                try:
                    stop_sequence = int(stop.get("stop_sequence") or 0)
                except (TypeError, ValueError):
                    stop_sequence = 0

                local_dt = datetime.fromtimestamp(epoch, tz)
                weekday = local_dt.weekday()  # Monday = 0
                service_date = local_dt.date().isoformat()
                seconds = sec_of_day(local_dt)

                key = (route_id, trip_id, stop_id, stop_sequence, weekday)
                observations[key].append((seconds, service_date))
                stop_predictions_seen += 1

                trip_key = (route_id, trip_id, weekday)
                meta = trip_meta.setdefault(trip_key, {
                    "route_id": route_id,
                    "trip_id": trip_id,
                    "weekday": weekday,
                    "weekday_name": WEEKDAY_NAMES[weekday],
                    "vehicle_ids": set(),
                    "service_dates": set(),
                })
                if vehicle_id:
                    meta["vehicle_ids"].add(vehicle_id)
                meta["service_dates"].add(service_date)

    derived_rows: List[Dict[str, Any]] = []
    for (route_id, trip_id, stop_id, stop_sequence, weekday), vals in observations.items():
        times = [v[0] for v in vals]
        dates = {v[1] for v in vals}
        estimate = circular_median(times)
        diffs = [circular_diff_seconds(estimate, v) for v in times]
        spread = statistics.median(diffs) if diffs else 0.0
        max_dev = max(diffs) if diffs else 0
        confidence = confidence_label(len(dates), spread, len(vals), args.min_days)
        weekday_name = WEEKDAY_NAMES[weekday]

        derived_rows.append({
            "source": "derived_from_rideguide_schedule_based",
            "official": "false",
            "route_id": route_id,
            "trip_id": trip_id,
            "stop_id": stop_id,
            "stop_sequence": stop_sequence,
            "weekday": weekday,
            "weekday_name": weekday_name,
            "inferred_time": fmt_hms(estimate),
            "inferred_seconds_since_midnight": estimate,
            "observations": len(vals),
            "distinct_service_dates": len(dates),
            "median_abs_deviation_seconds": round(float(spread), 1),
            "max_deviation_seconds": int(max_dev),
            "confidence": confidence,
        })

    derived_rows.sort(key=lambda r: (r["weekday"], r["route_id"], r["trip_id"], int(r["stop_sequence"])))

    trip_rows: List[Dict[str, Any]] = []
    for (_, _, _), meta in sorted(trip_meta.items()):
        trip_rows.append({
            "source": "derived_from_rideguide_schedule_based",
            "official": "false",
            "route_id": meta["route_id"],
            "trip_id": meta["trip_id"],
            "weekday": meta["weekday"],
            "weekday_name": meta["weekday_name"],
            "vehicle_ids": ";".join(sorted(meta["vehicle_ids"])),
            "distinct_service_dates": len(meta["service_dates"]),
        })

    schedule_fields = [
        "source", "official", "route_id", "trip_id", "stop_id", "stop_sequence",
        "weekday", "weekday_name", "inferred_time", "inferred_seconds_since_midnight",
        "observations", "distinct_service_dates", "median_abs_deviation_seconds",
        "max_deviation_seconds", "confidence",
    ]
    trip_fields = [
        "source", "official", "route_id", "trip_id", "weekday", "weekday_name",
        "vehicle_ids", "distinct_service_dates",
    ]

    write_csv(output_dir / "derived_schedule.csv", derived_rows, schedule_fields)
    write_csv(output_dir / "derived_trips.csv", trip_rows, trip_fields)

    summary = {
        "source": "Ride Guide GTFS-Realtime schedule_based TripUpdates",
        "official": False,
        "files_read": files_read,
        "trip_updates_seen": trip_updates_seen,
        "schedule_based_updates_seen": schedule_updates_seen,
        "stop_predictions_seen": stop_predictions_seen,
        "derived_schedule_rows": len(derived_rows),
        "derived_trip_patterns": len(trip_rows),
        "high_confidence_rows": sum(1 for row in derived_rows if row["confidence"] == "high"),
        "medium_confidence_rows": sum(1 for row in derived_rows if row["confidence"] == "medium"),
        "low_confidence_rows": sum(1 for row in derived_rows if row["confidence"] == "low"),
        "timezone": args.timezone,
        "note": "Derived schedule only. Do not present as official GTFS without validation.",
    }
    (output_dir / "inference_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"Wrote {output_dir / 'derived_schedule.csv'}")
    print(f"Wrote {output_dir / 'derived_trips.csv'}")
    print(f"Wrote {output_dir / 'inference_summary.json'}")


if __name__ == "__main__":
    main()
