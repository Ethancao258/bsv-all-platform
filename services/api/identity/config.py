"""Sole source-routing configuration. No application module hardcodes a DB URL."""
import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    env: str
    auth_provider: str
    db_a_url: str
    db_b_url: str | None
    source_config: dict
    session_secret: str
    privacy_pepper: str
    cookie_secure: bool
    allowed_host: str
    service_tokens: dict
    jwks_url: str
    token_issuer: str
    token_audience: str
    backup_dir: str
    backup_key_file: str
    allocator_warning_remaining: int
    registration_entities: tuple[str, ...]
    allowed_origins: tuple[str, ...]


def load_settings():
    cfg = json.loads(Path(os.getenv("BSV_DATA_SOURCES_FILE", ROOT / "config/modules/identity-data-sources.json")).read_text(encoding="utf-8"))
    routes = cfg["routes"]
    env = os.getenv("BSV_APP_ENV", "isolated")
    auth = os.getenv("BSV_AUTH_PROVIDER", "isolated")
    if env not in {"isolated", "staging", "production"}:
        raise RuntimeError("Unsupported BSV_APP_ENV")
    if env == "production" and auth != "cloudbase_jwks":
        raise RuntimeError("Production refuses isolated/test authentication")
    if env == "production" and os.getenv("BSV_ALLOW_TEST_AUTH"):
        raise RuntimeError("Production refuses test auth bypass")
    if auth not in {"isolated", "cloudbase_jwks"}:
        raise RuntimeError("Unknown authentication provider")
    a = os.getenv(routes["A"]["primary_url_env"], "sqlite+pysqlite:///./runtime/identity-isolated.db")
    b = os.getenv(routes["B"]["primary_url_env"])
    if env == "production" and not a.startswith("postgresql+psycopg://"):
        raise RuntimeError("Production requires PostgreSQL psycopg primary database A")
    if env == "production" and (not os.getenv("BSV_JWKS_URL") or not os.getenv("BSV_TOKEN_ISSUER") or not os.getenv("BSV_TOKEN_AUDIENCE")):
        raise RuntimeError("Production requires verified CloudBase JWKS issuer and audience configuration")
    if env == "production" and not os.getenv("BSV_COOKIE_SECURE", "1") == "1":
        raise RuntimeError("Production requires secure cookies")
    secret = os.getenv("BSV_SESSION_SECRET", "")
    pepper = os.getenv("BSV_PRIVACY_PEPPER", "")
    if (env != "isolated") and (len(secret) < 32 or len(pepper) < 32):
        raise RuntimeError("Staging/production requires independent high entropy secrets")
    if not secret:
        secret = "ONLY_FOR_ISOLATED_TEST_NOT_FOR_DEPLOYMENT_0123456789"
    if not pepper:
        pepper = "ONLY_FOR_ISOLATED_TEST_PRIVACY_PEPPER_0123456789"
    services = json.loads(os.getenv("BSV_SERVICE_TOKENS_JSON", "{}"))
    reg_entities = tuple(json.loads(os.getenv("BSV_REGISTRATION_ENTITIES_JSON",
                    '["DEMO_LEGAL"]' if env == "isolated" else '[]')))
    if env != "isolated" and not reg_entities:
        raise RuntimeError("Staging/production require authoritative registration legal entities")
    allowed_origins = tuple(json.loads(os.getenv("BSV_ALLOWED_ORIGINS_JSON", "[]")))
    if env == "production" and not allowed_origins:
        raise RuntimeError("Production requires explicit trusted browser origins")
    if env == "production":
        for name, value in services.items():
            if len(value.get("token", "")) < 32 or not value.get("actions"):
                raise RuntimeError(f"Invalid service-scoped credentials: {name}")
    return Settings(
        env=env, auth_provider=auth, db_a_url=a, db_b_url=b, source_config=cfg,
        session_secret=secret, privacy_pepper=pepper,
        cookie_secure=os.getenv("BSV_COOKIE_SECURE", "1" if env != "isolated" else "0") == "1",
        allowed_host=os.getenv("BSV_ALLOWED_HOST", "localhost"), service_tokens=services,
        jwks_url=os.getenv("BSV_JWKS_URL", ""), token_issuer=os.getenv("BSV_TOKEN_ISSUER", ""),
        token_audience=os.getenv("BSV_TOKEN_AUDIENCE", ""),
        backup_dir=os.getenv(routes["LOCAL"]["path_env"], "./runtime/archives"),
        backup_key_file=os.getenv(routes["LOCAL"]["key_file_env"], ""),
        allocator_warning_remaining=int(os.getenv("BSV_ALLOCATOR_WARN_REMAINING", "5000")),
        registration_entities=reg_entities, allowed_origins=allowed_origins,
    )
