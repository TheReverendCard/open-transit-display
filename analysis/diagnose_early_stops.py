#!/usr/bin/env python3
"""Diagnose very-early STOPPED_AT observations.

This script checks whether large negative delays are explained by a coach being
assigned to an upcoming trip while already waiting at that trip's first stop.
It joins recent realtime collector artifacts to the current Ride Guide
passenger timetable and reports coach/vehicle identifiers, trip starts, and
whether each very-early observation is at the first scheduled stop.

Outputs:
  summary.json
  early_stop_diagnosis.csv
  coach_trip_timeline.csv
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import shutil
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
    parser.add_argument("--output-dir", default="data/early_stop_diagnosis")
    parser.add_argument("--collector-days", type=int, default=7)
    parser.add_argument(
        "--early-seconds",
        type=int,
        default=300,
        help="Diagnose observations at least this many seconds early (default: 300).",
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
    artifacts: List[dict] = []
    page = 1
    while True:
        response = requests.get(
            f"{GITHUB_API}/repos/{repo}/actions/artifacts",
            headers=github_headers(),
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

    stop_times = read_csv(stop_times_path)
    stop_names = {}
    if stops_path is not None:
        stop_names = {row["stop_id"]: row.get("stop_name", "") for row in read_csv(stops_path)}

    timetable_by_exact: Dict[Tuple[str, str, str, int, str], dict] = {}
    trip_rows: Dict[Tuple[str, str, str], List[dict]] = defaultdict(list)
    for row in stop_times:
        seq = int(row["stop_sequence"])
        exact = (row["service_date"], row["route_id"], row["trip_id"], seq, row["stop_id"])
        timetable_by_exact[exact] = row
        trip_rows[(row["service_date"], row["route_id"], row["trip_id"])].append(row)

    trip_info = {}
    for key, rows in trip_rows.items():
        rows = sorted(rows, key=lambda r: int(r["stop_sequence"]))
        trip_info[key] = {
            "first_sequence": int(rows[0]["stop_sequence"]),
            "first_stop_id": rows[0]["stop_id"],
            "first_time": rows[0]["scheduled_time"],
            "last_sequence": int(rows[-1]["stop_sequence"]),
            "last_stop_id": rows[-1]["stop_id"],
            "last_time": rows[-1]["scheduled_time"],
            "route_short_name": rows[0].get("route_short_name", ""),
            "direction_name": rows[0].get("direction_name", ""),
        }

    vehicle_rows: Dict[str, List[dict]] = defaultdict(list)
    first_stopped: Dict[Tuple[str, str, str, int, str], dict] = {}

    for path in sorted(collector_root.rglob("*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("kind") != "vehicle":
                    continue
                vehicle_id = str(row.get("vehicle_id") or "").strip()
                service_date = service_date_iso(str(row.get("start_date") or ""))
                route_id = str(row.get("route_id") or "").strip()
                trip_id = str(row.get("trip_id") or "").strip()
                stop_id = str(row.get("stop_id") or "").strip()
                sequence = int(row.get("current_stop_sequence") or 0)
                actual_ts = row.get("vehicle_timestamp") or row.get("feed_timestamp")
                if not vehicle_id or not service_date or not route_id or not trip_id or not actual_ts:
                    continue

                compact = {
                    "vehicle_id": vehicle_id,
                    "service_date": service_date,
                    "route_id": route_id,
                    "trip_id": trip_id,
                    "stop_id": stop_id,
                    "stop_sequence": sequence,
                    "current_status": row.get("current_status"),
                    "actual_timestamp": int(actual_ts),
                }
                vehicle_rows[vehicle_id].append(compact)

                if int(row.get("current_status") if row.get("current_status") is not None else -1) != STOPPED_AT:
                    continue
                if not stop_id or not sequence:
                    continue
                key = (service_date, route_id, trip_id, sequence, stop_id)
                existing = first_stopped.get(key)
                if existing is None or compact["actual_timestamp"] < existing["actual_timestamp"]:
                    first_stopped[key] = compact

    # Build compact per-coach trip timeline from the first and last observed timestamps of each trip.
    coach_trip_groups: Dict[Tuple[str, str, str, str], List[dict]] = defaultdict(list)
    for vehicle_id, rows in vehicle_rows.items():
        for row in rows:
            coach_trip_groups[(vehicle_id, row["service_date"], row["route_id"], row["trip_id"])].append(row)

    coach_timeline = []
    for (vehicle_id, service_date, route_id, trip_id), rows in coach_trip_groups.items():
        rows = sorted(rows, key=lambda r: r["actual_timestamp"])
        info = trip_info.get((service_date, route_id, trip_id), {})
        coach_timeline.append({
            "vehicle_id": vehicle_id,
            "service_date": service_date,
            "route_id": route_id,
            "route_short_name": info.get("route_short_name", ""),
            "trip_id": trip_id,
            "direction_name": info.get("direction_name", ""),
            "first_seen": epoch_datetime(rows[0]["actual_timestamp"]).isoformat(),
            "last_seen": epoch_datetime(rows[-1]["actual_timestamp"]).isoformat(),
            "scheduled_trip_start": (
                scheduled_datetime(service_date, info["first_time"]).isoformat()
                if info.get("first_time") else ""
            ),
            "first_seen_stop_id": rows[0].get("stop_id", ""),
            "first_seen_sequence": rows[0].get("stop_sequence", ""),
        })
    coach_timeline.sort(key=lambda r: (r["vehicle_id"], r["first_seen"]))

    diagnoses = []
    for key, obs in sorted(first_stopped.items()):
        timetable = timetable_by_exact.get(key)
        if timetable is None:
            continue
        scheduled = scheduled_datetime(timetable["service_date"], timetable["scheduled_time"])
        observed = epoch_datetime(obs["actual_timestamp"])
        delay_seconds = int(round((observed - scheduled).total_seconds()))
        if delay_seconds > -args.early_seconds:
            continue

        trip_key = (obs["service_date"], obs["route_id"], obs["trip_id"])
        info = trip_info.get(trip_key, {})
        trip_start = scheduled_datetime(obs["service_date"], info["first_time"]) if info.get("first_time") else None
        is_first = (
            obs["stop_sequence"] == info.get("first_sequence")
            and obs["stop_id"] == info.get("first_stop_id")
        )
        seconds_before_trip_start = int(round((trip_start - observed).total_seconds())) if trip_start else None

        classification = "other_early_stop"
        if is_first and seconds_before_trip_start is not None and seconds_before_trip_start >= args.early_seconds:
            classification = "pre_start_staging"

        diagnoses.append({
            "service_date": obs["service_date"],
            "vehicle_id": obs["vehicle_id"],
            "route_id": obs["route_id"],
            "route_short_name": info.get("route_short_name", ""),
            "trip_id": obs["trip_id"],
            "direction_name": info.get("direction_name", ""),
            "stop_sequence": obs["stop_sequence"],
            "stop_id": obs["stop_id"],
            "stop_name": stop_names.get(obs["stop_id"], ""),
            "scheduled_stop_time": timetable["scheduled_time"],
            "observed_stop_time": observed.isoformat(),
            "delay_seconds": delay_seconds,
            "delay_minutes": round(delay_seconds / 60, 2),
            "trip_first_sequence": info.get("first_sequence", ""),
            "trip_first_stop_id": info.get("first_stop_id", ""),
            "trip_first_stop_name": stop_names.get(info.get("first_stop_id", ""), ""),
            "scheduled_trip_start": trip_start.isoformat() if trip_start else "",
            "seconds_before_trip_start": seconds_before_trip_start if seconds_before_trip_start is not None else "",
            "minutes_before_trip_start": round(seconds_before_trip_start / 60, 2) if seconds_before_trip_start is not None else "",
            "is_first_scheduled_stop": is_first,
            "classification": classification,
        })

    diagnoses.sort(key=lambda r: int(r["delay_seconds"]))
    staging = [r for r in diagnoses if r["classification"] == "pre_start_staging"]
    non_staging = [r for r in diagnoses if r["classification"] != "pre_start_staging"]

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "early_threshold_seconds": args.early_seconds,
        "very_early_stop_observations": len(diagnoses),
        "pre_start_staging_observations": len(staging),
        "other_early_stop_observations": len(non_staging),
        "pre_start_staging_pct": round(100 * len(staging) / len(diagnoses), 1) if diagnoses else None,
        "distinct_vehicle_ids_in_early_observations": len({r["vehicle_id"] for r in diagnoses}),
        "distinct_vehicle_ids_all_realtime": len(vehicle_rows),
        "note": (
            "pre_start_staging means the coach was reported STOPPED_AT the exact first scheduled stop "
            "of the trip at least the configured threshold before that trip's scheduled start. "
            "This is consistent with a coach being positioned/assigned early and should not be treated "
            "as an early passenger-service arrival without further evidence."
        ),
    }

    write_csv(
        output_dir / "early_stop_diagnosis.csv",
        diagnoses,
        [
            "service_date", "vehicle_id", "route_id", "route_short_name", "trip_id",
            "direction_name", "stop_sequence", "stop_id", "stop_name", "scheduled_stop_time",
            "observed_stop_time", "delay_seconds", "delay_minutes", "trip_first_sequence",
            "trip_first_stop_id", "trip_first_stop_name", "scheduled_trip_start",
            "seconds_before_trip_start", "minutes_before_trip_start", "is_first_scheduled_stop",
            "classification",
        ],
    )
    write_csv(
        output_dir / "coach_trip_timeline.csv",
        coach_timeline,
        [
            "vehicle_id", "service_date", "route_id", "route_short_name", "trip_id",
            "direction_name", "first_seen", "last_seen", "scheduled_trip_start",
            "first_seen_stop_id", "first_seen_sequence",
        ],
    )
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print("\nVery-early observations:")
    for row in diagnoses:
        print(
            f"vehicle={row['vehicle_id']} route={row['route_short_name']} trip={row['trip_id']} "
            f"stop={row['stop_sequence']} {row['stop_name']} delay={row['delay_minutes']}m "
            f"before_start={row['minutes_before_trip_start']}m class={row['classification']}"
        )


if __name__ == "__main__":
    main()
