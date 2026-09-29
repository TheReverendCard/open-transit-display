#!/usr/bin/env python3
"""Benchmark Ride Guide predictions against observed stops and tiny fallbacks.

This script compares three ETA sources for the same future stop:

1. rideguide: the time published in Ride Guide trip updates.
2. schedule: the published timetable time.
3. hold_last_delay: a deliberately tiny fallback model. It takes the delay at
   the most recent already-observed STOPPED_AT event on the same trip and adds
   that delay to the target stop's scheduled time.

Ground truth is the first vehicle-position timestamp where the coach reports
STOPPED_AT for the target stop. Pre-start staging at the first trip stop is
excluded from ground truth.

The script discovers the newest Ride Guide timetable artifact and recent
collector artifacts from GitHub Actions. It writes detailed samples plus
horizon/model summaries so the benchmark can run unattended on a schedule.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
import os
import shutil
import statistics
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple
from zoneinfo import ZoneInfo

import requests

GITHUB_API = "https://api.github.com"
NZ_TZ = ZoneInfo("Pacific/Auckland")
STOPPED_AT = 1
DEFAULT_HORIZONS = (5, 10, 15, 30)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/prediction_benchmark")
    parser.add_argument("--collector-days", type=int, default=14)
    parser.add_argument(
        "--horizons",
        default=",".join(str(value) for value in DEFAULT_HORIZONS),
        help="Comma-separated target horizons in minutes (default: 5,10,15,30).",
    )
    return parser.parse_args()


def github_headers() -> Dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def repository() -> str:
    value = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not value:
        raise RuntimeError("GITHUB_REPOSITORY is required")
    return value


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def list_artifacts() -> List[dict]:
    repo = repository()
    headers = github_headers()
    artifacts: List[dict] = []
    page = 1
    while True:
        response = requests.get(
            f"{GITHUB_API}/repos/{repo}/actions/artifacts",
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=60,
        )
        response.raise_for_status()
        batch = response.json().get("artifacts", [])
        artifacts.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return [artifact for artifact in artifacts if not artifact.get("expired")]


def download_extract(artifact: dict, target: Path) -> Path:
    response = requests.get(
        artifact["archive_download_url"],
        headers=github_headers(),
        timeout=120,
    )
    response.raise_for_status()
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extractall(target)
    return target


def read_csv(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def service_date_iso(value: str) -> str:
    value = (value or "").strip()
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return value


def scheduled_datetime(service_date: str, scheduled_time: str) -> datetime:
    hours, minutes, seconds = [int(part) for part in scheduled_time.split(":")]
    base = datetime.strptime(service_date, "%Y-%m-%d").replace(tzinfo=NZ_TZ)
    return base + timedelta(hours=hours, minutes=minutes, seconds=seconds)


def epoch_nz(value: int) -> datetime:
    return datetime.fromtimestamp(int(value), tz=timezone.utc).astimezone(NZ_TZ)


def percentile(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * p
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] * (1 - fraction) + ordered[upper] * fraction)


def closest_horizon(minutes_before: float, horizons: Sequence[int]) -> int | None:
    if minutes_before <= 0:
        return None
    nearest = min(horizons, key=lambda value: abs(minutes_before - value))
    tolerance = max(2.0, nearest * 0.35)
    if abs(minutes_before - nearest) > tolerance:
        return None
    return nearest


def row_timestamp(row: dict) -> int | None:
    value = row.get("vehicle_timestamp") or row.get("feed_timestamp")
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def read_realtime(files: Sequence[Path]) -> Tuple[List[dict], List[dict]]:
    vehicles: List[dict] = []
    updates: List[dict] = []
    seen_vehicle = set()
    seen_update = set()

    for path in files:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue

                kind = row.get("kind")
                if kind == "vehicle":
                    timestamp = row_timestamp(row)
                    key = (
                        row.get("vehicle_id"), row.get("route_id"), row.get("trip_id"),
                        row.get("start_date"), row.get("current_stop_sequence"), row.get("stop_id"),
                        row.get("current_status"), timestamp,
                    )
                    if key not in seen_vehicle:
                        seen_vehicle.add(key)
                        vehicles.append(row)
                elif kind == "trip_update":
                    timestamp = row.get("trip_timestamp") or row.get("feed_timestamp")
                    key = (
                        row.get("vehicle_id"), row.get("route_id"), row.get("trip_id"),
                        row.get("start_date"), timestamp,
                        json.dumps(row.get("stop_updates") or [], sort_keys=True, separators=(",", ":")),
                    )
                    if key not in seen_update:
                        seen_update.add(key)
                        updates.append(row)

    return vehicles, updates


def main() -> None:
    args = parse_args()
    horizons = sorted({int(value.strip()) for value in args.horizons.split(",") if value.strip()})
    if not horizons:
        raise RuntimeError("At least one horizon is required")

    output_dir = Path(args.output_dir)
    work_dir = output_dir / "work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    artifacts = list_artifacts()
    timetable_artifacts = [a for a in artifacts if a.get("name", "").startswith("rideguide-timetables-")]
    if not timetable_artifacts:
        raise RuntimeError("No Ride Guide timetable artifact found")
    timetable_artifact = max(timetable_artifacts, key=lambda a: parse_iso(a["created_at"]))

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.collector_days)
    collector_artifacts = [
        a for a in artifacts
        if a.get("name", "").startswith("collector-")
        and parse_iso(a["created_at"]) >= cutoff
    ]
    if not collector_artifacts:
        raise RuntimeError("No recent collector artifacts found")

    timetable_dir = download_extract(timetable_artifact, work_dir / "timetable")
    collector_root = work_dir / "collectors"
    for artifact in collector_artifacts:
        try:
            download_extract(artifact, collector_root / str(artifact["id"]))
        except requests.HTTPError as exc:
            print(f"Skipping collector artifact {artifact.get('name')}: {exc}")

    stop_times_path = next(timetable_dir.rglob("stop_times.csv"), None)
    if stop_times_path is None:
        raise RuntimeError("Timetable artifact does not contain stop_times.csv")

    timetable_rows = read_csv(stop_times_path)
    timetable_by_key: Dict[Tuple[str, str, str, int, str], dict] = {}
    trip_first_sequence: Dict[Tuple[str, str, str], int] = {}
    for row in timetable_rows:
        sequence = int(row["stop_sequence"])
        key = (row["service_date"], row["route_id"], row["trip_id"], sequence, row["stop_id"])
        timetable_by_key[key] = row
        trip_key = (row["service_date"], row["route_id"], row["trip_id"])
        trip_first_sequence[trip_key] = min(sequence, trip_first_sequence.get(trip_key, sequence))

    realtime_files = sorted(collector_root.rglob("*.jsonl.gz"))
    vehicles, updates = read_realtime(realtime_files)

    # Build clean observed stop events. Exclude pre-start staging at the first stop.
    observed: Dict[Tuple[str, str, str, int, str], dict] = {}
    for row in vehicles:
        if int(row.get("current_status") if row.get("current_status") is not None else -1) != STOPPED_AT:
            continue
        service_date = service_date_iso(str(row.get("start_date") or ""))
        route_id = str(row.get("route_id") or "").strip()
        trip_id = str(row.get("trip_id") or "").strip()
        stop_id = str(row.get("stop_id") or "").strip()
        sequence = int(row.get("current_stop_sequence") or 0)
        actual_ts = row_timestamp(row)
        if not all([service_date, route_id, trip_id, stop_id]) or not sequence or not actual_ts:
            continue
        key = (service_date, route_id, trip_id, sequence, stop_id)
        timetable = timetable_by_key.get(key)
        if timetable is None:
            continue
        actual_dt = epoch_nz(actual_ts)
        scheduled_dt = scheduled_datetime(service_date, timetable["scheduled_time"])
        trip_key = (service_date, route_id, trip_id)
        if sequence == trip_first_sequence.get(trip_key) and actual_dt < scheduled_dt:
            continue
        candidate = {
            "actual_ts": actual_ts,
            "actual_dt": actual_dt,
            "scheduled_dt": scheduled_dt,
            "vehicle_id": str(row.get("vehicle_id") or ""),
            "timetable": timetable,
        }
        existing = observed.get(key)
        if existing is None or actual_ts < existing["actual_ts"]:
            observed[key] = candidate

    # For the tiny model, track already-observed delay by trip over time.
    past_stops_by_trip: Dict[Tuple[str, str, str], List[Tuple[int, int]]] = defaultdict(list)
    for key, value in observed.items():
        service_date, route_id, trip_id, sequence, _ = key
        delay = int(round((value["actual_dt"] - value["scheduled_dt"]).total_seconds()))
        past_stops_by_trip[(service_date, route_id, trip_id)].append((value["actual_ts"], delay))
    for rows in past_stops_by_trip.values():
        rows.sort()

    samples: List[dict] = []
    selected_snapshot: Dict[Tuple[str, str, str, int, str, int, str], dict] = {}

    for update in updates:
        service_date = service_date_iso(str(update.get("start_date") or ""))
        route_id = str(update.get("route_id") or "").strip()
        trip_id = str(update.get("trip_id") or "").strip()
        vehicle_id = str(update.get("vehicle_id") or "")
        prediction_source = str(update.get("prediction_source") or "")
        snapshot_ts_raw = update.get("trip_timestamp") or update.get("feed_timestamp")
        try:
            snapshot_ts = int(snapshot_ts_raw) if snapshot_ts_raw else None
        except (TypeError, ValueError):
            snapshot_ts = None
        if not all([service_date, route_id, trip_id]) or not snapshot_ts:
            continue

        trip_key = (service_date, route_id, trip_id)
        last_delay = None
        for stop_ts, delay in past_stops_by_trip.get(trip_key, []):
            if stop_ts <= snapshot_ts:
                last_delay = delay
            else:
                break

        for stop in update.get("stop_updates") or []:
            stop_id = str(stop.get("stop_id") or "").strip()
            sequence = int(stop.get("stop_sequence") or 0)
            key = (service_date, route_id, trip_id, sequence, stop_id)
            truth = observed.get(key)
            timetable = timetable_by_key.get(key)
            if truth is None or timetable is None:
                continue
            seconds_before = truth["actual_ts"] - snapshot_ts
            if seconds_before <= 0:
                continue
            minutes_before = seconds_before / 60.0
            horizon = closest_horizon(minutes_before, horizons)
            if horizon is None:
                continue

            arrival = stop.get("arrival") or {}
            departure = stop.get("departure") or {}
            prediction_ts = arrival.get("time") or departure.get("time")
            if not prediction_ts:
                continue
            prediction_ts = int(prediction_ts)

            # Keep the snapshot closest to the requested horizon for each source/stop.
            selection_key = (*key, horizon, prediction_source or "unknown")
            distance = abs(minutes_before - horizon)
            existing = selected_snapshot.get(selection_key)
            if existing is not None and existing["distance"] <= distance:
                continue

            scheduled_ts = int(truth["scheduled_dt"].timestamp())
            tiny_ts = scheduled_ts + last_delay if last_delay is not None else None
            selected_snapshot[selection_key] = {
                "distance": distance,
                "sample": {
                    "service_date": service_date,
                    "route_id": route_id,
                    "route_short_name": timetable.get("route_short_name", ""),
                    "trip_id": trip_id,
                    "vehicle_id": vehicle_id,
                    "stop_sequence": sequence,
                    "stop_id": stop_id,
                    "scheduled_time": timetable.get("scheduled_time", ""),
                    "prediction_source": prediction_source,
                    "horizon_minutes": horizon,
                    "actual_minutes_before_stop": round(minutes_before, 2),
                    "snapshot_datetime": epoch_nz(snapshot_ts).isoformat(),
                    "actual_stop_datetime": truth["actual_dt"].isoformat(),
                    "rideguide_predicted_datetime": epoch_nz(prediction_ts).isoformat(),
                    "schedule_predicted_datetime": epoch_nz(scheduled_ts).isoformat(),
                    "hold_last_delay_predicted_datetime": epoch_nz(tiny_ts).isoformat() if tiny_ts else "",
                    "last_observed_delay_seconds": last_delay if last_delay is not None else "",
                    "rideguide_error_seconds": prediction_ts - truth["actual_ts"],
                    "schedule_error_seconds": scheduled_ts - truth["actual_ts"],
                    "hold_last_delay_error_seconds": tiny_ts - truth["actual_ts"] if tiny_ts else "",
                },
            }

    samples = [value["sample"] for value in selected_snapshot.values()]
    samples.sort(key=lambda row: (row["service_date"], row["route_id"], row["trip_id"], int(row["stop_sequence"]), int(row["horizon_minutes"])))

    metric_rows: List[dict] = []
    models = (
        ("rideguide", "rideguide_error_seconds"),
        ("schedule", "schedule_error_seconds"),
        ("hold_last_delay", "hold_last_delay_error_seconds"),
    )
    groups: Dict[Tuple[int, str], List[int]] = defaultdict(list)
    for row in samples:
        horizon = int(row["horizon_minutes"])
        for model, field in models:
            value = row.get(field, "")
            if value == "" or value is None:
                continue
            groups[(horizon, model)].append(int(value))

    for (horizon, model), errors in sorted(groups.items()):
        abs_errors = [abs(value) for value in errors]
        metric_rows.append(
            {
                "horizon_minutes": horizon,
                "model": model,
                "samples": len(errors),
                "mae_seconds": round(statistics.mean(abs_errors), 1),
                "median_absolute_error_seconds": round(statistics.median(abs_errors), 1),
                "p90_absolute_error_seconds": round(percentile(abs_errors, 0.90) or 0, 1),
                "mean_bias_seconds": round(statistics.mean(errors), 1),
            }
        )

    rideguide_abs = [abs(int(row["rideguide_error_seconds"])) for row in samples]
    schedule_abs = [abs(int(row["schedule_error_seconds"])) for row in samples]
    tiny_abs = [abs(int(row["hold_last_delay_error_seconds"])) for row in samples if row.get("hold_last_delay_error_seconds") != ""]

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "collector_days": args.collector_days,
        "collector_artifacts_considered": len(collector_artifacts),
        "collector_files_loaded": len(realtime_files),
        "timetable_artifact": timetable_artifact.get("name"),
        "observed_ground_truth_stops": len(observed),
        "benchmark_samples": len(samples),
        "horizons_minutes": horizons,
        "rideguide_overall_mae_seconds": round(statistics.mean(rideguide_abs), 1) if rideguide_abs else None,
        "schedule_overall_mae_seconds": round(statistics.mean(schedule_abs), 1) if schedule_abs else None,
        "hold_last_delay_overall_mae_seconds": round(statistics.mean(tiny_abs), 1) if tiny_abs else None,
        "hold_last_delay_samples": len(tiny_abs),
        "ground_truth_note": "First observed STOPPED_AT timestamp. Pre-start staging at the first trip stop is excluded.",
        "tiny_model_note": "Scheduled target time plus delay at the most recent already-observed stop on the same trip. It is intentionally simple enough for an offline fallback.",
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        output_dir / "prediction_samples.csv",
        samples,
        [
            "service_date", "route_id", "route_short_name", "trip_id", "vehicle_id",
            "stop_sequence", "stop_id", "scheduled_time", "prediction_source",
            "horizon_minutes", "actual_minutes_before_stop", "snapshot_datetime",
            "actual_stop_datetime", "rideguide_predicted_datetime", "schedule_predicted_datetime",
            "hold_last_delay_predicted_datetime", "last_observed_delay_seconds",
            "rideguide_error_seconds", "schedule_error_seconds", "hold_last_delay_error_seconds",
        ],
    )
    write_csv(
        output_dir / "prediction_metrics.csv",
        metric_rows,
        [
            "horizon_minutes", "model", "samples", "mae_seconds",
            "median_absolute_error_seconds", "p90_absolute_error_seconds", "mean_bias_seconds",
        ],
    )
    with (output_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")

    shutil.rmtree(work_dir, ignore_errors=True)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
