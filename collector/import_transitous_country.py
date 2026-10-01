"""Publish country-scoped static Transitous snapshots; never poll realtime feeds."""
import argparse, json, re, urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from fetch_metro import validate_static
from fetch_public_feeds import prepare, PROVIDERS

USER_AGENT = 'OpenTransitDisplay/1.0 (+https://github.com/TheReverendCard/open-transit-display)'
MAX_ZIP = 64 * 1024 * 1024

class SourceParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.heading = None; self.text = []; self.name = ''; self.records = {}
    def handle_starttag(self, tag, attrs):
        if tag == 'h4': self.heading = tag; self.text = []
        if tag != 'a': return
        href = dict(attrs).get('href', '')
        match = re.fullmatch(r'https://api\.transitous\.org/gtfs/([A-Za-z0-9_.~-]+)\.gtfs\.zip', href)
        if not match: return
        feed_id = match[1]; country = feed_id[:2].upper()
        if not re.fullmatch('[A-Z]{2}', country): return
        self.records[feed_id] = {'id': feed_id, 'country': country, 'name': self.name or feed_id,
                                'source_url': href, 'attribution_url': 'https://transitous.org/sources/'}
    def handle_data(self, value):
        if self.heading: self.text.append(value)
    def handle_endtag(self, tag):
        if tag == self.heading:
            self.name = ''.join(self.text).strip(); self.heading = None

def download(url, limit=MAX_ZIP):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': USER_AGENT}), timeout=45) as response:
        data = response.read(limit + 1)
    if len(data) > limit: raise ValueError('Feed exceeds publication size limit')
    return data

def catalogue(html):
    parser = SourceParser(); parser.feed(html)
    countries = {}
    for record in parser.records.values(): countries.setdefault(record['country'], []).append(record)
    return {'fetched_at': datetime.now(timezone.utc).isoformat(), 'countries': countries}

def mirror(country, catalog, output, previous=None, max_bytes=256*1024*1024):
    feeds = catalog['countries'].get(country, [])
    old = {}
    if previous and (previous/'index.json').exists():
        old = {r['id']: r for r in json.loads((previous/'index.json').read_text()).get('feeds', [])}
    records = []; budget = max_bytes
    # Fill missing feeds first; subsequent scheduled runs continue partially imported countries.
    def priority(source):
        record = old.get(source['id'], {})
        status = record.get('status', 'pending')
        # Pending sources progress before retries; rotate verified snapshots oldest first.
        return (0 if status == 'pending' else 1 if status == 'ready' else 2,
                record.get('fetched_at', ''), source['id'])
    feeds = sorted(feeds, key=priority)
    for position, source in enumerate(feeds):
        record = dict(source)
        if budget <= 0 or position >= 20:
            records.append(old.get(source['id'], {**record, 'status': 'pending'})); continue
        try:
            payload = download(source['source_url'], min(MAX_ZIP, budget)); budget -= len(payload)
            validate_static(payload)
            provider = source['id']; PROVIDERS[provider] = (source['name'], source['source_url'])
            metadata = prepare(provider, payload, output/'feeds')
            coordinates = metadata['boarding_stops']
            record.update(status='ready', fetched_at=metadata['fetched_at'], sha256=metadata['sha256'], bytes=len(payload),
                          bounds=[min(p[0] for p in coordinates), min(p[1] for p in coordinates), max(p[0] for p in coordinates), max(p[1] for p in coordinates)])
        except Exception as error:
            # Retain a previously verified feed; omit partial output on any validation failure.
            import shutil
            shutil.rmtree(output/'feeds'/source['id'], ignore_errors=True)
            record = old.get(source['id'], {**record, 'status': 'unavailable'})
            print(source['id'], type(error).__name__)
        records.append(record)
    output.mkdir(parents=True, exist_ok=True)
    (output/'index.json').write_text(json.dumps({'country': country, 'updated_at': datetime.now(timezone.utc).isoformat(), 'feeds': records}, separators=(',', ':')))
    return records

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--country'); parser.add_argument('--catalog-only', action='store_true'); parser.add_argument('--output', default='data/publication'); parser.add_argument('--previous'); args = parser.parse_args()
    catalog = catalogue(download('https://transitous.org/sources/', 12*1024*1024).decode())
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    (output/'transitous-source-catalog.json').write_text(json.dumps(catalog, separators=(',', ':')))
    if args.catalog_only: return
    if not args.country or not re.fullmatch('[A-Z]{2}', args.country): raise ValueError('Valid uppercase country code required')
    previous = Path(args.previous)/'countries'/args.country if args.previous else None
    mirror(args.country, catalog, output/'countries'/args.country, previous)

if __name__ == '__main__': main()
