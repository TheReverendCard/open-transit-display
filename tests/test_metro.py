import importlib.util
import io
import unittest
import urllib.error
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('metro', 'collector/fetch_metro.py')
metro = importlib.util.module_from_spec(spec); spec.loader.exec_module(metro)

class MetroTests(unittest.TestCase):
    def test_auth_fallback(self):
        for status in (401, 403):
            calls = []
            def request(req, timeout):
                calls.append(req)
                if len(calls) == 1:
                    raise urllib.error.HTTPError(req.full_url, status, 'rejected', {}, None)
                return io.BytesIO(b'feed')
            self.assertEqual(metro.fetch_feed('gtfs/v1/gtfs.zip', ['primary', 'secondary'], 10, request), (b'feed', 'secondary'))
            self.assertEqual([r.get_header('Ocp-apim-subscription-key') for r in calls], ['primary', 'secondary'])
            self.assertTrue(all('primary' not in r.full_url and 'secondary' not in r.full_url for r in calls))
    def test_upstream_failure_is_not_retried(self):
        def request(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 503, 'unavailable', {}, None)
        with self.assertRaisesRegex(RuntimeError, 'HTTP 503'):
            metro.fetch_feed('gtfs/v1/gtfs.zip', ['primary', 'secondary'], 10, request)
    def test_secret_names_and_duplicates(self):
        with patch.dict(metro.os.environ, {'METRO_LIVE_FEED_PRIMARY':' key ', 'METRO_LIVE_FEED_SECONDARY':'key'}, clear=True):
            self.assertEqual(metro.subscription_keys(), ['key'])
    def test_size_limit_and_missing_keys(self):
        with self.assertRaisesRegex(RuntimeError, 'size limit'):
            metro.fetch_feed('gtfs/v1/gtfs.zip', ['key'], 3, lambda *a, **k: io.BytesIO(b'1234'))
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            metro.fetch_feed('gtfs/v1/gtfs.zip', [], 3)
if __name__ == '__main__': unittest.main()
