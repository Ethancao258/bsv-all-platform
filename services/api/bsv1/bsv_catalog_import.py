"""Isolated-only, transactional importer for a verified WorkBuddy V2.2 package.

This command refuses remote databases. It never touches CloudBase or SQLite.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "platform/lighthouse/bsv1/catalog/isolated_migrations/0001_workbuddy_v22.sql"
EXPECTED_COUNTS = {
    "catalog.product": ("catalog_product.jsonl", "product_id", 63),
    "catalog.semifinished": ("catalog_semifinished.jsonl", "semifinished_id", 17),
    "catalog.material": ("catalog_material.jsonl", "material_id", 419),
    "catalog.bundle": ("catalog_bundle.jsonl", "bundle_id", 21),
    "catalog.bundle_slot": ("catalog_bundle_slot.jsonl", "slot_row_id", 21),
    "catalog.store_nps": ("catalog_store_nps.jsonl", "nps_row_id", 84),
    "catalog.recipe_step": ("catalog_recipe_step.jsonl", "recipe_step_id", 65),
    "catalog.price_quote": ("catalog_price_quote.jsonl", "quote_id", 0),
    "core.store": ("core_store.jsonl", "store_id", 4),
}
AUDIT_JSONL = {
    "audit.source_dictionary": ("audit_source_dictionary.jsonl", "dict_row_id", 399),
    "audit.source_legal_path": ("audit_source_legal_path.jsonl", "legal_row_id", 449),
    "audit.source_calc": ("audit_source_calc.jsonl", "calc_row_id", 597),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verified_package(package: Path, archive: Path) -> tuple[dict, str, dict[str, list[dict]]]:
    package = package.resolve()
    archive = archive.resolve()
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != "V2.2":
        raise ValueError("only WorkBuddy V2.2 packages are accepted")
    if sha256(archive) != "3f98fbe12eacdca481d1e7b3350a59410da7f1116c74a75a1c7b93fe63a0e5a1":
        raise ValueError("V2.2 package archive SHA256 does not match the received artifact")
    for relative, meta in manifest.get("files", {}).items():
        target = (package / relative).resolve()
        if not target.is_file() and relative.startswith("original/") and relative.endswith(".xlsx"):
            candidates = [path.resolve() for path in (package / "original").glob("*.xlsx")]
            if len(candidates) == 1:
                target = candidates[0]
        if package not in target.parents or not target.is_file():
            raise ValueError(f"manifest file missing or escapes package: {relative}")
        if target.stat().st_size != meta["bytes"] or sha256(target) != meta["sha256"]:
            raise ValueError(f"manifest hash mismatch: {relative}")
    if manifest.get("source_sha256") != "4ed9bc164981f267997bd146df54d27ae22fbdc9cc1c850776daed83d34c8e82":
        raise ValueError("source workbook SHA256 does not match the approved V2.2 source")
    counts: dict[str, list[dict]] = {}
    for table, (filename, _id, expected) in EXPECTED_COUNTS.items():
        rows = [json.loads(line) for line in (package / "staging" / filename).read_text(encoding="utf-8").splitlines() if line]
        if len(rows) != expected:
            raise ValueError(f"{table}: expected {expected} rows, received {len(rows)}")
        for row in rows:
            if row.get("_source_sha256") != manifest["source_sha256"] or row.get("ingest_status") != "IMPORTED_RAW":
                raise ValueError(f"{table}: source revision or raw status mismatch")
        counts[table] = rows
    for table, (filename, _id, expected) in AUDIT_JSONL.items():
        rows = [json.loads(line) for line in (package / "auxiliary" / filename).read_text(encoding="utf-8").splitlines() if line]
        if len(rows) != expected:
            raise ValueError(f"{table}: expected {expected} rows, received {len(rows)}")
        counts[table] = rows
    for filename, expected in (("catalog_bundle_slot.jsonl", 21), ("catalog_store_nps.jsonl", 84)):
        if len(counts["catalog." + filename.removeprefix("catalog_").removesuffix(".jsonl")]) != expected:
            raise ValueError(f"auxiliary catalog count mismatch: {filename}")
    fields = list(csv.DictReader((package / "field_dictionary.csv").open(encoding="utf-8-sig", newline="")))
    mappings = list(csv.DictReader((package / "source_mapping.csv").open(encoding="utf-8-sig", newline="")))
    formulas = list(csv.DictReader((package / "formula_index.csv").open(encoding="utf-8-sig", newline="")))
    if len(fields) != 381 or len({r["semantic_key"] for r in fields}) != 381:
        raise ValueError("field dictionary must contain 381 unique semantic keys")
    contract = json.loads((ROOT / "config/data-contracts.json").read_text(encoding="utf-8"))
    registered = contract["domains"]["catalog"].get("postgres_field_dictionary", {})
    if len(registered) != len(fields):
        raise ValueError("config/data-contracts.json does not register all 381 fields")
    for field in fields:
        semantic_key = field["semantic_key"]
        expected_field = {"table": field["target_table"], "column": field["column_name"],
                          "source_sheet": field["source_sheet"], "source_column": field["source_col"],
                          "source_header": field["source_header_zh"], "data_type": field["data_type"],
                          "permission_class": field["permission_class"], "null_meaning": field["null_meaning"]}
        if registered.get(semantic_key) != expected_field:
            raise ValueError(f"field dictionary and unified contract differ for {semantic_key}")
    if len(mappings) != 16815 or len(formulas) != 6275:
        raise ValueError("source mapping or formula count mismatch")
    if sum(str(row["is_array"]).lower() == "true" for row in formulas) != 4978:
        raise ValueError("array formula count mismatch")
    if sum(row["cached_type"] == "EMPTY" for row in formulas) != 2692:
        raise ValueError("formula cache-empty count mismatch")
    recipes = counts["catalog.recipe_step"]
    p_links = {row["recipe_step_id"]: row["output_link_id"] for row in recipes if str(row.get("output_link_id", "")).startswith("P")}
    if p_links != {"R000048": "P000003", "R000051": "P000004"}:
        raise ValueError("typed recipe output links differ from the accepted V2.2 evidence")
    product_ids = {row["product_id"] for row in counts["catalog.product"]}
    semifinished_ids = {row["semifinished_id"] for row in counts["catalog.semifinished"]}
    if sum(str(row.get("output_link_id", "")).startswith("C") for row in recipes) != 63:
        raise ValueError("expected 63 C-output recipe links")
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
        id_column = EXPECTED_COUNTS[table][1]
        for row in rows:
            record = {}
            for field in mapping:
                column = field["column_name"]
                if column in row:
                    record[field["source_header_zh"]] = row[column]
            raw_fields[(table, str(row[id_column]))] = record
    counts["audit.source_record"] = [
        {"entity_table": table, "record_id": record_id, "excel_row": next(
            int(row["_excel_row"]) for row in counts[table] if str(row[EXPECTED_COUNTS[table][1]]) == record_id),
         "raw_fields": raw}
        for (table, record_id), raw in raw_fields.items()
    ]
    return manifest, sha256(archive), counts


def _safe_dsn() -> str:
    if os.environ.get("BSV_APP_ENV") != "isolated" or os.environ.get("BSV_ALLOW_ISOLATED_CATALOG_IMPORT") != "1":
        raise PermissionError("set BSV_APP_ENV=isolated and BSV_ALLOW_ISOLATED_CATALOG_IMPORT=1 for an approved isolated run")
    dsn = os.environ.get("BSV_DB_URL", "").strip()
    parsed = urlsplit(dsn.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise PermissionError("catalog import only permits a loopback PostgreSQL 17 endpoint")
    if parsed.path.lstrip("/") != "bsv_all_prod":
        raise PermissionError("isolated integration database must be named bsv_all_prod")
    if not re.search(r"(?:^|&)sslmode=disable(?:&|$)", parsed.query) and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise PermissionError("untrusted database transport refused")
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)


def _connect():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("install services/api/identity/requirements.lock (psycopg 3.2.13)") from exc
    return psycopg.connect(_safe_dsn(), connect_timeout=5)


def migrate(conn) -> str:
    sql = MIGRATION.read_text(encoding="utf-8")
    checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    with conn.cursor() as cur:
        cur.execute("""SELECT EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_schema IN ('catalog','core','audit')
                         AND table_name NOT IN ('import_batch'))""")
        has_domain_tables = bool(cur.fetchone()[0])
        cur.execute("CREATE SCHEMA IF NOT EXISTS bsv_isolated_migration")
        cur.execute("""CREATE TABLE IF NOT EXISTS bsv_isolated_migration.applied (
                     version TEXT PRIMARY KEY, checksum CHAR(64) NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        cur.execute("SELECT checksum FROM bsv_isolated_migration.applied WHERE version=%s", ("0001_workbuddy_v22",))
        existing = cur.fetchone()
        conn.commit()
    if existing:
        if existing[0].strip() != checksum:
            raise RuntimeError("applied migration checksum differs; refusing to alter prior schema")
        return "ALREADY_APPLIED"
    if has_domain_tables:
        raise RuntimeError("catalog/core/audit objects exist without this isolation migration ledger; refusing to overlay")
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(sql, prepare=False)
            cur.execute("INSERT INTO bsv_isolated_migration.applied(version,checksum) VALUES (%s,%s)",
                        ("0001_workbuddy_v22", checksum))
    return "APPLIED"


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


def import_package(package: Path, archive: Path) -> dict:
    manifest, package_sha, rows = _verified_package(package, archive)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('server_version_num')::integer")
            server_version = cur.fetchone()[0]
        if server_version // 10000 != 17:
            raise RuntimeError(f"PostgreSQL 17 required; connected server version number={server_version}")
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
            if query_counts(conn, sha) != expected_sql_counts():
                raise RuntimeError("repeat import count verification failed")
            return {"status": "IDEMPOTENT_NOOP", "source_sha256": sha,
                    "batch_id": str(prior[0]), "migration": migration_state, "counts": stored}
        batch_id = uuid.uuid4()
        record_counts = {table: len(value) for table, value in rows.items()}
        record_counts["catalog.main_records"] = sum(record_counts[t] for t in EXPECTED_COUNTS if t != "catalog.bundle_slot" and t != "catalog.store_nps")
        with conn.transaction():
            from psycopg.types.json import Jsonb
            with conn.cursor() as cur:
                cur.execute("INSERT INTO audit.import_batch(batch_id,source_sha256,package_sha256,package_version,status,counts) VALUES (%s,%s,%s,%s,'COMMITTED_RAW',%s)",
                            (batch_id, sha, package_sha, manifest["version"], Jsonb(record_counts)))
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
            actual = query_counts(conn, sha)
            expected = expected_sql_counts()
            if actual != expected:
                raise RuntimeError(f"PostgreSQL count validation failed: expected={expected}, actual={actual}")
        return {"status": "COMMITTED_RAW", "source_sha256": sha, "package_sha256": package_sha,
                "batch_id": str(batch_id), "migration": migration_state, "counts": query_counts(conn, sha)}
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


def expected_sql_counts() -> dict[str, int]:
    return {**{table: expected for table, (_file, _id, expected) in EXPECTED_COUNTS.items()},
            **{table: expected for table, (_file, _id, expected) in AUDIT_JSONL.items()},
            "audit.source_mapping": 16815, "audit.field_dictionary": 381,
            "audit.excel_formula_index": 6275, "audit.source_record": 694}


def query_counts(conn, source_sha: str) -> dict[str, int]:
    expected = expected_sql_counts()
    actual = {}
    with conn.cursor() as cur:
        for table in expected:
            schema, name = table.split(".")
            column = "source_sha256" if table in {"audit.source_mapping", "audit.field_dictionary", "audit.source_record", "audit.excel_formula_index"} else "_source_sha256"
            cur.execute("SELECT count(*) FROM " + schema + "." + name + " WHERE " + column + "=%s", (source_sha,))
            actual[table] = cur.fetchone()[0]
    return actual


def activate_source_revision(source_sha: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha):
        raise ValueError("source SHA256 must be 64 lowercase hexadecimal characters")
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('server_version_num')::integer")
            server_version = cur.fetchone()[0]
        if server_version // 10000 != 17:
            raise RuntimeError("PostgreSQL 17 is required")
        with conn.transaction():
            with conn.cursor() as cur:
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
        return {"status": "ACTIVE_RAW_REVISION", "source_sha256": source_sha, "content_revision": revision}
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--package-dir", type=Path)
    mode.add_argument("--activate-source-sha")
    parser.add_argument("--archive", type=Path, help="exact verified WorkBuddy V2.2 ZIP")
    args = parser.parse_args()
    try:
        if args.activate_source_sha:
            result = activate_source_revision(args.activate_source_sha)
        else:
            if not args.archive:
                raise ValueError("--archive is required with --package-dir")
            result = import_package(args.package_dir, args.archive)
    except Exception as exc:
        print(f"IMPORT_REFUSED: {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
