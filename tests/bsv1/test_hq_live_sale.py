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
if __name__=="__main__":unittest.main()
