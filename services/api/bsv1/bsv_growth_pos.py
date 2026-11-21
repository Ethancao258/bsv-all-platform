"""V4.3 isolated POS/customer proof contract; stdlib, no second customer authority.

Guest/customer service signs a store-scoped 120-second consent proof with LINK_KEY.
The existing POS consumes it once against its current authorized open visit.
A distinct CONTEXT_KEY signs a 90-second *read-only* visit/customer context.
Never interpret either token as payment, eligibility for discount or customer identity issuance.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid

MAX_TOKEN = 900
ID_RE = re.compile(r"[A-Z0-9_-]{3,40}\Z")
VISIT_RE = re.compile(r"[a-zA-Z0-9_-]{3,80}\Z")
NONCE_RE = re.compile(r"[a-zA-Z0-9_-]{16,80}\Z")
_SIG_RE = re.compile(r"[a-f0-9]{64}\Z")


class ProofError(ValueError):
    pass


def _valid_key(key: str) -> bool:
    return isinstance(key, str) and len(key) >= 32 and not key.startswith("REPLACE")


def _pack(payload: dict, key: str) -> str:
    if not _valid_key(key):
        raise ProofError("Signing key unavailable")
    data = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(key.encode("utf-8"), data.encode("ascii"), hashlib.sha256).hexdigest()
    return data + "." + signature


def _unpack(token: str, key: str) -> dict:
    if not _valid_key(key):
        raise ProofError("Signing key unavailable")
    if not isinstance(token, str) or len(token) > MAX_TOKEN or token.count(".") != 1:
        raise ProofError("Bad proof format")
    part, signature = token.split(".", 1)
    if not part or not _SIG_RE.fullmatch(signature):
        raise ProofError("Bad proof signature")
    expected = hmac.new(key.encode("utf-8"), part.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ProofError("Invalid proof signature")
    try:
        data = base64.b64decode(part + "=" * (-len(part) % 4), altchars=b"-_", validate=True)
        body = json.loads(data)
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProofError("Invalid proof contents") from exc
    if not isinstance(body, dict):
        raise ProofError("Invalid proof object")
    return body


def _times(payload: dict, *, ttl: int, current: int | None = None) -> None:
    stamp = int(time.time()) if current is None else current
    iat, exp = payload.get("iat"), payload.get("exp")
    if (type(iat) is not int or type(exp) is not int or iat > stamp + 5
            or iat < stamp - ttl or exp <= stamp or exp - iat > ttl or exp <= iat):
        raise ProofError("Expired or invalid proof time")


def _uuid(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 36:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def make_guest_link(customer_id: str, store_id: str, key: str, *, current: int | None = None) -> str:
    if not _uuid(customer_id) or not ID_RE.fullmatch(store_id):
        raise ProofError("Bad customer or store ID")
    stamp = int(time.time()) if current is None else current
    return _pack({"kind": "guest-pos-link-v1", "customer_id": customer_id, "store_id": store_id,
                  "nonce": secrets.token_urlsafe(20), "iat": stamp, "exp": stamp + 120}, key)


def verify_guest_link(token: str, store_id: str, key: str, *, current: int | None = None) -> dict:
    body = _unpack(token, key)
    if (set(body) != {"kind", "customer_id", "store_id", "nonce", "iat", "exp"}
            or body["kind"] != "guest-pos-link-v1" or body["store_id"] != store_id
            or not _uuid(body["customer_id"]) or not NONCE_RE.fullmatch(body["nonce"])):
        raise ProofError("Guest proof scope invalid")
    _times(body, ttl=120, current=current)
    return body


def make_visit_context(customer_id: str, store_id: str, visit_id: str, key: str, *,
                       current: int | None = None) -> str:
    if not _uuid(customer_id) or not ID_RE.fullmatch(store_id) or not VISIT_RE.fullmatch(visit_id):
        raise ProofError("Bad visit context IDs")
    stamp = int(time.time()) if current is None else current
    return _pack({"customer_id": customer_id, "store_id": store_id, "visit_id": visit_id,
                  "iat": stamp, "exp": stamp + 90}, key)


def nonce_digest(nonce: str) -> str:
    if not NONCE_RE.fullmatch(nonce):
        raise ProofError("Bad nonce")
    return hashlib.sha256(nonce.encode("ascii")).hexdigest()
