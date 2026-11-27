"""Recalculate the seven-sheet original without changing formula expressions.

The calculator runs as the unprivileged web account, using a root-provisioned
no-network adapter. Only cache values are grafted onto original OOXML bytes.
"""
from __future__ import annotations
import os,subprocess,tempfile,shutil
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from xml.etree import ElementTree as ET
from decimal import Decimal,InvalidOperation
from bsv_v9_import import NS,text_elem
from bsv_catalog_workbook_preview import _validate_xlsx_bytes,_formula_index

def snapshot(z,paths):
    shared=[]
    if "xl/sharedStrings.xml" in z.namelist():
        shared=[text_elem(x) for x in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si",NS)]
    roots={s:ET.fromstring(z.read(p)) for s,p in paths.items()}
    cells={}
    for sheet,root in roots.items():
        for c in root.findall(".//m:sheetData/m:row/m:c",NS):
            address=sheet+"!"+c.get("r","")
            f=c.find("m:f",NS);v=c.find("m:v",NS);kind=c.get("t","n")
            value=v.text if v is not None else None
            if kind=="s" and value is not None:kind,value="str",shared[int(value)]
            elif kind=="inlineStr":
                istr=c.find("m:is",NS);kind,value="str",text_elem(istr) if istr is not None else None
            elif kind in ("n","") and value is not None:
                try:kind,value="n",Decimal(value)
                except InvalidOperation:raise ValueError("invalid formula numeric cache")
            if value in (None,""):value=None
            if f is not None or value is not None:cells[address]=(f is not None,kind,value,c)
    return roots,cells

def graft(input_path,calculated,output):
    from bsv_hq_workbook_package import sheet_paths
    for p in (input_path,calculated):_validate_xlsx_bytes(p.read_bytes())
    if _formula_index(input_path)!=_formula_index(calculated):
        raise ValueError("重算器改变公式表达式/数组定义，禁止使用")
    q=lambda x:"{"+NS["m"]+"}"+x
    with ZipFile(input_path) as a,ZipFile(calculated) as b:
        ap,bp=sheet_paths(a),sheet_paths(b)
        ar,ac=snapshot(a,ap);_,bc=snapshot(b,bp)
        left={k:(kind,val) for k,(f,kind,val,_) in ac.items() if not f}
        right={k:(kind,val) for k,(f,kind,val,_) in bc.items() if not f}
        if left!=right:raise ValueError("重算器改变非公式原始输入")
        for key,(formula,kind,prior,cell) in ac.items():
            if not formula:continue
            _,new_type,new_value,_=bc[key]
            if new_type=="e" and (kind,prior)!=(new_type,new_value):
                raise ValueError("重算产生新的公式错误："+key)
            for child in list(cell):
                if child.tag in (q("v"),q("is")):cell.remove(child)
            cell.attrib.pop("t",None)
            if new_value is not None:
                if new_type!="n":cell.set("t",new_type)
                ET.SubElement(cell,q("v")).text=str(new_value)
        replacements={ap[s]:ET.tostring(root,encoding="utf-8",xml_declaration=True) for s,root in ar.items()}
        with ZipFile(output,"w",compression=ZIP_DEFLATED) as out:
            for i in a.infolist():out.writestr(i,replacements.get(i.filename,a.read(i)))
    _validate_xlsx_bytes(output.read_bytes())
    if _formula_index(output)!=_formula_index(input_path):raise ValueError("重算后公式签名异常")

def recalculate(path):
    if not _formula_index(path):return
    executable=Path(os.getenv("BSV_HQ_CATALOG_RECALCULATOR",""))
    if not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
        raise ValueError("公式模板需要已安装的可信重算器；也可上传Excel保存后的新版本")
    st=executable.stat()
    if st.st_uid!=0 or st.st_mode&0o022 or not os.access(executable,os.X_OK):
        raise ValueError("重算器必须由root管理且不可由网页修改")
    with tempfile.TemporaryDirectory(prefix="bsv-hq-recalc-",dir=path.parent) as temp:
        temp=Path(temp);calculated=temp/"calculated.xlsx";out=temp/"verified.xlsx"
        try:
            subprocess.run([str(executable),"--input",str(path),"--output",str(calculated)],
                env={"PATH":"/usr/bin:/bin","LANG":"C.UTF-8"},stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,check=True,timeout=55)
        except (OSError,subprocess.SubprocessError) as exc:raise ValueError("可信重算器执行失败") from exc
        if calculated.is_symlink() or not calculated.is_file() or calculated.stat().st_size>50*1024*1024:
            raise ValueError("重算输出不安全")
        graft(path,calculated,out)
        os.replace(out,path)
