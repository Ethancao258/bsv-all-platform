import sys
import tempfile
import unittest
import zipfile
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/api/bsv1"))
sys.path.insert(0, str(ROOT / "tests/bsv1"))

from bsv_catalog_workbook_preview import preview_workbook
from make_fixture import write_fixture


class CatalogWorkbookPreviewTests(unittest.TestCase):
    def test_valid_workbook_previews_without_writes_and_same_hash_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.xlsx"
            write_fixture(path)
            content = path.read_bytes()
            result = preview_workbook(content, path)
            self.assertEqual(result["status"], "IDEMPOTENT_NOOP")
            self.assertEqual(result["counts"]["C"], 63)
            self.assertNotIn("database_write", result)

    def test_diff_reports_fields_and_pending_retirement_without_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "baseline.xlsx"
            candidate = Path(tmp) / "candidate.xlsx"
            write_fixture(base)
            write_fixture(candidate, product_count=62, first_name="修改名称")
            result = preview_workbook(candidate.read_bytes(), base)
            self.assertEqual(result["status"], "PREVIEW_ONLY")
            self.assertTrue(result["schema_compatible"])
            self.assertEqual(len(result["changes"]["pending_retire"]), 1)
            self.assertEqual(result["changes"]["pending_retire"][0]["status"], "PENDING_RETIRE")
            changed = next(row for row in result["changes"]["modified"] if row["record_id"] == "C000001")
            self.assertEqual(changed["changed_fields"], ["商品名称"])
            self.assertNotIn("28.35", str(changed))
            self.assertNotIn("演练步骤", str(changed))
            self.assertFalse(result["write_performed"])
            self.assertFalse(result["content_contract_compatible"])
            verified = preview_workbook(candidate.read_bytes(), base,
                                         expected_active_source_sha256=hashlib.sha256(base.read_bytes()).hexdigest())
            self.assertTrue(verified["content_contract_compatible"])
            self.assertNotIn("价格", str(result["changes"]))

    def test_duplicate_ids_and_corrupt_archives_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.xlsx"
            duplicate = Path(tmp) / "duplicate.xlsx"
            write_fixture(path)
            write_fixture(duplicate, duplicate_first_id=True)
            content = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "Excel文件为空或超过32MiB限制"):
                preview_workbook(b"")
            with self.assertRaisesRegex(ValueError, "Excel文件损坏或格式无效"):
                preview_workbook(b"not an xlsx")
            with self.assertRaisesRegex(ValueError, "L列固定ID重复"):
                preview_workbook(duplicate.read_bytes())
            malformed = Path(tmp) / "malformed.xlsx"
            with zipfile.ZipFile(malformed, "w") as archive:
                archive.writestr("xl/workbook.xml", "<bad/>")
            with self.assertRaisesRegex(ValueError, "OOXML工作簿"):
                preview_workbook(malformed.read_bytes())

    def test_new_unregistered_column_blocks_approval_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "baseline.xlsx"
            candidate = Path(tmp) / "candidate.xlsx"
            write_fixture(base)
            write_fixture(candidate, extra_header=True)
            result = preview_workbook(candidate.read_bytes(), base)
            self.assertFalse(result["schema_compatible"])
            self.assertFalse(result["content_contract_compatible"])
            self.assertIn("C_现场成品", result["schema_changes"])

    def test_stale_database_baseline_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "baseline.xlsx"
            candidate = Path(tmp) / "candidate.xlsx"
            write_fixture(base)
            write_fixture(candidate, first_name="新名称")
            with self.assertRaisesRegex(ValueError, "数据库版本与差异基线不一致"):
                preview_workbook(candidate.read_bytes(), base, expected_active_source_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
