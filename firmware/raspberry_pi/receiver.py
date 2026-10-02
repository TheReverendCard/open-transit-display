"""Offline signed-envelope verifier and display-plan CLI for Pi/Linux.

Run from repository root: python -m firmware.raspberry_pi.receiver --help
Uses local files only. No HTTP listener or untrusted remote commands.
"""
import argparse
import base64
import json
import os
import time
from pathlib import Path

from device_service.notices import Authority, decode_json, presentation, verify
from device_service.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--envelope', type=Path)
    parser.add_argument('--next-departure-seconds', type=int)
    args = parser.parse_args()
    os.umask(0o077)
    config = decode_json(args.config.read_bytes())
    # The service launcher must establish UTC from an authenticated time source
    # or backed RTC. The flag is a local provisioning assertion, not radio data.
    if config.get('clock_trusted') is not True:
        raise SystemExit('Trusted UTC is not provisioned; retaining transit fallback')
    authorities = {key: Authority(base64.b64decode(a['public_key'], validate=True),
                    frozenset(a['kinds']), frozenset(a['groups']), a.get('max_lifetime', 3600),
                    a.get('revoked', False)) for key, a in config['authorities'].items()}
    args.database.parent.mkdir(parents=True, exist_ok=True)
    store = Store(args.database)
    now = int(time.time())
    if args.envelope:
        if args.envelope.stat().st_size > 8192:
            raise SystemExit('Envelope too large')
        p = verify(decode_json(args.envelope.read_bytes()), authorities, now)
        if p['group'] not in config['groups']:
            raise SystemExit('Notice does not target this display')
        if not store.accept(p):
            raise SystemExit('Duplicate or older revision rejected')
    # Revocation and narrower grants also remove previously accepted notices.
    notices = [p for p in store.current(config['groups'], now)
               if (a := authorities.get(p['key_id'])) and not a.revoked
               and p['kind'] in a.kinds and p['group'] in a.groups]
    emergency_enabled = config.get('emergency_enabled', True)
    if not emergency_enabled:
        notices = [p for p in notices if p['kind'] != 'emergency']
    notices.sort(key=lambda p: (p['kind'] == 'emergency',
                               {'critical': 3, 'warning': 2, 'info': 1}[p['severity']], p['issued_at']), reverse=True)
    p = notices[0] if notices else None
    print(json.dumps({'page': presentation(p, now, args.next_departure_seconds, emergency_enabled),
                      'notice': p, 'evaluated_at': now}, ensure_ascii=False))


if __name__ == '__main__':
    main()
