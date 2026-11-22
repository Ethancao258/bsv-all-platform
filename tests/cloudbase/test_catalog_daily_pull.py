"""Offline tests for candidate CloudBase snapshot ingestion. No network or credentials."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from integrations.cloudbase.catalog_daily_pull import (
    TABLES, SnapshotError, build_candidate, extract_table, canonical_bytes,
)


class Response:
    status = 200
    def __init__(self, rows, count=None):
        self.body = json.dumps(rows).encode("utf-8")
        n = len(rows) if count is None else count
        self.headers = {"Content-Range": f"0-{len(rows)-1}/{n}" if rows else "*/0"}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size):
        return self.body[:size]


class Opener:
    def __init__(self, products=None, fail_table=None, short_table=None):
        self.urls = []
        self.products = products if products is not None else [{"product_id": "C000001", "name_zh": "测试酒"}]
        self.fail_table = fail_table
        self.short_table = short_table

    def open(self, req, timeout=20):
        self.urls.append(req.full_url)
        assert req.get_method() == "GET"
        assert req.full_url.startswith("https://inadequate-marten-d1dn9lb5fce2c0.api.tcloudbasegateway.com/")
        assert req.get_header("Authorization") == "Bearer test-secret"
        table = req.full_url.split("/v1/rdb/rest/", 1)[1].split("?", 1)[0]
        if table == self.fail_table:
            from urllib.error import HTTPError
            raise HTTPError(req.full_url, 403, "forbidden", {}, None)
        data = self.products if table == "bsv_products" else []
        count = len(data) + 1 if table == self.short_table else len(data)
        return Response(data, count)


class Tests(unittest.TestCase):
    ENV = "inadequate-marten-d1dn9lb5fce2c0"

    def test_read_only_export_atomic_and_private(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "candidates"
            fake = Opener()
            target, m = build_candidate(self.ENV, "test-secret", out, opener=fake)
            self.assertEqual(len(fake.urls), len(TABLES))
            self.assertEqual(set(m["tables"]), set(TABLES))
            self.assertEqual(m["status"], "CANDIDATE_NOT_APPROVED_NOT_PUBLISHED")
            self.assertEqual(m["tables"]["bsv_products"]["rows"], 1)
            self.assertEqual(os.stat(out).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(target / "bsv_products.json").st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((target / "bsv_products.json").read_text())[0]["product_id"], "C000001")
            self.assertEqual(m["tables"]["bsv_products"]["sha256"], hashlib.sha256(
                canonical_bytes(self_row := [{"product_id": "C000001", "name_zh": "测试酒"}])
            ).hexdigest())
            self.assertFalse((out / "current").exists())
            self.assertEqual(len(list(out.glob("candidate-*"))), 1)

    def test_no_partial_snapshot_on_api_denial(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "candidates"
            with self.assertRaises(SnapshotError):
                build_candidate(self.ENV, "test-secret", out,
                                opener=Opener(fail_table="bsv_price_quotes"))
            self.assertEqual(list(out.iterdir()), [])

    def test_incomplete_response_fails_closed(self):
        with self.assertRaisesRegex(SnapshotError, "partial page"):
            extract_table(Opener(short_table="bsv_products"), self.ENV,
                          "test-secret", "bsv_products")

    def test_duplicate_or_missing_product_id_rejected(self):
        for rows in [[{"name_zh": "没有ID"}],
                     [{"product_id": "C000001"}, {"product_id": "C000001"}],
                     []]:
            with self.subTest(rows=rows):
                with self.assertRaises(SnapshotError):
                    extract_table(Opener(products=rows), self.ENV, "test-secret", "bsv_products")

    def test_no_arbitrary_table_or_environment(self):
        with self.assertRaises(SnapshotError):
            extract_table(Opener(), self.ENV, "test-secret", "auth.users")
        with self.assertRaises(SnapshotError):
            extract_table(Opener(), "https://evil.test/", "test-secret", "bsv_products")


if __name__ == "__main__":
    unittest.main()
