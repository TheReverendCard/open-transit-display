"""Derive polling windows from actual GTFS trip runs, including service dates and DST."""
import csv
import io
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def rows(archive, name):
    if name not in archive.namelist(): return []
    with archive.open(name) as raw:
        return list(csv.DictReader(io.TextIOWrapper(raw, encoding='utf-8-sig')))


def seconds(value):
    h,m,s = map(int,value.split(':')); return h*3600+m*60+s


def epoch(day, time, zone):
    # GTFS time anchor: local noon minus 12 elapsed hours.
    noon=datetime.combine(day,datetime.min.time().replace(hour=12),tzinfo=zone)
    return int(noon.timestamp())-43200+time


def windows(path, days=10):
    with zipfile.ZipFile(path) as archive:
        agencies=rows(archive,'agency.txt'); zones={a.get('agency_id',''):a['agency_timezone'] for a in agencies}
        if len(set(zones.values())) != 1: raise ValueError('This adapter requires a single network timezone')
        zone=ZoneInfo(agencies[0]['agency_timezone']); today=datetime.now(zone).date()
        trip_services={t['trip_id']:t['service_id'] for t in rows(archive,'trips.txt')}
        spans={}
        for row in rows(archive,'stop_times.txt'):
            t=row.get('departure_time') or row.get('arrival_time')
            if not t: continue
            value=seconds(t); old=spans.get(row['trip_id'],[value,value]);spans[row['trip_id']]=[min(old[0],value),max(old[1],value)]
        frequency=defaultdict(list)
        for row in rows(archive,'frequencies.txt'): frequency[row['trip_id']].append(row)
        dates=defaultdict(set)
        for calendar in rows(archive,'calendar.txt'):
            start=datetime.strptime(calendar['start_date'],'%Y%m%d').date(); end=datetime.strptime(calendar['end_date'],'%Y%m%d').date()
            for offset in range(-1,days):
                day=today+timedelta(days=offset)
                if start<=day<=end and calendar[day.strftime('%A').lower()]=='1': dates[day].add(calendar['service_id'])
        for row in rows(archive,'calendar_dates.txt'):
            day=datetime.strptime(row['date'],'%Y%m%d').date()
            if row['exception_type']=='1': dates[day].add(row['service_id'])
            elif row['exception_type']=='2': dates[day].discard(row['service_id'])
        info=rows(archive,'feed_info.txt')
        covered_end=today+timedelta(days=days-1)
        if info and info[0].get('feed_end_date'): covered_end=min(covered_end,datetime.strptime(info[0]['feed_end_date'],'%Y%m%d').date())
        intervals=[]
        for offset in range(-1,days):
            day=today+timedelta(days=offset)
            for trip,service in trip_services.items():
                if service not in dates[day] or trip not in spans: continue
                start,end=spans[trip]
                periods=[(start,end)]
                if trip in frequency: periods=[(seconds(f['start_time']),seconds(f['end_time'])+end-start) for f in frequency[trip]]
                for start,end in periods:
                    intervals.append([epoch(day,start,zone)-900,epoch(day,end,zone)+1800])
        merged=[]
        for start,end in sorted(intervals):
            if merged and start<=merged[-1][1]: merged[-1][1]=max(merged[-1][1],end)
            else: merged.append([start,end])
        return {'timezone':str(zone),'covered_from':epoch(today,0,zone),'covered_until':epoch(covered_end,86400,zone),
                'lead_seconds':900,'late_grace_seconds':1800,'intervals':merged}
