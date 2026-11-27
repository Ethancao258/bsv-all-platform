"""Synthetic registered-template round trip; no real business data."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree.ElementTree import Element,SubElement,tostring
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"services/api/bsv1"))
from bsv_hq_workbook_package import dictionary,make_package,patch_workbook
from bsv_catalog_import import _verified_package,sha256
from bsv_hq_candidate import prepare
from bsv_v9_import import SHEETS,NS
from bsv_hq_sale_gate import validate_raw_change

def fixture(path):
    wb=Element("workbook",{"xmlns":NS["m"],"xmlns:r":NS["r"]})
    sheets=SubElement(wb,"sheets");rels=Element("Relationships")
    fields=dictionary()
    with ZipFile(path,"w") as z:
        z.writestr("[Content_Types].xml",'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        for n,sheet in enumerate(SHEETS,1):
            code=sheet[0];rid=f"rId{n}";target=f"sheet{n}.xml"
            SubElement(sheets,"sheet",{"name":sheet,"r:id":rid})
            SubElement(rels,"Relationship",{"Id":rid,"Target":target})
            root=Element("worksheet",{"xmlns":NS["m"]});sd=SubElement(root,"sheetData")
            headers={s["source_column"]:s["source_header"] for s in fields.values() if s["source_sheet"]==code and ":" not in s["source_column"]}
            def row(rn,values):
                node=SubElement(sd,"row",{"r":str(rn)})
                for col,value in values.items():
                    c=SubElement(node,"c",{"r":col+str(rn),"t":"inlineStr"})
                    SubElement(SubElement(c,"is"),"t").text=str(value)
            row(8,headers)
            if code=="C":row(9,{"L":"C000001","M":"合成饮品","AJ":"88"})
            if code=="T":row(9,{"L":"T000001","M":"合成门店","S":"BSVM"})
            z.writestr("xl/"+target,tostring(root,encoding="utf-8"))
        z.writestr("xl/workbook.xml",tostring(wb,encoding="utf-8"))
        z.writestr("xl/_rels/workbook.xml.rels",tostring(rels,encoding="utf-8"))

class PackageTests(unittest.TestCase):
    def test_roundtrip_and_edited_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/"source.xlsx";fixture(source)
            output=root/"out";output.mkdir()
            p,z=make_package(source,output)
            manifest,_,rows=_verified_package(p,z)
            self.assertEqual(manifest["counts"]["fields"],381)
            self.assertEqual(rows["catalog.product"][0]["product_id"],"C000001")
            self.assertEqual(rows["catalog.product"][0]["reference_price_raw"],"88")
            self.assertEqual(rows["core.store"][0]["store_id"],"BSVM")
            self.assertEqual(sha256(p/"original/catalog.xlsx"),sha256(source))
            draft={"status":"REVIEWED_NOT_PUBLISHED","kind":"edit","domain":"C","record_id":"C000001",
                   "fields":{"商品名称":"合成新名称"},"baseline_sha256":sha256(source)}
            result=prepare(root,draft,source)
            self.assertEqual(result["status"],"VERIFIED_PACKAGE_NOT_PUBLISHED")
            self.assertFalse(result["write_performed"])
            self.assertTrue((root/(result["source_sha256"]+".xlsx")).is_file())

    def test_create_and_sale_state_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/"source.xlsx";fixture(source)
            draft={"status":"REVIEWED_NOT_PUBLISHED","kind":"create","domain":"C","record_id":"C000002",
                   "fields":{"商品名称":"新增合成品"},"baseline_sha256":sha256(source)}
            result=prepare(root,draft,source)
            self.assertEqual(result["status"],"VERIFIED_PACKAGE_NOT_PUBLISHED")
            changed=root/"bad.xlsx"
            patch_workbook(source,{"kind":"edit","domain":"C","record_id":"C000001","fields":{"内容审核状态":"已批准"}},changed)
            with self.assertRaisesRegex(ValueError,"审核状态"):
                validate_raw_change(source,changed)

if __name__=="__main__":unittest.main()
