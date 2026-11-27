"""A raw catalog update cannot confer sale approval or change store ownership."""
from bsv_v9_import import unpack_v9

def validate_raw_change(baseline,candidate):
    before,bextras,_,_=unpack_v9(baseline)
    after,aextras,_,_=unpack_v9(candidate)
    protected={"内容审核状态","上架状态","审批状态","业务审批状态","销售状态","审核状态","是否可售",
               "首次图审核状态","二次图审核状态"}
    for sheet,rows in after.items():
        old={r["id"]:r["fields"] for r in before[sheet]}
        new={r["id"]:r["fields"] for r in rows}
        if sheet.startswith("T_") and old!=new:
            raise ValueError("门店主数据不由商品模块修改")
        for key,fields in new.items():
            prior=old.get(key,{})
            for name in protected & set(fields):
                value=fields[name]
                if key in old and value!=prior.get(name):
                    raise ValueError("资料导入不得修改独立销售/审核状态")
                if key not in old and value not in (None,"","草案","待审核","待核准","否","未上架","未发布","未审核"):
                    raise ValueError("新增资料不得自带批准/上架状态")
    # K auxiliary data must be explicitly reviewed, not hidden in the main diff.
    return {"bundle_aux_changed":bextras!=aextras}


def detailed_changes(baseline,candidate):
    from bsv_v9_import import workbook_read,col_num
    from bsv_hq_workbook_package import dictionary
    from bsv_catalog_workbook_preview import _formula_index
    before=workbook_read(baseline);after=workbook_read(candidate)
    registered={(s["source_sheet"],col_num(s["source_column"].split(":")[-1])):s for s in dictionary().values()}
    formulas=_formula_index(baseline)
    result=[];blocked=[]
    for sheet,old in before.items():
        new=after[sheet]
        for rn in sorted(set(old)|set(new)):
            left=old.get(rn,{});right=new.get(rn,{})
            for col in sorted(set(left)|set(right)):
                a=left.get(col);b=right.get(col)
                if a==b or a in (None,"") and b in (None,""):continue
                s=registered.get((sheet[0],col))
                if not s:
                    blocked.append(f"{sheet}!行{rn}列{col}：未登记数据变化");continue
                letter=s["source_column"].split(":")[-1]
                address=f"{sheet}!{letter}{rn}"
                if (rn==8 or sheet[0]=="T" or s["permission_class"]=="RESTRICTED"
                    or s["table"] in {"audit.source_dictionary","audit.source_legal_path","catalog.store_nps"}):
                    blocked.append(address+"：受保护资料变更");continue
                result.append({"address":address,"field":s["source_header"],"before":a,"after":b,
                    "formula_cache":address in formulas,"table":s["table"]})
    return {"cells":result[:300],"total":len(result),"blocked":blocked[:30],"blocked_count":len(blocked),
            "truncated":len(result)>300}
