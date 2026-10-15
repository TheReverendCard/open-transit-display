#!/usr/bin/env python3
"""Publish date-scoped stop/route schedule JSON beside verified GTFS.

These files contain timetable information, not realtime predictions.
"""
import argparse
import csv
from datetime import date, datetime, time, timedelta
import io
import json
from pathlib import Path
import zlib
from zoneinfo import ZoneInfo
from zipfile import ZipFile

NZ = ZoneInfo("Pacific/Auckland")
MAX_ENTRIES = 160

def rows(z, name):
    return list(csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig")))

def generate(gtfs: Path, output: Path, today: date | None = None):
    today = today or datetime.now(NZ).date()
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(gtfs) as z:
        routes = {r["route_id"]: r for r in rows(z, "routes.txt")}
        trips = {r["trip_id"]: r for r in rows(z, "trips.txt")}
        stops = {r["stop_id"]: r for r in rows(z, "stops.txt")}
        service_dates = {r["service_id"]: datetime.strptime(r["date"], "%Y%m%d").date()
                         for r in rows(z, "calendar_dates.txt") if r["exception_type"] == "1"
                         and r["service_id"] == r["date"]}
        by_trip = {}
        for r in rows(z, "stop_times.txt"):
            by_trip.setdefault(r["trip_id"], []).append(r)
    covered = sorted({d for d in service_dates.values()
                      if today <= d <= today + timedelta(days=9)})
    if not covered or today not in covered:
        raise ValueError("Snapshot does not cover today; refusing stale timetable")
    grouped = {}
    for trip_id, parts in by_trip.items():
        trip = trips.get(trip_id)
        if not trip or trip["service_id"] not in service_dates:
            continue
        service_date = service_dates[trip["service_id"]]
        if service_date not in covered:
            continue
        route = routes.get(trip["route_id"])
        if not route:
            continue
        short = route.get("route_short_name", "").strip()
        if not short:
            continue
        parts.sort(key=lambda r: int(r["stop_sequence"]))
        terminal = stops.get(parts[-1]["stop_id"], {}).get("stop_name", "")
        for part in parts[:-1]:
            if part.get("pickup_type", "0") == "1":
                continue
            stop_id = part["stop_id"]
            if stop_id not in stops:
                continue
            hours, mins, seconds = map(int, part["departure_time"].split(":"))
            departure = datetime.combine(service_date, time(), NZ) + timedelta(
                hours=hours, minutes=mins, seconds=seconds)
            dest = (trip.get("trip_headsign") or terminal or
                    route.get("route_long_name") or "").strip()
            if short == "6" and stop_id == "11000262" and "Rose Street" in terminal:
                dest = "Rose Street / CBD"
            grouped.setdefault((stop_id, short), []).append(
                (int(departure.timestamp()), dest, trip_id))
    written = []
    for (stop_id, short), events in sorted(grouped.items()):
        uniq = sorted(set(events))
        times = sorted({epoch for epoch, _, _ in uniq})
        if len(times) > MAX_ENTRIES:
            continue  # Never silently truncate and claim complete service coverage.
        checksum = f'{zlib.crc32(",".join(map(str, times)).encode("ascii")) & 0xffffffff:08X}'
        name = "Whangārei Museum" if stop_id == "11000262" else stops[stop_id]["stop_name"]
        destination = uniq[0][1] if len({x[1] for x in uniq}) == 1 else ""
        payload = {
            "schema": "otd-stop-schedule-v1", "provider": "citylink-derived",
            "source": "GTFS_STATIC", "stop_id": stop_id, "route": short,
            "stop_name": name, "destination": destination,
            "timezone": "Pacific/Auckland",
            "covered_dates": [d.isoformat() for d in covered],
            "revision": checksum, "departures": times,
        }
        path = output / stop_id / f"{short}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False,
                                   separators=(",", ":")) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(output)))
    return written

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gtfs", default="data/publication/citylink/gtfs.zip")
    p.add_argument("--output", default="data/publication/citylink/stops")
    p.add_argument("--today", type=date.fromisoformat,
                   help="For deterministic test fixtures only")
    a = p.parse_args()
    written = generate(Path(a.gtfs), Path(a.output), a.today)
    print(f"Wrote {len(written)} complete, date-specific stop/route snapshots")
    if "11000262/6.json" in written:
        print("Whangārei Museum Route 6 exported.")

if __name__ == "__main__":
    main()
