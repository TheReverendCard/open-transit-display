"""Stage validated static feeds only; realtime snapshots are not live hosting."""
import hashlib
import json
import shutil
from pathlib import Path
from service_windows import windows
from fetch_public_feeds import agency_previews

for provider, directory in [('metro','metro'),('auckland','auckland'),('metlink','metlink'),('citylink','citylink')]:
    source = Path('data') / directory
    report = source / 'connection-summary.json'
    if not report.exists(): continue
    summary = json.loads(report.read_text())
    if not summary['feeds'].get('static', {}).get('ok'): continue
    target = Path('data/publication') / provider; target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / 'gtfs.zip', target / 'gtfs.zip')
    metadata = {'provider':provider, 'fetched_at':summary['fetched_at_utc'],
                'sha256':hashlib.sha256((target/'gtfs.zip').read_bytes()).hexdigest(),
                'bytes':(target/'gtfs.zip').stat().st_size,
                'tables':summary['feeds']['static'], 'attribution':summary['attribution'],
                'service_windows':windows(target/'gtfs.zip'),
                'agencies':agency_previews((target/'gtfs.zip').read_bytes())}
    if (source/'trip-map.json').exists(): shutil.copyfile(source/'trip-map.json',target/'trip-map.json')
    (target / 'metadata.json').write_text(json.dumps(metadata, indent=2))
    print(f'Prepared validated {provider} timetable snapshot.')
