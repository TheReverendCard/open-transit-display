"""Fetch public NZ timetable feeds once nightly; no subscription keys or live polling."""
import csv
import hashlib
import io
import json
import math
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from fetch_metro import validate_static
from service_windows import windows, rows

PROVIDERS = {
    'waikato': ('Waikato Regional Council / BUSIT', 'https://wrcscheduledata.blob.core.windows.net/wrcgtfs/busit-nz-public.zip'),
    'bayofplenty': ('Bay of Plenty Regional Council / Baybus', 'https://s3.ap-southeast-2.amazonaws.com/gtfs.dynamis.live/boprc/prod/boprc-nz.zip'),
    'taranaki': ('Taranaki Regional Council / Taranaki Buses', 'https://data.trilliumtransit.com/gtfs/trc-nz/trc-nz.zip'),
    'nelson': ('Nelson City Council and Tasman District Council / eBus', 'https://data.trilliumtransit.com/gtfs/nsn-nz/nsn-nz.zip'),
    'otago': ('Otago Regional Council / Orbus', 'https://www.orc.govt.nz/transit/google_transit.zip'),
}


def prepare(provider, payload, output=Path('data/publication')):
    label, url = PROVIDERS[provider]
    counts = validate_static(payload)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        stops = {r['stop_id']: r for r in rows(archive, 'stops.txt')}
        # Match the browser importer: boardable points, excluding final trip stops.
        times = {}
        for r in rows(archive, 'stop_times.txt'):
            times.setdefault(r['trip_id'], []).append(r)
        boarding = set()
        for trip in times.values():
            trip.sort(key=lambda r: int(r['stop_sequence']))
            boarding.update(r['stop_id'] for r in trip[:-1] if r.get('pickup_type') != '1')
        coordinates = set()
        for stop_id in boarding:
            r = stops.get(stop_id)
            if not r or r.get('location_type', '0') not in ('', '0'): continue
            try: lat, lon = float(r['stop_lat']), float(r['stop_lon'])
            except (ValueError, KeyError): continue
            if math.isfinite(lat) and math.isfinite(lon) and abs(lat) <= 90 and abs(lon) <= 180:
                coordinates.add((lat, lon))
        if not coordinates: raise RuntimeError('No valid boarding points')
    target = output / provider
    target.mkdir(parents=True, exist_ok=True)
    (target / 'gtfs.zip').write_bytes(payload)
    service = windows(target / 'gtfs.zip')
    if not service['intervals']: raise RuntimeError('No scheduled service in the next ten days')
    metadata = {'provider': provider, 'fetched_at': datetime.now(timezone.utc).isoformat(),
                'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload),
                'tables': counts, 'attribution': label, 'source_url': url,
                'service_windows': service, 'boarding_stops': sorted(coordinates)}
    (target / 'metadata.json').write_text(json.dumps(metadata, separators=(',', ':')))
    return metadata


def main():
    for provider, (label, url) in PROVIDERS.items():
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'open-transit-display/1.0', 'Accept': 'application/zip'})
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = response.read(64 * 1024 * 1024 + 1)
            if len(payload) > 64 * 1024 * 1024: raise RuntimeError('Feed exceeds browser size limit')
            result = prepare(provider, payload)
            print(f"Prepared {provider}: {result['bytes']} bytes, {len(result['boarding_stops'])} boarding points.")
        except Exception as error:
            # Do not publish a partial or invalid replacement; keep last valid data branch snapshot.
            import shutil
            shutil.rmtree(Path('data/publication') / provider, ignore_errors=True)
            print(f'Retaining previous {provider} snapshot: {type(error).__name__}: {error}')

if __name__ == '__main__': main()
