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
    def change_table(self, path, name, text):
        with ZipFile(path) as z:
            tables = {n: z.read(n) for n in z.namelist()}
        tables[name] = text.encode()
        with ZipFile(path, "w") as z:
            for n, value in tables.items():
                z.writestr(n, value)

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

    def test_capacity_is_reported_without_truncation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.make_zip(root/"gtfs.zip")
            for count in (160, 161):
                text="trip_id,stop_id,stop_sequence,departure_time,pickup_type\n"
                text += "".join(f"t1,11000262,{i+1},08:{i//60:02d}:{i%60:02d},0\n" for i in range(count))
                text += f"t1,END,{count+1},09:00:00,1\n"
                self.change_table(root/"gtfs.zip", "stop_times.txt", text)
                out=root/str(count)
                files=m.generate(root/"gtfs.zip",out,date(2026,10,16))
                index=json.loads((out/"index.json").read_text())
                if count == 160:
                    self.assertEqual(len(files),1)
                    self.assertEqual(len(json.loads((out/files[0]).read_text())["departures"]),160)
                else:
                    self.assertEqual(files,[])
                    self.assertEqual(index["skipped"][0]["entries"],161)
                    self.assertFalse((out/"11000262/6.json").exists())

    def test_reject_gaps_and_generic_calendars(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.make_zip(root/"gtfs.zip")
            self.change_table(root/"gtfs.zip","calendar_dates.txt",
                "service_id,date,exception_type\n20261016,20261016,1\n20261018,20261018,1\n")
            with self.assertRaisesRegex(ValueError,"gaps"):
                m.generate(root/"gtfs.zip",root/"stops",date(2026,10,16))
            self.change_table(root/"gtfs.zip","calendar.txt","service_id\nweekly\n")
            with self.assertRaisesRegex(ValueError,"date-scoped"):
                m.generate(root/"gtfs.zip",root/"stops",date(2026,10,16))

    def test_overnight_time_and_dst_origin(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.make_zip(root/"gtfs.zip",day="20260927")
            self.change_table(root/"gtfs.zip","stop_times.txt",
                "trip_id,stop_id,stop_sequence,departure_time,pickup_type\n"
                "t1,11000262,1,25:15:00,0\nt1,END,2,25:45:00,1\n")
            m.generate(root/"gtfs.zip",root/"stops",date(2026,9,27))
            p=json.loads((root/"stops/11000262/6.json").read_text())
            expected=int(datetime(2026,9,27,12,tzinfo=ZoneInfo("Pacific/Auckland")).timestamp())-43200+25*3600+15*60
            self.assertEqual(p["departures"],[expected])

    def test_metadata_changes_keep_wire_crc_but_change_content_revision(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.make_zip(root/"gtfs.zip")
            m.generate(root/"gtfs.zip",root/"a",date(2026,10,16))
            before=json.loads((root/"a/11000262/6.json").read_text())
            self.change_table(root/"gtfs.zip","stops.txt",
                "stop_id,stop_name\n11000262,Museum\nEND,Other Terminal\n")
            m.generate(root/"gtfs.zip",root/"b",date(2026,10,16))
            after=json.loads((root/"b/11000262/6.json").read_text())
            self.assertEqual(before["revision"],after["revision"])
            self.assertNotEqual(before["content_revision"],after["content_revision"])

    def test_no_boarding_services_produce_explicit_empty_index(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.make_zip(root/"gtfs.zip")
            self.change_table(root/"gtfs.zip","stop_times.txt",
                "trip_id,stop_id,stop_sequence,departure_time,pickup_type\n"
                "t1,11000262,1,08:15:00,1\nt1,END,2,08:45:00,1\n")
            self.assertEqual(m.generate(root/"gtfs.zip",root/"stops",date(2026,10,16)),[])
            self.assertEqual(json.loads((root/"stops/index.json").read_text())["files"],[])

if __name__=="__main__":unittest.main()
