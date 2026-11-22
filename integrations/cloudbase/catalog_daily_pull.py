"""Read-only CloudBase product candidate snapshot.

Never changes CloudBase, POS SQLite, deployed code or the active publication.
This is a first-stage *candidate export*, not an approved product release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import sys
from datetime import datetime, timezone
from urllib import error, parse, request

TABLES = (
    "bsv_stores",
    "bsv_products",
    "bsv_bundles",
    "bsv_bundle_slots",
    "bsv_price_quotes",
    "bsv_store_availability",
    "bsv_menu_releases",
    "bsv_menu_texts",
)
MAX_ROWS_PER_TABLE = 1000
MAX_BYTES_PER_TABLE = 10 * 1024 * 1024
ENV_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{8,90}$")
CONTENT_RANGE_PATTERN = re.compile(r"^(?:\d+-\d+|\*)/(\d+)$")


class SnapshotError(RuntimeError):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def canonical_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def extract_table(opener, env_id, token, table, timeout=20):
    if table not in TABLES or not ENV_PATTERN.fullmatch(env_id):
        raise SnapshotError("Unapproved CloudBase environment or table")
    endpoint = (
        f"https://{env_id}.api.tcloudbasegateway.com"
        f"/v1/rdb/rest/{table}?"
        + parse.urlencode({"select": "*", "limit": MAX_ROWS_PER_TABLE, "offset": 0})
    )
    req = request.Request(endpoint, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "Prefer": "count=exact",
        "Cache-Control": "no-store",
    }, method="GET")
    try:
        with opener.open(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise SnapshotError(f"{table}: unexpected HTTP status {resp.status}")
            content_range = resp.headers.get("Content-Range", "")
            raw = resp.read(MAX_BYTES_PER_TABLE + 1)
    except error.HTTPError as exc:
        raise SnapshotError(f"{table}: HTTP {exc.code}; check read permissions/RLS") from None
    except (error.URLError, TimeoutError, OSError) as exc:
        raise SnapshotError(f"{table}: CloudBase connection failed ({type(exc).__name__})") from None
    if len(raw) > MAX_BYTES_PER_TABLE:
        raise SnapshotError(f"{table}: response exceeds size cap")
    count_match = CONTENT_RANGE_PATTERN.fullmatch(content_range.strip())
    if not count_match:
        raise SnapshotError(f"{table}: exact record count unavailable; refuse incomplete export")
    count = int(count_match.group(1))
    if count > MAX_ROWS_PER_TABLE:
        raise SnapshotError(f"{table}: {count} rows exceed single-page snapshot cap")
    try:
        rows = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"{table}: malformed JSON ({type(exc).__name__})") from None
    if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows):
        raise SnapshotError(f"{table}: expected a JSON array of objects")
    if len(rows) != count:
        raise SnapshotError(f"{table}: partial page ({len(rows)} of {count})")
    if table == "bsv_products":
        ids = [x.get("product_id") for x in rows]
        if not ids or any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
            raise SnapshotError("bsv_products: missing/duplicate product IDs")
    return rows


def write_private_json(path, payload):
    content = canonical_bytes(payload)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(content).hexdigest()


def build_candidate(env_id, token, output_root, *, opener=None):
    if not token or "\n" in token or "\r" in token:
        raise SnapshotError("Missing or invalid server-side CloudBase credential")
    if not ENV_PATTERN.fullmatch(env_id):
        raise SnapshotError("Invalid CloudBase environment ID")
    output_root = Path(output_root).absolute()
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    mode = output_root.lstat().st_mode
    if not stat.S_ISDIR(mode) or mode & 0o077:
        raise SnapshotError("Snapshot root must be a private non-symlink directory (0700)")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = output_root / f"candidate-{stamp}-{secrets.token_hex(4)}"
    pending = output_root / ("." + target.name + ".pending")
    pending.mkdir(mode=0o700)
    manifest = {
        "schema": "bsv.cloudbase.catalog-candidate.v1",
        "environment_id": env_id,
        "source": "CloudBase PostgreSQL public API",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "consistency": "NON_TRANSACTIONAL_READ_NOT_VERIFIED",
        "status": "CANDIDATE_NOT_APPROVED_NOT_PUBLISHED",
        "tables": {},
    }
    opener = opener or request.build_opener(NoRedirect())
    try:
        for table in TABLES:
            rows = extract_table(opener, env_id, token, table)
            sha = write_private_json(pending / f"{table}.json", rows)
            manifest["tables"][table] = {"rows": len(rows), "sha256": sha}
        manifest["manifest_sha256"] = hashlib.sha256(
            canonical_bytes(manifest)
        ).hexdigest()
        write_private_json(pending / "manifest.json", manifest)
        os.replace(pending, target)
        return target, manifest
    except BaseException:
        shutil.rmtree(pending, ignore_errors=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only candidate export; NO POS publish")
    parser.add_argument("--output-root", required=True,
                        help="Private staging directory; not an active POS database")
    args = parser.parse_args(argv)
    env_id = os.environ.get("BSV_CLOUDBASE_ENV_ID", "")
    token = os.environ.get("BSV_CLOUDBASE_READ_TOKEN", "")
    try:
        target, manifest = build_candidate(env_id, token, args.output_root)
    except SnapshotError as exc:
        print("CANDIDATE_PULL_BLOCKED:", exc, file=sys.stderr)
        return 2
    print(json.dumps({
        "result": manifest["status"],
        "path": str(target),
        "tables": {k: v["rows"] for k, v in manifest["tables"].items()},
        "approval": "REQUIRED",
        "pos_changed": False,
        "cloudbase_write_operations": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
