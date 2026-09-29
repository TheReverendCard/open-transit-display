#!/usr/bin/env python3
"""Monitor observed stop arrivals against scheduled times.

This module is deliberately independent of a particular static-GTFS importer.
It consumes the normalized JSONL.GZ files produced by collector/collect_rideguide.py
and a small schedule CSV.  Once static GTFS is imported, that importer only needs
to emit the schedule CSV schema documented below.

Schedule CSV columns:
    route_id, trip_id, stop_id, scheduled_at

`scheduled_at` must be an ISO-8601 timestamp with an offset, for example:
    2026-09-29T08:15:00+13:00

Observed arrivals are inferred conservatively from VEHICLE_POSITIONS records whose
GTFS-Realtime current_status is STOPPED_AT (numeric value 1).  The first observed
STOPPED_AT timestamp for each vehicle/trip/stop is treated as the arrival sample.
This is useful for monitoring and benchmarking, but it is not yet intended to be
our final ground-truth algorithm.

The script can also generate a deterministic demo dataset so the CSV and plotting
pipeline can be tested before a static GTFS feed is available.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt


STOPPED_AT = 1
ON_TIME_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class ScheduleKey:
    route_id: str
    trip_id: str
    stop_id: str


@dataclass
class ScheduleRow:
    key: ScheduleKey
    scheduled_at: datetime


@dataclass
class ArrivalRow:
    key: ScheduleKey
    vehicle_id: str
    observed_at: datetime
    received_at: datetime
    samples_seen: int = 1


def parse_iso(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp must include a timezone offset: {value}")
    return parsed


def format_iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def read_schedule(path: Path) -> dict[ScheduleKey, ScheduleRow]:
    schedule: dict[ScheduleKey, ScheduleRow] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"route_id", "trip_id", "stop_id", "scheduled_at"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"Schedule CSV is missing required columns: {', '.join(sorted(missing))}"
            )

        for row in reader:
            key = ScheduleKey(
                route_id=(row.get("route_id") or "").strip(),
                trip_id=(row.get("trip_id") or "").strip(),
                stop_id=(row.get("stop_id") or "").strip(),
            )
            if not all((key.route_id, key.trip_id, key.stop_id)):
                continue
            schedule[key] = ScheduleRow(
                key=key,
                scheduled_at=parse_iso(row["scheduled_at"]),
            )
    return schedule


def iter_jsonl_records(paths: Iterable[Path]):
    for path in paths:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    print(f"Skipping malformed JSON in {path}:{line_number}: {exc}")


def detect_arrivals(records: Iterable[dict]) -> dict[ScheduleKey, ArrivalRow]:
    arrivals: dict[ScheduleKey, ArrivalRow] = {}

    for record in records:
        if record.get("kind") != "vehicle":
            continue
        if int(record.get("current_status") or -1) != STOPPED_AT:
            continue

        route_id = str(record.get("route_id") or "").strip()
        trip_id = str(record.get("trip_id") or "").strip()
        stop_id = str(record.get("stop_id") or "").strip()
        vehicle_id = str(record.get("vehicle_id") or "").strip()
        if not all((route_id, trip_id, stop_id)):
            continue

        received_raw = record.get("received_at")
        if not received_raw:
            continue
        received_at = parse_iso(str(received_raw))

        vehicle_timestamp = record.get("vehicle_timestamp")
        if vehicle_timestamp:
            observed_at = datetime.fromtimestamp(
                int(vehicle_timestamp), tz=timezone.utc
            ).astimezone(received_at.tzinfo)
        else:
            observed_at = received_at

        key = ScheduleKey(route_id=route_id, trip_id=trip_id, stop_id=stop_id)
        existing = arrivals.get(key)

        if existing is None:
            arrivals[key] = ArrivalRow(
                key=key,
                vehicle_id=vehicle_id,
                observed_at=observed_at,
                received_at=received_at,
            )
        else:
            existing.samples_seen += 1
            if observed_at < existing.observed_at:
                existing.observed_at = observed_at
                existing.received_at = received_at
                existing.vehicle_id = vehicle_id

    return arrivals


def classify_variance(seconds: float) -> str:
    if seconds < -ON_TIME_WINDOW_SECONDS:
        return "early"
    if seconds > ON_TIME_WINDOW_SECONDS:
        return "late"
    return "on_time"


def join_schedule_and_arrivals(
    schedule: dict[ScheduleKey, ScheduleRow],
    arrivals: dict[ScheduleKey, ArrivalRow],
) -> list[dict]:
    rows: list[dict] = []

    for key, scheduled in sorted(
        schedule.items(), key=lambda item: item[1].scheduled_at
    ):
        arrival = arrivals.get(key)
        if arrival is None:
            continue

        observed = arrival.observed_at.astimezone(scheduled.scheduled_at.tzinfo)
        variance_seconds = (observed - scheduled.scheduled_at).total_seconds()

        rows.append(
            {
                "route_id": key.route_id,
                "trip_id": key.trip_id,
                "vehicle_id": arrival.vehicle_id,
                "stop_id": key.stop_id,
                "scheduled_at": format_iso(scheduled.scheduled_at),
                "observed_at": format_iso(observed),
                "variance_seconds": int(round(variance_seconds)),
                "variance_minutes": round(variance_seconds / 60.0, 2),
                "arrival_state": classify_variance(variance_seconds),
                "stopped_at_samples": arrival.samples_seen,
                "ground_truth_method": "first_STOPPED_AT_vehicle_timestamp",
            }
        )

    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "route_id",
        "trip_id",
        "vehicle_id",
        "stop_id",
        "scheduled_at",
        "observed_at",
        "variance_seconds",
        "variance_minutes",
        "arrival_state",
        "stopped_at_samples",
        "ground_truth_method",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def plot_rows(rows: list[dict], path: Path) -> None:
    if not rows:
        raise ValueError("No matched arrival rows are available to plot.")

    path.parent.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[tuple[datetime, float]]] = {}
    for row in rows:
        grouped.setdefault(row["route_id"], []).append(
            (parse_iso(row["scheduled_at"]), float(row["variance_minutes"]))
        )

    fig, ax = plt.subplots(figsize=(11, 6))
    for route_id, values in sorted(grouped.items()):
        values.sort(key=lambda value: value[0])
        ax.plot(
            [value[0] for value in values],
            [value[1] for value in values],
            marker="o",
            label=f"Route {route_id}",
        )

    ax.axhline(0, linewidth=1)
    ax.set_title("Route arrival variance from schedule")
    ax.set_xlabel("Scheduled arrival")
    ax.set_ylabel("Variance from schedule (minutes)")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def create_demo_schedule(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    base = datetime(2026, 9, 29, 7, 30, tzinfo=timezone(timedelta(hours=13)))
    demo = [
        ("1102", "demo-1102-01", "CENTRAL", base, -90),
        ("1104", "demo-1104-01", "CENTRAL", base + timedelta(minutes=12), 60),
        ("1102", "demo-1102-02", "CENTRAL", base + timedelta(minutes=30), 180),
        ("1104", "demo-1104-02", "CENTRAL", base + timedelta(minutes=42), -30),
        ("1102", "demo-1102-03", "CENTRAL", base + timedelta(minutes=60), 300),
        ("1104", "demo-1104-03", "CENTRAL", base + timedelta(minutes=72), 120),
        ("1102", "demo-1102-04", "CENTRAL", base + timedelta(minutes=90), 420),
        ("1104", "demo-1104-04", "CENTRAL", base + timedelta(minutes=102), 240),
        ("1102", "demo-1102-05", "CENTRAL", base + timedelta(minutes=120), 90),
        ("1104", "demo-1104-05", "CENTRAL", base + timedelta(minutes=132), -120),
        ("1102", "demo-1102-06", "CENTRAL", base + timedelta(minutes=150), 480),
        ("1104", "demo-1104-06", "CENTRAL", base + timedelta(minutes=162), 210),
    ]

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["route_id", "trip_id", "stop_id", "scheduled_at"],
        )
        writer.writeheader()
        for route_id, trip_id, stop_id, scheduled_at, _ in demo:
            writer.writerow(
                {
                    "route_id": route_id,
                    "trip_id": trip_id,
                    "stop_id": stop_id,
                    "scheduled_at": format_iso(scheduled_at),
                }
            )


def create_demo_observations(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    base = datetime(2026, 9, 29, 7, 30, tzinfo=timezone(timedelta(hours=13)))
    demo = [
        ("1102", "demo-1102-01", "bus-01", "CENTRAL", base, -90),
        ("1104", "demo-1104-01", "bus-02", "CENTRAL", base + timedelta(minutes=12), 60),
        ("1102", "demo-1102-02", "bus-01", "CENTRAL", base + timedelta(minutes=30), 180),
        ("1104", "demo-1104-02", "bus-02", "CENTRAL", base + timedelta(minutes=42), -30),
        ("1102", "demo-1102-03", "bus-03", "CENTRAL", base + timedelta(minutes=60), 300),
        ("1104", "demo-1104-03", "bus-04", "CENTRAL", base + timedelta(minutes=72), 120),
        ("1102", "demo-1102-04", "bus-03", "CENTRAL", base + timedelta(minutes=90), 420),
        ("1104", "demo-1104-04", "bus-04", "CENTRAL", base + timedelta(minutes=102), 240),
        ("1102", "demo-1102-05", "bus-05", "CENTRAL", base + timedelta(minutes=120), 90),
        ("1104", "demo-1104-05", "bus-06", "CENTRAL", base + timedelta(minutes=132), -120),
        ("1102", "demo-1102-06", "bus-05", "CENTRAL", base + timedelta(minutes=150), 480),
        ("1104", "demo-1104-06", "bus-06", "CENTRAL", base + timedelta(minutes=162), 210),
    ]

    with path.open("w", encoding="utf-8") as handle:
        for route_id, trip_id, vehicle_id, stop_id, scheduled_at, offset in demo:
            observed_at = scheduled_at + timedelta(seconds=offset)
            record = {
                "kind": "vehicle",
                "source": "demo",
                "organisation_id": 104,
                "received_at": format_iso(observed_at),
                "feed_timestamp": int(observed_at.timestamp()),
                "entity_id": f"demo-{vehicle_id}-{trip_id}",
                "vehicle_id": vehicle_id,
                "trip_id": trip_id,
                "route_id": route_id,
                "start_time": "",
                "start_date": "20260929",
                "stop_id": stop_id,
                "current_stop_sequence": 1,
                "current_status": STOPPED_AT,
                "latitude": -35.725,
                "longitude": 174.323,
                "bearing": 0.0,
                "speed": 0.0,
                "vehicle_timestamp": int(observed_at.timestamp()),
            }
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def expand_inputs(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        candidate = Path(pattern)
        if candidate.exists():
            paths.append(candidate)
            continue
        paths.extend(sorted(Path().glob(pattern)))
    return list(dict.fromkeys(paths))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare observed bus arrivals with scheduled arrival times."
    )
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Collector JSONL/JSONL.GZ file or glob. May be supplied more than once.",
    )
    parser.add_argument(
        "--schedule",
        type=Path,
        help="Schedule CSV with route_id, trip_id, stop_id, scheduled_at.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path("output/arrival_variance.csv"),
    )
    parser.add_argument(
        "--output-plot",
        type=Path,
        default=Path("output/arrival_variance.png"),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Generate deterministic demo schedule/observations and run the monitor.",
    )
    parser.add_argument(
        "--demo-dir",
        type=Path,
        default=Path("output/demo_input"),
    )
    args = parser.parse_args()

    if args.demo:
        schedule_path = args.demo_dir / "schedule.csv"
        observation_path = args.demo_dir / "observations.jsonl"
        create_demo_schedule(schedule_path)
        create_demo_observations(observation_path)
        input_paths = [observation_path]
    else:
        if args.schedule is None:
            parser.error("--schedule is required unless --demo is used")
        schedule_path = args.schedule
        input_paths = expand_inputs(args.input or ["data/run/*.jsonl.gz"])
        if not input_paths:
            parser.error("No collector input files matched --input")

    schedule = read_schedule(schedule_path)
    arrivals = detect_arrivals(iter_jsonl_records(input_paths))
    rows = join_schedule_and_arrivals(schedule, arrivals)

    write_csv(rows, args.output_csv)
    plot_rows(rows, args.output_plot)

    print(f"Schedule rows: {len(schedule)}")
    print(f"Detected STOPPED_AT arrivals: {len(arrivals)}")
    print(f"Matched schedule/arrival rows: {len(rows)}")
    print(f"CSV: {args.output_csv}")
    print(f"Plot: {args.output_plot}")


if __name__ == "__main__":
    main()
