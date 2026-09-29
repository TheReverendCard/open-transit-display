#!/usr/bin/env python3
"""Reconstruct chronological vehicle blocks from recent Ride Guide realtime data.

The analysis groups vehicle-position observations by physical vehicle_id and
tracks changes in route_id/trip_id over time.  It is intended to reveal whether
one coach operates successive trips, including trips on different public routes,
and to help diagnose apparently very-early stop observations around trip handoffs.

Outputs:
  vehicle_blocks.csv
  trip_transitions.csv
  summary.json
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

import requests

GITHUB_API = "https://api.github.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector-days", type=int, default=7)
    parser.add_argument("--output-dir", default="data/vehicle_blocks")
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


def download_extract(artifact: dict, target: Path) -> None:
    response = requests.get(
        artifact["archive_download_url"], headers=github_headers(), timeout=120
    )
    response.raise_for_status()
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extractall(target)


def write_csv(path: Path, rows: Iterable[dict], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def row_timestamp(row: dict) -> int | None:
    value = row.get("vehicle_timestamp") or row.get("feed_timestamp")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def load_vehicle_rows(files: Sequence[Path]) -> List[dict]:
    seen = set()
    rows = []
    for path in files:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("kind") != "vehicle":
                    continue
                vehicle_id = str(row.get("vehicle_id") or "").strip()
                route_id = str(row.get("route_id") or "").strip()
                trip_id = str(row.get("trip_id") or "").strip()
                ts = row_timestamp(row)
                if not vehicle_id or not route_id or not trip_id or ts is None:
                    continue
                key = (
                    vehicle_id,
                    ts,
                    route_id,
                    trip_id,
                    str(row.get("stop_id") or ""),
                    int(row.get("current_stop_sequence") or 0),
                    int(row.get("current_status") if row.get("current_status") is not None else -1),
                )
                if key in seen:
                    continue
                seen.add(key)
                rows.append({**row, "_ts": ts, "_source_file": path.name})
    return rows


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    work_dir = output_dir / "work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.collector_days)
    artifacts = [
        a
        for a in list_artifacts()
        if a.get("name", "").startswith("collector-")
        and parse_time(a["created_at"]) >= cutoff
    ]
    if not artifacts:
        raise RuntimeError("No recent collector artifacts found")

    collector_root = work_dir / "collectors"
    for artifact in artifacts:
        download_extract(artifact, collector_root / str(artifact["id"]))

    files = sorted(collector_root.rglob("*.jsonl.gz"))
    rows = load_vehicle_rows(files)
    by_vehicle: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        by_vehicle[str(row["vehicle_id"])].append(row)

    block_rows: List[dict] = []
    transition_rows: List[dict] = []
    cross_route_transitions = 0

    for vehicle_id, vehicle_rows in sorted(by_vehicle.items()):
        vehicle_rows.sort(key=lambda r: (r["_ts"], str(r.get("trip_id") or "")))
        segments = []
        current = None

        for row in vehicle_rows:
            assignment = (str(row.get("route_id") or ""), str(row.get("trip_id") or ""))
            if current is None or current["assignment"] != assignment:
                if current is not None:
                    segments.append(current)
                current = {
                    "assignment": assignment,
                    "first": row,
                    "last": row,
                    "observations": 1,
                }
            else:
                current["last"] = row
                current["observations"] += 1
        if current is not None:
            segments.append(current)

        for index, segment in enumerate(segments, start=1):
            first = segment["first"]
            last = segment["last"]
            route_id, trip_id = segment["assignment"]
            block_rows.append(
                {
                    "vehicle_id": vehicle_id,
                    "segment_index": index,
                    "route_id": route_id,
                    "trip_id": trip_id,
                    "start_date": first.get("start_date", ""),
                    "first_seen_utc": iso(first["_ts"]),
                    "last_seen_utc": iso(last["_ts"]),
                    "duration_seconds": max(0, last["_ts"] - first["_ts"]),
                    "observations": segment["observations"],
                    "first_stop_id": first.get("stop_id", ""),
                    "first_stop_sequence": first.get("current_stop_sequence", ""),
                    "first_status": first.get("current_status", ""),
                    "last_stop_id": last.get("stop_id", ""),
                    "last_stop_sequence": last.get("current_stop_sequence", ""),
                    "last_status": last.get("current_status", ""),
                }
            )

        for before, after in zip(segments, segments[1:]):
            prev = before["last"]
            nxt = after["first"]
            prev_route, prev_trip = before["assignment"]
            next_route, next_trip = after["assignment"]
            cross_route = prev_route != next_route
            if cross_route:
                cross_route_transitions += 1
            transition_rows.append(
                {
                    "vehicle_id": vehicle_id,
                    "previous_route_id": prev_route,
                    "previous_trip_id": prev_trip,
                    "next_route_id": next_route,
                    "next_trip_id": next_trip,
                    "cross_route": cross_route,
                    "previous_last_seen_utc": iso(prev["_ts"]),
                    "next_first_seen_utc": iso(nxt["_ts"]),
                    "gap_seconds": nxt["_ts"] - prev["_ts"],
                    "previous_last_stop_id": prev.get("stop_id", ""),
                    "previous_last_stop_sequence": prev.get("current_stop_sequence", ""),
                    "next_first_stop_id": nxt.get("stop_id", ""),
                    "next_first_stop_sequence": nxt.get("current_stop_sequence", ""),
                    "next_first_status": nxt.get("current_status", ""),
                }
            )

    write_csv(
        output_dir / "vehicle_blocks.csv",
        block_rows,
        [
            "vehicle_id", "segment_index", "route_id", "trip_id", "start_date",
            "first_seen_utc", "last_seen_utc", "duration_seconds", "observations",
            "first_stop_id", "first_stop_sequence", "first_status",
            "last_stop_id", "last_stop_sequence", "last_status",
        ],
    )
    write_csv(
        output_dir / "trip_transitions.csv",
        transition_rows,
        [
            "vehicle_id", "previous_route_id", "previous_trip_id", "next_route_id",
            "next_trip_id", "cross_route", "previous_last_seen_utc",
            "next_first_seen_utc", "gap_seconds", "previous_last_stop_id",
            "previous_last_stop_sequence", "next_first_stop_id",
            "next_first_stop_sequence", "next_first_status",
        ],
    )

    vehicles_with_multiple_routes = sum(
        1
        for vehicle_id, vehicle_rows in by_vehicle.items()
        if len({str(r.get("route_id") or "") for r in vehicle_rows}) > 1
    )
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "collector_artifacts": len(artifacts),
        "collector_files": len(files),
        "vehicle_position_rows_unique": len(rows),
        "distinct_vehicle_ids": len(by_vehicle),
        "vehicle_assignment_segments": len(block_rows),
        "assignment_transitions": len(transition_rows),
        "cross_route_transitions": cross_route_transitions,
        "vehicles_seen_on_multiple_routes": vehicles_with_multiple_routes,
        "note": "A transition is a change in route_id/trip_id for the same vehicle_id in chronological realtime vehicle-position observations. This reconstructs observed assignment blocks, not an operator-issued duty roster.",
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
