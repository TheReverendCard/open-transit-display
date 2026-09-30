import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0,'collector')
from build_derived_gtfs import build
from service_windows import windows,epoch

class DerivedTests(unittest.TestCase):
    def test_same_source_trip_on_two_dates_has_distinct_gtfs_ids(self):
        today=datetime.now(ZoneInfo('Pacific/Auckland')).date()
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);raw=root/'raw';out=root/'out'
            for offset in range(2):
                day=(today+timedelta(days=offset)).strftime('%Y%m%d');folder=raw/day;folder.mkdir(parents=True)
                payload={'date':day,'routeId':'r','routeShortName':'2','routeLongName':'Route', 'directions':[{'id':0,'directionName':'Out',
                  'stops':[{'id':'a','name':'A','location':[174.3,-35.7]},{'id':'b','name':'B','location':[174.31,-35.7]}],
                  'trips':[{'tripId':'t','stopTimes':[None,{'id':'a','time':'08:00:00','sequence':1,'timepoint':True},{'id':'b','time':'08:30:00','sequence':2,'timepoint':True}]}]}]}
                (folder/'r.json').write_text(json.dumps(payload))
            summary=build(raw,out);self.assertEqual(summary['feeds']['static']['trips.txt'],2)
            with zipfile.ZipFile(out/'gtfs.zip') as archive:
                trips=list(csv.DictReader(io.StringIO(archive.read('trips.txt').decode())));self.assertEqual(len({t['trip_id'] for t in trips}),2)
                stops=list(csv.DictReader(io.StringIO(archive.read('stop_times.txt').decode())));self.assertEqual(stops[1]['pickup_type'],'1')
                self.assertIn('derived',archive.read('feed_info.txt').decode())
            w=windows(out/'gtfs.zip');self.assertEqual(w['intervals'][0],[epoch(today,8*3600,ZoneInfo('Pacific/Auckland'))-900,epoch(today,8*3600+1800,ZoneInfo('Pacific/Auckland'))+1800])
    def test_location_only_does_not_generate_departures(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);folder=root/'raw'/'20261001';folder.mkdir(parents=True)
            (folder/'r.json').write_text(json.dumps({'routeId':'r','routeShortName':'2','routeLongName':'Route','directions':[]}))
            with self.assertRaises(ValueError):build(root/'raw',root/'out')
