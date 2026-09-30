import io
import sys
import unittest
import urllib.error
from unittest.mock import patch
sys.path.insert(0, 'collector')
import fetch_standard_feeds as feeds

class FeedTests(unittest.TestCase):
    def test_public_zip_does_not_receive_keys(self):
        for provider in feeds.PROVIDERS:
            calls = []
            with patch.dict(feeds.os.environ, {'METLINK':'secret','AUCKLAND_TRANSPORT_PRIMARY':'primary'}, clear=True):
                feeds.fetch(provider, False, lambda req, **kw: (calls.append(req) or io.BytesIO(b'zip')))
            self.assertEqual(calls[0].get_header('X-api-key'), None)
            self.assertEqual(calls[0].get_header('Ocp-apim-subscription-key'), None)
    def test_at_primary_falls_back_on_rejection(self):
        for status in (401, 403):
            calls = []
            def request(req, **kwargs):
                calls.append(req)
                if len(calls) == 1: raise urllib.error.HTTPError(req.full_url, status, '', {}, None)
                return io.BytesIO(b'feed')
            with patch.dict(feeds.os.environ, {'AUCKLAND_TRANSPORT_PRIMARY':'p','AUCKLAND_TRANSPORT_SECONDARY':'s'}, clear=True):
                self.assertEqual(feeds.fetch('auckland', True, request), (b'feed', 'secondary'))
            self.assertEqual([r.get_header('Ocp-apim-subscription-key') for r in calls], ['p','s'])
    def test_metlink_has_its_own_header(self):
        calls=[]
        with patch.dict(feeds.os.environ, {'METLINK':'m'}, clear=True):
            feeds.fetch('metlink', True, lambda req, **kw: (calls.append(req) or io.BytesIO(b'feed')))
        self.assertEqual(calls[0].get_header('X-api-key'), 'm')
        self.assertEqual(calls[0].get_header('Ocp-apim-subscription-key'), None)
    def test_missing_secret_fails_before_request(self):
        with patch.dict(feeds.os.environ, {}, clear=True), self.assertRaisesRegex(RuntimeError, 'missing'):
            feeds.fetch('metlink', True, lambda *a, **k: self.fail('Should not request'))
    def test_authenticated_redirect_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'redirect refused'):
            feeds.NoAuthenticatedRedirect().redirect_request(None,None,302,'',{},'https://other.example')
