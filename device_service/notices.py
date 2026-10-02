"""Transport-independent signed notices. No network or signing keys in this module."""
import base64
import json
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DOMAIN = b"OTD-NOTICE-V1\x00"
MAX_PAYLOAD = 4096
KINDS = {"transit", "emergency", "community"}


@dataclass(frozen=True)
class Authority:
    public_key: bytes
    kinds: frozenset[str]
    groups: frozenset[str]
    max_lifetime: int = 3600
    revoked: bool = False


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def decode_json(raw):
    return json.loads(raw, object_pairs_hook=_unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def verify(envelope, authorities, now):
    """Verify exact transmitted bytes, then validate authority, scope and freshness.

    Caller must supply a trusted UTC clock and persist accepted revisions before
    rendering. A transport/channel ID is never an authority credential.
    """
    if type(now) is not int or now <= 0:
        raise ValueError("trusted clock required")
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
        raise ValueError("invalid envelope")
    if not isinstance(envelope["payload"], str) or len(envelope["payload"]) > 5500:
        raise ValueError("oversized payload")
    raw = base64.b64decode(envelope["payload"], validate=True)
    if len(raw) > MAX_PAYLOAD:
        raise ValueError("oversized payload")
    if not isinstance(envelope["signature"], str) or len(envelope["signature"]) != 88:
        raise ValueError("invalid signature encoding")
    signature = base64.b64decode(envelope["signature"], validate=True)
    if len(signature) != 64:
        raise ValueError("invalid signature length")
    p = decode_json(raw)
    required = {"version", "key_id", "id", "revision", "kind", "group", "issued_at",
                "starts_at", "expires_at", "action", "severity", "source", "text"}
    if not isinstance(p, dict) or set(p) != required:
        raise ValueError("invalid payload fields")
    for name in ("key_id", "id", "group", "source", "text", "kind", "action", "severity"):
        if not isinstance(p[name], str) or not p[name] or len(p[name]) > (1200 if name == "text" else 160):
            raise ValueError("invalid string field")
        if any(ord(c) < 32 and c != "\n" for c in p[name]):
            raise ValueError("control character")
    authority = authorities.get(p["key_id"])
    if authority is None or authority.revoked:
        raise ValueError("unknown or revoked authority")
    Ed25519PublicKey.from_public_bytes(authority.public_key).verify(signature, DOMAIN + raw)
    for name in ("version", "revision", "issued_at", "starts_at", "expires_at"):
        if type(p[name]) is not int:
            raise ValueError("invalid integer field")
    if p["version"] != 1 or p["revision"] < 1:
        raise ValueError("unsupported version or revision")
    if p["kind"] not in KINDS or p["kind"] not in authority.kinds or p["group"] not in authority.groups:
        raise ValueError("authority outside permitted scope")
    if p["action"] not in {"upsert", "cancel"} or p["severity"] not in {"info", "warning", "critical"}:
        raise ValueError("invalid action or severity")
    if p["kind"] != "emergency" and p["severity"] == "critical":
        raise ValueError("critical takeover requires emergency authority")
    if not (0 < p["issued_at"] <= now + 60 and p["issued_at"] <= p["starts_at"] < p["expires_at"]):
        raise ValueError("invalid validity window")
    if p["expires_at"] <= now or p["expires_at"] - p["issued_at"] > authority.max_lifetime:
        raise ValueError("expired or excessive lifetime")
    return p


def presentation(notice, now, next_departure_seconds=None, emergency_enabled=True):
    """Return a layout decision; all times are seconds, 30-second rotation."""
    if not notice or notice["action"] == "cancel" or not notice["starts_at"] <= now < notice["expires_at"]:
        return "transit"
    if notice["kind"] != "emergency":
        return "transit_with_notice"
    if not emergency_enabled:
        return "transit"
    if notice["severity"] == "critical":
        return "emergency"
    if next_departure_seconds is not None and 0 <= next_departure_seconds <= 300:
        return "transit_with_emergency_banner"
    return "emergency" if ((now - notice["starts_at"]) // 30) % 2 == 0 else "transit_with_emergency_banner"
