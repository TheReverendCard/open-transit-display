#!/usr/bin/env python3
"""Assess the health and continuity of normalized Ride Guide collector data.

The collector writes normalized JSONL/JSONL.GZ rows. This script recursively
scans one or more files/directories and reports what was actually captured,
including collection gaps and hourly coverage.

Outputs:
  collection_health_summary.json
  collection_health_hourly.csv
  collection_health_gaps.csv
  collection_health_files.csv

The "expected 10-second samples" values are deliberately approximate. Ride
Guide sends more than one feed type, and multiple messages can land in the same
second, so received_at seconds are used as a simple observation heartbeat rather
than claiming to count exact WebSocket messages.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set
from zoneinfo import ZoneInfo


@dataclass
class HourStats:
    rows: int = 0
    observation_seconds: Set[int] = field(default_factory=set)
    kinds: Counter = field(default_factory=Counter)
    route_ids: Set[str] = field(default_factory=set)
    trip_ids: Set[str] = field(default_factory=set)
    vehicle_ids: Set[str] = field(default_factory=set)
    stop_ids: Set[str] = field(default_factory=set)
    schedule_based_rows: int = 0
    vehicle_assigned_rows: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report Ride Guide collection health.")
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="JSONL/JSONL.GZ file or directory. May be repeated.",
    )
    parser.add_argument("--output-dir", default="data/collection_health")
    parser.add_argument("--timezone", default="Pacific/Auckland")
    parser.add_argument(
        "--gap-threshold-seconds",
        type=int,
        default=30,
        help="Report heartbeat gaps at least this long.",
    )
    parser.add_argument(
        "--nominal-interval-seconds",
        type=int,
        default=10,
        help="Nominal Ride Guide update interval used for approximate coverage.",
    )
    return parser.parse_args()


def discover_files(inputs: Sequence[str]) -> List[Path]:
    found: Set[Path] = set()
    for raw in inputs:
        path = Path(raw)
        if path.is_file() and (path.name.endswith(".jsonl") or path.name.endswith(".jsonl.gz")):
            found.add(path)
        elif path.is_dir():
            found.update(path.rglob("*.jsonl"))
            found.update(path.rglob("*.jsonl.gz"))
    return sorted(found)


def open_text(path: Path):
    if path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def nonempty(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def row_stop_ids(row: Dict[str, Any]) -> Iterable[str]:
    stop_id = nonempty(row.get("stop_id"))
    if stop_id:
        yield stop_id
    for update in row.get("stop_updates") or []:
        if isinstance(update, dict):
            candidate = nonempty(update.get("stop_id"))
            if candidate:
                yield candidate


def add_identity(stats: HourStats, row: Dict[str, Any]) -> None:
    route_id = nonempty(row.get("route_id"))
    trip_id = nonempty(row.get("trip_id"))
    vehicle_id = nonempty(row.get("vehicle_id"))
    if route_id:
        stats.route_ids.add(route_id)
    if trip_id:
        stats.trip_ids.add(trip_id)
    if vehicle_id:
        stats.vehicle_ids.add(vehicle_id)
    stats.stop_ids.update(row_stop_ids(row))


def write_csv(path: Path, rows: Iterable[Dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    tz = ZoneInfo(args.timezone)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    files = discover_files(args.input)

    kind_counts: Counter = Counter()
    prediction_counts: Counter = Counter()
    unique_routes: Set[str] = set()
    unique_trips: Set[str] = set()
    unique_vehicles: Set[str] = set()
    unique_stops: Set[str] = set()
    heartbeat_seconds: Set[int] = set()
    hours: Dict[str, HourStats] = defaultdict(HourStats)
    file_rows: List[Dict[str, Any]] = []
    invalid_json_rows = 0
    rows_without_received_at = 0
    total_rows = 0

    for path in files:
        file_count = 0
        file_invalid = 0
        file_times: List[datetime] = []
        file_kinds: Counter = Counter()
        with open_text(path) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    invalid_json_rows += 1
                    file_invalid += 1
                    continue
                if not isinstance(row, dict):
                    invalid_json_rows += 1
                    file_invalid += 1
                    continue

                total_rows += 1
                file_count += 1
                kind = nonempty(row.get("kind")) or "unknown"
                kind_counts[kind] += 1
                file_kinds[kind] += 1

                prediction_source = nonempty(row.get("prediction_source"))
                if prediction_source:
                    prediction_counts[prediction_source] += 1

                route_id = nonempty(row.get("route_id"))
                trip_id = nonempty(row.get("trip_id"))
                vehicle_id = nonempty(row.get("vehicle_id"))
                if route_id:
                    unique_routes.add(route_id)
                if trip_id:
                    unique_trips.add(trip_id)
                if vehicle_id:
                    unique_vehicles.add(vehicle_id)
                unique_stops.update(row_stop_ids(row))

                received = parse_time(row.get("received_at"))
                if received is None:
                    rows_without_received_at += 1
                    continue

                file_times.append(received)
                second = int(received.timestamp())
                heartbeat_seconds.add(second)
                local = received.astimezone(tz)
                hour_key = local.replace(minute=0, second=0, microsecond=0).isoformat()
                stats = hours[hour_key]
                stats.rows += 1
                stats.observation_seconds.add(second)
                stats.kinds[kind] += 1
                add_identity(stats, row)
                if prediction_source == "schedule_based":
                    stats.schedule_based_rows += 1
                elif prediction_source == "vehicle_assigned":
                    stats.vehicle_assigned_rows += 1

        file_rows.append(
            {
                "path": str(path),
                "rows": file_count,
                "invalid_json_rows": file_invalid,
                "first_received_at": min(file_times).isoformat() if file_times else "",
                "last_received_at": max(file_times).isoformat() if file_times else "",
                "vehicle_rows": file_kinds.get("vehicle", 0),
                "trip_update_rows": file_kinds.get("trip_update", 0),
                "alert_rows": file_kinds.get("alert", 0),
                "empty_feed_rows": file_kinds.get("empty_feed", 0),
            }
        )

    heartbeats = sorted(heartbeat_seconds)
    gaps: List[Dict[str, Any]] = []
    gap_lengths: List[int] = []
    for previous, current in zip(heartbeats, heartbeats[1:]):
        delta = current - previous
        if delta >= args.gap_threshold_seconds:
            gap_lengths.append(delta)
            gaps.append(
                {
                    "gap_start_utc": datetime.fromtimestamp(previous, timezone.utc).isoformat(),
                    "gap_end_utc": datetime.fromtimestamp(current, timezone.utc).isoformat(),
                    "gap_start_local": datetime.fromtimestamp(previous, timezone.utc).astimezone(tz).isoformat(),
                    "gap_end_local": datetime.fromtimestamp(current, timezone.utc).astimezone(tz).isoformat(),
                    "gap_seconds": delta,
                    "gap_minutes": round(delta / 60.0, 2),
                    "approx_missed_10s_samples": max(0, round(delta / args.nominal_interval_seconds) - 1),
                }
            )

    hourly_rows: List[Dict[str, Any]] = []
    for hour_key in sorted(hours):
        stats = hours[hour_key]
        expected = max(1, round(3600 / args.nominal_interval_seconds))
        observed = len(stats.observation_seconds)
        hourly_rows.append(
            {
                "hour_local": hour_key,
                "rows": stats.rows,
                "observation_seconds": observed,
                "approx_expected_10s_samples": expected,
                "approx_heartbeat_coverage_percent": round(min(100.0, 100.0 * observed / expected), 2),
                "vehicle_rows": stats.kinds.get("vehicle", 0),
                "trip_update_rows": stats.kinds.get("trip_update", 0),
                "alert_rows": stats.kinds.get("alert", 0),
                "empty_feed_rows": stats.kinds.get("empty_feed", 0),
                "schedule_based_rows": stats.schedule_based_rows,
                "vehicle_assigned_rows": stats.vehicle_assigned_rows,
                "unique_routes": len(stats.route_ids),
                "unique_trips": len(stats.trip_ids),
                "unique_vehicles": len(stats.vehicle_ids),
                "unique_stops": len(stats.stop_ids),
            }
        )

    if heartbeats:
        first_dt = datetime.fromtimestamp(heartbeats[0], timezone.utc)
        last_dt = datetime.fromtimestamp(heartbeats[-1], timezone.utc)
        span_seconds = max(0, heartbeats[-1] - heartbeats[0])
        approx_expected = max(1, round(span_seconds / args.nominal_interval_seconds) + 1)
        approx_coverage = min(100.0, 100.0 * len(heartbeats) / approx_expected)
    else:
        first_dt = None
        last_dt = None
        span_seconds = 0
        approx_expected = 0
        approx_coverage = 0.0

    summary = {
        "files_scanned": len(files),
        "rows": total_rows,
        "invalid_json_rows": invalid_json_rows,
        "rows_without_received_at": rows_without_received_at,
        "first_received_at_utc": first_dt.isoformat() if first_dt else None,
        "last_received_at_utc": last_dt.isoformat() if last_dt else None,
        "collection_span_hours": round(span_seconds / 3600.0, 3),
        "observation_seconds": len(heartbeats),
        "nominal_interval_seconds": args.nominal_interval_seconds,
        "approx_expected_10s_samples_across_full_span": approx_expected,
        "approx_heartbeat_coverage_percent_across_full_span": round(approx_coverage, 2),
        "reported_gap_threshold_seconds": args.gap_threshold_seconds,
        "reported_gaps": len(gaps),
        "longest_gap_seconds": max(gap_lengths) if gap_lengths else 0,
        "median_reported_gap_seconds": round(median(gap_lengths), 2) if gap_lengths else 0,
        "kind_counts": dict(sorted(kind_counts.items())),
        "prediction_source_counts": dict(sorted(prediction_counts.items())),
        "unique_routes": len(unique_routes),
        "unique_trips": len(unique_trips),
        "unique_vehicles": len(unique_vehicles),
        "unique_stops": len(unique_stops),
        "timezone": args.timezone,
        "note": (
            "Coverage is a heartbeat diagnostic based on distinct received_at seconds, not an exact WebSocket-message count. "
            "Large gaps are still useful for identifying missing collection windows."
        ),
    }

    write_csv(
        output_dir / "collection_health_hourly.csv",
        hourly_rows,
        [
            "hour_local",
            "rows",
            "observation_seconds",
            "approx_expected_10s_samples",
            "approx_heartbeat_coverage_percent",
            "vehicle_rows",
            "trip_update_rows",
            "alert_rows",
            "empty_feed_rows",
            "schedule_based_rows",
            "vehicle_assigned_rows",
            "unique_routes",
            "unique_trips",
            "unique_vehicles",
            "unique_stops",
        ],
    )
    write_csv(
        output_dir / "collection_health_gaps.csv",
        gaps,
        [
            "gap_start_utc",
            "gap_end_utc",
            "gap_start_local",
            "gap_end_local",
            "gap_seconds",
            "gap_minutes",
            "approx_missed_10s_samples",
        ],
    )
    write_csv(
        output_dir / "collection_health_files.csv",
        file_rows,
        [
            "path",
            "rows",
            "invalid_json_rows",
            "first_received_at",
            "last_received_at",
            "vehicle_rows",
            "trip_update_rows",
            "alert_rows",
            "empty_feed_rows",
        ],
    )
    (output_dir / "collection_health_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(json.dumps(summary, indent=2))
    print(f"Wrote collection-health outputs to {output_dir}")


if __name__ == "__main__":
    main()
