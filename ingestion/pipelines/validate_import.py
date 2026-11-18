"""Validate proposed imports against an approved read-only snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
IDENTITY_KEYS = ("product_id", "store_id", "employee_id", "material_id")


def validate(source, mapping, snapshot, owners):
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if mapping["source_sha256"] != digest:
        raise ValueError("Source SHA-256 differs from the proposed mapping")
    if digest in snapshot["imported_source_sha256"]:
        raise ValueError("Source SHA-256 has already been imported")

    seen = set()
    for entry in mapping["identities"]:
        key = entry["key"]
        if key not in IDENTITY_KEYS:
            raise ValueError("Unsupported identity key")
        domain = owners[key]
        external = entry["external_key"]
        canonical = entry["canonical_id"]
        if not isinstance(external, str) or not external.strip():
            raise ValueError("External key is required")
        if not isinstance(canonical, str) or not canonical.strip():
            raise ValueError("Canonical ID is required")
        identity = (key, external)
        if identity in seen:
            raise ValueError(f"Duplicate source identity for {key}")
        seen.add(identity)
        authoritative = snapshot["identity_mappings"][domain][key]
        if authoritative.get(external) != canonical:
            raise ValueError(f"Unknown or conflicting authoritative mapping for {key}")

    return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        owners = json.loads((ROOT / "config/data-ownership.json").read_text())["key_owners"]
        mapping = json.loads(args.mapping.read_text())
        snapshot = json.loads(args.snapshot.read_text())
        digest = validate(args.source, mapping, snapshot, owners)
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
        print(f"REJECTED: {type(exc).__name__}" if not isinstance(exc, ValueError)
              or isinstance(exc, json.JSONDecodeError) else f"REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"PASS (dry run): {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
