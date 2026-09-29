#!/usr/bin/env python3
"""Build a provisional route/trip/stop catalogue from Ride Guide observations.

This is a derived structural catalogue, not an official GTFS feed. It uses the
normalized collector output to identify which stops occur on which trips and
routes, their observed sequence positions, and how consistently those patterns
repeat.

Outputs:
  route_catalogue.csv
  trip_catalogue.csv
  trip_stop_catalogue.csv
  stop_catalogue.csv
  catalogue_summary.json
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
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


@dataclass
class TripStopStats:
    observations: int = 0
    schedule_based_observations: int = 0
    vehicle_assigned_observations: int = 0
    unknown_source_observations: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    start_dates: Set[str] = field(default_factory=set)
    vehicle_ids: Set[str] = field(default_factory=set)


@dataclass
class TripStats:
    observations: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    start_times: Set[str] = field(default_factory=set)
    start_dates: Set[str] = field(default_factory=set)
    vehicle_ids: Set[str] = field(default_factory=set)
    prediction_sources: Counter = field(default_factory=Counter)


@dataclass
class StopStats:
    observations: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    route_ids: Set[str] = field(default_factory=set)
    trip_ids: Set[str] = field(default_factory=set)
    sequences: Set[int] = field(default_factory=set)
    schedule_based_observations: int = 0
    vehicle_assigned_observations: int = 0
    vehicle_position_observations: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a provisional Ride Guide route/trip/stop catalogue.")
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="JSONL/JSONL.GZ file or directory. May be repeated.",
    )
    parser.add_argument("--output-dir", default="data/realtime_catalogue")
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


def nonempty(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_time(value: Any) -> Optional[datetime]:
    text = nonempty(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(first: Optional[datetime], last: Optional[datetime], value: Optional[datetime]) -> Tuple[Optional[datetime], Optional[datetime]]:
    if value is None:
        return first, last
    if first is None or value < first:
        first = value
    if last is None or value > last:
        last = value
    return first, last


def sorted_join(values: Iterable[Any]) -> str:
    return ";".join(str(value) for value in sorted(set(values), key=lambda item: str(item)))


def write_csv(path: Path, rows: Iterable[Dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    files = discover_files(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    trip_stops: Dict[Tuple[str, str, int, str], TripStopStats] = defaultdict(TripStopStats)
    trips: Dict[Tuple[str, str], TripStats] = defaultdict(TripStats)
    stops: Dict[str, StopStats] = defaultdict(StopStats)
    route_trip_ids: Dict[str, Set[str]] = defaultdict(set)
    route_stop_ids: Dict[str, Set[str]] = defaultdict(set)
    route_observations: Counter = Counter()
    invalid_json_rows = 0
    total_rows = 0
    trip_update_rows = 0
    vehicle_rows = 0

    for path in files:
        with open_text(path) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    invalid_json_rows += 1
                    continue
                if not isinstance(row, dict):
                    invalid_json_rows += 1
                    continue

                total_rows += 1
                kind = nonempty(row.get("kind"))
                route_id = nonempty(row.get("route_id"))
                trip_id = nonempty(row.get("trip_id"))
                received = parse_time(row.get("received_at"))
                vehicle_id = nonempty(row.get("vehicle_id"))
                start_date = nonempty(row.get("start_date"))
                start_time = nonempty(row.get("start_time"))

                if route_id:
                    route_observations[route_id] += 1
                if route_id and trip_id:
                    route_trip_ids[route_id].add(trip_id)

                if kind == "trip_update":
                    trip_update_rows += 1
                    prediction_source = nonempty(row.get("prediction_source")) or "unknown"
                    if route_id and trip_id:
                        trip = trips[(route_id, trip_id)]
                        trip.observations += 1
                        trip.first_seen, trip.last_seen = touch(trip.first_seen, trip.last_seen, received)
                        if start_time:
                            trip.start_times.add(start_time)
                        if start_date:
                            trip.start_dates.add(start_date)
                        if vehicle_id:
                            trip.vehicle_ids.add(vehicle_id)
                        trip.prediction_sources[prediction_source] += 1

                    for update in row.get("stop_updates") or []:
                        if not isinstance(update, dict):
                            continue
                        stop_id = nonempty(update.get("stop_id"))
                        sequence = safe_int(update.get("stop_sequence"))
                        if not stop_id or sequence is None:
                            continue

                        if route_id:
                            route_stop_ids[route_id].add(stop_id)

                        stop = stops[stop_id]
                        stop.observations += 1
                        stop.first_seen, stop.last_seen = touch(stop.first_seen, stop.last_seen, received)
                        if route_id:
                            stop.route_ids.add(route_id)
                        if trip_id:
                            stop.trip_ids.add(trip_id)
                        stop.sequences.add(sequence)
                        if prediction_source == "schedule_based":
                            stop.schedule_based_observations += 1
                        elif prediction_source == "vehicle_assigned":
                            stop.vehicle_assigned_observations += 1

                        if route_id and trip_id:
                            detail = trip_stops[(route_id, trip_id, sequence, stop_id)]
                            detail.observations += 1
                            detail.first_seen, detail.last_seen = touch(detail.first_seen, detail.last_seen, received)
                            if start_date:
                                detail.start_dates.add(start_date)
                            if vehicle_id:
                                detail.vehicle_ids.add(vehicle_id)
                            if prediction_source == "schedule_based":
                                detail.schedule_based_observations += 1
                            elif prediction_source == "vehicle_assigned":
                                detail.vehicle_assigned_observations += 1
                            else:
                                detail.unknown_source_observations += 1

                elif kind == "vehicle":
                    vehicle_rows += 1
                    stop_id = nonempty(row.get("stop_id"))
                    sequence = safe_int(row.get("current_stop_sequence"))
                    if stop_id:
                        if route_id:
                            route_stop_ids[route_id].add(stop_id)
                        stop = stops[stop_id]
                        stop.observations += 1
                        stop.vehicle_position_observations += 1
                        stop.first_seen, stop.last_seen = touch(stop.first_seen, stop.last_seen, received)
                        if route_id:
                            stop.route_ids.add(route_id)
                        if trip_id:
                            stop.trip_ids.add(trip_id)
                        if sequence is not None:
                            stop.sequences.add(sequence)

    trip_stop_rows: List[Dict[str, Any]] = []
    for (route_id, trip_id, sequence, stop_id), stats in sorted(
        trip_stops.items(), key=lambda item: (item[0][0], item[0][1], item[0][2], item[0][3])
    ):
        source_total = (
            stats.schedule_based_observations
            + stats.vehicle_assigned_observations
            + stats.unknown_source_observations
        )
        dominant_source = ""
        if source_total:
            dominant_source = max(
                [
                    (stats.schedule_based_observations, "schedule_based"),
                    (stats.vehicle_assigned_observations, "vehicle_assigned"),
                    (stats.unknown_source_observations, "unknown"),
                ]
            )[1]
        trip_stop_rows.append(
            {
                "route_id": route_id,
                "trip_id": trip_id,
                "stop_sequence": sequence,
                "stop_id": stop_id,
                "observations": stats.observations,
                "schedule_based_observations": stats.schedule_based_observations,
                "vehicle_assigned_observations": stats.vehicle_assigned_observations,
                "unknown_source_observations": stats.unknown_source_observations,
                "dominant_prediction_source": dominant_source,
                "distinct_start_dates": len(stats.start_dates),
                "start_dates": sorted_join(stats.start_dates),
                "distinct_vehicle_ids": len(stats.vehicle_ids),
                "vehicle_ids": sorted_join(stats.vehicle_ids),
                "first_seen": stats.first_seen.isoformat() if stats.first_seen else "",
                "last_seen": stats.last_seen.isoformat() if stats.last_seen else "",
            }
        )

    trip_rows: List[Dict[str, Any]] = []
    stops_by_trip: Dict[Tuple[str, str], List[Tuple[int, str]]] = defaultdict(list)
    for route_id, trip_id, sequence, stop_id in trip_stops:
        stops_by_trip[(route_id, trip_id)].append((sequence, stop_id))

    for (route_id, trip_id), stats in sorted(trips.items()):
        pattern = sorted(set(stops_by_trip.get((route_id, trip_id), [])))
        first_stop_id = pattern[0][1] if pattern else ""
        last_stop_id = pattern[-1][1] if pattern else ""
        trip_rows.append(
            {
                "route_id": route_id,
                "trip_id": trip_id,
                "observations": stats.observations,
                "distinct_stops": len({stop_id for _, stop_id in pattern}),
                "min_stop_sequence": min((seq for seq, _ in pattern), default=""),
                "max_stop_sequence": max((seq for seq, _ in pattern), default=""),
                "first_stop_id": first_stop_id,
                "last_stop_id": last_stop_id,
                "start_times": sorted_join(stats.start_times),
                "start_dates": sorted_join(stats.start_dates),
                "distinct_start_dates": len(stats.start_dates),
                "vehicle_ids": sorted_join(stats.vehicle_ids),
                "schedule_based_observations": stats.prediction_sources.get("schedule_based", 0),
                "vehicle_assigned_observations": stats.prediction_sources.get("vehicle_assigned", 0),
                "unknown_source_observations": stats.prediction_sources.get("unknown", 0),
                "first_seen": stats.first_seen.isoformat() if stats.first_seen else "",
                "last_seen": stats.last_seen.isoformat() if stats.last_seen else "",
            }
        )

    stop_rows: List[Dict[str, Any]] = []
    for stop_id, stats in sorted(stops.items()):
        stop_rows.append(
            {
                "stop_id": stop_id,
                "observations": stats.observations,
                "route_ids": sorted_join(stats.route_ids),
                "distinct_routes": len(stats.route_ids),
                "trip_ids": sorted_join(stats.trip_ids),
                "distinct_trips": len(stats.trip_ids),
                "observed_sequences": sorted_join(stats.sequences),
                "schedule_based_observations": stats.schedule_based_observations,
                "vehicle_assigned_observations": stats.vehicle_assigned_observations,
                "vehicle_position_observations": stats.vehicle_position_observations,
                "first_seen": stats.first_seen.isoformat() if stats.first_seen else "",
                "last_seen": stats.last_seen.isoformat() if stats.last_seen else "",
            }
        )

    route_rows: List[Dict[str, Any]] = []
    all_routes = sorted(set(route_observations) | set(route_trip_ids) | set(route_stop_ids))
    for route_id in all_routes:
        route_rows.append(
            {
                "route_id": route_id,
                "observations": route_observations.get(route_id, 0),
                "distinct_trips": len(route_trip_ids.get(route_id, set())),
                "trip_ids": sorted_join(route_trip_ids.get(route_id, set())),
                "distinct_stops": len(route_stop_ids.get(route_id, set())),
                "stop_ids": sorted_join(route_stop_ids.get(route_id, set())),
            }
        )

    write_csv(
        output_dir / "route_catalogue.csv",
        route_rows,
        ["route_id", "observations", "distinct_trips", "trip_ids", "distinct_stops", "stop_ids"],
    )
    write_csv(
        output_dir / "trip_catalogue.csv",
        trip_rows,
        [
            "route_id",
            "trip_id",
            "observations",
            "distinct_stops",
            "min_stop_sequence",
            "max_stop_sequence",
            "first_stop_id",
            "last_stop_id",
            "start_times",
            "start_dates",
            "distinct_start_dates",
            "vehicle_ids",
            "schedule_based_observations",
            "vehicle_assigned_observations",
            "unknown_source_observations",
            "first_seen",
            "last_seen",
        ],
    )
    write_csv(
        output_dir / "trip_stop_catalogue.csv",
        trip_stop_rows,
        [
            "route_id",
            "trip_id",
            "stop_sequence",
            "stop_id",
            "observations",
            "schedule_based_observations",
            "vehicle_assigned_observations",
            "unknown_source_observations",
            "dominant_prediction_source",
            "distinct_start_dates",
            "start_dates",
            "distinct_vehicle_ids",
            "vehicle_ids",
            "first_seen",
            "last_seen",
        ],
    )
    write_csv(
        output_dir / "stop_catalogue.csv",
        stop_rows,
        [
            "stop_id",
            "observations",
            "route_ids",
            "distinct_routes",
            "trip_ids",
            "distinct_trips",
            "observed_sequences",
            "schedule_based_observations",
            "vehicle_assigned_observations",
            "vehicle_position_observations",
            "first_seen",
            "last_seen",
        ],
    )

    summary = {
        "files_scanned": len(files),
        "rows": total_rows,
        "invalid_json_rows": invalid_json_rows,
        "trip_update_rows": trip_update_rows,
        "vehicle_rows": vehicle_rows,
        "routes": len(route_rows),
        "trips": len(trip_rows),
        "stops": len(stop_rows),
        "trip_stop_patterns": len(trip_stop_rows),
        "note": "Derived from Ride Guide observations. Structural catalogue only; not official GTFS.",
    }
    (output_dir / "catalogue_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"Wrote realtime catalogue outputs to {output_dir}")


if __name__ == "__main__":
    main()
