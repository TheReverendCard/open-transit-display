#!/usr/bin/env python3
"""Validate a Ride Guide realtime collector run.

Reads one or more collector .jsonl/.jsonl.gz files and checks that the
Whangārei realtime workaround is producing plausibly live data.

Exit status:
  0 = healthy (warnings are allowed)
  1 = unhealthy

The thresholds are intentionally conservative so a quiet service period does
not create false failures.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Ride Guide realtime collector output.")
    parser.add_argument("--input", required=True, help="Collector file or directory")
    parser.add_argument("--min-vehicles", type=int, default=1)
    parser.add_argument("--min-trip-updates", type=int, default=1)
    parser.add_argument("--min-routes", type=int, default=5)
    parser.add_argument("--max-feed-age-seconds", type=int, default=300)
    parser.add_argument("--summary-json", default="data/run/health_summary.json")
    return parser.parse_args()


def iter_files(source: Path) -> Iterable[Path]:
    if source.is_file():
        yield source
        return
    for pattern in ("*.jsonl.gz", "*.jsonl"):
        yield from sorted(source.rglob(pattern))


def iter_rows(path: Path) -> Iterable[dict[str, Any]]:
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


def parse_iso8601(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def main() -> int:
    args = parse_args()
    source = Path(args.input)

    files = list(iter_files(source))
    if not files:
        print("HEALTH FAIL: no collector files found", file=sys.stderr)
        return 1

    counts = Counter()
    routes: set[str] = set()
    vehicles: set[str] = set()
    trips: set[str] = set()
    newest_source_timestamp: float | None = None
    newest_received_timestamp: float | None = None
    total_rows = 0

    for path in files:
        for row in iter_rows(path):
            total_rows += 1
            kind = str(row.get("kind") or "unknown")
            counts[kind] += 1

            route_id = str(row.get("route_id") or "")
            vehicle_id = str(row.get("vehicle_id") or "")
            trip_id = str(row.get("trip_id") or "")
            if route_id:
                routes.add(route_id)
            if vehicle_id:
                vehicles.add(vehicle_id)
            if trip_id:
                trips.add(trip_id)

            feed_timestamp = row.get("feed_timestamp")
            if feed_timestamp:
                try:
                    ts = float(feed_timestamp)
                    newest_source_timestamp = ts if newest_source_timestamp is None else max(newest_source_timestamp, ts)
                except (TypeError, ValueError):
                    pass

            for key in ("vehicle_timestamp", "trip_timestamp"):
                value = row.get(key)
                if value:
                    try:
                        ts = float(value)
                        newest_source_timestamp = ts if newest_source_timestamp is None else max(newest_source_timestamp, ts)
                    except (TypeError, ValueError):
                        pass

            received_ts = parse_iso8601(row.get("received_at"))
            if received_ts is not None:
                newest_received_timestamp = (
                    received_ts if newest_received_timestamp is None else max(newest_received_timestamp, received_ts)
                )

    now = datetime.now(timezone.utc).timestamp()
    source_age = None if newest_source_timestamp is None else max(0.0, now - newest_source_timestamp)
    received_age = None if newest_received_timestamp is None else max(0.0, now - newest_received_timestamp)

    failures: list[str] = []
    warnings: list[str] = []

    vehicle_rows = counts["vehicle"]
    trip_update_rows = counts["trip_update"]
    empty_rows = counts["empty_feed"]

    if vehicle_rows < args.min_vehicles:
        failures.append(f"vehicle rows {vehicle_rows} < required {args.min_vehicles}")
    if trip_update_rows < args.min_trip_updates:
        failures.append(f"trip update rows {trip_update_rows} < required {args.min_trip_updates}")
    if len(routes) < args.min_routes:
        failures.append(f"distinct routes {len(routes)} < required {args.min_routes}")
    if source_age is None:
        failures.append("no usable feed/vehicle/trip timestamp found")
    elif source_age > args.max_feed_age_seconds:
        failures.append(
            f"newest source timestamp is {source_age:.0f}s old, limit is {args.max_feed_age_seconds}s"
        )

    if received_age is None:
        warnings.append("no usable received_at timestamp found")
    elif received_age > args.max_feed_age_seconds:
        warnings.append(f"newest received_at timestamp is {received_age:.0f}s old")

    if empty_rows:
        empty_ratio = empty_rows / total_rows if total_rows else 0.0
        if empty_ratio >= 0.25:
            warnings.append(f"empty_feed rows are {empty_ratio:.1%} of all rows")
        else:
            warnings.append(f"{empty_rows} empty_feed rows observed")

    summary = {
        "healthy": not failures,
        "files_checked": len(files),
        "total_rows": total_rows,
        "vehicle_rows": vehicle_rows,
        "trip_update_rows": trip_update_rows,
        "alert_rows": counts["alert"],
        "empty_feed_rows": empty_rows,
        "distinct_routes": len(routes),
        "distinct_vehicle_ids": len(vehicles),
        "distinct_trip_ids": len(trips),
        "newest_source_age_seconds": None if source_age is None else round(source_age, 1),
        "newest_received_age_seconds": None if received_age is None else round(received_age, 1),
        "thresholds": {
            "min_vehicles": args.min_vehicles,
            "min_trip_updates": args.min_trip_updates,
            "min_routes": args.min_routes,
            "max_feed_age_seconds": args.max_feed_age_seconds,
        },
        "warnings": warnings,
        "failures": failures,
    }

    summary_path = Path(args.summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    status = "PASS" if not failures else "FAIL"
    print(f"HEALTH {status}")
    print(json.dumps(summary, indent=2))

    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        with open(github_summary, "a", encoding="utf-8") as handle:
            handle.write("## Whangārei realtime feed health\n\n")
            handle.write(f"**Status:** {status}\n\n")
            handle.write(
                f"- Vehicle rows: {vehicle_rows}\n"
                f"- Trip updates: {trip_update_rows}\n"
                f"- Routes seen: {len(routes)}\n"
                f"- Vehicles seen: {len(vehicles)}\n"
                f"- Trips seen: {len(trips)}\n"
                f"- Empty feed rows: {empty_rows}\n"
            )
            if source_age is not None:
                handle.write(f"- Newest source timestamp age: {source_age:.0f} s\n")
            for warning in warnings:
                handle.write(f"- Warning: {warning}\n")
            for failure in failures:
                handle.write(f"- Failure: {failure}\n")

    if failures:
        for failure in failures:
            print(f"HEALTH FAIL: {failure}", file=sys.stderr)
        return 1

    for warning in warnings:
        print(f"HEALTH WARNING: {warning}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
