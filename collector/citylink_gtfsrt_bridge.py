#!/usr/bin/env python3
"""Bridge CityLink / Ride Guide GTFS-Realtime onto the *published* CityLink GTFS IDs.

Static GTFS is published separately on the feed-data branch. Live protobuf
feeds are served by an always-running process, NOT by nightly GitHub Actions.
Only provider-observed predictions are promoted; missing stops use standard
GTFS-RT delay propagation in the optional stop-level JSON response.

Prerequisites: pip install gtfs-realtime-bindings websockets
Example: python collector/citylink_gtfsrt_bridge.py --gtfs citylink/gtfs.zip
         --trip-map citylink/trip-map.json --host 127.0.0.1 --port 8787
"""
from __future__ import annotations

import argparse
import asyncio
import csv
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
from pathlib import Path
import threading
import time as clock
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo
from zipfile import ZipFile

from google.transit import gtfs_realtime_pb2 as pb

NZ = ZoneInfo("Pacific/Auckland")
WS_URL = "wss://rti.ride.guide/"
ORIGIN = "https://app.ride.guide"
SUBSCRIBE = {"organisationId": 104, "feedTypes":
             ["VEHICLE_POSITIONS", "TRIP_UPDATES", "SERVICE_ALERTS"]}
KINDS = ("tripupdates", "vehiclepositions", "alerts")
STALE_SECONDS = 90
LOG = logging.getLogger("citylink_gtfsrt")


def table(archive, filename):
    return list(csv.DictReader(
        io.TextIOWrapper(archive.open(filename), encoding="utf-8-sig")))


def to_epoch(service_day, hhmmss):
    hours, minutes, seconds = (int(v) for v in hhmmss.split(":"))
    return int((datetime.combine(datetime.strptime(service_day, "%Y%m%d").date(),
                                 time(), NZ) +
                timedelta(hours=hours, minutes=minutes, seconds=seconds)).timestamp())


@dataclass(frozen=True)
class ScheduledStop:
    sequence: int
    stop_id: str
    arrival: int
    departure: int


class StaticIndex:
    """Read exactly the same static feed IDs a GTFS-RT consumer downloads."""

    def __init__(self, gtfs_zip: Path, trip_map_json: Path):
        mapping = json.loads(trip_map_json.read_text(encoding="utf-8"))
        if not mapping.get("derived"):
            raise ValueError("CityLink trip-map must be marked derived")
        self.trips = {}
        self.trip_stops = {}
        self.by_stop = {}
        self.source_map = {}
        self.routes = set()
        self.stop_ids = set()
        self.service_days = set()
        with ZipFile(gtfs_zip) as archive:
            trips = table(archive, "trips.txt")
            stops = table(archive, "stop_times.txt")
            self.routes = {r["route_id"] for r in table(archive, "routes.txt")}
            self.stop_ids = {s["stop_id"] for s in table(archive, "stops.txt")}
            self.service_days = {
                r["date"] for r in table(archive, "calendar_dates.txt")
                if r.get("exception_type") == "1"
            }
        for trip in trips:
            if trip["service_id"] not in self.service_days:
                continue
            self.trips[trip["trip_id"]] = trip
        for entry in mapping["trips"]:
            derived = entry["trip_id"]
            if derived not in self.trips:
                continue
            # Date-specific trip IDs *must* match the public static GTFS.
            key = (str(entry["source_trip_id"]), str(entry["route_id"]),
                   str(entry["start_date"]))
            self.source_map.setdefault(key, set()).add(derived)
        for r in stops:
            trip_id = r["trip_id"]
            if trip_id not in self.trips or r["stop_id"] not in self.stop_ids:
                continue
            day = self.trips[trip_id]["service_id"]
            stop = ScheduledStop(int(r["stop_sequence"]), r["stop_id"],
                                 to_epoch(day, r["arrival_time"]),
                                 to_epoch(day, r["departure_time"]))
            self.trip_stops.setdefault(trip_id, []).append(stop)
            self.by_stop.setdefault(stop.stop_id, []).append(
                (stop.departure, trip_id, stop.sequence))
        for trip_id in self.trip_stops:
            self.trip_stops[trip_id].sort(key=lambda x: x.sequence)
        for stop_id in self.by_stop:
            self.by_stop[stop_id].sort()

    def map_trip(self, descriptor):
        """Return unique derived static trip ID, otherwise None (never guess)."""
        source_id = descriptor.trip_id
        service_day = descriptor.start_date
        route = descriptor.route_id
        if source_id in self.trips:
            trip = self.trips[source_id]
            if service_day and trip["service_id"] != service_day:
                return None
            if route and trip["route_id"] != route:
                return None
            return source_id
        if not service_day:
            return None
        if route:
            candidates = self.source_map.get((source_id, route, service_day), set())
        else:
            candidates = set().union(*(v for (s, _, d), v in self.source_map.items()
                                       if s == source_id and d == service_day))
        return next(iter(candidates)) if len(candidates) == 1 else None

    def stop_for(self, trip_id, source):
        stops = self.trip_stops.get(trip_id, [])
        if source.stop_id:
            options = [s for s in stops if s.stop_id == source.stop_id]
            if len(options) == 1:
                return options[0]
            if len(options) > 1 and source.stop_sequence:
                return next((s for s in options if s.sequence == source.stop_sequence),
                            None)
            return None
        return next((s for s in stops if s.sequence == source.stop_sequence), None)


def remap_entity(entity, index: StaticIndex):
    """Return a valid remapped entity, or None if trip cannot be proven."""
    output = pb.FeedEntity()
    output.CopyFrom(entity)
    if entity.HasField("trip_update"):
        src = entity.trip_update
        mapped = index.map_trip(src.trip)
        if not mapped:
            return None
        out = output.trip_update
        out.trip.trip_id = mapped
        out.trip.route_id = index.trips[mapped]["route_id"]
        out.trip.start_date = index.trips[mapped]["service_id"]
        good = []
        for item in src.stop_time_update:
            actual = index.stop_for(mapped, item)
            if actual is None:
                continue
            mapped_item = pb.TripUpdate.StopTimeUpdate()
            mapped_item.CopyFrom(item)
            mapped_item.stop_id = actual.stop_id
            mapped_item.stop_sequence = actual.sequence
            good.append(mapped_item)
        del out.stop_time_update[:]
        for item in sorted(good, key=lambda x: x.stop_sequence):
            # Do not synthesize a prediction at missing stops.
            if out.stop_time_update and item.stop_sequence == out.stop_time_update[-1].stop_sequence:
                continue
            out.stop_time_update.add().CopyFrom(item)
        if not out.stop_time_update and out.trip.schedule_relationship not in (
                pb.TripDescriptor.CANCELED,):
            return None
    elif entity.HasField("vehicle"):
        src = entity.vehicle
        mapped = index.map_trip(src.trip)
        if not mapped:
            return None
        out = output.vehicle
        out.trip.trip_id = mapped
        out.trip.route_id = index.trips[mapped]["route_id"]
        out.trip.start_date = index.trips[mapped]["service_id"]
        if src.stop_id:
            if src.stop_id not in index.stop_ids:
                return None
            match = index.stop_for(mapped, src)
            if match:
                out.current_stop_sequence = match.sequence
        elif src.current_stop_sequence:
            # No stop_id to validate against the derived trip sequence.
            out.ClearField("current_stop_sequence")
    elif entity.HasField("alert"):
        # Preserve network-wide alerts, and validate any explicit trip linkage.
        for selector in output.alert.informed_entity:
            if selector.trip.trip_id:
                mapped = index.map_trip(selector.trip)
                if not mapped:
                    return None
                selector.trip.trip_id = mapped
                selector.trip.route_id = index.trips[mapped]["route_id"]
                selector.trip.start_date = index.trips[mapped]["service_id"]
            if selector.route_id and selector.route_id not in index.routes:
                return None
            if selector.stop_id and selector.stop_id not in index.stop_ids:
                return None
    else:
        return None
    return output


def kind_of(entity):
    if entity.HasField("trip_update"):
        return "tripupdates"
    if entity.HasField("vehicle"):
        return "vehiclepositions"
    if entity.HasField("alert"):
        return "alerts"
    return None


def predicted_time(event, scheduled_epoch):
    if event.HasField("time"):
        return int(event.time)
    if event.HasField("delay"):
        return scheduled_epoch + event.delay
    return None


class Bridge:
    def __init__(self, index: StaticIndex):
        self.index = index
        self.lock = threading.RLock()
        self.cache = {k: {} for k in KINDS}
        self.last_packet = {k: 0 for k in KINDS}
        self.last_source_time = {k: 0 for k in KINDS}
        self.unmatched = 0
        self.accepted = 0

    def ingest(self, blob: bytes, received_at=None):
        received_at = received_at or int(clock.time())
        feed = pb.FeedMessage()
        feed.ParseFromString(blob)
        source_time = int(feed.header.timestamp or received_at)
        if source_time > received_at + 60 or received_at - source_time > STALE_SECONDS:
            return False
        batches = {kind: {} for kind in KINDS}
        for entity in feed.entity:
            kind = kind_of(entity)
            if kind is None:
                continue
            out = remap_entity(entity, self.index)
            if out is None:
                self.unmatched += 1
                continue
            ident = out.id or (kind + ":" + str(len(batches[kind])))
            batches[kind][ident] = (out, source_time)
            self.accepted += 1
        with self.lock:
            if not feed.entity:
                # Empty FULL_DATASET is meaningful; no stale predictions should persist.
                for kind in KINDS:
                    self.cache[kind] = {}
                    self.last_packet[kind] = received_at
                    self.last_source_time[kind] = source_time
            else:
                for kind in KINDS:
                    # The upstream WebSocket may deliver different entity kinds in
                    # separate messages; a trip-update-only batch must not erase vehicles.
                    if any(kind_of(e) == kind for e in feed.entity):
                        if feed.header.incrementality == pb.FeedHeader.FULL_DATASET:
                            self.cache[kind] = batches[kind]
                        else:
                            self.cache[kind].update(batches[kind])
                        self.last_packet[kind] = received_at
                        self.last_source_time[kind] = source_time
        return True

    def active(self, kind, now=None):
        now = int(now or clock.time())
        with self.lock:
            freshness = self.last_packet[kind]
            if not freshness or now - self.last_source_time[kind] > STALE_SECONDS:
                return None
            return [obj for obj, ts in self.cache[kind].values()
                    if now - ts <= STALE_SECONDS]

    def protobuf(self, kind, now=None):
        now = int(now or clock.time())
        entities = self.active(kind, now)
        if entities is None:
            return None
        output = pb.FeedMessage()
        output.header.gtfs_realtime_version = "2.0"
        output.header.incrementality = pb.FeedHeader.FULL_DATASET
        output.header.timestamp = now
        for entity in entities:
            output.entity.add().CopyFrom(entity)
        return output.SerializeToString()

    def stop_arrivals(self, stop_id, route=None, now=None, limit=5):
        """Derived passenger JSON. GTFS-RT protobuf itself remains unexpanded."""
        now = int(now or clock.time())
        if stop_id not in self.index.stop_ids:
            return None
        updates = self.active("tripupdates", now)
        by_trip = {}
        if updates is not None:
            for entity in updates:
                if entity.HasField("trip_update"):
                    by_trip[entity.trip_update.trip.trip_id] = entity.trip_update
        results = []
        for when, tid, sequence in self.index.by_stop.get(stop_id, []):
            if when < now - 3600 or when > now + 6 * 3600:
                continue
            trip = self.index.trips[tid]
            if route is not None and trip["route_id"] != route:
                continue
            source, predicted, observed_at = "SCHED", when, None
            update = by_trip.get(tid)
            if update:
                if update.trip.schedule_relationship == pb.TripDescriptor.CANCELED:
                    source, predicted = "CANCELED", None
                else:
                    stops = {s.sequence: s for s in self.index.trip_stops[tid]}
                    shift = None
                    direct = False
                    for item in update.stop_time_update:
                        if item.stop_sequence > sequence:
                            break
                        if item.schedule_relationship == pb.TripUpdate.StopTimeUpdate.NO_DATA:
                            shift = None
                            direct = False
                            continue
                        scheduled = stops.get(item.stop_sequence)
                        if scheduled is None:
                            continue
                        event = (item.departure if item.HasField("departure")
                                 else item.arrival if item.HasField("arrival") else None)
                        base = scheduled.departure if item.HasField("departure") else scheduled.arrival
                        if event is not None:
                            event_time = predicted_time(event, base)
                            if event_time is not None:
                                shift = event_time - base
                                direct = item.stop_sequence == sequence
                    if shift is not None:
                        predicted = when + shift
                        vehicle_id = update.vehicle.id or ""
                        vehicle_backed = bool(vehicle_id) and "schedBasedVehicle" not in vehicle_id
                        if direct:
                            source = "LIVE" if vehicle_backed else "PROVIDER_ESTIMATE"
                        else:
                            source = "PROPAGATED" if vehicle_backed else "PROPAGATED_ESTIMATE"
                        observed_at = int(update.timestamp) if update.timestamp else \
                            self.last_source_time["tripupdates"]
            if predicted is not None and predicted < now - 120 and when < now - 120:
                continue
            results.append({
                "trip_id": tid, "route_id": trip["route_id"],
                "stop_id": stop_id, "scheduled": when,
                "predicted": predicted, "source": source,
                "observed_at": observed_at,
            })
        results.sort(key=lambda x: (x["predicted"] if x["predicted"] is not None
                                    else x["scheduled"], x["trip_id"]))
        return {"schema": "otd-stop-arrivals-v1", "stop_id": stop_id,
                "generated_at": now, "realtime_available": updates is not None,
                "arrivals": results[:limit]}

    def status(self):
        now = int(clock.time())
        with self.lock:
            return {"type": "derived_gtfsrt_bridge",
                    "upstream": "Ride Guide",
                    "timestamp": now,
                    "freshness_seconds": STALE_SECONDS,
                    "received_at": self.last_packet.copy(),
                    "upstream_timestamp": self.last_source_time.copy(),
                    "accepted_entities": self.accepted,
                    "unmatched_entities": self.unmatched,
                    "static_trips": len(self.index.trips),
                    "trip_update_entities": len(self.cache["tripupdates"])}


def handler_factory(bridge):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body: bytes, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            kind = {
                "/gtfs-realtime/tripupdates.pb": "tripupdates",
                "/gtfs-realtime/vehiclepositions.pb": "vehiclepositions",
                "/gtfs-realtime/alerts.pb": "alerts",
            }.get(path)
            if kind:
                body = bridge.protobuf(kind)
                if body is None:
                    return self.reply(503, b"Upstream feed not fresh\n", "text/plain")
                return self.reply(200, body, "application/x-protobuf")
            if path == "/health.json":
                payload = bridge.status()
            elif path.startswith("/v1/stops/") and path.endswith("/arrivals.json"):
                stop_id = unquote(path[len("/v1/stops/"):-len("/arrivals.json")].strip("/"))
                payload = bridge.stop_arrivals(stop_id)
                if payload is None:
                    return self.reply(404, b"Unknown stop\n", "text/plain")
            else:
                return self.reply(404, b"Unknown endpoint\n", "text/plain")
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            return self.reply(200, body, "application/json; charset=utf-8")

        def log_message(self, fmt, *args):
            LOG.info("http %s " + fmt, self.client_address[0], *args)

    return Handler


async def receive_forever(bridge, ws_url):
    import websockets
    while True:
        try:
            async with websockets.connect(ws_url, origin=ORIGIN,
                                          ping_interval=20, ping_timeout=20,
                                          max_size=8_000_000) as ws:
                await ws.send(json.dumps(SUBSCRIBE))
                LOG.info("Ride Guide GTFS-RT stream connected")
                async for message in ws:
                    if isinstance(message, bytes):
                        try:
                            bridge.ingest(message)
                        except Exception:
                            LOG.exception("Rejected malformed upstream protobuf")
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("Ride Guide disconnected; retrying after 5 seconds")
            await asyncio.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs", type=Path, required=True)
    parser.add_argument("--trip-map", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--ws-url", default=WS_URL)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    backend = Bridge(StaticIndex(args.gtfs, args.trip_map))
    http = ThreadingHTTPServer((args.host, args.port), handler_factory(backend))
    threading.Thread(target=http.serve_forever, daemon=True).start()
    LOG.info("Listening on %s:%d (use trusted HTTPS proxy for public access)",
             args.host, args.port)
    try:
        asyncio.run(receive_forever(backend, args.ws_url))
    finally:
        http.shutdown()
        http.server_close()


if __name__ == "__main__":
    main()
