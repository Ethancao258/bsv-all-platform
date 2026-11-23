import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/api/bsv1"))
import bsv_catalog_import as importer


class CatalogImportSafetyTests(unittest.TestCase):
    def test_import_requires_explicit_isolation_and_loopback_database(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(PermissionError):
                importer._safe_dsn()
        base = {"BSV_APP_ENV": "isolated", "BSV_ALLOW_ISOLATED_CATALOG_IMPORT": "1"}
        with patch.dict(os.environ, {**base, "BSV_DB_URL": "postgresql://u:p@db.example/bsv_all_prod"}, clear=True):
            with self.assertRaises(PermissionError):
                importer._safe_dsn()
        with patch.dict(os.environ, {**base, "BSV_DB_URL": "postgresql://u:p@127.0.0.1/bsv_identity_isolated_internal"}, clear=True):
            with self.assertRaises(PermissionError):
                importer._safe_dsn()
        with patch.dict(os.environ, {**base, "BSV_DB_URL": "postgresql://u:p@127.0.0.1:5432/bsv_all_prod"}, clear=True):
            self.assertEqual(importer._safe_dsn(), "postgresql://u:p@127.0.0.1:5432/bsv_all_prod")

    def test_versioned_migration_has_typed_recipe_links_and_no_destructive_ddl(self):
        sql = importer.MIGRATION.read_text(encoding="utf-8").lower()
        self.assertIn("primary key (\"product_id\", _source_sha256)", sql)
        self.assertIn("foreign key (output_product_id, _source_sha256)", sql)
        self.assertIn("foreign key (output_semifinished_id, _source_sha256)", sql)
        self.assertIn("ck_recipe_output_typed", sql)
        self.assertNotRegex(sql, r"\b(drop|truncate)\s+(table|schema|database)\b")
        self.assertIn("isolation migration", sql)


if __name__ == "__main__":
    unittest.main()
