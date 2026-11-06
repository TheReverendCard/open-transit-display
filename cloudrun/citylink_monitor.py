#!/usr/bin/env python3
"""Authenticated, metadata-only CityLink probe for Cloud Run + Cloud Scheduler.

Only POST /collect starts a probe.  No realtime protobuf, GPS, individual
arrivals, trip identifiers, or vehicle identifiers are stored or returned.
Cloud Run IAM must require authentication; use Cloud Scheduler OIDC.

The public static timetable/trip map is fetched from ONE feed-data commit,
then discarded after the request.  The provider WebSocket is contacted only
during a valid CityLink service window.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "collector"))

from citylink_gtfsrt_bridge import Bridge, StaticIndex  # noqa: E402
from publish_citylink_gtfsrt_snapshot import collect, metadata  # noqa: E402
from service_windows import windows  # noqa: E402

REPO = "TheReverendCard/open-transit-display"
API_REF = f"https://api.github.com/repos/{REPO}/branches/feed-data"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}"
COLLECT_SECONDS = 40
LOCK = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(record: dict) -> None:
    # All callers must supply aggregate operational metadata only.
    print("CITYLINK_MONITOR=" + json.dumps(record, sort_keys=True, separators=(",", ":")), flush=True)


def download(url: str, limit: int = 32_000_000) -> bytes:
    req = Request(url, headers={
        "User-Agent": "open-transit-display-metadata-monitor",
        "Accept": "application/vnd.github+json" if url == API_REF else "application/octet-stream",
    })
    with urlopen(req, timeout=20) as response:
        value = response.read(limit + 1)
    if len(value) > limit:
        raise ValueError("static file exceeds configured size limit")
    return value


def static_files(root: Path) -> tuple[str, Path, Path]:
    info = json.loads(download(API_REF, limit=100_000))
    commit = info["commit"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid static-feed commit SHA")
    gtfs = root / "gtfs.zip"
    trip_map = root / "trip-map.json"
    gtfs.write_bytes(download(f"{RAW_BASE}/{commit}/citylink/gtfs.zip"))
    trip_map.write_bytes(download(f"{RAW_BASE}/{commit}/citylink/trip-map.json"))
    return commit, gtfs, trip_map


def probe(scheduled_at: str | None = None) -> dict:
    started = utc_now()
    baseline = {
        "schema": "otd-citylink-cloudrun-monitor-v1",
        "status": "started",
        "started_at_utc": started,
        "scheduled_at_utc": scheduled_at,
        "service_timezone": "Pacific/Auckland",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="citylink-monitor-") as temp:
            commit, gtfs, trip_map = static_files(Path(temp))
            now = int(time.time())
            service = windows(gtfs)
            covered = service["covered_from"] <= now < service["covered_until"]
            active = covered and any(
                first <= now <= last for first, last in service["intervals"]
            )
            baseline.update(
                static_feed_commit=commit,
                timetable_covered=covered,
                service_window_active=active,
            )
            if not active:
                baseline.update(
                    status="skipped_outside_service" if covered else "skipped_invalid_timetable",
                    completed_at_utc=utc_now(),
                )
                log(baseline)
                return {"status": baseline["status"]}

            index = StaticIndex(gtfs, trip_map)
            bridge = Bridge(index)
            asyncio.run(collect(bridge, COLLECT_SECONDS))
            now = int(time.time())
            summary = metadata(index, bridge, now, commit)
            counters = bridge.status()["counters"]
            counts = {
                kind: summary["feeds"][kind]["entities"]
                for kind in ("tripupdates", "vehiclepositions", "alerts")
            }
            packet_count = counters.get("packets_seen", 0)
            status = (
                "no_packets" if packet_count == 0
                else "empty_snapshot" if not any(counts.values())
                else "sampled"
            )
            baseline.update(
                status=status,
                generated_at_utc=summary["generated_at_utc"],
                counts=counts,
                source_age_seconds={
                    kind: item["source_age_seconds_at_generation"]
                    for kind, item in summary["feeds"].items()
                },
                oldest_entity_age_seconds={
                    kind: item["oldest_entity_age_seconds_at_generation"]
                    for kind, item in summary["feeds"].items()
                },
                packets_seen=packet_count,
                connection_errors=counters.get("connection_errors", 0),
                decode_errors=counters.get("decode_errors", 0),
                empty_feed_packets=counters.get("empty_feed_packets", 0),
                completed_at_utc=utc_now(),
            )
            log(baseline)
            return {"status": status}
    except Exception as exc:
        # Do NOT stringify exceptions, since they might include upstream data.
        baseline.update(
            status="error",
            error_type=type(exc).__name__,
            completed_at_utc=utc_now(),
        )
        log(baseline)
        return {"status": "error"}


class Handler(BaseHTTPRequestHandler):
    def respond(self, status: int, data: dict) -> None:
        payload = (json.dumps(data, separators=(",", ":")) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.respond(200, {"status": "ready"})
        else:
            self.respond(404, {"status": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/collect":
            self.respond(404, {"status": "not_found"})
            return
        if not LOCK.acquire(blocking=False):
            self.respond(409, {"status": "busy"})
            return
        try:
            result = probe(self.headers.get("X-CloudScheduler-ScheduleTime"))
            self.respond(503 if result["status"] in ("error", "no_packets") else 200, result)
        finally:
            LOCK.release()

    def log_message(self, format: str, *args) -> None:
        # Avoid recording request content or additional request metadata.
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("CityLink metadata-only collector ready", flush=True)
    server.serve_forever()
