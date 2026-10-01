import base64
import json
import tempfile
import unittest
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from device_service.notices import Authority, DOMAIN, presentation, verify
from device_service.store import Store
from device_service.transit import active, applies, stop_changes


class Notices(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.authorities = {'authority-1': Authority(self.public, frozenset({'emergency'}), frozenset({'stop-A'}))}
        self.p = dict(version=1, key_id='authority-1', id='notice-1', revision=1,
                      kind='emergency', group='stop-A', issued_at=1000, starts_at=1000,
                      expires_at=1600, action='upsert', severity='warning', source='Test authority', text='Test notice')

    def envelope(self, p=None):
        raw = json.dumps(self.p if p is None else p).encode()
        return {'payload': base64.b64encode(raw).decode(),
                'signature': base64.b64encode(self.key.sign(DOMAIN + raw)).decode()}

    def test_valid(self):
        self.assertEqual(verify(self.envelope(), self.authorities, 1000), self.p)

    def test_tamper(self):
        envelope = self.envelope()
        self.p['text'] = 'Attacker text'
        envelope['payload'] = self.envelope()['payload']
        with self.assertRaises(InvalidSignature): verify(envelope, self.authorities, 1000)

    def test_unknown_revoked_and_wrong_key(self):
        for auth in ({}, {'authority-1': Authority(self.public, frozenset({'emergency'}), frozenset({'stop-A'}), revoked=True)},
                     {'authority-1': Authority(bytes(32), frozenset({'emergency'}), frozenset({'stop-A'}))}):
            with self.subTest(auth=bool(auth)), self.assertRaises((ValueError, InvalidSignature)):
                verify(self.envelope(), auth, 1000)

    def test_scope_and_kind(self):
        for field, value in [('group', 'stop-B'), ('kind', 'community')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify(self.envelope(dict(self.p, **{field: value})), self.authorities, 1000)

    def test_validity(self):
        for patch in [{'expires_at': 1000}, {'expires_at': 5000}, {'issued_at': 1100},
                      {'starts_at': 1700}, {'revision': True}, {'version': 2}]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                verify(self.envelope(dict(self.p, **patch)), self.authorities, 1000)

    def test_no_clock(self):
        with self.assertRaises(ValueError): verify(self.envelope(), self.authorities, 0)

    def test_duplicate_keys(self):
        raw = json.dumps(self.p)[:-1].encode() + b', "revision": 2}'
        envelope = {'payload': base64.b64encode(raw).decode(),
                    'signature': base64.b64encode(self.key.sign(DOMAIN + raw)).decode()}
        with self.assertRaises(ValueError): verify(envelope, self.authorities, 1000)

    def test_oversize(self):
        with self.assertRaises(ValueError): verify(self.envelope(dict(self.p, text='X'*5000)), self.authorities, 1000)

    def test_rotation(self):
        self.assertEqual(presentation(self.p, 1000, 301), 'emergency')
        self.assertEqual(presentation(self.p, 1030, 301), 'transit_with_emergency_banner')
        self.assertEqual(presentation(self.p, 1000, 300), 'transit_with_emergency_banner')
        self.assertEqual(presentation(self.p, 1000, 0), 'transit_with_emergency_banner')
        self.assertEqual(presentation(self.p, 1000, None), 'emergency')

    def test_critical_expiry_and_cancel(self):
        self.p['severity'] = 'critical'
        self.assertEqual(presentation(self.p, 1000, 5), 'emergency')
        self.assertEqual(presentation(self.p, 1600, 5), 'transit')
        self.assertEqual(presentation(self.p, 999, 5), 'transit')
        self.assertEqual(presentation(self.p, 1000, 5, False), 'transit')
        self.p['action'] = 'cancel'
        self.assertEqual(presentation(self.p, 1000, 5), 'transit')

    def test_durable_replay_and_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.sqlite3'
            store = Store(path)
            self.assertTrue(store.accept(verify(self.envelope(), self.authorities, 1000)))
            self.assertFalse(store.accept(self.p))
            cancelled = dict(self.p, revision=2, action='cancel')
            self.assertTrue(store.accept(verify(self.envelope(cancelled), self.authorities, 1000)))
            store.db.close()
            restarted = Store(path)
            self.assertFalse(restarted.accept(self.p))
            self.assertEqual(restarted.current(['stop-A'], 1001), [])
            restarted.db.close()

    def test_private_owner_queue(self):
        store = Store(':memory:')
        store.subscribe('alice', 'device-A', 'feed-A', 'stop-1', ['route-1'])
        store.subscribe('bob', 'device-B', 'feed-B', 'stop-1', [])
        with self.assertRaises(PermissionError): store.subscribe('bob', 'device-A', 'feed-A', 'stop-1', [])
        change = {'stop_id': 'stop-1', 'type': 'stop_coordinates_changed'}
        store.queue_change('event-1', 'feed-A', change)
        store.queue_change('event-1', 'feed-A', change)
        self.assertEqual(len(store.inbox('alice')), 1)
        self.assertEqual(store.inbox('bob'), [])


class Transit(unittest.TestCase):
    def test_selectors_and_namespace(self):
        alert = {'informed_entity': [{'route_id': 'R1', 'stop_id': 'S1'}, {'route_id': 'R2'}]}
        self.assertTrue(applies('F1', alert, {'feed_id': 'F1', 'route_id': 'R1', 'stop_id': 'S1'}))
        self.assertFalse(applies('F1', alert, {'feed_id': 'F1', 'route_id': 'R1', 'stop_id': 'S2'}))
        self.assertFalse(applies('F1', alert, {'feed_id': 'F2', 'route_id': 'R2'}))
        self.assertTrue(applies('F1', alert, {'feed_id': 'F1', 'route_id': 'R2'}))

    def test_nested_trip_and_unknown_fields(self):
        context = {'feed_id': 'F', 'trip_id': 'T', 'route_id': 'R', 'start_date': '20261002'}
        self.assertTrue(applies('F', {'informed_entity': [{'trip': {'trip_id': 'T', 'start_date': '20261002'}}]}, context))
        self.assertFalse(applies('F', {'informed_entity': [{'trip': {'trip_id': 'T', 'start_date': '20261003'}}]}, context))
        self.assertFalse(applies('F', {'informed_entity': [{'future_unknown': 'x'}]}, context))
        self.assertFalse(applies('F', {'informed_entity': [{}]}, context))

    def test_active_periods(self):
        self.assertTrue(active({}, 1000))
        self.assertFalse(active({'active_period': [{'start': 10, 'end': 20}]}, 20))
        self.assertTrue(active({'active_period': [{'start': 10, 'end': 20}, {'start': 30}]}, 31))

    def test_snapshot_candidates(self):
        previous = {'A': {'stop_lat': -35, 'stop_lon': 174}, 'B': {'stop_lat': -35, 'stop_lon': 174}}
        current = {'A': {'stop_lat': -35.001, 'stop_lon': 174}}
        with self.assertRaises(ValueError): stop_changes(previous, current)
        changes = stop_changes(previous, current, validated_complete=True)
        self.assertEqual([c['type'] for c in changes], ['stop_coordinates_changed', 'stop_missing'])
        self.assertTrue(all(c['review_required'] for c in changes))
        self.assertEqual(stop_changes(previous, previous, validated_complete=True), [])


if __name__ == '__main__': unittest.main()
