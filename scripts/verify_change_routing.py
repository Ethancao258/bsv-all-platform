#!/usr/bin/env python3
"""Read-only validation of BSV ALL's machine-readable change-routing index.

This registry is an index for agents; it never connects to databases or deploys code.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config/change-routing.json"
MODULE_ID = re.compile(r"^[a-z][a-z0-9-]*$")
NAMESPACE = re.compile(r"^(identity\.(?:A|B|LOCAL)|supply\.[A-G])$")

def validate(index: dict) -> list[str]:
    errors: list[str] = []
    if index.get("default_environment") != "isolated":
        errors.append("Default environment must be isolated")
    if index.get("control_cli_status") != "ISOLATED_MANUAL_IMPLEMENTED_HOST_NOT_RUN":
        errors.append("Expected manual isolated controller without verified host rollout")
    if index.get("classification") != "CHANGE_ROUTING_INDEX_NOT_RUNTIME_SECRETS":
        errors.append("Unexpected source classification")
    namespaces = index.get("data_source_namespaces", {})
    modules = index.get("modules", [])
    if not isinstance(namespaces, dict) or not isinstance(modules, list):
        return ["Invalid index structure"]
    expected = {f"identity.{x}" for x in ("A", "B", "LOCAL")}
    expected |= {f"supply.{x}" for x in "ABCDEFG"}
    if set(namespaces) != expected:
        errors.append("Datasource namespaces must be exactly identity.A/B/LOCAL and supply.A-G")
    ids: set[str] = set()
    domain_registry = json.loads((ROOT / "config/domain-registry.json").read_text(encoding="utf-8"))
    known_domains = {d["id"] for d in domain_registry["domains"]} | {"platform"}
    frozen = set(json.loads((ROOT / "config/architecture-lock.json").read_text(encoding="utf-8"))["frozen_top_level"])
    for alias, source in namespaces.items():
        if not NAMESPACE.fullmatch(alias):
            errors.append(f"Unqualified or unexpected alias: {alias}")
        filename = source.get("config")
        if not isinstance(filename, str) or not (ROOT / filename).is_file():
            errors.append(f"Missing source registry config: {alias}")
    for module in modules:
        key = module.get("module_id", "")
        if not MODULE_ID.fullmatch(key) or key in ids:
            errors.append(f"Invalid or duplicate module id: {key}")
        ids.add(key)
        if module.get("primary_domain") not in known_domains:
            errors.append(f"Unknown primary domain: {key}")
        if not module.get("code_paths"):
            errors.append(f"Unroutable module: {key}")
        for ref in module.get("code_paths", []) + module.get("test_paths", []):
            if not isinstance(ref, str) or ref.startswith("/") or ".." in Path(ref).parts:
                errors.append(f"Unsafe repository path: {ref}")
            elif ref.split("/", 1)[0] not in frozen or not (ROOT / ref).exists():
                errors.append(f"Unknown code/test path: {ref}")
        for source in module.get("data_sources", []):
            if source not in namespaces:
                errors.append(f"Unknown namespaced datasource for {key}: {source}")
        for unit in module.get("runtime_units", []):
            if not re.fullmatch(r"bsv-all-internal-stage@[a-z-]+\.service", unit):
                errors.append(f"Unknown runtime unit: {unit}")
    if len(modules) < 6:
        errors.append("Too few routable BSV modules")
    if not index.get("never_auto_approve"):
        errors.append("Mandatory high-risk approval exclusions missing")
    return errors

def main() -> int:
    index = json.loads(REGISTRY.read_text(encoding="utf-8"))
    errors = validate(index)
    if errors:
        for error in errors:
            print("CHANGE_ROUTING_ERROR:", error, file=sys.stderr)
        return 1
    print(f"CHANGE_ROUTING_VALID modules={len(index['modules'])} sources={len(index['data_source_namespaces'])}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
