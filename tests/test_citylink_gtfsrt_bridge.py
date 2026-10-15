"""Verify CityLink canonical GTFS-RT compatibility and explicit prediction provenance."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from google.transit import gtfs_realtime_pb2 as pb

SOURCE = Path(__file__).resolve().parents[1] / "collector" / "citylink_gtfsrt_bridge.py"
spec = importlib.util.spec_from_file_location("citylink_gtfsrt_bridge", SOURCE)
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def make_static(folder):
    contents = {
        "routes.txt": "route_id,route_short_name,route_type\n1102,6,3\n",
        "stops.txt": "stop_id,stop_name\ns1,Start\ns2,Intermediate\ns3,End\n",
        "trips.txt":
            "route_id,service_id,trip_id,trip_headsign\n"
            "1102,20261016,1102:0:13:20261016,Rose Street\n",
        "calendar_dates.txt": "service_id,date,exception_type\n20261016,20261016,1\n",
        "stop_times.txt":
            "trip_id,stop_id,stop_sequence,arrival_time,departure_time\n"
            "1102:0:13:20261016,s1,1,08:00:00,08:00:00\n"
            "1102:0:13:20261016,s2,2,08:10:00,08:10:00\n"
            "1102:0:13:20261016,s3,3,08:20:00,08:20:00\n",
    }
    with ZipFile(folder/"gtfs.zip", "w") as z:
        for name, text in contents.items():
            z.writestr(name, text)
    (folder/"trip-map.json").write_text(json.dumps({
        "derived": True,
        "trips": [{"source_trip_id":"13","route_id":"1102",
                   "start_date":"20261016",
                   "trip_id":"1102:0:13:20261016"}]
    }))


def message(now, *, vehicle="bus7", source_id="13", add_last=False,
            no_data_at_middle=False, start_date="20261016"):
    feed = pb.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = now
    entity = feed.entity.add()
    entity.id = "test13"
    trip = entity.trip_update
    trip.trip.trip_id = source_id
    trip.trip.route_id = "1102"
    trip.trip.start_date = start_date
    trip.vehicle.id = vehicle
    trip.timestamp = now
    first = trip.stop_time_update.add()
    first.stop_id = "s1"
    first.stop_sequence = 1
    first.departure.time = module.to_epoch("20261016", "08:05:00")
    if no_data_at_middle:
        middle = trip.stop_time_update.add()
        middle.stop_id = "s2"
        middle.stop_sequence = 2
        middle.schedule_relationship = pb.TripUpdate.StopTimeUpdate.NO_DATA
    if add_last:
        last = trip.stop_time_update.add()
        last.stop_id = "s3"
        last.stop_sequence = 3
        last.arrival.time = module.to_epoch("20261016", "08:26:00")
    return feed.SerializeToString()


class CitylinkRealtimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        make_static(root)
        self.index = module.StaticIndex(root/"gtfs.zip", root/"trip-map.json")
        self.bridge = module.Bridge(self.index)
        self.now = module.to_epoch("20261016", "08:02:00")

    def tearDown(self):
        self.tmp.cleanup()

    def test_canonical_trip_id_and_sparse_gtfsrt(self):
        self.assertTrue(self.bridge.ingest(message(self.now), self.now))
        public = pb.FeedMessage()
        public.ParseFromString(self.bridge.protobuf("tripupdates", self.now))
        self.assertEqual(public.header.gtfs_realtime_version, "2.0")
        self.assertEqual(public.entity[0].trip_update.trip.trip_id,
                         "1102:0:13:20261016")
        self.assertEqual(len(public.entity[0].trip_update.stop_time_update), 1)

    def test_standard_delay_propagates_to_intermediate_stop(self):
        self.bridge.ingest(message(self.now), self.now)
        stop = self.bridge.stop_arrivals("s2", now=self.now)
        self.assertEqual(stop["arrivals"][0]["source"], "PROPAGATED")
        self.assertEqual(stop["arrivals"][0]["predicted"],
                         module.to_epoch("20261016", "08:15:00"))

    def test_new_direct_prediction_supersedes_upstream_delay(self):
        self.bridge.ingest(message(self.now, add_last=True), self.now)
        last = self.bridge.stop_arrivals("s3", now=self.now)
        self.assertEqual(last["arrivals"][0]["source"], "LIVE")
        self.assertEqual(last["arrivals"][0]["predicted"],
                         module.to_epoch("20261016", "08:26:00"))

    def test_no_data_blocks_propagation(self):
        self.bridge.ingest(message(self.now, no_data_at_middle=True), self.now)
        middle = self.bridge.stop_arrivals("s2", now=self.now)
        self.assertEqual(middle["arrivals"][0]["source"], "SCHED")
        self.assertEqual(middle["arrivals"][0]["predicted"],
                         module.to_epoch("20261016", "08:10:00"))

    def test_schedule_based_upstream_is_not_live_vehicle_tracking(self):
        self.bridge.ingest(message(self.now, vehicle="schedBasedVehicle1"), self.now)
        middle = self.bridge.stop_arrivals("s2", now=self.now)
        self.assertEqual(middle["arrivals"][0]["source"], "PROPAGATED_ESTIMATE")

    def test_unmatched_trip_id_not_faked(self):
        self.bridge.ingest(message(self.now, source_id="notARealTrip"), self.now)
        self.assertEqual(len(self.bridge.active("tripupdates", self.now)), 0)
        arrivals = self.bridge.stop_arrivals("s2", now=self.now)
        self.assertEqual(arrivals["arrivals"][0]["source"], "SCHED")
        self.assertGreater(self.bridge.unmatched, 0)

    def test_ambiguous_undated_upstream_is_not_assumed(self):
        self.bridge.ingest(message(self.now, start_date=""), self.now)
        self.assertEqual(len(self.bridge.active("tripupdates", self.now)), 0)

    def test_expired_realtime_downgrades_to_timetable(self):
        self.bridge.ingest(message(self.now), self.now)
        self.assertIsNone(self.bridge.protobuf("tripupdates", self.now + 100))
        result = self.bridge.stop_arrivals("s2", now=self.now + 100)
        self.assertEqual(result["arrivals"][0]["source"], "SCHED")
        self.assertFalse(result["realtime_available"])

    def test_upstream_date_mismatch_rejected(self):
        self.bridge.ingest(message(self.now, start_date="20261017"), self.now)
        self.assertEqual(len(self.bridge.active("tripupdates", self.now)), 0)

    def test_full_dataset_replaces_old_trip_update(self):
        self.bridge.ingest(message(self.now), self.now)
        self.bridge.ingest(message(self.now + 1, source_id="UNKNOWN"), self.now + 1)
        self.assertEqual(len(self.bridge.active("tripupdates", self.now + 1)), 0)


if __name__=="__main__":
    unittest.main()
