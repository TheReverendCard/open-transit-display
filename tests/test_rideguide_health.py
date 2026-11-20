"""Regression coverage for date-specific Ride Guide health checks.

A fresh but empty provider stream on a calendar-defined holiday must not
become an outage. An expired static calendar must not hide a real outage.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from collector import check_rideguide_health as health


class DatedServiceHealthTests(unittest.TestCase):
    def test_labour_day_no_service_but_tuesday_service(self):
        args = type("Args", (), {
            "weekday_start": "05:45", "weekday_end": "19:15",
            "saturday_start": "06:40", "saturday_end": "17:30",
            "sunday_service": False,
        })()
        # Fixture mirrors the exact published feed-data schedule: no
        # Labour Day bus on Mon 26 Oct 2026; service Tue 27 Oct.
        mon = datetime.fromisoformat("2026-10-26T07:24:00+13:00")
        tue = datetime.fromisoformat("2026-10-27T07:24:00+13:00")
        windows = {
            "covered_from": int(mon.timestamp()) - 3600,
            "covered_until": int(tue.timestamp()) + 86400,
            "intervals": [[int(tue.timestamp()) - 3600, int(tue.timestamp()) + 3600]],
        }
        self.assertTrue(health.service_expected(mon, args))  # Old weekly assumption.
        self.assertFalse(health.service_expected(mon, args, windows))
        self.assertTrue(health.service_expected(tue, args, windows))

    def test_missing_static_coverage_is_unknown_not_no_service(self):
        args = type("Args", (), {})()
        dt = datetime.fromisoformat("2026-10-26T07:24:00+13:00")
        t = int(dt.timestamp())
        windows = {"covered_from": t - 86400, "covered_until": t - 1, "intervals": []}
        self.assertIsNone(health.service_expected(dt, args, windows))

    def test_invalid_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "metadata.json"
            for payload in ({}, {"service_windows": {"covered_from": 1,
                              "covered_until": 20, "intervals": [[15, 10]]}}):
                file.write_text(json.dumps(payload))
                with self.assertRaises(ValueError):
                    health.load_service_windows(file)

    def run_health(self, intervals, covered=True):
        now = datetime.now(timezone.utc)
        instant = int(now.timestamp())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = root / "stream.jsonl"
            rows.write_text(json.dumps({
                "kind": "empty_feed",
                "feed_timestamp": instant,
                "received_at": now.isoformat(),
            }) + "\n")
            static = root / "metadata.json"
            static.write_text(json.dumps({"service_windows": {
                "timezone": "Pacific/Auckland",
                "covered_from": instant - 3600 if covered else instant - 7200,
                "covered_until": instant + 3600 if covered else instant - 3600,
                "intervals": intervals,
            }}))
            summary = root / "summary.json"
            cli = ["collector/check_rideguide_health.py",
                   "--input", str(rows),
                   "--service-windows-json", str(static),
                   "--summary-json", str(summary)]
            output = io.StringIO()
            with patch.object(sys, "argv", cli), redirect_stdout(output):
                exit_code = health.main()
            return exit_code, json.loads(summary.read_text())

    def test_fresh_empty_on_no_service_day_is_healthy(self):
        status, summary = self.run_health([])
        self.assertEqual(status, 0)
        self.assertEqual(summary["status"], "healthy")
        self.assertIs(summary["service_expected"], False)
        self.assertEqual(summary["service_calendar_source"], "dated_gtfs")

    def test_fresh_empty_during_real_service_is_unhealthy(self):
        now = int(datetime.now(timezone.utc).timestamp())
        status, summary = self.run_health([[now - 300, now + 300]])
        self.assertEqual(status, 1)
        self.assertIs(summary["service_expected"], True)
        self.assertIn("no useful active vehicle or trip-update stream detected during expected service",
                      summary["failures"])

    def test_expired_calendar_fails_explicitly(self):
        status, summary = self.run_health([], covered=False)
        self.assertEqual(status, 1)
        self.assertIsNone(summary["service_expected"])
        self.assertIn("does not cover", summary["failures"][0])


if __name__ == "__main__":
    unittest.main()
