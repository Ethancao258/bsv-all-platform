import unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"services/api/bsv1"))
from bsv_hq_live_sale import plan_sales

class LiveSaleTests(unittest.TestCase):
    def setUp(self):
        self.a={"name":"A","price_cents":8800,"fingerprint":"a"}
        self.b={"name":"B","price_cents":10000,"fingerprint":"b"}
        self.current={"C000001":self.a,"C000002":self.b}
    def test_only_explicitly_approved_products_sell(self):
        self.assertEqual(plan_sales(self.current,{},{"C000001":"LIST"}),{"C000001":self.a})
    def test_changed_active_price_requires_new_approval(self):
        with self.assertRaises(ValueError):plan_sales(self.current,{"C000001":dict(self.a,price_cents=9000)},{"C000002":"LIST"})
        self.assertEqual(plan_sales(self.current,{"C000001":dict(self.a,price_cents=9000)},{"C000001":"LIST"}),{"C000001":self.a})
    def test_preserve_existing_unmodified_and_unlist(self):
        self.assertEqual(plan_sales(self.current,{"C000001":self.a},{"C000002":"LIST"}),self.current)
        self.assertEqual(plan_sales(self.current,self.current,{"C000001":"UNLIST"}),{"C000002":self.b})
    def test_bootstrap_cannot_silently_remove_legacy(self):
        with self.assertRaises(ValueError):plan_sales(self.current,{},{"C000002":"LIST"},["C000001"])
    def test_invalid_price_and_domain(self):
        with self.assertRaises(ValueError):plan_sales({"C000001":dict(self.a,price_cents=None)},{},{"C000001":"LIST"})
        with self.assertRaises(ValueError):plan_sales(self.current,{},{"K000001":"LIST"})
class ProjectionTests(unittest.TestCase):
    def test_real_sqlite_projection_and_no_legacy_overwrite(self):
        import tempfile,sqlite3,os
        from unittest.mock import patch
        from make_fixture import write_fixture
        from bsv_v9_import import unpack_v9,sync_v9,price_is_current
        from bsv_hq_live_sale import facts,finalize_pos
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"source.xlsx";dbpath=root/"pos.sqlite3"
            write_fixture(source,approved=True)
            with sqlite3.connect(dbpath) as db:
                db.executescript("""CREATE TABLE bsv_products(id TEXT PRIMARY KEY,name TEXT NOT NULL,price_cents INTEGER NOT NULL,demo_only INTEGER NOT NULL,discount_eligible INTEGER NOT NULL);
                    CREATE TABLE order_history(id TEXT PRIMARY KEY,amount INTEGER);
                    INSERT INTO order_history VALUES('old',1234);""")
            pages,_,_,summary=unpack_v9(source)
            release={"id":"11111111-1111-4111-8111-111111111111","source_sha256":summary["source_sha256"],"items":{"C000001":facts(pages)["C000001"]}}
            with patch.dict(os.environ,{"BSV_APP_ENV":"production","BSV_CATALOG_LIVE":"1"}):
                sync_v9(dbpath,source,force=True,sale_release=release)
                with sqlite3.connect(dbpath) as db:
                    db.row_factory=sqlite3.Row
                    self.assertFalse(price_is_current(db,db.execute("SELECT * FROM bsv_products WHERE id='C000001'").fetchone(),"BSVM"))
                finalize_pos(dbpath,release)
                with sqlite3.connect(dbpath) as db:
                    db.row_factory=sqlite3.Row
                    self.assertTrue(price_is_current(db,db.execute("SELECT * FROM bsv_products WHERE id='C000001'").fetchone(),"BSVM"))
                    self.assertFalse(price_is_current(db,db.execute("SELECT * FROM bsv_products WHERE id='C000002'").fetchone(),"BSVM"))
                    self.assertEqual(db.execute("SELECT amount FROM order_history WHERE id='old'").fetchone()[0],1234)
            with patch.dict(os.environ,{"BSV_APP_ENV":"isolated","BSV_CATALOG_LIVE":"0"}):
                with self.assertRaises(PermissionError):sync_v9(dbpath,source,force=True)

if __name__=="__main__":unittest.main()
