"""Read-only validation and version diff for the registered seven-sheet workbook.

This module intentionally stops before PostgreSQL writes. A management route may
only call the controlled importer after a separately authenticated approval
contract is implemented and reviewed.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from bsv_v9_import import SHEETS, unpack_v9, workbook_read, MAIN_LAST, col_num

MAX_WORKBOOK_BYTES = 32 * 1024 * 1024
MAX_ZIP_MEMBERS = 4096
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _validate_xlsx_bytes(content: bytes) -> None:
    if not content or len(content) > MAX_WORKBOOK_BYTES:
        raise ValueError("Excel文件为空或超过32MiB限制")
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(content)) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(infos) > MAX_ZIP_MEMBERS or len(names) != len(set(names)):
                raise ValueError("Excel压缩包成员数量异常或存在重复路径")
            total = 0
            for item in infos:
                name = Path(item.filename)
                if name.is_absolute() or ".." in name.parts or "\\" in item.filename:
                    raise ValueError("Excel压缩包包含越界路径")
                if item.flag_bits & 0x1:
                    raise ValueError("不接受加密Excel压缩包")
                total += item.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("Excel解压后超过256MiB限制")
                if item.file_size and item.compress_size == 0:
                    raise ValueError("Excel压缩包比例异常")
                if item.compress_size and item.file_size / item.compress_size > 10000:
                    raise ValueError("Excel压缩包比例异常")
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise ValueError("文件不是有效的OOXML工作簿")
            if any(name.startswith(("xl/externalLinks/", "xl/activeX/", "xl/embeddings/")) for name in names):
                raise ValueError("工作簿含外部链接或嵌入对象，已拒绝预览")
            if any(name.lower().endswith("vbaproject.bin") for name in names):
                raise ValueError("不接受含宏的工作簿")
            # Reject entities and all external relationship targets before any XML parser.
            for item in infos:
                if item.filename.lower().endswith((".xml", ".rels")):
                    raw = archive.read(item)
                    if b"\x00" in raw or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                        raise ValueError("工作簿XML含不支持的编码或实体声明")
                    if item.filename.lower().endswith(".rels"):
                        rels = ET.fromstring(raw)
                        if any(str(x.get("TargetMode", "")).lower() == "external" for x in rels):
                            raise ValueError("工作簿包含外部关系")
            bad = archive.testzip()
            if bad:
                raise ValueError("Excel压缩包CRC校验失败")
    except zipfile.BadZipFile as exc:
        raise ValueError("Excel文件损坏或格式无效") from exc


def _formula_index(path: Path) -> dict[str, str]:
    """Return address->formula SHA, preserving formula changes without exposing values."""
    result: dict[str, str] = {}
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.get("Id"): item.get("Target") for item in rels}
        for sheet in workbook.findall(".//m:sheets/m:sheet", NS):
            name = sheet.get("name")
            if name not in SHEETS:
                continue
            target = targets.get(sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"))
            if not target:
                raise ValueError("工作表关系缺失：" + str(name))
            target = target.lstrip("/") if target.startswith("/") else os.path.normpath("xl/" + target)
            root = ET.fromstring(archive.read(target))
            for cell in root.findall(".//m:sheetData/m:row/m:c", NS):
                formula = cell.find("m:f", NS)
                if formula is not None:
                    address = f"{name}!{cell.get('r', '')}"
                    signature = json.dumps({"text": formula.text or "", "type": formula.get("t"),
                                            "ref": formula.get("ref")}, sort_keys=True, ensure_ascii=False)
                    result[address] = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    return result


def _records(path: Path):
    data, extras, quotes, summary = unpack_v9(path)
    index = {}
    for sheet, rows in data.items():
        for row in rows:
            index[(sheet, row["id"])] = row
    headers = {}
    for sheet, rows in workbook_read(path).items():
        head = rows.get(8, {})
        last = col_num(MAIN_LAST[sheet])
        headers[sheet] = [(column,str(head[column])) for column in range(11, last + 1)
                          if head.get(column) not in (None, "")]
    return index, headers, len(extras), len(quotes), summary


def preview_workbook(candidate_bytes: bytes, baseline_path: Path | None = None,
                     expected_active_source_sha256: str | None = None) -> dict:
    """Validate and compare an .xlsx without writing to SQLite or PostgreSQL.

    Removed rows are reported as PENDING_RETIRE; the helper never deletes or
    marks active rows. A semantic header change is a hard compatibility block.
    """
    _validate_xlsx_bytes(candidate_bytes)
    with tempfile.TemporaryDirectory(prefix="bsv-catalog-preview-") as directory:
        candidate = Path(directory) / "candidate.xlsx"
        candidate.write_bytes(candidate_bytes)
        new, new_headers, extras_count, quote_count, summary = _records(candidate)
        if baseline_path is None:
            old, old_headers, old_extras_count, old_quote_count = {}, {}, 0, 0
            old_sha = None
            old_formulas = {}
        else:
            baseline_path = Path(baseline_path)
            baseline_bytes = baseline_path.read_bytes()
            _validate_xlsx_bytes(baseline_bytes)
            old_sha = hashlib.sha256(baseline_bytes).hexdigest()
            if expected_active_source_sha256 and expected_active_source_sha256 != old_sha:
                raise ValueError("当前数据库版本与差异基线不一致，请重新读取活动版本后再预览")
            if old_sha == hashlib.sha256(candidate_bytes).hexdigest():
                return {"status": "IDEMPOTENT_NOOP", "source_sha256": old_sha,
                        "schema_compatible": True, "changes": {"added": [], "modified": [],
                        "pending_retire": [], "formula_cells": []}, "counts": summary}
            old, old_headers, old_extras_count, old_quote_count, _ = _records(baseline_path)
            old_formulas = _formula_index(baseline_path)
        new_formulas = _formula_index(candidate)
        schema_changes = {sheet: {"before": old_headers.get(sheet), "after": new_headers.get(sheet)}
                          for sheet in SHEETS if sheet in old_headers and old_headers[sheet] != new_headers[sheet]}
        if expected_active_source_sha256 and expected_active_source_sha256 != old_sha:
            raise ValueError("当前数据库版本与差异基线不一致，请重新读取活动版本后再预览")
        database_baseline_verified = bool(old_sha and expected_active_source_sha256 == old_sha)
        added, modified, pending = [], [], []
        for key, row in sorted(new.items()):
            prior = old.get(key)
            if prior is None:
                added.append({"sheet": key[0], "record_id": key[1], "display_name": row["name"]})
            else:
                before, after = prior["fields"], row["fields"]
                changed = sorted(field for field in set(before) | set(after) if before.get(field) != after.get(field))
                if changed:
                    modified.append({"sheet": key[0], "record_id": key[1], "display_name": row["name"],
                                     "changed_fields": changed})
        for key, row in sorted(old.items()):
            if key not in new:
                pending.append({"sheet": key[0], "record_id": key[1], "display_name": row["name"],
                                "status": "PENDING_RETIRE"})
        formula_cells = sorted(address for address in set(old_formulas) | set(new_formulas)
                               if old_formulas.get(address) != new_formulas.get(address))
        return {
            "status": "PREVIEW_ONLY",
            "source_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            "baseline_sha256": old_sha,
            "schema_compatible": baseline_path is not None and not schema_changes,
            "schema_changes": schema_changes,
            "database_baseline_verified": database_baseline_verified,
            "content_contract_compatible": baseline_path is not None and not schema_changes and database_baseline_verified,
            "changes": {"added": added, "modified": modified, "pending_retire": pending,
                        "formula_cells": formula_cells},
            "counts": {"records_by_sheet": dict(Counter(row["sheet"] for row in
                        [{"sheet": key[0]} for key in new])),
                       "extras": extras_count, "quotes": quote_count,
                       "baseline_extras": old_extras_count, "baseline_quotes": old_quote_count,
                       "source_summary": summary},
            "write_performed": False,
        }
