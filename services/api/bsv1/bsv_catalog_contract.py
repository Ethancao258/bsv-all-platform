"""Semantic catalog projection from the shared data contract registry."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "config" / "data-contracts.json"


@lru_cache(maxsize=1)
def _registry() -> dict:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if data.get("contract_version") != "bsv-data-contracts-v1":
        raise RuntimeError("unsupported data contract registry")
    return data


def semantic_attributes(sheet: str, source_fields: dict) -> dict:
    """Return semantic keys, never Excel coordinates or SQL column offsets."""
    mappings = _registry().get("domains", {}).get("catalog", {}).get("stable_fields", {})
    return {
        semantic_key: source_fields[spec["source_header"]]
        for semantic_key, spec in mappings.items()
        if spec.get("sheet") == sheet
        and isinstance(spec.get("source_header"), str)
        and spec["source_header"] in source_fields
    }


def registry_version() -> str:
    return _registry()["contract_version"]
