#!/usr/bin/env python3
"""Compare Ride Guide timetable trip IDs with recent realtime collector data.

The script discovers GitHub Actions artifacts in the current repository,
downloads the newest Ride Guide timetable snapshot and recent collector
artifacts, then compares timetable trips with realtime trip IDs by service
date, route ID, and trip ID.

Outputs in --output-dir:
  summary.json
  route_summary.csv
  trip_matches.csv
  unmatched_realtime.csv
  unmatched_timetable.csv
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
from typing import Dict, Iterable, List, Sequence, Set, Tuple

import requests


GITHUB_API = "https://api.github.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/timetable_realtime_compare")
    parser.add_argument(
        "--collector-days",
        type=int,
        default=3,
        help="How many days of recent collector artifacts to inspect (default: 3).",
    )
    return parser.parse_args()


def github_headers() -> Dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def repository() -> str:
    value = os.environ.get("GITHUB_REPOSITORY")
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
    headers = github_headers()
    response = requests.get(artifact["archive_download_url"], headers=headers, timeout=120)
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


def load_realtime(files: Sequence[Path]) -> Tuple[Set[Tuple[str, str, str]], Dict[Tuple[str, str, str], dict]]:
    keys: Set[Tuple[str, str, str]] = set()
    details: Dict[Tuple[str, str, str], dict] = {}

    for path in files:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("kind") not in {"vehicle", "trip_update"}:
                    continue
                trip_id = str(row.get("trip_id") or "").strip()
                route_id = str(row.get("route_id") or "").strip()
                date = service_date_iso(str(row.get("start_date") or ""))
                if not trip_id or not route_id or not date:
                    continue
                key = (date, route_id, trip_id)
                keys.add(key)
                existing = details.setdefault(
                    key,
                    {
                        "service_date": date,
                        "route_id": route_id,
                        "trip_id": trip_id,
                        "vehicle_ids": set(),
                        "kinds": set(),
                        "prediction_sources": set(),
                        "observations": 0,
                    },
                )
                existing["observations"] += 1
                if row.get("vehicle_id"):
                    existing["vehicle_ids"].add(str(row["vehicle_id"]))
                existing["kinds"].add(str(row.get("kind") or ""))
                if row.get("prediction_source"):
                    existing["prediction_sources"].add(str(row["prediction_source"]))

    return keys, details


def serialise_detail(detail: dict) -> dict:
    return {
        "service_date": detail["service_date"],
        "route_id": detail["route_id"],
        "trip_id": detail["trip_id"],
        "vehicle_ids": ";".join(sorted(detail["vehicle_ids"])),
        "kinds": ";".join(sorted(detail["kinds"])),
        "prediction_sources": ";".join(sorted(detail["prediction_sources"])),
        "observations": detail["observations"],
    }


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
        a
        for a in artifacts
        if a.get("name", "").startswith("collector-") and parse_time(a["created_at"]) >= cutoff
    ]
    if not collector_artifacts:
        raise RuntimeError("No recent collector artifacts found")

    timetable_dir = download_extract(timetable_artifact, work_dir / "timetable")
    collector_root = work_dir / "collectors"
    for artifact in collector_artifacts:
        download_extract(artifact, collector_root / str(artifact["id"]))

    trip_csv = next(timetable_dir.rglob("trips.csv"), None)
    if trip_csv is None:
        raise RuntimeError("Timetable artifact does not contain trips.csv")
    timetable_rows = read_csv(trip_csv)
    timetable_by_key = {
        (row["service_date"], row["route_id"], row["trip_id"]): row for row in timetable_rows
    }
    timetable_keys = set(timetable_by_key)

    realtime_files = sorted(collector_root.rglob("*.jsonl.gz"))
    realtime_keys, realtime_details = load_realtime(realtime_files)

    exact_matches = timetable_keys & realtime_keys
    realtime_dates = sorted({key[0] for key in realtime_keys})
    timetable_on_realtime_dates = {key for key in timetable_keys if key[0] in set(realtime_dates)}
    unmatched_realtime = realtime_keys - timetable_keys
    unmatched_timetable = timetable_on_realtime_dates - realtime_keys

    match_rows = []
    for key in sorted(exact_matches):
        timetable = timetable_by_key[key]
        detail = serialise_detail(realtime_details[key])
        match_rows.append(
            {
                **detail,
                "route_short_name": timetable.get("route_short_name", ""),
                "direction_id": timetable.get("direction_id", ""),
                "direction_name": timetable.get("direction_name", ""),
                "first_time": timetable.get("first_time", ""),
                "last_time": timetable.get("last_time", ""),
                "stop_count": timetable.get("stop_count", ""),
            }
        )

    unmatched_rt_rows = [serialise_detail(realtime_details[key]) for key in sorted(unmatched_realtime)]
    unmatched_tt_rows = [timetable_by_key[key] for key in sorted(unmatched_timetable)]

    route_keys = sorted({(key[0], key[1]) for key in realtime_keys | timetable_on_realtime_dates})
    route_rows = []
    for service_date, route_id in route_keys:
        rt = {k for k in realtime_keys if k[0] == service_date and k[1] == route_id}
        tt = {k for k in timetable_on_realtime_dates if k[0] == service_date and k[1] == route_id}
        matched = rt & tt
        route_rows.append(
            {
                "service_date": service_date,
                "route_id": route_id,
                "timetable_trips": len(tt),
                "realtime_trips": len(rt),
                "exact_matches": len(matched),
                "realtime_match_pct": round(100 * len(matched) / len(rt), 1) if rt else "",
                "timetable_observed_pct": round(100 * len(matched) / len(tt), 1) if tt else "",
            }
        )

    write_csv(
        output_dir / "trip_matches.csv",
        match_rows,
        [
            "service_date", "route_id", "route_short_name", "trip_id", "direction_id",
            "direction_name", "first_time", "last_time", "stop_count", "vehicle_ids",
            "kinds", "prediction_sources", "observations",
        ],
    )
    write_csv(
        output_dir / "unmatched_realtime.csv",
        unmatched_rt_rows,
        ["service_date", "route_id", "trip_id", "vehicle_ids", "kinds", "prediction_sources", "observations"],
    )
    write_csv(
        output_dir / "unmatched_timetable.csv",
        unmatched_tt_rows,
        list(timetable_rows[0].keys()) if timetable_rows else ["service_date", "route_id", "trip_id"],
    )
    write_csv(
        output_dir / "route_summary.csv",
        route_rows,
        [
            "service_date", "route_id", "timetable_trips", "realtime_trips", "exact_matches",
            "realtime_match_pct", "timetable_observed_pct",
        ],
    )

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "timetable_artifact": timetable_artifact["name"],
        "timetable_artifact_id": timetable_artifact["id"],
        "collector_artifacts": len(collector_artifacts),
        "collector_files": len(realtime_files),
        "realtime_service_dates": realtime_dates,
        "timetable_trip_keys_all_dates": len(timetable_keys),
        "timetable_trip_keys_on_realtime_dates": len(timetable_on_realtime_dates),
        "realtime_trip_keys": len(realtime_keys),
        "exact_trip_key_matches": len(exact_matches),
        "unmatched_realtime_trip_keys": len(unmatched_realtime),
        "unobserved_timetable_trip_keys_on_realtime_dates": len(unmatched_timetable),
        "realtime_exact_match_pct": round(100 * len(exact_matches) / len(realtime_keys), 1) if realtime_keys else None,
        "note": (
            "Exact match means service_date + route_id + trip_id are identical between the "
            "passenger timetable API and captured Ride Guide realtime data. Timetable trips not "
            "seen in a short realtime collection are not necessarily missing or invalid; they may "
            "simply have operated outside the captured windows."
        ),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
