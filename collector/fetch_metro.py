"""Fetch official Christchurch feeds using GitHub Actions environment secrets."""
import csv
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BASE = 'https://apis.metroinfo.co.nz/rti/'
FEEDS = {'static': ('gtfs/v1/gtfs.zip', 'gtfs.zip', 32 * 1024 * 1024),
         'trip_updates': ('gtfsrt/v1/trip-updates.pb', 'trip-updates.pb', 8 * 1024 * 1024)}


def subscription_keys():
    return list(dict.fromkeys(key.strip() for name in
        ('METRO_LIVE_FEED_PRIMARY', 'METRO_LIVE_FEED_SECONDARY')
        if (key := os.environ.get(name, '')).strip()))


def fetch_feed(path, keys, limit, open_url=urllib.request.urlopen):
    if not keys:
        raise RuntimeError('Metro GitHub Actions secrets are missing')
    for index, key in enumerate(keys):
        request = urllib.request.Request(BASE + path, headers={
            'Ocp-Apim-Subscription-Key': key,
            'User-Agent': 'open-transit-display/1.0'})
        try:
            with open_url(request, timeout=45) as response:
                payload = response.read(limit + 1)
                if len(payload) > limit:
                    raise RuntimeError('Feed exceeds size limit')
                return payload, 'primary' if index == 0 else 'secondary'
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            if status in (401, 403) and index + 1 < len(keys):
                continue
            raise RuntimeError(f'Metro HTTP {status}; check product subscription') from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError('Metro could not be reached') from None
    raise RuntimeError('Metro subscription keys unavailable')


def validate_static(payload, expanded_limit=128 * 1024 * 1024):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        required = {'agency.txt', 'routes.txt', 'stops.txt', 'trips.txt', 'stop_times.txt'}
        if not required <= names or not {'calendar.txt', 'calendar_dates.txt'} & names:
            raise RuntimeError('Incomplete GTFS timetable ZIP')
        if sum(f.file_size for f in archive.infolist()) > expanded_limit:
            raise RuntimeError('Expanded timetable exceeds size limit')
        if archive.testzip():
            raise RuntimeError('GTFS timetable CRC check failed')
        counts = {}
        for table in sorted(required):
            with archive.open(table) as raw:
                counts[table] = sum(1 for _ in csv.DictReader(io.TextIOWrapper(raw, encoding='utf-8-sig')))
        return counts


def validate_live(payload):
    from google.transit import gtfs_realtime_pb2
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(payload)
    if not feed.IsInitialized():
        raise RuntimeError('Invalid GTFS realtime message')
    return {'feed_timestamp': feed.header.timestamp,
            'entities': len(feed.entity),
            'trip_updates': sum(e.HasField('trip_update') for e in feed.entity)}


def main():
    output = Path('data/metro'); output.mkdir(parents=True, exist_ok=True)
    keys = subscription_keys()
    summary = {'fetched_at_utc': datetime.now(timezone.utc).isoformat(),
               'source': BASE, 'attribution': 'Environment Canterbury, CC BY 4.0', 'feeds': {}}
    for name, (path, filename, limit) in FEEDS.items():
        try:
            payload, used = fetch_feed(path, keys, limit)
            details = validate_static(payload) if name == 'static' else validate_live(payload)
            (output / filename).write_bytes(payload)
            summary['feeds'][name] = {'ok': True, 'key_slot': used, 'bytes': len(payload), **details}
        except Exception as error:
            # Do not log request objects, headers, keys, or upstream error bodies.
            message = str(error) if isinstance(error, RuntimeError) else 'Feed validation failed'
            summary['feeds'][name] = {'ok': False, 'error': message}
    (output / 'connection-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if all(f['ok'] for f in summary['feeds'].values()) else 1


if __name__ == '__main__':
    sys.exit(main())
