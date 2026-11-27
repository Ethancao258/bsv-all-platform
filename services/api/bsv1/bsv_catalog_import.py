"""Isolated-only, transactional importer for a verified WorkBuddy V2.2 package.

This command refuses remote databases. It never touches CloudBase or SQLite.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import hmac
import json
import os
import re
import stat
import time
import uuid
import zipfile
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "platform/lighthouse/bsv1/catalog/isolated_migrations/0001_workbuddy_v22.sql"
PACKAGE_ROWS = {
    "catalog.product": ("catalog_product.jsonl", "product_id", "catalog_product"),
    "catalog.semifinished": ("catalog_semifinished.jsonl", "semifinished_id", "catalog_semifinished"),
    "catalog.material": ("catalog_material.jsonl", "material_id", "catalog_material"),
    "catalog.bundle": ("catalog_bundle.jsonl", "bundle_id", "catalog_bundle"),
    "catalog.bundle_slot": ("catalog_bundle_slot.jsonl", "slot_row_id", "catalog_bundle_slot"),
    "catalog.store_nps": ("catalog_store_nps.jsonl", "nps_row_id", "catalog_store_nps"),
    "catalog.recipe_step": ("catalog_recipe_step.jsonl", "recipe_step_id", "catalog_recipe_step"),
    "catalog.price_quote": ("catalog_price_quote.jsonl", "quote_id", "catalog_price_quote"),
    "core.store": ("core_store.jsonl", "store_id", "core_store"),
}
AUDIT_ROWS = {
    "audit.source_dictionary": ("audit_source_dictionary.jsonl", "dict_row_id", "audit_source_dictionary"),
    "audit.source_legal_path": ("audit_source_legal_path.jsonl", "legal_row_id", "audit_source_legal_path"),
    "audit.source_calc": ("audit_source_calc.jsonl", "calc_row_id", "audit_source_calc"),
}
CANONICAL_ROW_ID = {
    "catalog.product": re.compile(r"C\d{6}"),
    "catalog.semifinished": re.compile(r"P\d{6}"),
    "catalog.material": re.compile(r"M\d{6}"),
    "catalog.bundle": re.compile(r"K\d{6}"),
    "catalog.recipe_step": re.compile(r"R\d{6}"),
    "catalog.price_quote": re.compile(r"Q\d{6}"),
}
REGISTERED_STORES = {"BSVM", "BSVS", "BSVT", "BSVF"}
EXPECTED_CATALOG_RELATIONS = {
    ("catalog", name, kind) for name, kind in (
        ("product", "BASE TABLE"), ("semifinished", "BASE TABLE"),
        ("material", "BASE TABLE"), ("bundle", "BASE TABLE"),
        ("bundle_slot", "BASE TABLE"), ("store_nps", "BASE TABLE"),
        ("recipe_step", "BASE TABLE"), ("price_quote", "BASE TABLE"),
        ("active_content", "BASE TABLE"),
    )
} | {("core", "store", "BASE TABLE")} | {
    ("audit", name, "BASE TABLE") for name in (
        "source_dictionary", "source_legal_path", "source_calc", "excel_formula_index",
        "import_batch", "content_activation_event", "source_mapping", "field_dictionary",
        "source_record",
    )
} | {
    ("audit", name, "VIEW") for name in ("source_record_staff", "source_record_confidential")
} | {("bsv_isolated_migration", "applied", "BASE TABLE")}
EXPECTED_CATALOG_RELATIONS |= {
    # PostgreSQL creates this owned sequence for the BIGSERIAL primary key in
    # 0001_workbuddy_v22.sql. Keep it explicit: ignoring all relkind=S objects
    # would allow unrelated sequences to hide in the catalog database.
    ("audit", "excel_formula_index_formula_id_seq", "SEQUENCE"),
}
EXPECTED_MIGRATIONS = (
    ("0001_workbuddy_v22", MIGRATION),
    ("0002_catalog_reader_least_privilege", MIGRATION.with_name("0002_catalog_reader_least_privilege.sql")),
    ("0003_recipe_order_read", MIGRATION.with_name("0003_recipe_order_read.sql")),
)


def _manifest_counts(manifest: dict) -> dict[str, int]:
    counts = manifest.get("counts", {}).get("counts")
    if not isinstance(counts, dict) or not counts or any(not isinstance(v, int) or v < 0 for v in counts.values()):
        raise ValueError("manifest must provide non-negative integer table counts")
    return counts


def _approval_key() -> bytes:
    path = Path(os.environ.get("BSV_CATALOG_APPROVAL_KEY_FILE", ""))
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise PermissionError("a provisioned BSV_CATALOG_APPROVAL_KEY_FILE is required")
    info = path.stat()
    if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO) or info.st_uid != os.geteuid():
        raise PermissionError("approval key must be owned by the executing account and mode 0600 or stricter")
    key = path.read_bytes()
    if len(key) < 32:
        raise PermissionError("approval key must contain at least 32 random bytes")
    return key


def _approval_payload(approval: dict) -> dict:
    return {k: approval[k] for k in ("approval_id", "action", "archive_sha256", "manifest_sha256", "source_sha256",
                                      "contract_sha256", "expected_active_source_sha256", "approver",
                                      "change_id", "issued_at", "expires_at")}


def create_approval(package: Path, archive: Path, *, approver: str, change_id: str,
                    expected_active_source_sha256: str | None, output: Path, action: str = "import") -> dict:
    manifest, _package_sha, _rows = _verified_package(package, archive)
    manifest_path = package.resolve() / "manifest.json"
    if not re.fullmatch(r"[A-Za-z0-9._@-]{3,128}", approver) or not re.fullmatch(r"[A-Za-z0-9._/-]{3,128}", change_id):
        raise ValueError("approver and change_id must be auditable identifiers")
    authenticated_operator = os.environ.get("SUDO_USER") or getpass.getuser()
    if approver != authenticated_operator:
        raise PermissionError("approver must match the authenticated operating-system account")
    if expected_active_source_sha256 and not re.fullmatch(r"[0-9a-f]{64}", expected_active_source_sha256):
        raise ValueError("expected active source SHA must be a 64-character lowercase SHA256 or empty")
    if action not in {"import", "activate"}:
        raise ValueError("package approval action must be import or activate")
    body = {"approval_id": str(uuid.uuid4()), "action": action, "archive_sha256": sha256(archive.resolve()),
            "manifest_sha256": sha256(manifest_path), "source_sha256": manifest.get("source_sha256"),
            "contract_sha256": sha256(ROOT / "config/data-contracts.json"),
            "expected_active_source_sha256": expected_active_source_sha256,
            "approver": approver, "change_id": change_id,
            "issued_at": int(time.time()), "expires_at": int(time.time()) + 86400}
    body["hmac_sha256"] = hmac.new(_approval_key(), json.dumps(body, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return body


def _verify_approval(path: Path, package: Path, archive: Path, manifest: dict, *, action: str = "import") -> dict:
    if path.is_symlink() or not path.is_file():
        raise PermissionError("approval artifact must be a regular private file")
    info = path.stat()
    if info.st_uid != os.geteuid() or info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise PermissionError("approval artifact must be owned by the executing account and private")
    approval = json.loads(path.read_text(encoding="utf-8"))
    supplied = approval.get("hmac_sha256", "")
    payload = _approval_payload(approval)
    expected = hmac.new(_approval_key(), json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise PermissionError("package approval signature is invalid")
    if approval.get("action") != action:
        raise PermissionError("package approval action does not authorize this operation")
    now = int(time.time())
    if not approval.get("issued_at", 0) <= now <= approval.get("expires_at", 0) or approval["expires_at"] - approval["issued_at"] > 86400:
        raise PermissionError("package approval is expired or has an invalid lifetime")
    if (approval["archive_sha256"] != sha256(archive.resolve())
            or approval["manifest_sha256"] != sha256(package.resolve() / "manifest.json")
            or approval["source_sha256"] != manifest.get("source_sha256")
            or approval["contract_sha256"] != sha256(ROOT / "config/data-contracts.json")):
        raise PermissionError("approval does not bind this package and current data contract")
    return approval


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verified_package(package: Path, archive: Path) -> tuple[dict, str, dict[str, list[dict]]]:
    if package.is_symlink() or archive.is_symlink():
        raise ValueError("package directory and archive must not be symlinks")
    package = package.resolve()
    archive = archive.resolve()
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("package") != "BSV_ALL_Excel标准数据包" or not re.fullmatch(r"V2\.[0-9]+", str(manifest.get("version", ""))):
        raise ValueError("unsupported catalog package identity or major version")
    if (manifest.get("target", {}).get("engine") != "PostgreSQL 17"
            or manifest.get("target", {}).get("database") != "bsv_all_prod (Codex实施)"
            or manifest.get("target", {}).get("schemas") != ["catalog", "core", "audit"]):
        raise ValueError("package target differs from the isolated PostgreSQL 17 contract")
    declared_counts = _manifest_counts(manifest)
    if manifest.get("counts", {}).get("source_sha256") != manifest.get("source_sha256"):
        raise ValueError("manifest source revision declarations disagree")
    declared_files = manifest.get("files")
    if not isinstance(declared_files, dict) or not declared_files:
        raise ValueError("manifest file hash inventory is required")
    actual_files = set()
    for path in package.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"symlinks are not allowed in the package: {path.relative_to(package)}")
        if path.is_file() and path.name != "manifest.json":
            actual_files.add(path.relative_to(package).as_posix())
    normalized_actual_files = set(actual_files)
    expected_original = [name for name in declared_files if name.startswith("original/") and name.endswith(".xlsx")]
    if len(expected_original) == 1 and expected_original[0] not in actual_files:
        candidates = [path for path in (package / "original").glob("*.xlsx") if path.is_file()]
        meta = declared_files[expected_original[0]]
        if len(candidates) == 1 and candidates[0].stat().st_size == meta["bytes"] and sha256(candidates[0]) == meta["sha256"]:
            normalized_actual_files.discard(candidates[0].relative_to(package).as_posix())
            normalized_actual_files.add(expected_original[0])
    if normalized_actual_files != set(declared_files):
        raise ValueError("manifest does not enumerate the exact extracted package file set")
    for relative, meta in declared_files.items():
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError(f"invalid package path: {relative}")
        target = (package / relative).resolve()
        if not target.is_file() and relative in expected_original:
            candidates = [path.resolve() for path in (package / "original").glob("*.xlsx") if path.is_file()]
            if len(candidates) == 1 and candidates[0].stat().st_size == meta["bytes"] and sha256(candidates[0]) == meta["sha256"]:
                target = candidates[0]
        if package not in target.parents or not target.is_file():
            raise ValueError(f"manifest file missing or escapes package: {relative}")
        if target.stat().st_size != meta["bytes"] or sha256(target) != meta["sha256"]:
            raise ValueError(f"manifest hash mismatch: {relative}")
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        if len(names) != len(set(names)) or any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
            raise ValueError("archive contains duplicate or unsafe paths")
        if set(names) != set(declared_files) | {"manifest.json"}:
            raise ValueError("archive file set differs from the extracted manifest inventory")
        for relative, meta in declared_files.items():
            payload = zipped.read(relative)
            if len(payload) != meta["bytes"] or hashlib.sha256(payload).hexdigest() != meta["sha256"]:
                raise ValueError(f"archive content differs from the package manifest: {relative}")
        zipped_manifest = json.loads(zipped.read("manifest.json"))
        if zipped_manifest != manifest:
            raise ValueError("archive manifest differs from the extracted manifest")
    counts: dict[str, list[dict]] = {}
    for table, (filename, _id, count_key) in PACKAGE_ROWS.items():
        if count_key not in declared_counts:
            raise ValueError(f"manifest is missing required row count {count_key}")
        expected = declared_counts[count_key]
        rows = [json.loads(line) for line in (package / "staging" / filename).read_text(encoding="utf-8").splitlines() if line]
        if len(rows) != expected:
            raise ValueError(f"{table}: expected {expected} rows, received {len(rows)}")
        for row in rows:
            if row.get("_source_sha256") != manifest["source_sha256"] or row.get("ingest_status") != "IMPORTED_RAW":
                raise ValueError(f"{table}: source revision or raw status mismatch")
        id_pattern = CANONICAL_ROW_ID.get(table)
        if id_pattern:
            ids = [row.get(_id) for row in rows]
            if any(not isinstance(value, str) or not id_pattern.fullmatch(value) for value in ids) or len(ids) != len(set(ids)):
                raise ValueError(f"{table}: permanent IDs are malformed or duplicated")
        counts[table] = rows
    for table, (filename, _id, count_key) in AUDIT_ROWS.items():
        if count_key not in declared_counts:
            raise ValueError(f"manifest is missing required auxiliary row count {count_key}")
        expected = declared_counts[count_key]
        rows = [json.loads(line) for line in (package / "auxiliary" / filename).read_text(encoding="utf-8").splitlines() if line]
        if len(rows) != expected:
            raise ValueError(f"{table}: expected {expected} rows, received {len(rows)}")
        counts[table] = rows
    store_ids = [row.get("store_id") for row in counts["core.store"]]
    if (any(store_id not in REGISTERED_STORES for store_id in store_ids)
            or len(store_ids) != len(set(store_ids))):
        raise ValueError("package contains an unregistered or duplicate store ID")
    for filename, count_key in (("catalog_bundle_slot.jsonl", "catalog_bundle_slot"), ("catalog_store_nps.jsonl", "catalog_store_nps")):
        if len(counts["catalog." + filename.removeprefix("catalog_").removesuffix(".jsonl")]) != declared_counts[count_key]:
            raise ValueError(f"auxiliary catalog count mismatch: {filename}")
    fields = list(csv.DictReader((package / "field_dictionary.csv").open(encoding="utf-8-sig", newline="")))
    mappings = list(csv.DictReader((package / "source_mapping.csv").open(encoding="utf-8-sig", newline="")))
    formulas = list(csv.DictReader((package / "formula_index.csv").open(encoding="utf-8-sig", newline="")))
    if len(fields) != manifest.get("counts", {}).get("fields") or len({r["semantic_key"] for r in fields}) != len(fields):
        raise ValueError("field dictionary count or semantic key uniqueness mismatch")
    contract = json.loads((ROOT / "config/data-contracts.json").read_text(encoding="utf-8"))
    registered = contract["domains"]["catalog"].get("postgres_field_dictionary", {})
    # Compatible content revisions may change values and row totals, but the
    # semantic-to-physical schema contract must remain exactly registered.
    if len(registered) != len(fields):
        raise ValueError("field dictionary shape differs from the registered semantic contract")
    for field in fields:
        semantic_key = field["semantic_key"]
        expected_field = {"table": field["target_table"], "column": field["column_name"],
                          "source_sheet": field["source_sheet"], "source_column": field["source_col"],
                          "source_header": field["source_header_zh"], "data_type": field["data_type"],
                          "permission_class": field["permission_class"], "null_meaning": field["null_meaning"]}
        if registered.get(semantic_key) != expected_field:
            raise ValueError(f"field dictionary and unified contract differ for {semantic_key}")
    if len(mappings) != manifest.get("counts", {}).get("mappings") or len(formulas) != manifest.get("counts", {}).get("formulas"):
        raise ValueError("source mapping or formula count differs from the package manifest")
    product_ids = {row["product_id"] for row in counts["catalog.product"]}
    semifinished_ids = {row["semifinished_id"] for row in counts["catalog.semifinished"]}
    recipes = counts["catalog.recipe_step"]
    for row in recipes:
        link = row.get("output_link_id")
        valid = product_ids if link and link.startswith("C") else semifinished_ids if link and link.startswith("P") else set()
        if link and link not in valid:
            raise ValueError(f"recipe output ID is unresolved: {row.get('recipe_step_id')}")
    counts["audit.field_dictionary"] = fields
    counts["audit.source_mapping"] = mappings
    counts["audit.excel_formula_index"] = formulas
    raw_fields: dict[tuple[str, str], dict] = {}
    for table, rows in counts.items():
        if table.startswith("audit."):
            continue
        mapping = [f for f in fields if f["target_table"] == table]
        id_column = PACKAGE_ROWS[table][1]
        for row in rows:
            record = {}
            for field in mapping:
                column = field["column_name"]
                if column in row:
                    record[field["source_header_zh"]] = row[column]
            raw_fields[(table, str(row[id_column]))] = record
    counts["audit.source_record"] = [
        {"entity_table": table, "record_id": record_id, "excel_row": next(
            int(row["_excel_row"]) for row in counts[table] if str(row[PACKAGE_ROWS[table][1]]) == record_id),
         "raw_fields": raw}
        for (table, record_id), raw in raw_fields.items()
    ]
    return manifest, sha256(archive), counts


def _safe_dsn(env_name: str = "BSV_CATALOG_ADMIN_DB_URL") -> str:
    from bsv_catalog_live import import_enabled
    if not import_enabled():
        raise PermissionError("explicit catalog environment and approved import capability required")
    dsn = os.environ.get(env_name, "").strip()
    parsed = urlsplit(dsn.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise PermissionError(f"catalog import only permits a loopback PostgreSQL 17 endpoint via {env_name}")
    if parsed.path.lstrip("/") != "bsv_all_prod":
        raise PermissionError("isolated integration database must be named bsv_all_prod")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if set(query) - {"sslmode", "connect_timeout", "application_name"}:
        raise PermissionError("unsupported PostgreSQL connection override")
    if query.get("sslmode", ["disable"]) != ["disable"]:
        raise PermissionError("isolated loopback PostgreSQL transport must use sslmode=disable")
    if not re.search(r"(?:^|&)sslmode=disable(?:&|$)", parsed.query) and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise PermissionError("untrusted database transport refused")
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)


def _connect():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("install services/api/identity/requirements.lock (psycopg 3.2.13)") from exc
    return psycopg.connect(_safe_dsn(), connect_timeout=5)


def _active_source(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT source_sha256 FROM catalog.active_content WHERE singleton_id=1")
        row = cur.fetchone()
    return row[0].strip() if row else None


def _catalog_layout_state(conn) -> tuple[str, set[tuple[str, str, str]]]:
    """Classify the whole non-system database layout before any DDL.

    Only an actually empty database or the exact registered migration shape is
    eligible for an import. User schemas, extra relations and partial migration
    ledgers are preserved and rejected.
    """
    allowed_schemas = {"public", "catalog", "core", "audit", "bsv_isolated_migration"}
    with conn.cursor() as cur:
        cur.execute("""SELECT nspname FROM pg_namespace
                       WHERE nspname NOT IN ('pg_catalog','information_schema')
                         AND nspname NOT LIKE 'pg_toast%'
                         AND nspname NOT LIKE 'pg_temp_%'
                         AND nspname NOT LIKE 'pg_toast_temp_%'""")
        schemas = {row[0] for row in cur.fetchall()}
        cur.execute("""SELECT n.nspname,c.relname,
                              CASE WHEN c.relkind IN ('r','p') THEN 'BASE TABLE'
                                   WHEN c.relkind='v' THEN 'VIEW'
                                   WHEN c.relkind='S' THEN 'SEQUENCE' ELSE c.relkind::text END
                       FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                       WHERE n.nspname NOT IN ('pg_catalog','information_schema')
                         AND n.nspname NOT LIKE 'pg_toast%'
                         AND n.nspname NOT LIKE 'pg_temp_%'
                         AND n.nspname NOT LIKE 'pg_toast_temp_%'
                         AND c.relkind IN ('r','p','v','m','f','S') ORDER BY 1,2""")
        relations = {(row[0], row[1], row[2]) for row in cur.fetchall()}
    unknown_schemas = schemas - allowed_schemas
    if unknown_schemas:
        raise RuntimeError("catalog database contains unregistered schemas; preserve data and stop")
    with conn.cursor() as cur:
        cur.execute("""SELECT
                         (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                          WHERE n.nspname NOT IN ('pg_catalog','information_schema')
                            AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp_%'
                            AND n.nspname NOT LIKE 'pg_toast_temp_%')
                       + (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                          WHERE n.nspname NOT IN ('pg_catalog','information_schema')
                            AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp_%'
                            AND n.nspname NOT LIKE 'pg_toast_temp_%'
                            AND t.typtype IN ('b','d','e','r') AND t.typrelid=0 AND t.typelem=0)""")
        unknown_code_objects = cur.fetchone()[0]
    if not relations:
        if schemas - {"public"} or unknown_code_objects:
            raise RuntimeError("catalog database contains leftover empty schemas; refusing to treat it as fresh")
        return "EMPTY", relations
    if relations != EXPECTED_CATALOG_RELATIONS:
        raise RuntimeError("catalog database relations are partial or unregistered; preserve data and stop")
    with conn.cursor() as cur:
        cur.execute("""SELECT seq_ns.nspname, seq.relname, dep.deptype,
                              table_ns.nspname, table_rel.relname, column_info.attname
                       FROM pg_class seq
                       JOIN pg_namespace seq_ns ON seq_ns.oid=seq.relnamespace
                       JOIN pg_depend dep ON dep.classid='pg_class'::regclass AND dep.objid=seq.oid
                       JOIN pg_class table_rel ON table_rel.oid=dep.refobjid
                       JOIN pg_namespace table_ns ON table_ns.oid=table_rel.relnamespace
                       JOIN pg_attribute column_info ON column_info.attrelid=table_rel.oid
                                                    AND column_info.attnum=dep.refobjsubid
                       WHERE seq.relkind='S' AND seq_ns.nspname='audit'
                         AND seq.relname='excel_formula_index_formula_id_seq'
                         AND dep.deptype='a'""")
        sequence_ownership = cur.fetchall()
    if sequence_ownership != [(
        "audit", "excel_formula_index_formula_id_seq", "a",
        "audit", "excel_formula_index", "formula_id",
    )]:
        raise RuntimeError("registered catalog sequence is not owned by the expected BIGSERIAL column")
    if unknown_code_objects:
        raise RuntimeError("catalog database contains unregistered callable/type objects; preserve data and stop")
    with conn.cursor() as cur:
        cur.execute("SELECT version,checksum FROM bsv_isolated_migration.applied ORDER BY version")
        applied = {row[0]: row[1].strip() for row in cur.fetchall()}
    expected = {version: hashlib.sha256(path.read_bytes()).hexdigest() for version, path in EXPECTED_MIGRATIONS}
    if applied != expected:
        raise RuntimeError("catalog migration ledger is incomplete or differs from the registered SQL; preserve data and stop")
    return "MANAGED_SCHEMA", relations


def migrate(conn) -> str:
    layout_state, _relations = _catalog_layout_state(conn)
    if layout_state == "EMPTY":
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA bsv_isolated_migration")
            cur.execute("""CREATE TABLE bsv_isolated_migration.applied (
                         version TEXT PRIMARY KEY, checksum CHAR(64) NOT NULL,
                         applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.commit()
    states = []
    for version, path in EXPECTED_MIGRATIONS:
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        with conn.cursor() as cur:
            cur.execute("SELECT checksum FROM bsv_isolated_migration.applied WHERE version=%s", (version,))
            existing = cur.fetchone()
        # End the read transaction before entering the per-migration transaction.
        # With psycopg's default autocommit=False, otherwise conn.transaction() is
        # only a savepoint; callers closing the connection would roll back DDL and
        # the migration ledger even though this function returned successfully.
        conn.commit()
        if existing:
            if existing[0].strip() != checksum:
                raise RuntimeError(f"applied migration {version} checksum differs; refusing to alter prior schema")
            states.append("ALREADY_APPLIED")
            continue
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(sql, prepare=False)
                cur.execute("INSERT INTO bsv_isolated_migration.applied(version,checksum) VALUES (%s,%s)",
                            (version, checksum))
        states.append("APPLIED")
    return "+".join(states)


def _columns(conn, table: str) -> dict[str, str]:
    schema, name = table.split(".")
    with conn.cursor() as cur:
        cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                       WHERE table_schema=%s AND table_name=%s""", (schema, name))
        return {row[0]: row[1] for row in cur.fetchall()}


def _typed_row(row: dict, columns: dict[str, str], table: str) -> dict:
    result = {}
    for key, value in row.items():
        if key not in columns:
            raise ValueError(f"unexpected source field {table}.{key}")
        dtype = columns[key]
        if dtype == "jsonb":
            if not hasattr(value, "obj"):
                from psycopg.types.json import Jsonb
                value = Jsonb(value)
            result[key] = value
        elif value in (None, "") and dtype not in {"text", "character varying", "character"}:
            result[key] = None
        elif value is None:
            result[key] = None
        elif dtype in {"integer", "smallint", "bigint"}:
            result[key] = int(value)
        elif dtype in {"numeric", "double precision", "real"}:
            result[key] = Decimal(str(value))
        elif dtype == "boolean":
            normalized = str(value).strip().lower()
            if normalized not in {"true", "false", "t", "f", "1", "0", "yes", "no"}:
                raise ValueError(f"invalid boolean for {table}.{key}")
            result[key] = normalized in {"true", "t", "1", "yes"}
        else:
            result[key] = str(value)
    return result


def _insert_rows(conn, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    from psycopg import sql
    from psycopg.types.json import Jsonb
    columns = _columns(conn, table)
    for source in rows:
        row = dict(source)
        if table in {"audit.source_mapping", "audit.field_dictionary", "audit.source_record"} and not row.get("source_sha256"):
            raise ValueError(f"{table} is missing the source revision")
        if table == "catalog.recipe_step":
            target = row.get("output_link_id")
            row["output_product_id"] = target if isinstance(target, str) and target.startswith("C") else None
            row["output_semifinished_id"] = target if isinstance(target, str) and target.startswith("P") else None
        if table == "audit.source_record":
            row["raw_fields"] = Jsonb(row["raw_fields"])
        typed = _typed_row(row, columns, table)
        names = tuple(typed)
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(*table.split(".")),
            sql.SQL(",").join(map(sql.Identifier, names)),
            sql.SQL(",").join(sql.Placeholder() for _ in names),
        )
        with conn.cursor() as cur:
            cur.execute(query, tuple(typed[name] for name in names))


def import_package(package: Path, archive: Path, approval_file: Path) -> dict:
    manifest, package_sha, rows = _verified_package(package, archive)
    approval = _verify_approval(approval_file, package, archive, manifest)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('server_version_num')::integer")
            server_version = cur.fetchone()[0]
        if server_version // 10000 != 17:
            raise RuntimeError(f"PostgreSQL 17 required; connected server version number={server_version}")
        with conn.cursor() as cur:
            cur.execute("""SELECT EXISTS (SELECT 1 FROM information_schema.tables
                           WHERE table_schema='catalog' AND table_name='active_content')""")
            has_active_table = cur.fetchone()[0]
            if has_active_table:
                cur.execute("SELECT source_sha256 FROM catalog.active_content WHERE singleton_id=1")
                active_before_migration_row = cur.fetchone()
                active_before_migration = active_before_migration_row[0].strip() if active_before_migration_row else None
            else:
                active_before_migration = None
        if active_before_migration != approval["expected_active_source_sha256"]:
            raise RuntimeError("active content differs from the package approval; request a new approval")
        from bsv_catalog_live import live_enabled,require_live_layout,reject_pending_sale
        if live_enabled():
            migration_state=require_live_layout(conn)
            reject_pending_sale(conn)
            conn.commit()
        else:
            migration_state = migrate(conn)
        sha = manifest["source_sha256"]
        with conn.cursor() as cur:
            cur.execute("SELECT batch_id, status FROM audit.import_batch WHERE source_sha256=%s", (sha,))
            prior = cur.fetchone()
        if prior:
            if prior[1] != "COMMITTED_RAW":
                raise RuntimeError("existing import is incomplete; no automatic repair attempted")
            with conn.cursor() as cur:
                cur.execute("SELECT counts FROM audit.import_batch WHERE source_sha256=%s", (sha,))
                stored = cur.fetchone()[0]
            if query_counts(conn, sha, expected_sql_counts(manifest)) != expected_sql_counts(manifest):
                raise RuntimeError("repeat import count verification failed")
            return {"status": "IDEMPOTENT_NOOP", "source_sha256": sha,
                    "batch_id": str(prior[0]), "migration": migration_state, "counts": stored}
        # Close the preceding SELECT transaction: the import must be a top-level
        # transaction, not a savepoint that is rolled back on connection close.
        conn.commit()
        batch_id = uuid.uuid4()
        record_counts = {table: len(value) for table, value in rows.items()}
        record_counts["catalog.main_records"] = sum(record_counts[t] for t in PACKAGE_ROWS)
        with conn.transaction():
            from psycopg.types.json import Jsonb
            with conn.cursor() as cur:
                cur.execute("LOCK TABLE catalog.active_content IN EXCLUSIVE MODE")
                reject_pending_sale(conn)
                cur.execute("SELECT source_sha256 FROM catalog.active_content WHERE singleton_id=1")
                active_row = cur.fetchone()
                active_source = active_row[0].strip() if active_row else None
                if active_source != approval["expected_active_source_sha256"]:
                    raise RuntimeError("active content changed after package approval; request a new approval")
                cur.execute("SELECT 1 FROM audit.import_batch WHERE source_sha256=%s", (sha,))
                if cur.fetchone():
                    raise RuntimeError("source imported concurrently; inspect existing revision")
                cur.execute("""INSERT INTO audit.import_batch(
                    batch_id,source_sha256,package_sha256,package_version,status,counts,approval_id,approver,
                    change_id,manifest_sha256,contract_sha256,expected_active_source_sha256,approval_hmac_sha256)
                    VALUES (%s,%s,%s,%s,'COMMITTED_RAW',%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (batch_id, sha, package_sha, manifest["version"], Jsonb(record_counts), approval["approval_id"],
                     approval["approver"], approval["change_id"], approval["manifest_sha256"],
                     approval["contract_sha256"], approval["expected_active_source_sha256"], approval["hmac_sha256"]))
            # Parent rows precede all same-revision foreign key dependants.
            order = ["core.store", "catalog.product", "catalog.semifinished", "catalog.material", "catalog.bundle",
                     "catalog.bundle_slot", "catalog.store_nps", "catalog.recipe_step", "catalog.price_quote",
                     "audit.source_dictionary", "audit.source_legal_path", "audit.source_calc"]
            for table in order:
                _insert_rows(conn, table, rows[table])
            for table in ("audit.source_mapping", "audit.field_dictionary", "audit.source_record"):
                mapped = rows[table]
                if table in {"audit.source_mapping", "audit.field_dictionary"}:
                    generated = "mapping_row" if table == "audit.source_mapping" else "dictionary_row"
                    mapped = [dict(row, source_sha256=sha, **{generated: i})
                              for i, row in enumerate(mapped, 1)]
                elif table == "audit.source_record":
                    mapped = [dict(row, source_sha256=sha) for row in mapped]
                _insert_rows(conn, table, mapped)
            _insert_formula_rows(conn, rows["audit.excel_formula_index"], sha)
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE(MAX(content_revision),0)+1 FROM catalog.active_content")
                revision = cur.fetchone()[0]
                cur.execute("""INSERT INTO catalog.active_content(singleton_id,source_sha256,content_revision,activation_status)
                               VALUES (1,%s,%s,'IMPORTED_RAW') ON CONFLICT(singleton_id) DO UPDATE
                               SET source_sha256=EXCLUDED.source_sha256, content_revision=EXCLUDED.content_revision,
                                   activated_at=now(), activation_status='IMPORTED_RAW'""", (sha, revision))
                cur.execute("""INSERT INTO audit.content_activation_event
                    (event_id,source_sha256,prior_source_sha256,content_revision,operation,approval_id,approver,change_id,approval_hmac_sha256)
                    VALUES (%s,%s,%s,%s,'IMPORT_RAW',%s,%s,%s,%s)""",
                    (uuid.uuid4(), sha, active_source, revision, approval["approval_id"], approval["approver"],
                     approval["change_id"], approval["hmac_sha256"]))
            actual = query_counts(conn, sha, expected_sql_counts(manifest))
            expected = expected_sql_counts(manifest)
            if actual != expected:
                raise RuntimeError(f"PostgreSQL count validation failed: expected={expected}, actual={actual}")
        return {"status": "COMMITTED_RAW", "source_sha256": sha, "package_sha256": package_sha,
                "batch_id": str(batch_id), "migration": migration_state,
                "counts": query_counts(conn, sha, expected_sql_counts(manifest))}
    finally:
        conn.close()


def _insert_formula_rows(conn, rows: list[dict], source_sha: str) -> None:
    from psycopg import sql
    columns = _columns(conn, "audit.excel_formula_index")
    for item in rows:
        row = {"source_sha256": source_sha, "sheet_code": item["sheet_code"],
               "cell_address": item["cell_address"], "col_letter": item.get("col_letter") or None,
               "row_num": int(item["row_num"]) if item.get("row_num") else None,
               "source_region": item.get("source_region") or None, "header_zh": item.get("header_zh") or None,
               "formula_text": item["formula_text"], "is_array": str(item["is_array"]).lower() == "true",
               "array_ref": item.get("array_ref") or None, "cached_value": item.get("cached_value") or None,
               "cached_type": item.get("cached_type") or None}
        names = tuple(row)
        query = sql.SQL("INSERT INTO audit.excel_formula_index ({}) VALUES ({})").format(
            sql.SQL(",").join(map(sql.Identifier, names)), sql.SQL(",").join(sql.Placeholder() for _ in names))
        with conn.cursor() as cur:
            cur.execute(query, tuple(row[name] for name in names))


def expected_sql_counts(manifest: dict) -> dict[str, int]:
    declared = _manifest_counts(manifest)
    result = {table: declared[key] for table, (_file, _id, key) in PACKAGE_ROWS.items()}
    result.update({table: declared[key] for table, (_file, _id, key) in AUDIT_ROWS.items()})
    result.update({"audit.source_mapping": manifest["counts"]["mappings"],
                   "audit.field_dictionary": manifest["counts"]["fields"],
                   "audit.excel_formula_index": manifest["counts"]["formulas"],
                   "audit.source_record": sum(declared[key] for _table, (_file, _id, key) in PACKAGE_ROWS.items())})
    return result


def query_counts(conn, source_sha: str, expected: dict[str, int]) -> dict[str, int]:
    actual = {}
    with conn.cursor() as cur:
        for table in expected:
            schema, name = table.split(".")
            column = "source_sha256" if table in {"audit.source_mapping", "audit.field_dictionary", "audit.source_record", "audit.excel_formula_index"} else "_source_sha256"
            cur.execute("SELECT count(*) FROM " + schema + "." + name + " WHERE " + column + "=%s", (source_sha,))
            actual[table] = cur.fetchone()[0]
    return actual


def inspect_existing_import(package: Path, archive: Path, approvals_dir: Path) -> dict:
    """Read-only gate for resuming a deployment after its software was rolled back.

    A retry is permitted only when the *active* database revision is the exact
    same package, its COMMITTED_RAW audit row and original HMAC approval agree,
    and every table count still matches the package manifest.  Nothing is
    repaired, deleted, re-imported, or activated here.
    """
    manifest, package_sha, _rows = _verified_package(package, archive)
    source_sha = manifest["source_sha256"]
    expected_counts = expected_sql_counts(manifest)
    if approvals_dir.is_symlink() or not approvals_dir.is_dir():
        raise PermissionError("private approval evidence directory is missing or unsafe")
    conn = _connect()
    try:
        # This path is an audit gate only; make accidental writes impossible
        # even if the implementation is extended later.
        conn.execute("SET TRANSACTION READ ONLY")
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('server_version_num')::integer")
            if cur.fetchone()[0] // 10000 != 17:
                raise RuntimeError("PostgreSQL 17 required for retry audit")
        layout_state, relations = _catalog_layout_state(conn)
        if layout_state == "EMPTY":
            return {"status": "FRESH", "source_sha256": source_sha,
                    "package_sha256": package_sha, "counts": expected_counts}
        tables = {(schema, name) for schema, name, kind in relations if kind == "BASE TABLE"}
        required = {("catalog", "active_content"), ("audit", "import_batch"),
                    ("audit", "content_activation_event")}
        if not required <= tables:
            raise RuntimeError("catalog schema is partial or not the registered migration; refusing retry")
        with conn.cursor() as cur:
            cur.execute("SELECT source_sha256,content_revision,activation_status "
                        "FROM catalog.active_content WHERE singleton_id=1")
            active = cur.fetchone()
            cur.execute("""SELECT batch_id::text,status,package_sha256,package_version,counts,
                                  approval_id::text,approver,change_id,manifest_sha256,contract_sha256,
                                  expected_active_source_sha256,approval_hmac_sha256
                           FROM audit.import_batch WHERE source_sha256=%s""", (source_sha,))
            batches = cur.fetchall()
        active_sha = active[0].strip() if active else None
        if not batches and active is None:
            # A database with an empty, fully applied schema is a safe first
            # import. Any leftover rows or an unrelated batch make it unknown.
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM audit.import_batch")
                if cur.fetchone()[0] != 0:
                    raise RuntimeError("catalog has unrelated import history without an active pointer; refusing retry")
            for schema, name in sorted(tables):
                if (schema, name) in {
                    ("audit", "import_batch"),
                    ("bsv_isolated_migration", "applied"),
                }:
                    continue
                from psycopg import sql
                with conn.cursor() as cur:
                    cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
                        sql.Identifier(schema), sql.Identifier(name)))
                    if cur.fetchone()[0] != 0:
                        raise RuntimeError("catalog has unowned data but no active content pointer; refusing retry")
            return {"status": "FRESH", "source_sha256": source_sha,
                    "package_sha256": package_sha, "counts": expected_counts}
        if active_sha != source_sha or active[2] != "IMPORTED_RAW" or len(batches) != 1:
            raise RuntimeError("active catalog state differs from this package; preserve data and stop")
        (batch_id, status, stored_package_sha, package_version, stored_record_counts,
         approval_id, approver, change_id, manifest_sha, contract_sha,
         expected_active_sha, approval_hmac) = batches[0]
        if (status != "COMMITTED_RAW" or stored_package_sha.strip() != package_sha
                or package_version != manifest.get("version")
                or manifest_sha.strip() != sha256(package.resolve() / "manifest.json")
                or contract_sha.strip() != sha256(ROOT / "config/data-contracts.json")
                or not approval_id or not approver or not change_id or not approval_hmac):
            raise RuntimeError("import audit does not match the exact package/contract; refusing retry")
        actual_counts = query_counts(conn, source_sha, expected_counts)
        if actual_counts != expected_counts:
            raise RuntimeError("persisted catalog rows differ from the exact package counts; refusing retry")
        with conn.cursor() as cur:
            cur.execute("""SELECT source_sha256,prior_source_sha256,content_revision,approver,
                                  change_id,approval_hmac_sha256
                           FROM audit.content_activation_event
                           WHERE approval_id=%s AND operation='IMPORT_RAW'""", (approval_id,))
            events = cur.fetchall()
        if (len(events) != 1 or events[0][0].strip() != source_sha
                or events[0][1] != expected_active_sha or events[0][2] != active[1]
                or events[0][3] != approver or events[0][4] != change_id
                or events[0][5].strip() != approval_hmac.strip()):
            raise RuntimeError("catalog import event does not match the active batch; refusing retry")

        approval = None
        for path in sorted(approvals_dir.glob("approval-*.json")):
            if path.is_symlink() or not path.is_file():
                raise PermissionError("approval directory contains a non-regular entry")
            info = path.stat()
            if info.st_uid != os.geteuid() or info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise PermissionError("approval evidence ownership or mode is unsafe")
            item = json.loads(path.read_text(encoding="utf-8"))
            if item.get("approval_id") == approval_id:
                if approval is not None:
                    raise PermissionError("duplicate approval ID evidence")
                approval = item
        if approval is None:
            raise RuntimeError("original import approval evidence is missing; refusing retry")
        issued_at = approval.get("issued_at")
        expires_at = approval.get("expires_at")
        if (not isinstance(issued_at, int) or not isinstance(expires_at, int)
                or issued_at > expires_at or expires_at - issued_at > 86400
                or issued_at > int(time.time())):
            raise RuntimeError("original approval lifetime evidence is malformed; refusing retry")
        payload = _approval_payload(approval)
        expected_hmac = hmac.new(
            _approval_key(), json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
            hashlib.sha256).hexdigest()
        if (not hmac.compare_digest(approval.get("hmac_sha256", ""), expected_hmac)
                or not hmac.compare_digest(approval["hmac_sha256"], approval_hmac.strip())
                or approval.get("action") != "import"
                or approval.get("source_sha256") != source_sha
                or approval.get("archive_sha256") != sha256(archive.resolve())
                or approval.get("manifest_sha256") != manifest_sha.strip()
                or approval.get("contract_sha256") != contract_sha.strip()
                or approval.get("approver") != approver or approval.get("change_id") != change_id
                or approval.get("expected_active_source_sha256") != expected_active_sha):
            raise RuntimeError("original approval signature or its bound facts differ; refusing retry")
        return {"status": "SAFE_RESUME_IDEMPOTENT_NOOP", "source_sha256": source_sha,
                "package_sha256": package_sha, "batch_id": batch_id,
                "content_revision": active[1], "counts": actual_counts}
    finally:
        conn.close()


def activate_source_revision(source_sha: str, package: Path, archive: Path, approval_file: Path) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha):
        raise ValueError("source SHA256 must be 64 lowercase hexadecimal characters")
    manifest, _package_sha, _rows = _verified_package(package, archive)
    approval = _verify_approval(approval_file, package, archive, manifest, action="activate")
    if manifest["source_sha256"] != source_sha:
        raise PermissionError("activation SHA differs from the approved package")
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('server_version_num')::integer")
            server_version = cur.fetchone()[0]
        if server_version // 10000 != 17:
            raise RuntimeError("PostgreSQL 17 is required")
        from bsv_catalog_live import live_enabled,require_live_layout,reject_pending_sale
        if live_enabled():require_live_layout(conn)
        # End the implicit read transaction so the activation block is a real
        # commit, not a savepoint discarded when this short-lived connection closes.
        conn.commit()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("LOCK TABLE catalog.active_content IN EXCLUSIVE MODE")
                reject_pending_sale(conn)
                cur.execute("SELECT source_sha256 FROM catalog.active_content WHERE singleton_id=1")
                active = cur.fetchone()
                active_sha = active[0].strip() if active else None
                if active_sha != approval["expected_active_source_sha256"]:
                    raise RuntimeError("active content changed after rollback approval; request a new approval")
                cur.execute("SELECT status FROM audit.import_batch WHERE source_sha256=%s", (source_sha,))
                batch = cur.fetchone()
                if not batch or batch[0] != "COMMITTED_RAW":
                    raise RuntimeError("target source revision is not a complete raw import")
                cur.execute("SELECT COALESCE(MAX(content_revision),0)+1 FROM catalog.active_content")
                revision = cur.fetchone()[0]
                cur.execute("""INSERT INTO catalog.active_content(singleton_id,source_sha256,content_revision,activation_status)
                               VALUES (1,%s,%s,'IMPORTED_RAW') ON CONFLICT(singleton_id) DO UPDATE
                               SET source_sha256=EXCLUDED.source_sha256,content_revision=EXCLUDED.content_revision,
                                   activated_at=now(),activation_status='IMPORTED_RAW'""", (source_sha, revision))
                cur.execute("""INSERT INTO audit.content_activation_event
                    (event_id,source_sha256,prior_source_sha256,content_revision,operation,approval_id,approver,change_id,approval_hmac_sha256)
                    VALUES (%s,%s,%s,%s,'ACTIVATE_RAW',%s,%s,%s,%s)""",
                    (uuid.uuid4(), source_sha, active_sha, revision, approval["approval_id"], approval["approver"],
                     approval["change_id"], approval["hmac_sha256"]))
        return {"status": "ACTIVE_RAW_REVISION", "source_sha256": source_sha, "content_revision": revision}
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--package-dir", type=Path)
    mode.add_argument("--activate-source-sha")
    parser.add_argument("--issue-approval", action="store_true", help="sign an expiring approval for one exact package")
    parser.add_argument("--archive", type=Path, help="exact verified catalog package ZIP")
    parser.add_argument("--activation-package-dir", type=Path, help="verified package directory for a signed activation")
    parser.add_argument("--approval", type=Path, help="signed approval JSON required for import")
    parser.add_argument("--approver")
    parser.add_argument("--change-id")
    parser.add_argument("--expected-active-source-sha")
    parser.add_argument("--approval-output", type=Path)
    parser.add_argument("--approval-action", choices=("import", "activate"), default="import")
    parser.add_argument("--audit-existing", action="store_true",
                        help="read-only exact-package audit used only for safe deployment resume")
    parser.add_argument("--approvals-dir", type=Path,
                        help="private directory holding the original import approval evidence")
    args = parser.parse_args()
    try:
        if args.audit_existing:
            if not args.package_dir or not args.archive or not args.approvals_dir:
                raise ValueError("read-only retry audit requires --package-dir --archive --approvals-dir")
            result = inspect_existing_import(args.package_dir, args.archive, args.approvals_dir)
        elif args.issue_approval:
            if not all((args.package_dir, args.archive, args.approver, args.change_id, args.approval_output)):
                raise ValueError("approval requires --package-dir --archive --approver --change-id --approval-output")
            result = create_approval(args.package_dir, args.archive, approver=args.approver,
                                     change_id=args.change_id,
                                     expected_active_source_sha256=args.expected_active_source_sha,
                                     output=args.approval_output, action=args.approval_action)
        elif args.activate_source_sha:
            if not args.activation_package_dir or not args.archive or not args.approval:
                raise ValueError("activation requires --activation-package-dir --archive and --approval")
            result = activate_source_revision(args.activate_source_sha, args.activation_package_dir,
                                              args.archive, args.approval)
        else:
            if not args.archive:
                raise ValueError("--archive is required with --package-dir")
            if not args.approval:
                raise ValueError("--approval is required; package import is never implicit")
            result = import_package(args.package_dir, args.archive, args.approval)
    except Exception as exc:
        print(f"IMPORT_REFUSED: {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
