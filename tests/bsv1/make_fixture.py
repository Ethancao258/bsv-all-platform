"""Generate a minimal synthetic V9 workbook for the standard-library importer."""
from pathlib import Path
from sys import argv
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZipFile


def write_fixture(path):
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    wb = Element("workbook", {"xmlns": main, "xmlns:r": rel})
    sheets = SubElement(wb, "sheets")
    relations = Element("Relationships")
    pages = (
        ("C_现场成品", "商品ID"), ("P_预调半成品", "半成品ID"),
        ("M_采购纯饮", "物料ID"), ("K_套餐组合", "套餐ID"),
        ("R_配方耗用", "工序记录ID"), ("Q_门店报价", "报价记录ID"),
        ("T_门店注册", "网点记录ID"),
    )
    with ZipFile(path, "w") as archive:
        for i, (page, label) in enumerate(pages, 1):
            target = f"sheet{i}.xml"
            ref = f"rId{i}"
            SubElement(sheets, "sheet", {"name": page, "r:id": ref})
            SubElement(relations, "Relationship", {"Id": ref, "Target": target})
            sheet = Element("worksheet", {"xmlns": main})
            data = SubElement(sheet, "sheetData")
            rows = [{"L": label}]
            if i == 1:
                rows[0].update(M="商品名称", AJ="标注售价", AK="完整制作步骤", AL="制作时长（秒）")
                for n in range(1, 64):
                    record = {"L": f"C{n:06}", "M": f"合成商品 {n}", "AK": "演练步骤", "AL": "45"}
                    if n <= 52:
                        record["AJ"] = "28.35"
                    rows.append(record)
            if i == 7:
                rows[0]["N"] = "门店ID"
                for n, code in enumerate(("BSVM", "BSVS", "BSVT", "BSVF"), 1):
                    rows.append({"L": f"T{n:06}", "N": code})
            for rn, record in enumerate(rows, 8):
                row = SubElement(data, "row", {"r": str(rn)})
                for column, value in record.items():
                    cell = SubElement(row, "c", {"r": f"{column}{rn}", "t": "inlineStr"})
                    SubElement(SubElement(cell, "is"), "t").text = value
            archive.writestr("xl/" + target, tostring(sheet, encoding="utf-8"))
        archive.writestr("xl/workbook.xml", tostring(wb, encoding="utf-8"))
        archive.writestr("xl/_rels/workbook.xml.rels", tostring(relations))


if __name__ == "__main__":
    write_fixture(Path(argv[1]))
