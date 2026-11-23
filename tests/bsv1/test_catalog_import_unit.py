import os
import sys
import json
import tempfile
import time
import hmac
import hashlib
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
        with patch.dict(os.environ, {**base, "BSV_CATALOG_ADMIN_DB_URL": "postgresql://u:p@db.example/bsv_all_prod"}, clear=True):
            with self.assertRaises(PermissionError):
                importer._safe_dsn()
        with patch.dict(os.environ, {**base, "BSV_CATALOG_ADMIN_DB_URL": "postgresql://u:p@127.0.0.1/bsv_identity_isolated_internal"}, clear=True):
            with self.assertRaises(PermissionError):
                importer._safe_dsn()
        with patch.dict(os.environ, {**base, "BSV_CATALOG_ADMIN_DB_URL": "postgresql://u:p@127.0.0.1:5432/bsv_all_prod"}, clear=True):
            self.assertEqual(importer._safe_dsn(), "postgresql://u:p@127.0.0.1:5432/bsv_all_prod")

    def test_versioned_migration_has_typed_recipe_links_and_no_destructive_ddl(self):
        sql = importer.MIGRATION.read_text(encoding="utf-8").lower()
        self.assertIn("primary key (\"product_id\", _source_sha256)", sql)
        self.assertIn("foreign key (output_product_id, _source_sha256)", sql)
        self.assertIn("foreign key (output_semifinished_id, _source_sha256)", sql)
        self.assertIn("ck_recipe_output_typed", sql)
        self.assertNotRegex(sql, r"\b(drop|truncate)\s+(table|schema|database)\b")
        self.assertIn("isolation migration", sql)
        hardening = importer.MIGRATION.with_name("0002_catalog_reader_least_privilege.sql").read_text(encoding="utf-8")
        self.assertIn("REVOKE ALL ON ALL TABLES", hardening)
        self.assertIn("source_record_confidential", hardening)

    def test_signed_package_approval_binds_hashes_contract_and_expiry(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            key = root / "approval.key"
            key.write_bytes(b"k" * 48)
            key.chmod(0o600)
            package = root / "package"
            package.mkdir()
            manifest_path = package / "manifest.json"
            manifest_path.write_text('{"source_sha256":"' + "a" * 64 + '"}')
            archive = root / "package.zip"
            original_archive = b"signed bytes"
            archive.write_bytes(original_archive)
            body = {"approval_id": "test-approval", "action": "import", "archive_sha256": importer.sha256(archive),
                    "manifest_sha256": importer.sha256(manifest_path), "source_sha256": "a" * 64,
                    "contract_sha256": importer.sha256(importer.ROOT / "config/data-contracts.json"),
                    "expected_active_source_sha256": None, "approver": "operator@example.test",
                    "change_id": "ISSUE-40", "issued_at": int(time.time()), "expires_at": int(time.time()) + 600}
            body["hmac_sha256"] = hmac.new(key.read_bytes(), json.dumps(body, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
            approval_path = root / "approval.json"
            approval_path.write_text(json.dumps(body))
            approval_path.chmod(0o600)
            with patch.dict(os.environ, {"BSV_CATALOG_APPROVAL_KEY_FILE": str(key)}):
                accepted = importer._verify_approval(approval_path, package, archive, {"source_sha256": "a" * 64})
                self.assertEqual(accepted["change_id"], "ISSUE-40")
                archive.write_bytes(b"tampered bytes")
                with self.assertRaises(PermissionError):
                    importer._verify_approval(approval_path, package, archive, {"source_sha256": "a" * 64})
                archive.write_bytes(original_archive)
                body["expires_at"] = int(time.time()) - 1
                payload = importer._approval_payload(body)
                body["hmac_sha256"] = hmac.new(key.read_bytes(), json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
                approval_path.write_text(json.dumps(body))
                with self.assertRaisesRegex(PermissionError, "expired"):
                    importer._verify_approval(approval_path, package, archive, {"source_sha256": "a" * 64})

    def test_row_expectations_follow_package_manifest_counts(self):
        manifest = {"counts": {"source_sha256": "a" * 64, "counts": {
            "catalog_product": 9, "catalog_semifinished": 2, "catalog_material": 4,
            "catalog_bundle": 1, "catalog_bundle_slot": 1, "catalog_store_nps": 3,
            "catalog_recipe_step": 8, "catalog_price_quote": 0, "core_store": 1,
            "audit_source_dictionary": 7, "audit_source_legal_path": 5, "audit_source_calc": 2,
        }, "fields": 3, "mappings": 17, "formulas": 19}}
        counts = importer.expected_sql_counts(manifest)
        self.assertEqual(counts["catalog.product"], 9)
        self.assertEqual(counts["audit.field_dictionary"], 3)
        self.assertEqual(counts["audit.source_record"], 29)


if __name__ == "__main__":
    unittest.main()
