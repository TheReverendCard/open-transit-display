#!/usr/bin/env python3
"""Museum stop / CityLink date-specific derived GTFS -> USB LoRa gateway.

This is a timetable-only SCHED source, not a realtime ETA feed.
Windows:
  py -m pip install pyserial tzdata
  py museum_gateway.py --list-stops museum
  py museum_gateway.py --port COM5 --stop-id 11000262
Sender's Arduino Serial Monitor must be closed when running the gateway.
"""
import argparse
import csv
from datetime import datetime, timedelta
import io
from pathlib import Path
import sys
import time
from urllib.request import urlopen, Request
from zoneinfo import ZoneInfo
from zipfile import ZipFile

FEED_URL = "https://raw.githubusercontent.com/TheReverendCard/open-transit-display/feed-data/citylink/gtfs.zip"
NZ = ZoneInfo("Pacific/Auckland")
CACHE = Path(__file__).with_name("citylink_gtfs_cache.zip")

def csv_table(z, name):
    with z.open(name) as stream:
        return list(csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig")))

def fetch_zip(force=False):
    # Preserve the last snapshot for offline inspection, but never use
    # events from a service date that the feed does not explicitly cover.
    if force or not CACHE.exists() or time.time()-CACHE.stat().st_mtime>20*3600:
        print(f"Fetching current derived CityLink feed: {FEED_URL}", flush=True)
        try:
            req=Request(FEED_URL,headers={"User-Agent":"OpenTransitDisplay/0.3"})
            with urlopen(req,timeout=30) as r:
                blob=r.read(5_000_000)
            with ZipFile(io.BytesIO(blob)) as z:
                for name in ("stops.txt","routes.txt","trips.txt","stop_times.txt","calendar_dates.txt"):
                    if name not in z.namelist():
                        raise ValueError(f"Missing GTFS table {name}")
            CACHE.write_bytes(blob)
        except Exception as exc:
            if not CACHE.exists():
                raise RuntimeError(f"Cannot fetch GTFS and no cached copy exists: {exc}") from exc
            print(f"WARNING: using cached GTFS after download failure: {exc}",file=sys.stderr)
    return CACHE

def load_gtfs(path):
    with ZipFile(path) as z:
        return {name:csv_table(z,name+".txt") for name in
                ("stops","routes","trips","stop_times","calendar_dates")}

def stop_candidates(db,substring,route="6"):
    routes={r["route_id"] for r in db["routes"] if
            r.get("route_short_name","").strip()==route}
    trips={t["trip_id"] for t in db["trips"] if t["route_id"] in routes}
    used={s["stop_id"] for s in db["stop_times"] if
          s["trip_id"] in trips and s.get("pickup_type","0")!="1"}
    return [s for s in db["stops"] if
            substring.casefold() in s.get("stop_name","").casefold() and s["stop_id"] in used]

def stop_events(db,stop_id,route):
    route_info={r["route_id"]:r for r in db["routes"]}
    trips={t["trip_id"]:t for t in db["trips"] if
           route_info.get(t["route_id"],{}).get("route_short_name","").strip()==route}
    enabled={r["service_id"] for r in db["calendar_dates"] if r.get("exception_type")=="1"}
    rows=[]
    for s in db["stop_times"]:
        if s["stop_id"]!=stop_id or s.get("pickup_type","0")=="1":
            continue
        trip=trips.get(s["trip_id"])
        if not trip or trip["service_id"] not in enabled:
            continue
        date=datetime.strptime(trip["service_id"],"%Y%m%d").date()
        hh,mm,ss=map(int,s["departure_time"].split(":"))
        when=datetime.combine(date,datetime.min.time(),NZ)+timedelta(hours=hh,minutes=mm,seconds=ss)
        name=trip.get("trip_headsign","")
        direction=name.split("·")[-1].strip() if "·" in name else name.strip()
        if not direction:direction=route_info[trip["route_id"]].get("route_long_name","")
        rows.append((int(when.timestamp()),direction))
    return sorted(set(rows))

def ascii_safe(s,maxlen):
    import unicodedata
    s=unicodedata.normalize("NFKD",s)
    s="".join(c for c in s if c.isascii() and c not in "|\r\n")
    return s.strip()[:maxlen] or "--"

def make_packet(events,now,stop,route):
    epoch=int(now.timestamp())
    future=[(t,d) for t,d in events if t>epoch-120]
    selected=future[0] if future else (0,"")
    previous=max((t for t,_ in events if t<selected[0]),default=0) if selected[0] else 0
    following=next((t for t,_ in events if t>selected[0]),0) if selected[0] else 0
    next_service=next((t for t,_ in events if t>epoch),0)
    fields=["OTD1",str(epoch),ascii_safe(route,10),
            ascii_safe(selected[1] or "Maunu",30),
            ascii_safe(stop["stop_name"],40),str(selected[0]),"0","SCHED",
            str(previous),str(following),str(next_service)]
    packet="|".join(fields)
    if len(packet.encode("ascii"))>220:
        raise ValueError("Packet exceeds sender limit")
    return packet,selected[0],next_service

def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port",help="USB serial COM port of LoRa sender (COM5)")
    parser.add_argument("--list-stops",metavar="SEARCH",help="Search stops before transmitting")
    parser.add_argument("--stop-id",help="Use exact GTFS stop ID, e.g. 11000262")
    parser.add_argument("--route",default="6")
    parser.add_argument("--interval",type=int,default=60,help="Broadcast seconds, minimum 30")
    parser.add_argument("--force-download",action="store_true")
    parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    db=load_gtfs(fetch_zip(args.force_download))
    if args.list_stops:
        candidates=stop_candidates(db,args.list_stops,args.route)
        print(f"CityLink Route {args.route}, name contains {args.list_stops!r}:")
        for s in candidates:
            print(f"  {s['stop_id']}: {s['stop_name']} ({s.get('stop_lat')}, {s.get('stop_lon')})")
        if not candidates:print("No matches. Try --list-stops maunu.")
        return
    if args.stop_id:
        stop=next((s for s in db["stops"] if s["stop_id"]==args.stop_id),None)
        if not stop:parser.error("Stop ID not found in latest feed")
    else:
        candidates=stop_candidates(db,"museum",args.route)
        if len(candidates)!=1:
            for s in candidates:print(f"Possible Museum stop {s['stop_id']}: {s['stop_name']}")
            parser.error("Use --stop-id after --list-stops museum")
        stop=candidates[0]
    events=stop_events(db,stop["stop_id"],args.route)
    if not events:parser.error(f"No Route {args.route} departures for stop {stop['stop_id']}")
    now=datetime.now(NZ)
    covered_dates={datetime.strptime(r["date"],"%Y%m%d").date() for r in
                   db["calendar_dates"] if r.get("exception_type")=="1"}
    if now.date() not in covered_dates:
        parser.error(f"Feed does not include today ({now.date()}). Last date: {max(covered_dates)}. Refresh snapshot.")
    print(f"Stop: {stop['stop_name']} ({stop['stop_id']}) Route: {args.route}")
    packet,selected,wake=make_packet(events,now,stop,args.route)
    print("Payload:",packet)
    if selected:print("Next timetable departure:",datetime.fromtimestamp(selected,NZ).isoformat())
    if wake:print("Next available service:",datetime.fromtimestamp(wake,NZ).isoformat())
    if args.dry_run:return
    if not args.port:parser.error("Provide --port COMx, or --dry-run")
    if args.interval<30:parser.error("Interval must be >= 30 seconds")
    try:import serial
    except ImportError:parser.error("Install pyserial: py -m pip install pyserial tzdata")
    print("Close sender Arduino Serial Monitor; Ctrl+C to stop.")
    with serial.Serial(args.port,115200,timeout=0.7,write_timeout=4) as dev:
        time.sleep(2)
        while True:
            now=datetime.now(NZ)
            if now.date() not in covered_dates:
                raise RuntimeError("Current service date no longer in cached feed. Restart to refresh.")
            packet,selected,wake=make_packet(events,now,stop,args.route)
            dev.write((packet+"\n").encode("ascii"))
            dev.flush()
            feedback=dev.read_until(b"\n").decode(errors="replace").strip()
            print(f"{now:%Y-%m-%d %H:%M:%S} -> LoRa: {feedback or '(no USB feedback)'}",flush=True)
            time.sleep(args.interval)

if __name__=="__main__":
    main()
