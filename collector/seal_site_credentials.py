"""Encrypt each API key for the Site runtime; never write plaintext credentials."""
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

NAMES = ['METRO_LIVE_FEED_PRIMARY', 'METRO_LIVE_FEED_SECONDARY',
         'AUCKLAND_TRANSPORT_PRIMARY', 'AUCKLAND_TRANSPORT_SECONDARY', 'METLINK']

def main():
    settings = json.loads(Path('collector/site-feed-public-key.json').read_text())
    key = serialization.load_der_public_key(base64.b64decode(settings['spki']))
    encrypted = {}
    for name in NAMES:
        value = os.environ.get(name, '').strip()
        if value:
            encrypted[name] = base64.b64encode(key.encrypt(value.encode(), padding.OAEP(
                mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))).decode()
    if not encrypted:
        raise RuntimeError('No repository feed secrets are available')
    target = Path('data/publication'); target.mkdir(parents=True, exist_ok=True)
    (target / 'credentials.enc.json').write_text(json.dumps({
        'algorithm':'RSA-OAEP-256', 'updated_at':datetime.now(timezone.utc).isoformat(), 'keys':encrypted}), encoding='utf-8')
    print('Encrypted feed credentials prepared for the Site runtime.')

if __name__ == '__main__': main()
