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
