"""Read-only helpers for the shared BSV ALL data contract registry.

This module intentionally does not create databases or run migrations. It resolves
the centrally-approved PostgreSQL DSN when configured and keeps old module-local
data sources explicit until their domains are migrated and reviewed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "config" / "data-contracts.json"


def load_registry(path: Path = REGISTRY) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("contract_version") != "bsv-data-contracts-v1":
        raise ValueError("unsupported data contract registry version")
    ownership_path = ROOT / data["registry_refs"]["data_ownership"]
    ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
    if not ownership.get("key_owners"):
        raise ValueError("data ownership registry is missing")
    return data


def resolve_database(*, module: str, environ: dict[str, str] | None = None) -> dict:
    """Resolve the intended endpoint without connecting or exposing secrets.

    `BSV_DB_URL` is the only central PostgreSQL setting. Legacy module URLs and
    SQLite paths are returned only as compatibility metadata; they are never
    silently promoted to the central database.
    """
    env = os.environ if environ is None else environ
    registry = load_registry()
    central = str(env.get("BSV_DB_URL", "")).strip()
    if central:
        parsed = urlsplit(central)
        if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg", "postgresql+psycopg2"}:
            raise ValueError("BSV_DB_URL must use a PostgreSQL driver URL")
        if parsed.path.lstrip("/") != registry["database"]["database_name"]:
            raise ValueError("BSV_DB_URL must target the registered database name")
        if not parsed.hostname:
            raise ValueError("BSV_DB_URL host is required")
        return {"kind": "central", "env_name": "BSV_DB_URL", "database": registry["database"]["database_name"],
                "configured": True}

    compatibility = registry["database"]["compatibility"]
    if module == "supply":
        env_name = compatibility["supply_sources_registry"]
        return {"kind": "source-registry", "env_name": env_name,
                "configured": bool(str(env.get(env_name, "")).strip())}
    if module in {"identity", "academy"}:
        source_ref = next(ref for ref in registry["registry_refs"]["module_data_sources"]
                          if ref.endswith("identity-data-sources.json"))
        source_cfg = json.loads((ROOT / source_ref).read_text(encoding="utf-8"))
        env_name = source_cfg["routes"]["A"].get("compatibility_url_env",
                                                  source_cfg["routes"]["A"]["primary_url_env"])
    else:
        env_name = {
            "pos": compatibility["pos_operational_sqlite"],
            "growth": compatibility["growth_database"],
        }.get(module)
    if not env_name:
        raise ValueError("unknown module")
    value = str(env.get(env_name, "")).strip()
    return {"kind": "legacy", "env_name": env_name, "configured": bool(value)}


def semantic_attributes(sheet: str, source_fields: dict, *, path: Path = REGISTRY) -> dict:
    """Project source-header keyed records to registered semantic keys."""
    registry = json.loads(Path(path).read_text(encoding="utf-8"))
    mappings = registry.get("domains", {}).get("catalog", {}).get("stable_fields", {})
    return {
        key: source_fields.get(spec["source_header"])
        for key, spec in mappings.items()
        if spec.get("sheet") == sheet and spec.get("source_header") in source_fields
    }
