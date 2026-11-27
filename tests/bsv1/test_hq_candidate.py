import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"services/api/bsv1"))
sys.path.insert(0,str(ROOT/"tests/bsv1"))
from make_fixture import write_fixture
from bsv_hq_candidate import verify_draft_change

class CandidateTests(unittest.TestCase):
    def test_exact_edit_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/"a.xlsx";b=root/"b.xlsx"
            write_fixture(a);write_fixture(b,first_name="新名称")
            draft={"kind":"edit","record_id":"C000001","domain":"C","fields":{"商品名称":"新名称"}}
            verify_draft_change(draft,a,b)
            with self.assertRaises(ValueError):
                verify_draft_change(dict(draft,fields={"商品名称":"别的名称"}),a,b)
            write_fixture(b,product_count=62,first_name="新名称")
            with self.assertRaises(ValueError):
                verify_draft_change(draft,a,b)
    def test_new_needs_allocator(self):
        with self.assertRaises(ValueError):
            verify_draft_change({"kind":"create"},None,None)

if __name__=="__main__":
    unittest.main()
