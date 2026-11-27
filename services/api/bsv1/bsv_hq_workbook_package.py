"""Registered seven-sheet XLSX -> existing WorkBuddy package format.
No schema inference, formula evaluation, sale approval or database writes.
"""
from __future__ import annotations
import csv
import json
import re
import shutil
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

from bsv_catalog_import import ROOT, PACKAGE_ROWS, AUDIT_ROWS, _verified_package, sha256
from bsv_catalog_workbook_preview import _validate_xlsx_bytes
from bsv_v9_import import SHEETS, NS, col_num, workbook_read, unpack_v9, a1, cents_from_price

MAIN = dict(zip("CPMKRQT", ("catalog.product","catalog.semifinished","catalog.material",
    "catalog.bundle","catalog.recipe_step","catalog.price_quote","core.store")))
SUB = {"catalog.bundle_slot":"CR","catalog.store_nps":"DC"}
DERIVED = {"catalog.bundle_slot":"slot_row_id","catalog.store_nps":"nps_row_id"}
REGISTRY = ROOT/"config/data-contracts.json"

def dictionary():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))["domains"]["catalog"]["postgres_field_dictionary"]

def table_specs():
    result=defaultdict(list)
    for key,spec in dictionary().items():
        result[spec["table"]].append((key,spec))
    return result

def sheet_paths(z):
    wb=ET.fromstring(z.read("xl/workbook.xml"))
    rels=ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets={r.get("Id"):r.get("Target") for r in rels}
    import posixpath
    result={}
    for sh in wb.findall(".//m:sheets/m:sheet",NS):
        name=sh.get("name")
        if name not in SHEETS or name in result:
            raise ValueError("存在未登记或重复工作表")
        target=targets.get(sh.get("{%s}id"%NS["r"]))
        if not target:
            raise ValueError("工作表路径缺失")
        path=target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/"+target)
        if not path.startswith("xl/worksheets/") and not re.fullmatch(r"xl/sheet\d+\.xml",path):
            raise ValueError("工作表路径不受支持")
        result[name]=path
    if set(result)!=set(SHEETS):
        raise ValueError("缺少登记工作表")
    return result

def typed(value,spec,address):
    if value is None or value=="":
        return None
    dtype=spec["data_type"]
    if dtype=="TEXT":
        return str(value)
    if isinstance(value,bool):
        raise ValueError("数值字段不能是布尔："+address)
    try:
        d=Decimal(str(value))
        if not d.is_finite():
            raise InvalidOperation()
        if dtype=="INTEGER":
            if d!=d.to_integral_value() or not -2147483648<=d<=2147483647:
                raise InvalidOperation()
            return int(d)
        m=re.fullmatch(r"NUMERIC\((\d+),(\d+)\)",dtype)
        if m:
            precision,scale=map(int,m.groups())
            if d!=d.quantize(Decimal(1).scaleb(-scale)) or abs(d)>=Decimal(10)**(precision-scale):
                raise InvalidOperation()
            return str(d)
    except (InvalidOperation,ValueError) as exc:
        raise ValueError("数值字段格式或精度异常："+address) from exc
    raise ValueError("未登记字段类型："+dtype)

def csv_write(path,rows,headers):
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=headers);w.writeheader();w.writerows(rows)

def jsonl_write(path,rows):
    with path.open("w",encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row,ensure_ascii=False,sort_keys=True,allow_nan=False)+"\n")

def make_package(workbook:Path,output:Path):
    _validate_xlsx_bytes(workbook.read_bytes())
    unpack_v9(workbook)  # existing fixed IDs, quote and template validation
    sheets=workbook_read(workbook)
    sheet_by={s[0]:s for s in SHEETS}
    specs=table_specs()
    by_code={s[0]:sheets[s] for s in SHEETS}
    digest=sha256(workbook)
    field_rows=[]; mapping=[]; formulas=[]; rowsets={}
    loc={}
    for key,s in dictionary().items():
        code=s["source_sheet"]
        column=s["source_column"].split(":")[-1]
        col=col_num(column)
        if (code,col) in loc:
            raise ValueError("字段登记列重复")
        loc[(code,col)]=(key,s)
        field_rows.append({"semantic_key":key,"target_table":s["table"],"column_name":s["column"],
            "source_sheet":code,"source_col":s["source_column"],"source_header_zh":s["source_header"],
            "data_type":s["data_type"],"key_role":"","permission_class":s["permission_class"],
            "null_meaning":s["null_meaning"],"id_note":""})
        if s["table"] in PACKAGE_ROWS:
            header=by_code[code].get(8,{}).get(col)
            if header!=s["source_header"]:
                raise ValueError(f"{sheet_by[code]}!{column}8: 表头与登记契约不一致")
    # Every mapped non-empty cell has an explicit source address; raw workbook
    # is also archived byte-for-byte, including formatting and unmapped metadata.
    for code,rows in by_code.items():
        for rn,cells in rows.items():
            if rn<9:
                continue
            for col,value in cells.items():
                if value in (None,"") or (code,col) not in loc:
                    continue
                key,s=loc[(code,col)]
                letter=s["source_column"].split(":")[-1]
                mapping.append({"excel_address":f"{code}!{letter}{rn}","excel_col":letter,
                    "excel_header_zh":s["source_header"],"excel_region":s["table"],
                    "target_table":s["table"],"target_column":s["column"],
                    "transform":"registered_type","reversibility":"raw_workbook_preserved"})
    # Main and subzone facts are selected by the registered ID/anchor column.
    def meta(code,rn):
        return {"ingest_status":"IMPORTED_RAW","_source_sha256":digest,
                "_excel_row":rn,"_source_sheet":code}
    for table,(_,idcol,_) in PACKAGE_ROWS.items():
        code=specs[table][0][1]["source_sheet"]
        anchor=col_num(SUB.get(table,"L"))
        out=[]
        for rn,cells in sorted(by_code[code].items()):
            if rn<9:
                continue
            if cells.get(anchor) in (None,""):
                # A prefilled formula-only template row is not an entity.
                continue
            row=meta(code,rn)
            for _,s in specs[table]:
                letter=s["source_column"].split(":")[-1]
                row[s["column"]]=typed(cells.get(col_num(letter)),s,f"{code}!{letter}{rn}")
            if table in DERIVED:
                row[idcol]=f"{code}:{table.split('.')[1]}:{rn}"
            if not row.get(idcol):
                raise ValueError(f"{code}!{rn}: 必需记录编号为空")
            out.append(row)
        rowsets[table]=out
    # Auxiliary dictionary/legal/calc sections are wide, indexed by workbook
    # row, not independent business IDs. Preserve all registered populated cells.
    for table,(_,idcol,_) in AUDIT_ROWS.items():
        grouped={}
        for _,s in specs[table]:
            code=s["source_sheet"]
            letter=s["source_column"].split(":")[-1]
            for rn,cells in by_code[code].items():
                if rn<9:
                    continue
                value=cells.get(col_num(letter))
                if value in (None,""):
                    continue
                row=grouped.setdefault(rn,{"ingest_status":"IMPORTED_RAW","_source_sha256":digest,
                    "_excel_row":rn,"_source_sheet":None,idcol:f"{table.split('.')[1]}:{rn}"})
                row[s["column"]]=typed(value,s,f"{code}!{letter}{rn}")
        rowsets[table]=[grouped[rn] for rn in sorted(grouped)]
    # Retain raw formula text and saved cache, including blanks; no recomputation.
    with ZipFile(workbook) as z:
        for sheet,target in sheet_paths(z).items():
            code=sheet[0]
            xml=ET.fromstring(z.read(target))
            for cell in xml.findall(".//m:sheetData/m:row/m:c",NS):
                f=cell.find("m:f",NS)
                if f is None:
                    continue
                address=cell.get("r","")
                parsed=a1(address)
                if not parsed:
                    raise ValueError("公式地址异常")
                col,rn=parsed
                s=loc.get((code,col),(None,{}))[1]
                value=cell.find("m:v",NS)
                formulas.append({"sheet_code":code,"cell_address":address,
                    "col_letter":re.sub(r"\d+","",address),"row_num":rn,
                    "source_region":s.get("table","unmapped"),"header_zh":s.get("source_header",""),
                    "formula_text":f.text or "","is_array":str(f.get("t")=="array").lower(),
                    "array_ref":f.get("ref",""),"cached_value":value.text if value is not None else "",
                    "cached_type":cell.get("t","")})
    check_links(rowsets)
    package=output/"package";package.mkdir(mode=0o700)
    for d in ("original","staging","auxiliary"):
        (package/d).mkdir(mode=0o700)
    shutil.copyfile(workbook,package/"original/catalog.xlsx")
    counts={}
    for table,(filename,_,count) in {**PACKAGE_ROWS,**AUDIT_ROWS}.items():
        jsonl_write(package/("staging" if table in PACKAGE_ROWS else "auxiliary")/filename,rowsets[table])
        counts[count]=len(rowsets[table])
    csv_write(package/"field_dictionary.csv",field_rows,list(field_rows[0]))
    csv_write(package/"source_mapping.csv",mapping,["excel_address","excel_col","excel_header_zh","excel_region","target_table","target_column","transform","reversibility"])
    csv_write(package/"formula_index.csv",formulas,["sheet_code","cell_address","col_letter","row_num","source_region","header_zh","formula_text","is_array","array_ref","cached_value","cached_type"])
    manifest={"package":"BSV_ALL_Excel标准数据包","version":"V2.3","source_sha256":digest,
        "target":{"engine":"PostgreSQL 17","database":"bsv_all_prod (Codex实施)","schemas":["catalog","core","audit"]},
        "counts":{"source_sha256":digest,"counts":counts,"fields":len(field_rows),"mappings":len(mapping),"formulas":len(formulas)},
        "files":{p.relative_to(package).as_posix():{"bytes":p.stat().st_size,"sha256":sha256(p)} for p in package.rglob("*") if p.is_file()},
        "formula_policy":"original_text_and_saved_cache_only_no_recalculation"}
    (package/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True),encoding="utf-8")
    archive=output/"package.zip"
    with ZipFile(archive,"w",compression=ZIP_DEFLATED) as z:
        for p in sorted(package.rglob("*")):
            if p.is_file():z.write(p,p.relative_to(package).as_posix())
    _verified_package(package,archive)
    return package,archive

def check_links(rows):
    ids={t:{r[PACKAGE_ROWS[t][1]] for r in v} for t,v in rows.items() if t in PACKAGE_ROWS}
    products=ids["catalog.product"]|ids["catalog.material"]|ids["catalog.bundle"]
    output=ids["catalog.product"]|ids["catalog.semifinished"]
    def check(row,key,allowed,required=False):
        value=row.get(key)
        if (value and value not in allowed) or (required and not value):
            raise ValueError(f"{row['_source_sheet']}!{row['_excel_row']}: {key} 引用不存在")
    for x in rows["catalog.recipe_step"]:
        check(x,"output_link_id",output)
        check(x,"input_material_id",ids["catalog.material"])
    for x in rows["catalog.material"]:
        check(x,"linked_inventory_material_id",ids["catalog.material"])
        check(x,"store_id",ids["core.store"])
    for x in rows["catalog.bundle_slot"]:
        check(x,"slot_bundle_id",ids["catalog.bundle"],True)
        check(x,"candidate_product_id",ids["catalog.product"]|ids["catalog.material"])
    for x in rows["catalog.store_nps"]:
        check(x,"nps_bundle_id",ids["catalog.bundle"],True);check(x,"store_id",ids["core.store"],True)
    for x in rows["catalog.price_quote"]:
        check(x,"store_id",ids["core.store"],True);check(x,"product_id",products,True)
        if x.get("approved_price_raw") and cents_from_price(x["approved_price_raw"]) is None:
            raise ValueError(f"Q!{x['_excel_row']}: 报价不是合法人民币分精度")

def patch_workbook(baseline:Path,draft:dict,target:Path):
    """Make an exact edit on a formula-free registered template.
    Formula-bearing files require a reviewed recalculation workflow, never stale cache reuse.
    """
    _validate_xlsx_bytes(baseline.read_bytes())
    code=draft["domain"]
    table=MAIN[code]
    specs={s["source_header"]:s for _,s in table_specs()[table]}
    sheet=next(s for s in SHEETS if s.startswith(code+"_"))
    q=lambda name:"{"+NS["m"]+"}"+name
    with ZipFile(baseline) as zin:
        paths=sheet_paths(zin)
        roots={name:ET.fromstring(zin.read(p)) for name,p in paths.items()}
        if any(root.findall(".//m:f",NS) for root in roots.values()):
            raise ValueError("公式模板需可信重算后上传Excel；不允许网页编辑沿用过期缓存")
        root=roots[sheet];sd=root.find("m:sheetData",NS)
        rows={int(x.get("r")):x for x in sd.findall("m:row",NS)}
        existing=workbook_read(baseline)[sheet]
        if draft["kind"]=="edit":
            rn=next((r for r,c in existing.items() if r>=9 and c.get(12)==draft["record_id"]),None)
            if rn is None:raise ValueError("固定编号不存在")
        elif draft["kind"]=="create":
            rn=max([8,*rows])+1
            if rn>1048576:raise ValueError("工作表已满")
            rows[rn]=ET.SubElement(sd,q("row"),{"r":str(rn)})
        else:raise ValueError("不支持自动删除或回退")
        values=dict(draft["fields"])
        if draft["kind"]=="create":
            idspec=next(s for s in specs.values() if s["source_column"]=="L")
            values[idspec["source_header"]]=draft["record_id"]
        row=rows[rn]
        for name,value in values.items():
            if name not in specs:raise ValueError("未登记字段")
            spec=specs[name];letter=spec["source_column"];address=f"{letter}{rn}"
            cell=next((c for c in row.findall("m:c",NS) if c.get("r")==address),None)
            if cell is None:cell=ET.SubElement(row,q("c"),{"r":address})
            for child in list(cell):cell.remove(child)
            cell.set("t","inlineStr")
            ET.SubElement(ET.SubElement(cell,q("is")),q("t")).text=str(value)
        row[:]=sorted(list(row),key=lambda c:(a1(c.get("r","")) or (99999,0))[0])
        dimension=root.find("m:dimension",NS)
        if dimension is not None:
            # Recompute only the used-cell range from all cells.
            cells=[a1(c.get("r","")) for c in root.findall(".//m:sheetData/m:row/m:c",NS)]
            cells=[x for x in cells if x]
            def letter(n):
                s=""
                while n:n,r=divmod(n-1,26);s=chr(65+r)+s
                return s
            dimension.set("ref",f"A1:{letter(max(x[0] for x in cells))}{max(x[1] for x in cells)}")
        with ZipFile(target,"w",compression=ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                data=ET.tostring(root,encoding="utf-8",xml_declaration=True) if info.filename==paths[sheet] else zin.read(info)
                zout.writestr(info,data)
