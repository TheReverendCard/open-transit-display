#!/usr/bin/env python3
"""Produce a bounded CityLink GTFS-Realtime snapshot for opt-in GitHub publication.

Not a live WebSocket server. This writes standard protobuf files and a manifest,
but never publishes them. Public distribution must be separately authorized.
The manifest is the source of truth for entity ages and static GTFS revision.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from google.transit import gtfs_realtime_pb2 as pb

from citylink_gtfsrt_bridge import (
    Bridge, KINDS, ORIGIN, SUBSCRIBE, StaticIndex, WS_URL,
)

NZ = ZoneInfo("Pacific/Auckland")
MAX_CONSUMER_AGE_SECONDS = 600  # Hard upper bound; clients may choose shorter.
COLLECTION_SECONDS_DEFAULT = 40


def utc_iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def metadata(index: StaticIndex, bridge: Bridge, now: int, static_commit: str):
    """Only committed, canonical static-feed IDs qualify for this snapshot."""
    if not static_commit or len(static_commit) != 40 or any(
        c not in "0123456789abcdef" for c in static_commit.lower()
    ):
        raise ValueError("static_commit must be the exact 40-character feed-data commit SHA")

    feeds = {}
    for kind in KINDS:
        # Never rejuvenate stale cached entities using a recent transport packet.
        entities = bridge.active(kind, now)
        if entities is None:
            entities = []
        with bridge.lock:
            entity_times = [
                timestamp for _, timestamp in bridge.cache[kind].values()
                if now - timestamp <= (600 if kind == "alerts" else 90)
            ] if bridge.active(kind, now) is not None else []
            last_packet = bridge.last_packet[kind]
            source_stamp = bridge.last_source_time[kind]
        feeds[kind] = {
            "entities": len(entities),
            "source_observation_at": utc_iso(source_stamp) if source_stamp else None,
            "latest_packet_received_at": utc_iso(last_packet) if last_packet else None,
            "oldest_included_entity_at": utc_iso(min(entity_times)) if entity_times else None,
            "source_age_seconds_at_generation": max(0, now - source_stamp) if source_stamp else None,
            "oldest_entity_age_seconds_at_generation": max(0, now - min(entity_times)) if entity_times else None,
        }
    return {
        "schema": "otd-citylink-gtfsrt-snapshot-v1",
        "derived": True,
        "publisher": "Open Transit Display",
        "provider": "Ride Guide / CityLink",
        "static_feed_branch": "feed-data",
        "static_feed_commit": static_commit.lower(),
        "static_gtfs_path": "citylink/gtfs.zip",
        "static_trip_map_path": "citylink/trip-map.json",
        "service_dates": sorted(index.service_days),
        "generated_at_utc": utc_iso(now),
        "publication_started_at_utc": None,
        "max_consumer_age_seconds": MAX_CONSUMER_AGE_SECONDS,
        "note": (
            "Not a freshness guarantee. Consumers MUST verify their current time, "
            "original entity/source timestamps, date/route/trip/stop identity, and "
            "static feed revision; downgrade old LIVE claims to dated estimates or SCHED. "
            "The 90-second adapter filter applies only when the snapshot is generated."
        ),
        "feeds": feeds,
    }


def export(index: StaticIndex, bridge: Bridge, root: Path, static_commit: str, now=None,
           stop_id=None, route_id=None, route_label=None):
    """Create complete atomic candidate files; never output partial publication."""
    now = int(time.time()) if now is None else int(now)
    output = root / "citylink"
    output.mkdir(parents=True, exist_ok=True)
    manifest = metadata(index, bridge, now, static_commit)

    # Write standard GTFS-Realtime FULL_DATASET messages.
    for kind in KINDS:
        fresh = bridge.active(kind, now)
        feed = pb.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        feed.header.incrementality = pb.FeedHeader.FULL_DATASET
        feed.header.timestamp = now
        for entity in fresh or []:
            feed.entity.add().CopyFrom(entity)
        data = feed.SerializeToString()
        basename = {
            "tripupdates": "tripupdates.pb",
            "vehiclepositions": "vehiclepositions.pb",
            "alerts": "alerts.pb",
        }[kind]
        (output / basename).write_bytes(data)
        manifest["feeds"][kind]["path"] = "citylink/" + basename
        manifest["feeds"][kind]["sha256"] = hashlib.sha256(data).hexdigest()

    if stop_id is not None:
        if stop_id not in index.stop_ids:
            raise ValueError("requested stop_id not present in the static GTFS")
        if route_id is not None and route_id not in index.routes:
            raise ValueError("requested route_id not present in the static GTFS")
        arrivals = bridge.stop_arrivals(stop_id, route=route_id, now=now, limit=12)
        arrivals["static_feed_commit"] = static_commit.lower()
        arrivals["snapshot_generated_at_utc"] = manifest["generated_at_utc"]
        arrivals["max_consumer_age_seconds"] = MAX_CONSUMER_AGE_SECONDS
        # Explicit upstream timestamps in arrivals are more important than
        # the age of the GitHub or radio download for truthful LIVE labels.
        # This label is a filename only; route matching uses canonical ID.
        short_route = str(route_label or route_id or "all")
        if not short_route.replace("-", "").isalnum():
            raise ValueError("route_label must be a simple path-safe identifier")
        folder = output / "stops" / str(stop_id)
        folder.mkdir(parents=True, exist_ok=True)
        relative = "citylink/stops/" + str(stop_id) + "/" + str(short_route) + ".json"
        encoded = (json.dumps(arrivals, sort_keys=True, separators=(",", ":")) +
                   "\n").encode("utf-8")
        (folder / (str(short_route) + ".json")).write_bytes(encoded)
        manifest["stop_snapshots"] = [{
            "stop_id": stop_id,
            "route_id": route_id,
            "path": relative,
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }]

    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


async def collect(bridge: Bridge, seconds: int, ws_url: str = WS_URL):
    """Single bounded WebSocket collection; returns without claiming availability."""
    import websockets
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            async with websockets.connect(
                ws_url, origin=ORIGIN, ping_interval=20, ping_timeout=20,
                open_timeout=10, max_size=8_000_000,
            ) as ws:
                bridge.connection_state(True)
                await ws.send(json.dumps(SUBSCRIBE))
                try:
                    while time.monotonic() < deadline:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        try:
                            packet = await asyncio.wait_for(ws.recv(), min(15, remaining))
                        except asyncio.TimeoutError:
                            continue
                        if isinstance(packet, bytes):
                            try:
                                bridge.ingest(packet)
                            except Exception:
                                bridge.record_error("decode_errors")
                finally:
                    bridge.connection_state(False)
        except asyncio.CancelledError:
            bridge.connection_state(False)
            raise
        except Exception:
            bridge.connection_state(False)
            bridge.record_error("connection_errors")
            await asyncio.sleep(min(3, max(0, deadline - time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs", required=True, type=Path)
    parser.add_argument("--trip-map", required=True, type=Path)
    parser.add_argument("--static-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--collect-seconds", type=int, default=COLLECTION_SECONDS_DEFAULT)
    parser.add_argument("--ws-url", default=WS_URL)
    parser.add_argument("--stop-id", default=None)
    parser.add_argument("--route-id", default=None)
    parser.add_argument("--route-label", default=None)
    args = parser.parse_args()
    if not 1 <= args.collect_seconds <= 180:
        parser.error("--collect-seconds must be between 1 and 180")
    index = StaticIndex(args.gtfs, args.trip_map)
    backend = Bridge(index)
    asyncio.run(collect(backend, args.collect_seconds, args.ws_url))
    out = export(index, backend, args.output, args.static_commit,
                 stop_id=args.stop_id, route_id=args.route_id,
                 route_label=args.route_label)
    # Log counts, ages and revision only; never raw vehicle identifiers or locations.
    print(json.dumps({
        "generated_at_utc": out["generated_at_utc"],
        "static_feed_commit": out["static_feed_commit"],
        "service_dates": out["service_dates"],
        "feeds": out["feeds"],
        "rejections": backend.status()["counters"],
    }, indent=2))


if __name__ == "__main__":
    main()
