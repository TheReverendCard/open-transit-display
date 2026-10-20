"""Offline tests of bounded publication snapshots, with no provider connection."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from google.transit import gtfs_realtime_pb2 as pb
from test_citylink_gtfsrt_bridge import make_static, message, module as bridge_module

SRC = Path(__file__).resolve().parents[1] / "collector" / "publish_citylink_gtfsrt_snapshot.py"
spec = importlib.util.spec_from_file_location("publish_citylink_gtfsrt_snapshot", SRC)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

REVISION = "a" * 40


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_static(self.root)
        self.index = bridge_module.StaticIndex(
            self.root / "gtfs.zip", self.root / "trip-map.json"
        )
        self.bridge = bridge_module.Bridge(self.index)
        self.now = bridge_module.to_epoch("20261016", "08:02:00")

    def tearDown(self):
        self.tmp.cleanup()

    def test_published_protobuf_uses_canonical_static_trip_id(self):
        self.assertTrue(self.bridge.ingest(message(self.now), self.now))
        doc = module.export(self.index, self.bridge, self.root / "out", REVISION, self.now)
        wire = pb.FeedMessage()
        wire.ParseFromString((self.root / "out/citylink/tripupdates.pb").read_bytes())
        self.assertEqual(wire.header.incrementality, pb.FeedHeader.FULL_DATASET)
        self.assertEqual(wire.entity[0].trip_update.trip.trip_id, "1102:0:13:20261016")
        self.assertEqual(doc["static_feed_commit"], REVISION)
        self.assertEqual(doc["feeds"]["tripupdates"]["entities"], 1)
        self.assertEqual(doc["feeds"]["tripupdates"]["source_age_seconds_at_generation"], 0)
        self.assertEqual(doc["max_consumer_age_seconds"], 600)
        self.assertIsNone(doc["publication_started_at_utc"])
        self.assertEqual(
            json.loads((self.root / "out/citylink/manifest.json").read_text())["schema"],
            "otd-citylink-gtfsrt-snapshot-v1"
        )

    def test_stale_prediction_cannot_become_fresh_publication(self):
        self.bridge.ingest(message(self.now), self.now)
        doc = module.export(self.index, self.bridge, self.root / "out", REVISION, self.now + 700)
        wire = pb.FeedMessage()
        wire.ParseFromString((self.root / "out/citylink/tripupdates.pb").read_bytes())
        self.assertEqual(len(wire.entity), 0)
        self.assertEqual(doc["feeds"]["tripupdates"]["entities"], 0)
        self.assertGreater(doc["feeds"]["tripupdates"]["source_age_seconds_at_generation"], 600)
        self.assertIsNone(doc["feeds"]["tripupdates"]["oldest_included_entity_at"])

    def test_valid_empty_feed_is_explicitly_empty_not_fabricated(self):
        doc = module.export(self.index, self.bridge, self.root / "out", REVISION, self.now)
        for name in ("tripupdates", "vehiclepositions", "alerts"):
            wire = pb.FeedMessage()
            wire.ParseFromString((self.root / ("out/citylink/" + name + ".pb")).read_bytes())
            self.assertEqual(wire.header.gtfs_realtime_version, "2.0")
            self.assertEqual(len(wire.entity), 0)
            self.assertEqual(doc["feeds"][name]["entities"], 0)
            self.assertIsNone(doc["feeds"][name]["source_observation_at"])

    def test_static_revision_required_for_publication(self):
        with self.assertRaises(ValueError):
            module.export(self.index, self.bridge, self.root / "out", "unknown", self.now)


if __name__ == "__main__":
    unittest.main()
