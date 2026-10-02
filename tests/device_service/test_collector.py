import unittest
from google.transit import gtfs_realtime_pb2
from collector.collect_rideguide import alert_to_dict
from device_service.transit import active, applies


class CollectorAlerts(unittest.TestCase):
    def test_preserves_scope_validity_and_effect(self):
        entity = gtfs_realtime_pb2.FeedEntity(id='move-1')
        entity.alert.header_text.translation.add(text='Stop temporarily moved', language='en')
        entity.alert.active_period.add(start=1000, end=2000)
        scope = entity.alert.informed_entity.add(route_id='R1', stop_id='S1')
        scope.trip.trip_id = 'T1'
        entity.alert.effect = gtfs_realtime_pb2.Alert.STOP_MOVED
        result = alert_to_dict(entity, 1000, '2026-10-01T00:00:00Z')
        self.assertEqual(result['effect'], 'STOP_MOVED')
        self.assertEqual(result['active_period'], [{'start': 1000, 'end': 2000}])
        self.assertTrue(active(result, 1500))
        self.assertFalse(active(result, 2000))
        self.assertTrue(applies('F', result, {'feed_id': 'F', 'route_id': 'R1', 'stop_id': 'S1', 'trip_id': 'T1'}))
        self.assertFalse(applies('F', result, {'feed_id': 'F', 'route_id': 'R1', 'stop_id': 'S2', 'trip_id': 'T1'}))


if __name__ == '__main__': unittest.main()
