"""Template: convert date-specific provider timetables into explicitly derived GTFS.

Input: raw/YYYYMMDD/route.json with routeId, directions/stops/trips/stopTimes.
Location-only observations never invent timetable times. Providers without a
published timetable must supply a separately reviewed schedule to this adapter.
"""
import argparse
import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PICKUP={'REGULAR_SCHEDULE':0,'NO_PICKUP':1,'NO_DROPOFF':1,'NOT_AVAILABLE':1,
        'MUST_PHONE_AGENCY':2,'MUST_COORDINATE_WITH_DRIVER':3}

def pickup(value):
    if value in (None,''): return 0
    if str(value) in ('0','1','2','3'): return int(value)
    if value not in PICKUP: raise ValueError('Unknown pickup/drop-off rule')
    return PICKUP[value]

def write_table(archive,name,headers,records):
    text=io.StringIO(newline=''); writer=csv.DictWriter(text,fieldnames=headers);writer.writeheader();writer.writerows(records)
    archive.writestr(name,text.getvalue())

def build(raw,output):
    stops={};routes={};trips={};stop_times=[];dates=set();mapping=[]
    files=sorted(raw.glob('*/*.json'))
    if not files: raise ValueError('No provider timetable payloads')
    for path in files:
        day=path.parent.name; datetime.strptime(day,'%Y%m%d');dates.add(day)
        payload=json.loads(path.read_text());route=str(payload['routeId'])
        if str(payload.get('date',day)).replace('-','')!=day: raise ValueError('Provider timetable date mismatch')
        routes[route]={'route_id':route,'agency_id':'citylink_derived','route_short_name':payload['routeShortName'],
                       'route_long_name':payload['routeLongName'],'route_type':3}
        for direction_index,direction in enumerate(payload.get('directions',[])):
            for stop in direction.get('stops',[]):
                lon,lat=stop['location'];
                if not (-90<=float(lat)<=90 and -180<=float(lon)<=180): raise ValueError('Invalid stop coordinates')
                stops[str(stop['id'])]={'stop_id':str(stop['id']),'stop_code':stop.get('stopCode',stop['id']),
                                       'stop_name':stop['name'],'stop_lat':lat,'stop_lon':lon,'location_type':0}
            for trip in direction.get('trips',[]):
                source_id=str(trip['tripId']);trip_id=f"{route}:{direction['id']}:{source_id}:{day}"
                rows=[row for row in trip.get('stopTimes',[]) if isinstance(row,dict)]
                if len(rows)<2: continue
                if any(not row.get('time') or str(row['id']) not in stops for row in rows): raise ValueError('Trip has incomplete stop times')
                previous=-1; elapsed=-1
                for index,row in enumerate(rows):
                    seq=int(row['sequence']);h,m,s=map(int,row['time'].split(':'));t=h*3600+m*60+s
                    if m>=60 or s>=60 or t<elapsed or seq<=previous: raise ValueError('Trip times or sequence are not ordered; use GTFS times over 24:00 for overnight service')
                    previous=seq;elapsed=t
                    stop_times.append({'trip_id':trip_id,'arrival_time':row['time'],'departure_time':row['time'],
                        'stop_id':str(row['id']),'stop_sequence':seq,'pickup_type':1 if index==len(rows)-1 else pickup(row.get('pickupType')),
                        'drop_off_type':pickup(row.get('dropOffType')),'timepoint':1 if row.get('timepoint') else 0})
                trips[trip_id]={'route_id':route,'service_id':day,'trip_id':trip_id,'trip_headsign':payload['routeLongName']+' · '+direction.get('directionName',''),
                               'direction_id':direction_index%2}
                mapping.append({'trip_id':trip_id,'source_trip_id':source_id,'route_id':route,'start_date':day,
                                'start_time':rows[0]['time'],'end_time':rows[-1]['time']})
    output.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output/'gtfs.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
        write_table(archive,'agency.txt',['agency_id','agency_name','agency_url','agency_timezone'],[{
            'agency_id':'citylink_derived','agency_name':'CityLink, Whangārei (derived feed)','agency_url':'https://www.buslink.co.nz/','agency_timezone':'Pacific/Auckland'}])
        for name,records in [('stops',list(stops.values())),('routes',list(routes.values())),('trips',list(trips.values())),('stop_times',stop_times)]:
            if not records: raise ValueError('No '+name+' records')
            write_table(archive,name+'.txt',list(records[0]),records)
        write_table(archive,'calendar_dates.txt',['service_id','date','exception_type'],[{'service_id':day,'date':day,'exception_type':1} for day in sorted(dates)])
        write_table(archive,'feed_info.txt',['feed_publisher_name','feed_publisher_url','feed_lang','feed_start_date','feed_end_date','feed_version'],[{
            'feed_publisher_name':'Open Transit Display, derived from CityLink / Ride Guide published timetables',
            'feed_publisher_url':'https://github.com/TheReverendCard/open-transit-display','feed_lang':'en','feed_start_date':min(dates),'feed_end_date':max(dates),
            'feed_version':datetime.now(timezone.utc).isoformat()}])
    (output/'trip-map.json').write_text(json.dumps({'derived':True,'trips':mapping},separators=(',',':')))
    summary={'fetched_at_utc':datetime.now(timezone.utc).isoformat(),'attribution':'Derived from CityLink / Ride Guide date-specific published timetables; not an official agency GTFS feed',
             'feeds':{'static':{'ok':True,'routes.txt':len(routes),'stops.txt':len(stops),'trips.txt':len(trips),'stop_times.txt':len(stop_times)}}}
    (output/'connection-summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--output',required=True);a=p.parse_args();build(Path(a.raw),Path(a.output))
