#!/usr/bin/env python3
"""Publish date-scoped stop/route schedule JSON beside verified GTFS.

These files contain timetable information, not realtime predictions.
"""
import argparse
import csv
import hashlib
from datetime import date, datetime, time, timedelta
import io
import json
from pathlib import Path
import zlib
from zoneinfo import ZoneInfo
from zipfile import ZipFile
from urllib.parse import quote

NZ = ZoneInfo("Pacific/Auckland")
MAX_ENTRIES = 160

def rows(z, name):
    return list(csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig")))

def generate(gtfs: Path, output: Path, today: date | None = None):
    today = today or datetime.now(NZ).date()
    with ZipFile(gtfs) as z:
        if "calendar.txt" in z.namelist():
            raise ValueError("Only date-scoped derived CityLink feeds are supported")
        routes = {r["route_id"]: r for r in rows(z, "routes.txt")}
        trips = {r["trip_id"]: r for r in rows(z, "trips.txt")}
        stops = {r["stop_id"]: r for r in rows(z, "stops.txt")}
        calendar = rows(z, "calendar_dates.txt")
        if any(r["exception_type"] != "1" or r["service_id"] != r["date"] for r in calendar):
            raise ValueError("Expected explicit date-scoped CityLink service IDs")
        service_dates = {r["service_id"]: datetime.strptime(r["date"], "%Y%m%d").date()
                         for r in calendar}
        by_trip = {}
        for r in rows(z, "stop_times.txt"):
            by_trip.setdefault(r["trip_id"], []).append(r)
    covered = sorted({d for d in service_dates.values()
                      if today <= d <= today + timedelta(days=9)})
    if not covered or today not in covered:
        raise ValueError("Snapshot does not cover today; refusing stale timetable")
    # Do not silently skip incomplete coverage or pretend a missing day has no buses.
    if covered != [today + timedelta(days=i) for i in range((covered[-1] - today).days + 1)]:
        raise ValueError("Snapshot has gaps in date coverage")
    output.mkdir(parents=True, exist_ok=True)
    source_sha = hashlib.sha256(gtfs.read_bytes()).hexdigest()
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
            if part.get("pickup_type", "0") in ("1", "2", "3"):
                continue
            stop_id = part["stop_id"]
            if stop_id not in stops:
                continue
            hours, mins, seconds = map(int, part["departure_time"].split(":"))
            if hours < 0 or not 0 <= mins < 60 or not 0 <= seconds < 60:
                raise ValueError("Invalid GTFS departure time")
            # GTFS time origin is local noon minus 12 elapsed hours, including DST.
            epoch = int(datetime.combine(service_date, time(12), NZ).timestamp()) - 43200
            epoch += hours * 3600 + mins * 60 + seconds
            dest = (trip.get("trip_headsign") or terminal or
                    route.get("route_long_name") or "").strip()
            if short == "6" and stop_id == "11000262" and "Rose Street" in terminal:
                dest = "Rose Street / CBD"
            grouped.setdefault((stop_id, short), []).append(
                (epoch, dest, trip_id))
    written = []
    skipped = []
    for (stop_id, short), events in sorted(grouped.items()):
        uniq = sorted(set(events))
        times = sorted({epoch for epoch, _, _ in uniq})
        if len(times) > MAX_ENTRIES:
            skipped.append({"stop_id": stop_id, "route": short, "entries": len(times),
                            "reason": "device_capacity_exceeded"})
            continue
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
            "static_feed_sha256": source_sha,
        }
        # CRC remains exactly the OTDL1 epoch-list checksum. Metadata has a separate revision.
        payload["content_revision"] = hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        if stop_id in (".", "..") or short in (".", ".."):
            raise ValueError("Invalid stop/route path component")
        path = output / quote(stop_id, safe="") / f"{quote(short, safe='')}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False,
                                   separators=(",", ":")) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(output)))
    manifest = {
        "schema": "otd-stop-schedule-index-v1",
        "source": "GTFS_STATIC", "static_feed_sha256": source_sha,
        "covered_dates": [d.isoformat() for d in covered],
        "max_entries": MAX_ENTRIES, "files": written, "skipped": skipped,
        "note": "Static timetable only. Not live predictions. No weekly repetition.",
    }
    (output / "index.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
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
