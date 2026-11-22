"""POS catalog read adapter over the current authoritative SQLite projection.

Callers use stable product IDs and source-independent semantic attributes. The
physical Excel/SQLite implementation is confined to this adapter pending the
approved PostgreSQL field dictionary and migration gate.
"""
from __future__ import annotations

import json
import sqlite3

from bsv_catalog_contract import semantic_attributes

PAGE_BY_PREFIX = {
    "C": "C_现场成品", "P": "P_预调半成品", "M": "M_采购纯饮",
    "K": "K_套餐组合", "R": "R_配方耗用", "Q": "Q_门店报价",
    "T": "T_门店注册",
}


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
