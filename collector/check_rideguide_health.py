#!/usr/bin/env python3
"""Validate a Ride Guide realtime collector run.

Reads collector .jsonl/.jsonl.gz files and checks that the Whangārei realtime
workaround is reachable and, during expected CityLink service hours, is
producing useful live trip data.

Exit status:
  0 = healthy (warnings are allowed)
  1 = unhealthy
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from collections import Counter
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Ride Guide realtime collector output.")
    parser.add_argument("--input", required=True, help="Collector file or directory")
    parser.add_argument("--timezone", default="Pacific/Auckland")
    parser.add_argument("--max-feed-age-seconds", type=int, default=300)

    # During expected service, these are hard health requirements.
    parser.add_argument("--min-trip-updates", type=int, default=1)
    parser.add_argument("--min-routes", type=int, default=1)

    # These are informational thresholds only.
    parser.add_argument("--warn-min-vehicles", type=int, default=1)
    parser.add_argument("--warn-min-routes", type=int, default=5)

    # Current CityLink operating envelope, deliberately padded around the
    # first/last scheduled trips. Sunday currently has no regular service.
    parser.add_argument("--weekday-start", default="05:45")
    parser.add_argument("--weekday-end", default="19:15")
    parser.add_argument("--saturday-start", default="06:40")
    parser.add_argument("--saturday-end", default="17:30")
    parser.add_argument("--sunday-service", action="store_true")

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


def parse_hhmm(value: str) -> time:
    try:
        hour_text, minute_text = value.split(":", 1)
        return time(hour=int(hour_text), minute=int(minute_text))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid HH:MM value: {value!r}") from exc


def service_expected(local_dt: datetime, args: argparse.Namespace) -> bool:
    weekday = local_dt.weekday()  # Monday = 0, Sunday = 6
    local_t = local_dt.time().replace(second=0, microsecond=0)

    if weekday <= 4:
        return parse_hhmm(args.weekday_start) <= local_t <= parse_hhmm(args.weekday_end)

    if weekday == 5:
        return parse_hhmm(args.saturday_start) <= local_t <= parse_hhmm(args.saturday_end)

    return bool(args.sunday_service)


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

    now_utc = datetime.now(timezone.utc)
    now_ts = now_utc.timestamp()
    source_age = None if newest_source_timestamp is None else max(0.0, now_ts - newest_source_timestamp)
    received_age = None if newest_received_timestamp is None else max(0.0, now_ts - newest_received_timestamp)

    reference_ts = newest_received_timestamp if newest_received_timestamp is not None else now_ts
    local_dt = datetime.fromtimestamp(reference_ts, ZoneInfo(args.timezone))
    expected_service = service_expected(local_dt, args)

    failures: list[str] = []
    warnings: list[str] = []

    vehicle_rows = counts["vehicle"]
    trip_update_rows = counts["trip_update"]
    empty_rows = counts["empty_feed"]

    # Connectivity/freshness checks always apply, including outside service.
    if total_rows == 0:
        failures.append("collector file contained no decoded rows")

    if source_age is None:
        failures.append("no usable feed/vehicle/trip timestamp found")
    elif source_age > args.max_feed_age_seconds:
        failures.append(
            f"newest source timestamp is {source_age:.0f}s old, limit is {args.max_feed_age_seconds}s"
        )

    if received_age is None:
        failures.append("no usable received_at timestamp found")
    elif received_age > args.max_feed_age_seconds:
        failures.append(
            f"newest received_at timestamp is {received_age:.0f}s old, limit is {args.max_feed_age_seconds}s"
        )

    # Live-data checks only apply when regular service should actually be running.
    if expected_service:
        if trip_update_rows < args.min_trip_updates:
            failures.append(f"trip update rows {trip_update_rows} < required {args.min_trip_updates}")
        if len(routes) < args.min_routes:
            failures.append(f"distinct routes {len(routes)} < required {args.min_routes}")

        if vehicle_rows < args.warn_min_vehicles:
            warnings.append(
                f"vehicle rows {vehicle_rows} < preferred {args.warn_min_vehicles}"
            )
        if len(routes) < args.warn_min_routes:
            warnings.append(
                f"distinct routes {len(routes)} < preferred {args.warn_min_routes}"
            )
    else:
        warnings.append(
            "outside expected regular CityLink service hours; active vehicle/trip counts are informational only"
        )

    if empty_rows:
        empty_ratio = empty_rows / total_rows if total_rows else 0.0
        if empty_ratio >= 0.25:
            warnings.append(f"empty_feed rows are {empty_ratio:.1%} of all rows")
        else:
            warnings.append(f"{empty_rows} empty_feed rows observed")

    summary = {
        "healthy": not failures,
        "service_expected": expected_service,
        "check_local_time": local_dt.isoformat(timespec="seconds"),
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
            "min_trip_updates_during_service": args.min_trip_updates,
            "min_routes_during_service": args.min_routes,
            "warn_min_vehicles": args.warn_min_vehicles,
            "warn_min_routes": args.warn_min_routes,
            "max_feed_age_seconds": args.max_feed_age_seconds,
            "weekday_service_window": f"{args.weekday_start}-{args.weekday_end}",
            "saturday_service_window": f"{args.saturday_start}-{args.saturday_end}",
            "sunday_service": args.sunday_service,
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
            handle.write(f"- Check time: {local_dt.isoformat(timespec='minutes')}\n")
            handle.write(f"- Regular service expected: {'yes' if expected_service else 'no'}\n")
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
