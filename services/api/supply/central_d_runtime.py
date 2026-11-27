"""Concrete candidate D bindings and explicit, fail-closed ASGI factory.

No runtime DDL; the verified inventory owner must approve the real schema and
use the existing audit/outbox and stock_lot authority. This reference binding
matches the isolated proposal only, or an independently reviewed equivalent.
"""
from decimal import Decimal
from hmac import compare_digest
import os

from fastapi import FastAPI, HTTPException
from .central_d_postgres import DWorker, d_router, rows, uid, dump
from .central_production_rules import ApprovedRule, ident, quantity
from .config import load_settings
from .gateway import Gateway, Unreachable


def refuse(code, message):
    raise HTTPException(code, message)


class AuthoritySources:
    def __init__(self, gateway):
        self.gateway=gateway

    def read(self,key,path,token,params=None):
        try:
            return self.gateway.read(key,path,user_token=token,params=params,
                                     allow_cache=False,primary_only=True)["data"]
        except Unreachable:
            refuse(503,key+" 权威数据源不可用")

    def identity(self,c,token):
        return self.read("B","/auth/me",token)

    def location(self,c,ctx,store):
        result=self.read("C","/stores",ctx["token"])
        if not isinstance(result,list):
            refuse(502,"C 门店响应无效")
        selected=[x for x in result if isinstance(x,dict) and x.get("store_id")==store and
                  x.get("legal_entity_id")==ctx["legal"] and x.get("approved") is True]
        if len(selected)!=1:
            refuse(403,"门店或中央仓归属未经核验")
        return selected[0]

    def policy(self,c,ctx,item):
        value=self.read("A","/production-policy",ctx["token"],{"item_id":item})
        if not isinstance(value,dict) or value.get("item_id")!=item or value.get("duration_basis")!="PRODUCED_AT":
            refuse(409,"A 未返回已批准的生产规则")
        rule=ApprovedRule(value.get("rule_version"),value.get("approved"),value.get("elapsed_seconds"),value.get("opened_seconds"))
        unit=value.get("unit")
        return {"item_id":item,"rule":rule,"unit":unit,
            "standard_amount":quantity(value.get("standard_amount"),unit),
            "yield_amount":quantity(value.get("yield_amount"),unit),
            "recipe_inputs":validate_inputs(value.get("recipe_inputs")),
            **{key:ident(value.get(key)) for key in ("name","recipe_version","sop_version","storage","usage")}}


def validate_inputs(value):
    if not isinstance(value,list) or not 1<=len(value)<=100:
        raise ValueError("approved recipe inputs required")
    inputs={}
    for row in value:
        if not isinstance(row,dict):
            raise ValueError("invalid approved recipe input")
        item=ident(row.get("material_id")); unit=row.get("unit")
        if item in inputs:
            raise ValueError("catalog must aggregate each material by base unit")
        inputs[item]={"unit":unit,"amount":quantity(row.get("amount"),unit)}
    return inputs


def consume_ingredients(c,ctx,policy,lots,total,batch,source,produced_at):
    """Real FEFO depletion of selected authoritative lots, in the D transaction."""
    required=policy.get("recipe_inputs")
    if not isinstance(required,dict) or not required:
        refuse(409,"缺少批准的投料数量")
    output=quantity(policy.get("yield_amount"),policy["unit"])
    ratio=total/output
    demand={}
    for item,row in required.items():
        # No hidden rounding or mixing units. Unsupported fractional quantities
        # require the owner to publish an approved recipe with usable precision.
        scaled=row["amount"]*ratio
        canonical=scaled.quantize(Decimal("0.0001"))
        if canonical*output!=row["amount"]*total:
            refuse(409,"批准配方投入不能精确表示为基础单位四位小数")
        demand[item]=quantity(canonical,row["unit"])
    if not lots or len(set(lots))!=len(lots):
        refuse(422,"须选择唯一的原料批次")
    selected=rows(c,"""SELECT * FROM supply.stock_lot WHERE legal_entity_id=%s AND stock_lot_id=ANY(%s)
                 ORDER BY stock_lot_id FOR UPDATE""",(ctx["legal"],lots))
    if len(selected)!=len(lots):
        refuse(409,"原料批次不存在或不属于本公司")
    for row in selected:
        item=row["material_id"]
        if (item not in demand or row["stock_location_id"]!=source or row["state"]!="ACCEPTED"
            or row["base_uom"]!=required[item]["unit"] or row["remaining_base"]<=0
            or not row["received_at"]<=produced_at<row["expires_at"] or ctx["now"]>=row["expires_at"]):
            refuse(409,"原料批次、库位、单位或效期需要复核")
    used=set()
    for row in sorted(selected,key=lambda x:(x["expires_at"],x["stock_lot_id"])):
        item=row["material_id"]; amount=min(demand[item],row["remaining_base"])
        if amount<=0:
            continue
        demand[item]-=amount
        used.add(row["stock_lot_id"])
        c.execute("""UPDATE supply.stock_lot SET remaining_base=remaining_base-%s,version=version+1
                  WHERE stock_lot_id=%s AND legal_entity_id=%s AND remaining_base>=%s""",
                  (amount,row["stock_lot_id"],ctx["legal"],amount))
        if c.rowcount!=1:
            refuse(409,"原料库存已变化")
        c.execute("""INSERT INTO supply.movement(movement_id,request_id,item_id,lot_id,
                  from_location_id,to_location_id,qty_base,actor_employee_id,occurred_at,central_kind)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'RAW_CONSUMED')""",
                  (uid(),ctx["rid"],item,row["stock_lot_id"],source,"SUP59:PRODUCTION:"+batch,amount,ctx["actor"],ctx["now"]))
    if any(v>0 for v in demand.values()):
        refuse(409,"原料库存不足，未放行")
    if used!=set(lots):
        refuse(409,"选择的原料批次含未实际耗用记录")


def record_event(c,ctx,operation,data):
    """Only explicit business input/result; never persist the ctx bearer token."""
    event=uid()
    c.execute("""INSERT INTO event_audit.supply_event
              (audit_event_id,legal_entity_id,actor_employee_id,request_id,operation,occurred_at,facts)
              VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)""",
              (event,ctx["legal"],ctx["actor"],ctx["rid"],operation,ctx["now"],dump(data)))
    c.execute("INSERT INTO event_audit.supply_outbox VALUES (%s,%s,'PENDING',%s)",(uid(),event,ctx["now"]))


REQUIRED_COLUMNS={
    "supply.shipment":{"shipment_id","central_legal","eta","dispatched","version"},
    "supply.shipment_package":{"package_id","central_legal","stock_location_id","remaining_base","original","recall_reason","opening_evidence_id"},
    "supply.central_plan":{"plan_id","facts","legal_entity_id"},
    "supply.central_batch":{"batch_id","plan_id","facts"},
    "supply.central_receipt":{"shipment_id","package_id","facts"},
    "supply.central_print":{"request_id","package_id","operation"},
    "supply.stock_lot":{"stock_lot_id","legal_entity_id","material_id","remaining_base","expires_at","opening_evidence_id"},
    "supply.movement":{"movement_id","central_kind","qty_base"},
    "supply.idempotent_result":{"actor_scope","request_id","fingerprint","response"},
    "event_audit.supply_event":{"audit_event_id","request_id","facts"},
    "event_audit.supply_outbox":{"sync_event_id","audit_event_id","state"},
}


def schema_report(connection):
    """Metadata only. No record reads or credentials in output."""
    with connection.transaction(), connection.cursor() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        c.execute("""SELECT table_schema,table_name,column_name FROM information_schema.columns
                    WHERE table_schema=ANY(%s)""",(["supply","event_audit"],))
        actual={}
        for schema,table,column in c.fetchall():
            actual.setdefault(schema+"."+table,set()).add(column)
        missing={key:sorted(cols-actual.get(key,set())) for key,cols in REQUIRED_COLUMNS.items() if cols-actual.get(key,set())}
        return {"compatible_columns":not missing,"missing":missing,"tables_present":sorted(actual)}


def opening_from_env(c,ctx,store):
    from .central_source_adapter import pinned
    path=os.getenv("BSV_SUP59_OPENING_FILE","")
    digest=os.getenv("BSV_SUP59_OPENING_SHA256","")
    if not path and not digest:return []
    value=pinned(path,digest)
    if value.get("legal_entity_id")!=ctx["legal"] or not isinstance(value.get("items"),list):
        refuse(403,"历史期初凭证法人不一致")
    return [r for r in value["items"] if r.get("store_id")==store]


def create_authority_app():
    """Uvicorn --factory entry; not enabled by importing or installing files."""
    if os.getenv("BSV_SUP59_D_AUTHORITY_ENABLED")!="1" or os.getenv("BSV_SUP59_D_SCHEMA_REVIEWED")!="1":
        raise RuntimeError("D owner approval and real schema review required")
    dsn=os.getenv("BSV_SUP59_D_DSN",""); secret=os.getenv("BSV_SUP59_D_SERVICE_TOKEN","")
    if not dsn or len(secret)<32:
        raise RuntimeError("approved D database and service credentials required")
    import psycopg
    def connect():
        return psycopg.connect(dsn)
    with connect() as db:
        if not schema_report(db)["compatible_columns"]:
            raise RuntimeError("D schema mapping incomplete; no migration executed")
    settings=load_settings()
    if settings.mode!="remote":
        raise RuntimeError("authority service requires approved remote source configuration")
    sources=AuthoritySources(Gateway(settings,None))
    worker=DWorker(connect=connect,identity=sources.identity,location=sources.location,policy=sources.policy,
                   consume_ingredients=consume_ingredients,record_event=record_event,opening_provider=opening_from_env)
    def authenticate(request):
        token=request.headers.get("X-BSV-Service-Token","")
        if not token or not compare_digest(token,secret):
            refuse(401,"服务身份无效")
    app=FastAPI(title="BSV D central supply authority candidate",docs_url=None,redoc_url=None,openapi_url=None)
    app.include_router(d_router(worker,authenticate_service=authenticate))
    return app
