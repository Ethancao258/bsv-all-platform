"""Test-only isolated auth, production verified external JWT, revocable server sessions."""
import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
import jwt
from jwt import PyJWKClient
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from domains.workforce.identity.models import AuthSession, IsolatedUser, now
from domains.workforce.identity.core import DomainError, aware

HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=2)
SESSION_SECONDS = 8 * 3600


def hash_opaque(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db, subject):
    opaque = secrets.token_urlsafe(40)
    csrf = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=hash_opaque(opaque), subject=subject,
                       csrf_hash=hash_opaque(csrf), expires_at=now() + timedelta(seconds=SESSION_SECONDS)))
    return opaque, csrf


def validate_session(db, raw):
    if not raw or len(raw) > 180:
        raise DomainError("Sign-in required", 401, "UNAUTHENTICATED")
    session = db.get(AuthSession, hash_opaque(raw))
    if not session or session.revoked_at or aware(session.expires_at) <= now():
        raise DomainError("Session expired or revoked", 401, "UNAUTHENTICATED")
    return session


def verify_csrf(session, incoming):
    if not incoming or not hmac.compare_digest(hash_opaque(incoming), session.csrf_hash):
        raise DomainError("CSRF proof missing or invalid", 403, "CSRF_DENIED")


def create_isolated_user(db, username, password):
    if not re.fullmatch(r"[a-z0-9_.-]{4,60}", username):
        raise DomainError("Invalid test username", 422, "INVALID_USERNAME")
    if len(password) < 14 or len(password) > 128:
        raise DomainError("Use a test password of 14-128 characters", 422, "PASSWORD_POLICY")
    if db.scalar(select(IsolatedUser).where(IsolatedUser.username == username)):
        raise DomainError("Account exists", 409, "ACCOUNT_EXISTS")
    obj = IsolatedUser(subject="isolated:" + secrets.token_hex(16), username=username,
                       password_hash=HASHER.hash(password))
    db.add(obj); db.flush()
    return obj


def login_isolated(db, username, password):
    obj = db.scalar(select(IsolatedUser).where(IsolatedUser.username == username))
    if not obj or obj.disabled_at:
        raise DomainError("Invalid credentials", 401, "INVALID_CREDENTIALS")
    try:
        HASHER.verify(obj.password_hash, password)
    except (VerifyMismatchError, Exception):
        raise DomainError("Invalid credentials", 401, "INVALID_CREDENTIALS")
    return obj.subject


def validate_external_token(token, settings):
    if settings.auth_provider != "cloudbase_jwks":
        raise DomainError("External auth not enabled", 503, "AUTH_NOT_CONFIGURED")
    try:
        client = PyJWKClient(settings.jwks_url, cache_jwk_set=True, lifespan=300)
        key = client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256", "ES256"],
                            issuer=settings.token_issuer, audience=settings.token_audience,
                            options={"require": ["exp", "iat", "sub", "iss", "aud"]}, leeway=30)
        sub = claims.get("sub")
        if not isinstance(sub, str) or len(sub) > 128 or not sub:
            raise ValueError("Invalid subject")
        return "cloudbase:" + sub
    except Exception:
        raise DomainError("Unverified identity provider token", 401, "INVALID_EXTERNAL_TOKEN")


class Throttle:
    """Per-worker isolated test throttle; distributed edge/redis limiter mandatory before production."""
    def __init__(self):
        self.attempts = defaultdict(deque)

    def check(self, key, limit=10, window=60):
        t = time.monotonic()
        d = self.attempts[key]
        while d and d[0] <= t - window:
            d.popleft()
        if len(d) >= limit:
            raise DomainError("Too many requests; retry later", 429, "RATE_LIMITED")
        d.append(t)
