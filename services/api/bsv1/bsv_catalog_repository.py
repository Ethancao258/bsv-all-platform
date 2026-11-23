"""Catalog read repositories with explicit SQLite compatibility and PostgreSQL 17 mode."""
from __future__ import annotations

import json
import os
import sqlite3
from urllib.parse import urlsplit

from bsv_catalog_contract import postgres_field, semantic_attributes

PAGE_BY_PREFIX = {
    "C": "C_现场成品", "P": "P_预调半成品", "M": "M_采购纯饮",
    "K": "K_套餐组合", "R": "R_配方耗用", "Q": "Q_门店报价",
    "T": "T_门店注册",
}

ENTITY_KEYS_BY_PREFIX = {
    "C": ("catalog.product.product_id", "catalog.product.name_zh", "catalog.product.sales_series"),
    "P": ("catalog.semifinished.semifinished_id", "catalog.semifinished.name_zh", "catalog.semifinished.category_l2"),
    "M": ("catalog.material.material_id", "catalog.material.name_zh", "catalog.material.category_l1"),
    "K": ("catalog.bundle.bundle_id", "catalog.bundle.name_zh", "catalog.bundle.category_l1"),
}
SHEET_BY_PREFIX = {"C": "C_现场成品", "P": "P_预调半成品", "M": "M_采购纯饮", "K": "K_套餐组合"}


def postgres_catalog_enabled() -> bool:
    """PostgreSQL is an opt-in catalog read source in an explicitly isolated stack."""
    return (os.environ.get("BSV_CATALOG_READ_SOURCE", "sqlite").strip().lower() == "postgres"
            and os.environ.get("BSV_APP_ENV") == "isolated"
            and bool(os.environ.get("BSV_DB_URL", "").strip()))


def _dsn() -> str:
    from services.api.shared.data_contracts import resolve_database
    from urllib.parse import urlsplit
    resolved = resolve_database(module="pos")
    if resolved["kind"] != "central":
        raise RuntimeError("BSV_DB_URL is not configured as the central PostgreSQL source")
    value = os.environ["BSV_DB_URL"].strip()
    parsed = urlsplit(value.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("isolated POS catalog reads only permit loopback PostgreSQL")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


class SQLiteCatalogReadRepository:
    """Read-only access to existing imported V9 facts; never writes SQLite."""

    def __init__(self, connection: sqlite3.Connection):
        self.db = connection

    def get_product(self, product_id: str) -> dict | None:
        if not isinstance(product_id, str) or len(product_id) != 7 or product_id[:1] not in PAGE_BY_PREFIX:
            return None
        row = self.db.execute(
            "SELECT fixed_id,display_name,page,fields_json,imported_sha FROM bsv_v9_record WHERE fixed_id=? AND page=?",
            (product_id, PAGE_BY_PREFIX[product_id[0]]),
        ).fetchone()
        if row is None:
            return None
        fields = json.loads(row["fields_json"])
        return {"product_id": row["fixed_id"], "name": row["display_name"],
                "sheet": row["page"], "source_sha256": row["imported_sha"],
                "source_fields": fields,
                "attributes": semantic_attributes(row["page"], fields)}

    def search(self, sheets: tuple[str, ...], limit: int = 1000) -> list[dict]:
        if not sheets or not 1 <= limit <= 5000:
            return []
        placeholders = ",".join("?" for _ in sheets)
        rows = self.db.execute(
            f"SELECT fixed_id,display_name,page,fields_json,imported_sha FROM bsv_v9_record "
            f"WHERE page IN ({placeholders}) ORDER BY source_row LIMIT ?", (*sheets, limit)
        ).fetchall()
        results = []
        for row in rows:
            fields = json.loads(row["fields_json"])
            results.append({"product_id": row["fixed_id"], "name": row["display_name"],
                            "sheet": row["page"], "source_sha256": row["imported_sha"],
                            "source_fields": fields,
                            "attributes": semantic_attributes(row["page"], fields)})
        return results


class PostgresCatalogReadRepository:
    """Read-only versioned catalog queries; operational POS facts remain SQLite."""

    def __init__(self, dsn: str | None = None, connect=None):
        if connect is None:
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError("PostgreSQL catalog reader requires the locked psycopg dependency") from exc
            connect = psycopg.connect
        self._connect = connect
        self._dsn = dsn or _dsn()

    def _connection(self, *, confidential: bool = False):
        conn = self._connect(self._dsn, connect_timeout=3, autocommit=True)
        try:
            conn.execute("SET ROLE bsv_catalog_confidential_reader" if confidential else "SET ROLE bsv_catalog_reader")
            version = conn.execute("SELECT current_setting('server_version_num')::integer").fetchone()[0]
            if version // 10000 != 17:
                raise RuntimeError("catalog source must be PostgreSQL 17")
        except BaseException:
            conn.close()
            raise
        return conn

    @staticmethod
    def _entity(prefix: str) -> tuple[str, str, str, str]:
        if prefix not in ENTITY_KEYS_BY_PREFIX:
            raise ValueError("unsupported catalog entity")
        id_key, name_key, series_key = ENTITY_KEYS_BY_PREFIX[prefix]
        id_field, name_field, series_field = (postgres_field(key) for key in (id_key, name_key, series_key))
        if id_field["table"] != name_field["table"] or id_field["table"] != series_field["table"]:
            raise ValueError("catalog semantic fields resolve to different entities")
        return id_field["table"], id_field["column"], name_field["column"], series_field["column"]

    @staticmethod
    def _active(cur) -> dict:
        cur.execute("""SELECT a.source_sha256, a.content_revision, a.activated_at,
                              b.status, b.package_version
                       FROM catalog.active_content a JOIN audit.import_batch b USING(source_sha256)
                       WHERE a.singleton_id=1""")
        row = cur.fetchone()
        if not row:
            raise RuntimeError("PostgreSQL catalog has no imported active revision")
        return {"sha256": row[0].strip(), "revision": row[1], "imported_at": row[2].isoformat(),
                "status": row[3], "version": row[4]}

    @staticmethod
    def _source_fields(cur, table: str, record_id: str, source_sha: str, *, confidential: bool = False) -> dict | None:
        view = "source_record_confidential" if confidential else "source_record_staff"
        cur.execute(f"""SELECT raw_fields FROM audit.{view}
                       WHERE entity_table=%s AND record_id=%s AND source_sha256=%s""",
                    (table, record_id, source_sha))
        row = cur.fetchone()
        return row[0] if row else None

    @staticmethod
    def _permission_filter(cur, table: str, source_sha: str, fields: dict,
                           allow_confidential: bool) -> tuple[dict, list[str]]:
        permissions = ("RESTRICTED",) if allow_confidential else ("CONFIDENTIAL", "RESTRICTED")
        cur.execute("""SELECT source_header_zh FROM audit.field_dictionary
                       WHERE source_sha256=%s AND target_table=%s
                         AND permission_class = ANY(%s)""", (source_sha, table, list(permissions)))
        blocked = {row[0] for row in cur.fetchall() if row[0]}
        return {k: v for k, v in fields.items() if k not in blocked}, sorted(k for k in fields if k in blocked)

    def source(self) -> dict:
        with self._connection() as conn, conn.cursor() as cur:
            active = self._active(cur)
        return {"status": active["status"], "sha256": active["sha256"], "imported_at": active["imported_at"],
                "content_revision": active["revision"], "package_version": active["version"],
                "source": "postgresql"}

    def get_product(self, product_id: str, *, allow_confidential: bool = False) -> dict | None:
        if not isinstance(product_id, str) or not __import__("re").fullmatch(r"[CPMK]\d{6}", product_id):
            return None
        table, id_column, name_column, _series_column = self._entity(product_id[0])
        with self._connection(confidential=allow_confidential) as conn, conn.cursor() as cur:
            active = self._active(cur)
            from psycopg import sql
            cur.execute(sql.SQL("SELECT {}, {}, ingest_status FROM {} WHERE {}=%s AND _source_sha256=%s").format(
                sql.Identifier(id_column), sql.Identifier(name_column), sql.Identifier(*table.split(".")),
                sql.Identifier(id_column)), (product_id, active["sha256"]))
            row = cur.fetchone()
            if not row:
                return None
            fields = self._source_fields(cur, table, product_id, active["sha256"], confidential=allow_confidential) or {}
            fields, withheld = self._permission_filter(cur, table, active["sha256"], fields, allow_confidential)
        page = SHEET_BY_PREFIX[product_id[0]]
        attrs = semantic_attributes(page, fields)
        result = {"product_id": product_id, "id": product_id, "name": row[1], "domain": product_id[0],
                  "sheet": page, "fields": fields, "source_fields": fields, "attributes": attrs,
                  "withheld_fields": withheld, "sale_enabled": False,
                  "source": {"status": active["status"], "sha256": active["sha256"],
                             "imported_at": active["imported_at"], "content_revision": active["revision"],
                             "source": "postgresql"}}
        if product_id.startswith("P"):
            status = str(fields.get("审核状态") or fields.get("内容审核状态") or "")
            result["production_standard_approved"] = status in {"已批准", "已核准", "审核通过"}
        if product_id.startswith("K"):
            result["store_research"] = self._bundle_research(product_id, active["sha256"])
        return result

    def _bundle_research(self, bundle_id: str, source_sha: str) -> list[dict]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT entity_table, record_id, excel_row, raw_fields FROM audit.source_record_staff
                           WHERE source_sha256=%s AND entity_table IN ('catalog.bundle_slot','catalog.store_nps')
                             AND raw_fields->>'套餐ID'=%s ORDER BY excel_row""", (source_sha, bundle_id))
            return [{"section": row[0], "source_row": row[2], "fields": row[3]} for row in cur.fetchall()]

    def search(self, term: str, domain: str = "ALL", limit: int = 100) -> dict:
        if domain not in {"ALL", "C", "P", "M", "K", "READY"} or len(term) > 100 or not 1 <= limit <= 100:
            raise ValueError("invalid catalog search")
        if not term:
            return {"items": [], "source": self.source()}
        if domain == "READY":
            return {"items": [], "source": self.source()}
        prefixes = [domain] if domain != "ALL" else ["C", "P", "M", "K"]
        needle = f"%{term}%"
        with self._connection() as conn, conn.cursor() as cur:
            active = self._active(cur)
            items = []
            for prefix in prefixes:
                table, id_col, name_col, series_col = self._entity(prefix)
                from psycopg import sql
                category_cols = [postgres_field(f"{table}.category_l{i}")["column"] for i in range(1, 5)]
                search_cols = [id_col, name_col, series_col, *category_cols]
                terms = [sql.SQL("CAST({} AS TEXT) ILIKE %s").format(sql.Identifier("t", column))
                         for column in search_cols]
                query = sql.SQL("SELECT t.{},t.{},t.{} FROM {} t WHERE t._source_sha256=%s AND ({}) ORDER BY t.{} LIMIT %s").format(
                    sql.Identifier(id_col), sql.Identifier(name_col), sql.Identifier(series_col),
                    sql.Identifier(*table.split(".")), sql.SQL(" OR ").join(terms), sql.Identifier(id_col))
                cur.execute(query, (active["sha256"], *([needle] * len(search_cols)), limit))
                for record_id, name, series in cur.fetchall():
                    fields = self._source_fields(cur, table, record_id, active["sha256"], confidential=False) or {}
                    fields, withheld = self._permission_filter(cur, table, active["sha256"], fields, False)
                    items.append({"id": record_id, "product_id": record_id, "name": name, "domain": prefix,
                                  "series": series or "", "sale_enabled": False, "fields": fields,
                                  "source_fields": fields, "attributes": semantic_attributes(SHEET_BY_PREFIX[prefix], fields),
                                  "withheld_fields": withheld})
                    if len(items) >= limit:
                        break
                if len(items) >= limit:
                    break
        return {"items": items, "source": {"status": active["status"], "sha256": active["sha256"],
                "imported_at": active["imported_at"], "content_revision": active["revision"],
                "source": "postgresql"}}

    def recipe(self, item_id: str, *, allow_confidential: bool = False) -> dict | None:
        item = self.get_product(item_id, allow_confidential=allow_confidential)
        if not item or item_id[0] not in {"C", "P"}:
            return None
        active = item["source"]
        with self._connection(confidential=allow_confidential) as conn, conn.cursor() as cur:
            col = "output_product_id" if item_id.startswith("C") else "output_semifinished_id"
            cur.execute(f"""SELECT recipe_step_id,input_material_id,output_link_id
                           FROM catalog.recipe_step WHERE {col}=%s AND _source_sha256=%s
                           ORDER BY _excel_row""", (item_id, active["sha256"]))
            rows = cur.fetchall()
            operations = []
            for record_id, material_id, output_id in rows:
                fields = self._source_fields(cur, "catalog.recipe_step", record_id, active["sha256"], confidential=allow_confidential) or {}
                if not allow_confidential:
                    fields, _ = self._permission_filter(cur, "catalog.recipe_step", active["sha256"], fields, False)
                material = None
                if material_id:
                    material = self.get_product(material_id, allow_confidential=allow_confidential)
                operations.append({"record_id": record_id, "output_id": output_id, "fields": fields,
                                   "material_link_status": "BOUND" if material_id else "SOURCE_MATERIAL_ID_MISSING",
                                   "material": material})
        from bsv_collab import _media_file
        fields = item.get("source_fields", {})
        media = {
            "materials": fields.get("配方图文件名｜首次确认"),
            "final": fields.get("成品图文件名"),
        }
        photos = {kind: {"filename": filename, "available": bool(_media_file(item_id, filename))}
                  for kind, filename in media.items() if filename}
        return {"product_id": item_id, "name": item["name"], "recipe_text": item["attributes"].get("recipe_text"),
                "steps": item["attributes"].get("recipe_steps"),
                "sourcing_guide": item["attributes"].get("sourcing_guide"),
                "recipe_operations": operations, "photos": photos, "source": item["source"],
                "contract_version": "bsv-data-contracts-v1"}
