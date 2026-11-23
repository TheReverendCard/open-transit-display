"""Offline unit tests; never contact Ride Guide or publish any feed records."""
import importlib.util
import io
from pathlib import Path
from contextlib import redirect_stdout
from unittest import TestCase
from unittest.mock import patch
import unittest

SCRIPT = Path(__file__).parent / "citylink_monitor.py"
spec = importlib.util.spec_from_file_location("citylink_monitor", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SHA = "a" * 40


class MonitorTest(TestCase):
    def test_outside_service_never_connects(self):
        with patch.object(mod, "static_files", return_value=(SHA, Path("unused.zip"), Path("unused.json"))), \
             patch.object(mod, "windows", return_value={
                "covered_from": 0, "covered_until": 9999999999, "intervals": []}), \
             patch.object(mod, "collect") as collect, redirect_stdout(io.StringIO()) as output:
            result = mod.probe()
        self.assertEqual(result["status"], "skipped_outside_service")
        collect.assert_not_called()
        self.assertIn("CITYLINK_MONITOR=", output.getvalue())

    def test_failure_excludes_exception_details(self):
        with patch.object(mod, "static_files", side_effect=RuntimeError("secret GPS data")), \
             redirect_stdout(io.StringIO()) as output:
            result = mod.probe()
        self.assertEqual(result["status"], "error")
        self.assertNotIn("secret GPS data", output.getvalue())
        self.assertIn('"error_type":"RuntimeError"', output.getvalue())

    def test_active_records_only_aggregate_data(self):
        async def fake_collect(*args, **kwargs):
            return None

        summary = {"generated_at_utc": "2026-10-25T01:00:00+00:00", "feeds": {
            kind: {"entities": n, "source_age_seconds_at_generation": 4,
                   "oldest_entity_age_seconds_at_generation": 9}
            for kind, n in (("tripupdates", 4), ("vehiclepositions", 2), ("alerts", 0))
        }}
        class FakeBridge:
            def __init__(self, index):
                self.index = index
            def status(self):
                return {"counters": {"packets_seen": 3, "decode_errors": 0}}

        with patch.object(mod, "static_files", return_value=(SHA, Path("unused.zip"), Path("unused.json"))), \
             patch.object(mod, "windows", return_value={
                "covered_from": 0, "covered_until": 9999999999,
                "intervals": [[0, 9999999999]]}), \
             patch.object(mod, "StaticIndex", return_value=object()), \
             patch.object(mod, "Bridge", FakeBridge), \
             patch.object(mod, "collect", fake_collect), \
             patch.object(mod, "metadata", return_value=summary), \
             redirect_stdout(io.StringIO()) as output:
            result = mod.probe()
        self.assertEqual(result["status"], "sampled")
        self.assertIn('"tripupdates":4', output.getvalue())
        self.assertNotIn("vehicle_id", output.getvalue())
        self.assertNotIn("latitude", output.getvalue())


if __name__ == "__main__":
    unittest.main()
