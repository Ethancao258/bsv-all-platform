"""Private version store regression tests using only synthetic seven-sheet workbooks."""
import json
import os
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/api/bsv1"))
sys.path.insert(0, str(Path(__file__).parent))
import bsv_v9_catalog_store as store
from make_fixture import write_fixture


class CatalogVersionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store_dir = self.root / "private-catalog"
        self.db = self.root / "synthetic.sqlite3"
        self.one = self.root / "one.xlsx"
        self.two = self.root / "two.xlsx"
        write_fixture(self.one, approved=False)
        self.two.write_bytes(self.one.read_bytes() + b"\n")
        db = sqlite3.connect(self.db)
        db.executescript("""
          CREATE TABLE bsv_products(
            id TEXT PRIMARY KEY,name TEXT NOT NULL,price_cents INTEGER NOT NULL,
            demo_only INTEGER NOT NULL,discount_eligible INTEGER NOT NULL);
          CREATE TABLE order_history(id TEXT PRIMARY KEY, amount INTEGER);
          INSERT INTO order_history VALUES('ORDER-SENTINEL',1234);
          CREATE TABLE seats(id TEXT PRIMARY KEY, label TEXT);
          INSERT INTO seats VALUES('SEAT-SENTINEL','A1');
        """)
        db.commit()
        db.close()

    def test_seven_sheets_validate_and_source_is_private(self):
        digest, target, summary = store._store_version(self.one, store._private_root(self.store_dir))
        self.assertEqual(len(digest), 64)
        self.assertEqual(target.name, digest + ".xlsx")
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.store_dir.stat().st_mode & 0o777), 0o700)
        self.assertCountEqual(summary["store_ids"], ["BSVM", "BSVS", "BSVT", "BSVF"])
        self.assertEqual(summary["Q"], 0)
        self.assertEqual(summary["C"], 63)
        self.assertEqual(summary["c_sale_eligible"], 0)

    def test_bad_source_never_replaces_active_and_manual_lock_blocks_cloud(self):
        first = store.activate_workbook(self.one, self.db, self.store_dir)
        active_before = json.loads((self.store_dir / "current.json").read_text())
        db = sqlite3.connect(self.db)
        prior_sha = db.execute("SELECT source_sha FROM bsv_v9_sync WHERE one=1").fetchone()[0]
        bad = self.root / "bad.xlsx"
        bad.write_bytes(b"not an excel workbook")
        with self.assertRaises(Exception):
            store.activate_workbook(bad, self.db, self.store_dir)
        blocked = store.activate_workbook(self.two, self.db, self.store_dir, source_mode="cloudbase")
        active_after = json.loads((self.store_dir / "current.json").read_text())
        now_sha = db.execute("SELECT source_sha FROM bsv_v9_sync WHERE one=1").fetchone()[0]
        db.close()
        self.assertEqual(first["status"], "ACTIVATED")
        self.assertEqual(blocked["status"], "MANUAL_LOCKED")
        self.assertEqual(active_after, active_before)
        self.assertEqual(now_sha, prior_sha)

    def test_unchanged_is_idempotent_and_rollback_restores_prior(self):
        one = store.activate_workbook(self.one, self.db, self.store_dir)
        unchanged = store.activate_workbook(self.one, self.db, self.store_dir)
        two = store.activate_workbook(self.two, self.db, self.store_dir)
        rolled = store.rollback_catalog(self.db, self.store_dir)
        db = sqlite3.connect(self.db)
        active_sha = db.execute("SELECT source_sha FROM bsv_v9_sync WHERE one=1").fetchone()[0]
        product_flags = db.execute("SELECT DISTINCT sale_enabled FROM bsv_products").fetchall()
        order_sentinel = db.execute("SELECT amount FROM order_history WHERE id='ORDER-SENTINEL'").fetchone()[0]
        seat_sentinel = db.execute("SELECT label FROM seats WHERE id='SEAT-SENTINEL'").fetchone()[0]
        db.close()
        self.assertEqual(unchanged["status"], "UNCHANGED")
        self.assertEqual(two["previous_sha256"], one["active_sha256"])
        self.assertEqual(rolled["status"], "ROLLED_BACK")
        self.assertEqual(rolled["active_sha256"], one["active_sha256"])
        self.assertEqual(active_sha, one["active_sha256"])
        self.assertEqual(product_flags, [(0,)])
        self.assertEqual(order_sentinel, 1234)
        self.assertEqual(seat_sentinel, "A1")

    def test_private_version_symlink_is_rejected(self):
        root = store._private_root(self.store_dir)
        outside = self.root / "outside.xlsx"
        outside.write_bytes(self.one.read_bytes())
        digest, target, _ = store._store_version(outside, root)
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaises(RuntimeError):
            store._version_path(root, digest)


if __name__ == "__main__":
    unittest.main()
