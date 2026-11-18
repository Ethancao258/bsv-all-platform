"""Pure business validation and replenishment algorithm. No database or AI dependencies."""
from decimal import Decimal, ROUND_CEILING
from datetime import datetime

BUCKETS = {0,25,50,75,100}

def validate_count(full_packages:int, opened_percent:int|None, opened_count:int=0):
    if isinstance(full_packages,bool) or not isinstance(full_packages,int) or full_packages<0:
        raise ValueError('完整包装数必须为非负整数')
    if opened_count not in (0,1):
        return {"method":"UNKNOWN","reason":"多份开封，请复核"}
    if opened_count == 0:
        if opened_percent not in (None,0):raise ValueError('没有开封包装时剩余档位必须为空或0')
        return {"method":"FIVE_BUCKET","estimated_packages":str(Decimal(full_packages)),"exact":False}
    if opened_percent is None:
        return {"method":"UNKNOWN","reason":"无法观察开封余量，请复核"}
    if opened_percent not in BUCKETS:
        raise ValueError('开封余量只能选 0、25、50、75、100，或留空标记未知')
    return {"method":"FIVE_BUCKET","estimated_packages":str(Decimal(full_packages)+Decimal(opened_percent)/100),"exact":False}

def calc_reorder(*, confirmed_available, usage_before_next, arrivals_before_next, reserved,
                 expiry_before_next, demand_next_cycle, safety_stock, arrivals_next_cycle,
                 pack_size,approved=True, reliable=True, max_packs=None):
    """One-period, same-unit forecast; arrivals_next_cycle only if timely before demand."""
    if not approved or not reliable:
        return {"status":"REVIEW_REQUIRED","reason":"物料未批准或输入不可靠"}
    fields=(confirmed_available,usage_before_next,arrivals_before_next,reserved,
            expiry_before_next,demand_next_cycle,safety_stock,arrivals_next_cycle,pack_size)
    vals=list(map(lambda v:Decimal(str(v)),fields))
    if any(x<0 for x in vals) or vals[-1]<=0:
        raise ValueError('数量不能为负且包装量必须大于0')
    a0,d01,i01,r01,e01,d12,s12,i12,pack=vals
    projected=a0+i01-d01-r01-e01
    if projected<0:
        return {"status":"REVIEW_REQUIRED","reason":"下次送货前预计发生缺货，必须先处理缺口","pre_arrival_shortage":str(-projected)}
    stock_before=projected
    gap=max(Decimal(0),d12+s12-stock_before-i12)
    packs=int((gap/pack).to_integral_value(rounding=ROUND_CEILING))
    if max_packs is not None and packs>max_packs:
        return {"status":"REVIEW_REQUIRED","reason":"超过授权配送上限","requested_packs":packs}
    return {"status":"SUGGESTED","packages":packs,"quantity":str(pack*packs),
            "expected_stock_before":str(stock_before),"shortfall":str(gap),"unit":"INPUT_BASE_UNIT"}

def unique_codes(codes):
    cleaned=[str(c).strip() for c in codes]
    if not cleaned or any(not c for c in cleaned) or len(set(cleaned))!=len(cleaned):
        raise ValueError('扫码列表不能为空或包含重复包装码')
    return cleaned
