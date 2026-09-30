"""Official AT and Metlink feeds, authenticated only inside GitHub Actions."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from fetch_metro import validate_static, validate_live

PROVIDERS = {
    'auckland': {
        'label': 'Auckland Transport',
        'static': 'https://gtfs.at.govt.nz/gtfs.zip',
        'live': 'https://api.at.govt.nz/realtime/legacy/tripupdates',
        'header': 'Ocp-Apim-Subscription-Key',
        'secrets': ['AUCKLAND_TRANSPORT_PRIMARY', 'AUCKLAND_TRANSPORT_SECONDARY'],
    },
    'metlink': {
        'label': 'Greater Wellington Regional Council / Metlink',
        'static': 'https://static.opendata.metlink.org.nz/v1/gtfs/full.zip',
        'live': 'https://api.opendata.metlink.org.nz/v1/gtfs-rt/tripupdates',
        'header': 'x-api-key',
        'secrets': ['METLINK'],
    },
}

class NoAuthenticatedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Authenticated feed redirect refused')


def fetch(provider, live, open_url=None):
    config = PROVIDERS[provider]
    keys = list(dict.fromkeys(os.environ[n].strip() for n in config['secrets'] if os.environ.get(n, '').strip())) if live else [None]
    if not keys:
        raise RuntimeError('Required GitHub Actions secret is missing')
    if open_url is None:
        open_url = urllib.request.build_opener(NoAuthenticatedRedirect()).open if live else urllib.request.urlopen
    url = config['live' if live else 'static']
    limit = (16 if live else 96) * 1024 * 1024
    for index, key in enumerate(keys):
        headers = {'Accept': 'application/x-protobuf' if live else 'application/zip', 'User-Agent': 'open-transit-display/1.0'}
        if key: headers[config['header']] = key
        try:
            with open_url(urllib.request.Request(url, headers=headers), timeout=90) as response:
                payload = response.read(limit + 1)
                if len(payload) > limit: raise RuntimeError('Feed exceeds size limit')
                return payload, ('primary' if index == 0 else 'secondary') if live else 'public'
        except urllib.error.HTTPError as error:
            status = error.code; error.close()
            if status in (401, 403) and index + 1 < len(keys): continue
            raise RuntimeError(f'Provider HTTP {status}; check API subscription') from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError('Provider could not be reached') from None
    raise RuntimeError('Subscription unavailable')


def normalize_live(payload):
    if payload.lstrip().startswith(b'{'):
        from google.protobuf.json_format import ParseDict
        from google.transit import gtfs_realtime_pb2
        data = json.loads(payload)
        # AT's legacy JSON API wraps the standard feed in a response object.
        if 'header' not in data and isinstance(data.get('response'), dict): data = data['response']
        if not isinstance(data.get('header'), dict) or not isinstance(data.get('entity'), list):
            raise RuntimeError('Response is not a GTFS realtime feed')
        feed = gtfs_realtime_pb2.FeedMessage()
        ParseDict(data, feed)
        payload = feed.SerializeToString()
    return payload, validate_live(payload)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--provider', choices=PROVIDERS, required=True)
    parser.add_argument('--static-only', action='store_true')
    args = parser.parse_args(); output = Path('data') / args.provider; output.mkdir(parents=True, exist_ok=True)
    summary = {'provider': args.provider, 'attribution': PROVIDERS[args.provider]['label'],
               'fetched_at_utc': datetime.now(timezone.utc).isoformat(), 'feeds': {}}
    for name, live in [('static', False), ('trip_updates', True)]:
        if args.static_only and live: continue
        try:
            payload, slot = fetch(args.provider, live)
            if live: payload, details = normalize_live(payload)
            else: details = validate_static(payload, expanded_limit=512 * 1024 * 1024)
            (output / ('trip-updates.pb' if live else 'gtfs.zip')).write_bytes(payload)
            summary['feeds'][name] = {'ok': True, 'key_slot': slot, 'bytes': len(payload), **details}
        except Exception as error:
            summary['feeds'][name] = {'ok': False, 'error': str(error) if isinstance(error, RuntimeError) else 'Feed validation failed'}
    (output / 'connection-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if all(f['ok'] for f in summary['feeds'].values()) else 1

if __name__ == '__main__': sys.exit(main())
