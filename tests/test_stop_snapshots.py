"""Tests for small Wi-Fi stop snapshot export; no external network needed."""
import importlib.util
import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
import zlib

SOURCE=Path(__file__).resolve().parents[1]/"collector"/"build_stop_snapshots.py"
spec=importlib.util.spec_from_file_location("build_stop_snapshots",SOURCE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SnapshotTests(unittest.TestCase):
    def make_zip(self,path,day="20261016"):
        csvs={
            "stops.txt":"stop_id,stop_name\n11000262,Whangarei Museum\nEND,Rose Street Bus Depot (Route 6)\n",
            "routes.txt":"route_id,route_short_name,route_long_name\nr6,6,Maunu\n",
            "trips.txt":f"trip_id,route_id,service_id,trip_headsign\nt1,r6,{day},Maunu clockwise\nt2,r6,{day},Maunu clockwise\n",
            "stop_times.txt":"trip_id,stop_id,stop_sequence,departure_time,pickup_type\nt1,11000262,1,08:15:00,0\nt1,END,2,08:45:00,1\nt2,11000262,1,09:15:00,0\nt2,END,2,09:45:00,1\n",
            "calendar_dates.txt":f"service_id,date,exception_type\n{day},{day},1\n",
        }
        with ZipFile(path,"w") as z:
            for name,value in csvs.items():z.writestr(name,value)

    def test_valid_snapshot_and_crc(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.make_zip(root/"gtfs.zip")
            files=m.generate(root/"gtfs.zip",root/"stops",date(2026,10,16))
            self.assertEqual(files,["11000262/6.json"])
            p=json.loads((root/"stops"/files[0]).read_text())
            self.assertEqual(p["stop_name"],"Whangārei Museum")
            self.assertEqual(p["destination"],"Rose Street / CBD")
            self.assertEqual(p["covered_dates"],["2026-10-16"])
            self.assertEqual(len(p["departures"]),2)
            calc=zlib.crc32(",".join(map(str,p["departures"])).encode()) & 0xffffffff
            self.assertEqual(p["revision"],f"{calc:08X}")

    def test_reject_stale_date(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.make_zip(root/"gtfs.zip")
            with self.assertRaisesRegex(ValueError,"does not cover today"):
                m.generate(root/"gtfs.zip",root/"stops",date(2026,10,17))

if __name__=="__main__":unittest.main()
