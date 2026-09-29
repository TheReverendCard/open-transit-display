import asyncio
import gzip
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import websockets
from google.transit import gtfs_realtime_pb2


WS_URL = "wss://rti.ride.guide/"
ORIGIN = "https://app.ride.guide"
ORGANISATION_ID = 104

SUBSCRIPTION = {
    "organisationId": ORGANISATION_ID,
    "feedTypes": [
        "VEHICLE_POSITIONS",
        "TRIP_UPDATES",
        "SERVICE_ALERTS",
    ],
}

RUN_SECONDS = int(os.environ.get("RUN_SECONDS", "600"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "data/run"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def event_to_dict(event):
    result = {}
    if event.time:
        result["time"] = int(event.time)
    if event.HasField("delay"):
        result["delay"] = int(event.delay)
    if event.HasField("uncertainty"):
        result["uncertainty"] = int(event.uncertainty)
    return result


def vehicle_to_dict(entity, feed_timestamp, received_at):
    v = entity.vehicle
    return {
        "kind": "vehicle",
        "source": "rideguide",
        "organisation_id": ORGANISATION_ID,
        "received_at": received_at,
        "feed_timestamp": feed_timestamp,
        "entity_id": entity.id,
        "vehicle_id": v.vehicle.id,
        "trip_id": v.trip.trip_id,
        "route_id": v.trip.route_id,
        "start_time": v.trip.start_time,
        "start_date": v.trip.start_date,
        "stop_id": v.stop_id,
        "current_stop_sequence": int(v.current_stop_sequence),
        "current_status": int(v.current_status),
        "latitude": float(v.position.latitude),
        "longitude": float(v.position.longitude),
        "bearing": float(v.position.bearing),
        "speed": float(v.position.speed),
        "vehicle_timestamp": int(v.timestamp) if v.timestamp else None,
    }


def trip_update_to_dict(entity, feed_timestamp, received_at):
    t = entity.trip_update

    if t.vehicle.id and "schedBasedVehicle" in t.vehicle.id:
        prediction_source = "schedule_based"
    elif t.vehicle.id:
        prediction_source = "vehicle_assigned"
    else:
        prediction_source = "unknown"

    stop_updates = []
    for stop in t.stop_time_update:
        stop_updates.append(
            {
                "stop_id": stop.stop_id,
                "stop_sequence": int(stop.stop_sequence),
                "arrival": event_to_dict(stop.arrival) if stop.HasField("arrival") else None,
                "departure": event_to_dict(stop.departure) if stop.HasField("departure") else None,
            }
        )

    return {
        "kind": "trip_update",
        "source": "rideguide",
        "organisation_id": ORGANISATION_ID,
        "received_at": received_at,
        "feed_timestamp": feed_timestamp,
        "entity_id": entity.id,
        "vehicle_id": t.vehicle.id,
        "trip_id": t.trip.trip_id,
        "route_id": t.trip.route_id,
        "start_time": t.trip.start_time,
        "start_date": t.trip.start_date,
        "trip_timestamp": int(t.timestamp) if t.timestamp else None,
        "prediction_source": prediction_source,
        "stop_updates": stop_updates,
    }


def alert_text(translated_string):
    values = []
    for translation in translated_string.translation:
        if translation.text:
            values.append(
                {
                    "text": translation.text,
                    "language": translation.language,
                }
            )
    return values


def alert_to_dict(entity, feed_timestamp, received_at):
    alert = entity.alert
    return {
        "kind": "alert",
        "source": "rideguide",
        "organisation_id": ORGANISATION_ID,
        "received_at": received_at,
        "feed_timestamp": feed_timestamp,
        "entity_id": entity.id,
        "header": alert_text(alert.header_text),
        "description": alert_text(alert.description_text),
    }


def decode_message(data, received_at):
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(data)

    feed_timestamp = int(feed.header.timestamp) if feed.header.timestamp else None
    rows = []

    if not feed.entity:
        rows.append(
            {
                "kind": "empty_feed",
                "source": "rideguide",
                "organisation_id": ORGANISATION_ID,
                "received_at": received_at,
                "feed_timestamp": feed_timestamp,
                "gtfs_realtime_version": feed.header.gtfs_realtime_version,
            }
        )
        return rows

    for entity in feed.entity:
        if entity.HasField("vehicle"):
            rows.append(vehicle_to_dict(entity, feed_timestamp, received_at))
        elif entity.HasField("trip_update"):
            rows.append(trip_update_to_dict(entity, feed_timestamp, received_at))
        elif entity.HasField("alert"):
            rows.append(alert_to_dict(entity, feed_timestamp, received_at))

    return rows


async def collect():
    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    output_path = OUTPUT_DIR / f"rideguide-{stamp}.jsonl.gz"

    end_monotonic = time.monotonic() + RUN_SECONDS
    rows_written = 0
    messages_received = 0

    print(f"Collecting from {WS_URL}")
    print(f"Run length: {RUN_SECONDS} seconds")
    print(f"Output: {output_path}")

    with gzip.open(output_path, "wt", encoding="utf-8") as output:
        while time.monotonic() < end_monotonic:
            try:
                async with websockets.connect(
                    WS_URL,
                    origin=ORIGIN,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                ) as ws:
                    await ws.send(json.dumps(SUBSCRIPTION))
                    print("Connected and subscribed.")

                    while time.monotonic() < end_monotonic:
                        timeout = min(30, max(1, end_monotonic - time.monotonic()))
                        message = await asyncio.wait_for(ws.recv(), timeout=timeout)

                        if not isinstance(message, bytes):
                            continue

                        messages_received += 1
                        received_at = utc_now_iso()

                        try:
                            rows = decode_message(message, received_at)
                        except Exception as exc:
                            print(f"Decode error: {exc}")
                            continue

                        for row in rows:
                            output.write(json.dumps(row, separators=(",", ":")) + "\n")
                            rows_written += 1

                        output.flush()

            except asyncio.TimeoutError:
                print("No message received before timeout; reconnecting if time remains.")
            except Exception as exc:
                print(f"Connection error: {exc}")
                if time.monotonic() < end_monotonic:
                    await asyncio.sleep(5)

    print(f"Finished. Messages: {messages_received}; rows: {rows_written}")
    print(output_path)


if __name__ == "__main__":
    asyncio.run(collect())
