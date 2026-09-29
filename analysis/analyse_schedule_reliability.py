#!/usr/bin/env python3
"""Join Ride Guide passenger timetables to observed realtime stop events.

This analysis uses exact service_date + route_id + trip_id + stop sequence/ID
joins.  "Observed" stop time is the first vehicle-position timestamp where the
GTFS-Realtime vehicle status is STOPPED_AT for that stop.  With a roughly
10-second collector cadence this is an approximation of arrival/stop time, not
an exact door-open timestamp.

The script discovers the newest Ride Guide timetable artifact and recent
collector artifacts from GitHub Actions, then writes:

  summary.json
  stop_observations.csv
  unmatched_stop_observations.csv
  trip_reliability.csv
  route_reliability.csv

No fuzzy trip matching is used.
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/schedule_reliability")
    parser.add_argument(
        "--collector-days",
        type=int,
        default=7,
        help="How many days of recent collector artifacts to inspect (default: 7).",
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


def parse_time(value: str) -> datetime:
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
    return [a for a in artifacts if not a.get("expired")]


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


def epoch_datetime(value: int) -> datetime:
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


def first_stopped_observations(files: Sequence[Path]) -> Dict[Tuple[str, str, str, int, str], dict]:
    observations: Dict[Tuple[str, str, str, int, str], dict] = {}

    for path in files:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("kind") != "vehicle":
                    continue
                if int(row.get("current_status") if row.get("current_status") is not None else -1) != STOPPED_AT:
                    continue

                service_date = service_date_iso(str(row.get("start_date") or ""))
                route_id = str(row.get("route_id") or "").strip()
                trip_id = str(row.get("trip_id") or "").strip()
                stop_id = str(row.get("stop_id") or "").strip()
                sequence = int(row.get("current_stop_sequence") or 0)
                actual_ts = row.get("vehicle_timestamp") or row.get("feed_timestamp")

                if not all([service_date, route_id, trip_id, stop_id]) or not sequence or not actual_ts:
                    continue

                key = (service_date, route_id, trip_id, sequence, stop_id)
                candidate = {
                    "service_date": service_date,
                    "route_id": route_id,
                    "trip_id": trip_id,
                    "stop_sequence": sequence,
                    "stop_id": stop_id,
                    "vehicle_id": str(row.get("vehicle_id") or ""),
                    "actual_timestamp": int(actual_ts),
                    "received_at": str(row.get("received_at") or ""),
                    "source_file": path.name,
                }
                existing = observations.get(key)
                if existing is None or candidate["actual_timestamp"] < existing["actual_timestamp"]:
                    observations[key] = candidate

    return observations


def delay_band(delay_seconds: int) -> str:
    if delay_seconds < -60:
        return "early_gt_1m"
    if delay_seconds <= 60:
        return "within_1m"
    if delay_seconds <= 300:
        return "late_1_to_5m"
    return "late_gt_5m"


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    work_dir = output_dir / "work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    artifacts = list_artifacts()
    timetable_artifacts = [a for a in artifacts if a.get("name", "").startswith("rideguide-timetables-")]
    if not timetable_artifacts:
        raise RuntimeError("No Ride Guide timetable artifact found")
    timetable_artifact = max(timetable_artifacts, key=lambda a: parse_time(a["created_at"]))

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.collector_days)
    collector_artifacts = [
        a for a in artifacts
        if a.get("name", "").startswith("collector-")
        and parse_time(a["created_at"]) >= cutoff
    ]
    if not collector_artifacts:
        raise RuntimeError("No recent collector artifacts found")

    timetable_dir = download_extract(timetable_artifact, work_dir / "timetable")
    collector_root = work_dir / "collectors"
    for artifact in collector_artifacts:
        download_extract(artifact, collector_root / str(artifact["id"]))

    stop_times_path = next(timetable_dir.rglob("stop_times.csv"), None)
    stops_path = next(timetable_dir.rglob("stops.csv"), None)
    if stop_times_path is None:
        raise RuntimeError("Timetable artifact does not contain stop_times.csv")

    timetable_rows = read_csv(stop_times_path)
    stop_names = {}
    if stops_path is not None:
        stop_names = {row["stop_id"]: row.get("stop_name", "") for row in read_csv(stops_path)}

    timetable_by_key: Dict[Tuple[str, str, str, int, str], dict] = {}
    timetable_by_sequence: Dict[Tuple[str, str, str, int], dict] = {}
    for row in timetable_rows:
        sequence = int(row["stop_sequence"])
        exact_key = (row["service_date"], row["route_id"], row["trip_id"], sequence, row["stop_id"])
        seq_key = (row["service_date"], row["route_id"], row["trip_id"], sequence)
        timetable_by_key[exact_key] = row
        timetable_by_sequence[seq_key] = row

    realtime_files = sorted(collector_root.rglob("*.jsonl.gz"))
    observations = first_stopped_observations(realtime_files)

    matched_rows: List[dict] = []
    unmatched_rows: List[dict] = []

    for key, observation in sorted(observations.items()):
        timetable = timetable_by_key.get(key)
        match_method = "exact_stop_id_and_sequence"
        if timetable is None:
            seq_key = key[:4]
            timetable = timetable_by_sequence.get(seq_key)
            match_method = "sequence_only"
        if timetable is None:
            unmatched_rows.append(observation)
            continue

        scheduled = scheduled_datetime(timetable["service_date"], timetable["scheduled_time"])
        actual = epoch_datetime(observation["actual_timestamp"])
        delay_seconds = int(round((actual - scheduled).total_seconds()))
        matched_rows.append(
            {
                **observation,
                "route_short_name": timetable.get("route_short_name", ""),
                "direction_id": timetable.get("direction_id", ""),
                "direction_name": timetable.get("direction_name", ""),
                "scheduled_time": timetable.get("scheduled_time", ""),
                "scheduled_datetime": scheduled.isoformat(),
                "observed_stop_datetime": actual.isoformat(),
                "delay_seconds": delay_seconds,
                "delay_minutes": round(delay_seconds / 60, 2),
                "delay_band": delay_band(delay_seconds),
                "stop_name": stop_names.get(timetable.get("stop_id", ""), ""),
                "timetable_stop_id": timetable.get("stop_id", ""),
                "match_method": match_method,
            }
        )

    trip_groups: Dict[Tuple[str, str, str], List[dict]] = defaultdict(list)
    route_groups: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for row in matched_rows:
        trip_groups[(row["service_date"], row["route_id"], row["trip_id"])].append(row)
        route_groups[(row["service_date"], row["route_id"])].append(row)

    trip_rows: List[dict] = []
    for (service_date, route_id, trip_id), rows in sorted(trip_groups.items()):
        rows = sorted(rows, key=lambda row: int(row["stop_sequence"]))
        delays = [int(row["delay_seconds"]) for row in rows]
        trip_rows.append(
            {
                "service_date": service_date,
                "route_id": route_id,
                "route_short_name": rows[0]["route_short_name"],
                "trip_id": trip_id,
                "direction_id": rows[0]["direction_id"],
                "direction_name": rows[0]["direction_name"],
                "vehicle_ids": ";".join(sorted({row["vehicle_id"] for row in rows if row["vehicle_id"]})),
                "observed_stops": len(rows),
                "first_observed_sequence": rows[0]["stop_sequence"],
                "last_observed_sequence": rows[-1]["stop_sequence"],
                "first_delay_seconds": delays[0],
                "last_delay_seconds": delays[-1],
                "delay_change_seconds": delays[-1] - delays[0],
                "median_delay_seconds": round(statistics.median(delays), 1),
                "min_delay_seconds": min(delays),
                "max_delay_seconds": max(delays),
            }
        )

    route_rows: List[dict] = []
    for (service_date, route_id), rows in sorted(route_groups.items()):
        delays = [int(row["delay_seconds"]) for row in rows]
        bands = defaultdict(int)
        for row in rows:
            bands[row["delay_band"]] += 1
        route_rows.append(
            {
                "service_date": service_date,
                "route_id": route_id,
                "route_short_name": rows[0]["route_short_name"],
                "observed_stop_events": len(rows),
                "observed_trips": len({row["trip_id"] for row in rows}),
                "median_delay_seconds": round(statistics.median(delays), 1),
                "mean_delay_seconds": round(statistics.mean(delays), 1),
                "p90_delay_seconds": round(percentile(delays, 0.90) or 0, 1),
                "min_delay_seconds": min(delays),
                "max_delay_seconds": max(delays),
                "early_gt_1m": bands["early_gt_1m"],
                "within_1m": bands["within_1m"],
                "late_1_to_5m": bands["late_1_to_5m"],
                "late_gt_5m": bands["late_gt_5m"],
            }
        )

    write_csv(
        output_dir / "stop_observations.csv",
        matched_rows,
        [
            "service_date", "route_id", "route_short_name", "trip_id", "direction_id",
            "direction_name", "vehicle_id", "stop_sequence", "stop_id", "timetable_stop_id",
            "stop_name", "scheduled_time", "scheduled_datetime", "observed_stop_datetime",
            "delay_seconds", "delay_minutes", "delay_band", "match_method", "received_at",
            "source_file",
        ],
    )
    write_csv(
        output_dir / "unmatched_stop_observations.csv",
        unmatched_rows,
        [
            "service_date", "route_id", "trip_id", "vehicle_id", "stop_sequence", "stop_id",
            "actual_timestamp", "received_at", "source_file",
        ],
    )
    write_csv(
        output_dir / "trip_reliability.csv",
        trip_rows,
        [
            "service_date", "route_id", "route_short_name", "trip_id", "direction_id",
            "direction_name", "vehicle_ids", "observed_stops", "first_observed_sequence",
            "last_observed_sequence", "first_delay_seconds", "last_delay_seconds",
            "delay_change_seconds", "median_delay_seconds", "min_delay_seconds", "max_delay_seconds",
        ],
    )
    write_csv(
        output_dir / "route_reliability.csv",
        route_rows,
        [
            "service_date", "route_id", "route_short_name", "observed_stop_events",
            "observed_trips", "median_delay_seconds", "mean_delay_seconds", "p90_delay_seconds",
            "min_delay_seconds", "max_delay_seconds", "early_gt_1m", "within_1m",
            "late_1_to_5m", "late_gt_5m",
        ],
    )

    all_delays = [int(row["delay_seconds"]) for row in matched_rows]
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "timetable_artifact": timetable_artifact["name"],
        "timetable_artifact_id": timetable_artifact["id"],
        "collector_artifacts": len(collector_artifacts),
        "collector_files": len(realtime_files),
        "stopped_at_observations_unique": len(observations),
        "matched_stop_observations": len(matched_rows),
        "unmatched_stop_observations": len(unmatched_rows),
        "observed_trips": len(trip_groups),
        "exact_stop_matches": sum(1 for row in matched_rows if row["match_method"] == "exact_stop_id_and_sequence"),
        "sequence_only_matches": sum(1 for row in matched_rows if row["match_method"] == "sequence_only"),
        "median_delay_seconds": round(statistics.median(all_delays), 1) if all_delays else None,
        "mean_delay_seconds": round(statistics.mean(all_delays), 1) if all_delays else None,
        "p90_delay_seconds": round(percentile(all_delays, 0.90), 1) if all_delays else None,
        "note": (
            "Observed stop time is the first captured vehicle-position timestamp with GTFS-Realtime "
            "current_status=STOPPED_AT. It is therefore an approximate observed stop time, normally "
            "bounded by collector cadence, not an exact passenger boarding timestamp."
        ),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
