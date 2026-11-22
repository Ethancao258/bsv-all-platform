"""Read-only recipe lookup by permanent product ID, with no order/task dependency."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services/api/bsv1"))
import bsv_collab


class RecipeReadOnlyLookupTests(unittest.TestCase):
    def test_product_media_reads_from_persistent_id_directory_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"media"
            product=root/"C000001"
            product.mkdir(parents=True)
            image=product/"glass.jpg"
            image.write_bytes(b"synthetic image")
            with patch.dict(os.environ,{"BSV_PRODUCT_MEDIA_ROOT":str(root)}):
                self.assertEqual(bsv_collab._media_file("C000001","glass.jpg"),image.resolve())
                self.assertIsNone(bsv_collab._media_file("C000001","../glass.jpg"))
                outside=Path(temp)/"outside.jpg"
                outside.write_bytes(b"outside")
                (product/"escape.jpg").symlink_to(outside)
                self.assertIsNone(bsv_collab._media_file("C000001","escape.jpg"))
                external_dir=Path(temp)/"external"
                external_dir.mkdir();(external_dir/"image.jpg").write_bytes(b"external")
                (root/"C000002").symlink_to(external_dir,target_is_directory=True)
                self.assertIsNone(bsv_collab._media_file("C000002","image.jpg"))

    def test_recipe_and_operations_resolve_by_exact_catalog_ids_without_order(self):
        import sqlite3
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript("""
          CREATE TABLE bsv_v9_record(
            page TEXT,fixed_id TEXT,display_name TEXT,source_row INTEGER,fields_json TEXT,imported_sha TEXT);
          CREATE TABLE bsv_v9_sync(one INTEGER,source_sha TEXT,imported_at TEXT);
        """)
        product = {"配方文字":"金酒 30ml", "完整制作步骤":"摇和后过滤", "寻酒指引":"吧台A架",
                   "杯具":"鸡尾酒杯", "内容审核状态":"草案"}
        db.execute("INSERT INTO bsv_v9_record VALUES(?,?,?,?,?,?)",
                   ("C_现场成品","C000001","合成鸡尾酒",9,json.dumps(product,ensure_ascii=False),"a"*64))
        recipe_row = {"出品关联ID":"C000001","制作步骤":"先量取金酒","投入物料ID":""}
        db.execute("INSERT INTO bsv_v9_record VALUES(?,?,?,?,?,?)",
                   ("R_配方耗用","R000001","工序",9,json.dumps(recipe_row,ensure_ascii=False),"a"*64))
        db.execute("INSERT INTO bsv_v9_record VALUES(?,?,?,?,?,?)",
                   ("R_配方耗用","R000002","错链工序",10,json.dumps({"出品名称":"合成鸡尾酒","制作步骤":"不得按名称关联"},ensure_ascii=False),"a"*64))
        db.execute("INSERT INTO bsv_v9_sync VALUES(1,?,?)",("a"*64,"2026-11-22T00:00:00+00:00"))
        result=bsv_collab.recipe(db,"BSVM","C000001")
        self.assertEqual(result["fields"]["完整制作步骤"],"摇和后过滤")
        self.assertEqual([x["record_id"] for x in result["recipe_operations"]],["R000001"])
        self.assertEqual(result["recipe_operations"][0]["material_link_status"],"NO_MATERIAL_ID")
        self.assertEqual(result["source"]["sha256"],"a"*64)
        self.assertIn("获准销售",result["warning"])
        db.close()


if __name__ == "__main__":
    unittest.main()
