"""Real PostgreSQL candidate test. All identity/catalog/raw-lot facts are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
import os
import json

import psycopg
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from services.api.supply.central_d_postgres import DWorker, d_router
from services.api.supply.central_production_rules import ApprovedRule

ROOT=Path(__file__).resolve().parents[2]

def rid():
    return str(uuid4())

@pytest.fixture
def scenario():
    dsn=os.getenv("BSV_SUP59_TEST_URL")
    if not dsn:
        pytest.skip("dedicated disposable PostgreSQL fixture is not configured")
    parsed=urlsplit(dsn)
    assert parsed.hostname=="127.0.0.1" and parsed.path=="/bsv_sup59_isolated_candidate"
    def connect():
        return psycopg.connect(dsn)
    with connect() as c:
        c.execute("SELECT set_config('bsv.sup59_schema_fixture','yes',true)")
        c.execute((ROOT/"contracts/supply/central_schema_proposal.sql").read_text())
        c.execute((ROOT/"contracts/supply/sup59_postgres_isolated_candidate.sql").read_text())
        c.execute("""CREATE SCHEMA fixture_support;
          CREATE TABLE fixture_support.raw_lot(id text PRIMARY KEY, remaining numeric NOT NULL CHECK(remaining>=0));
          INSERT INTO fixture_support.raw_lot VALUES ('LOT-1',4000);
          CREATE TABLE fixture_support.events(request_id uuid PRIMARY KEY, actor text, operation text, facts jsonb);
        """)
    now=[datetime(2026,11,27,12,tzinfo=timezone.utc)]
    identities={
        "hq":dict(employee_id="EMP-HQ",legal_entity_id="SYNTH",role_stores={"dispatch":["WH","BSVS"],"receive":["BSVS"]}),
        "shop":dict(employee_id="EMP-SHOP",legal_entity_id="SYNTH",role_stores={"receive":["BSVS"]}),
        "other":dict(employee_id="EMP-OTHER",legal_entity_id="SYNTH",role_stores={"receive":["BSVT"]}),
        "foreign":dict(employee_id="EMP-SHOP",legal_entity_id="OTHER",role_stores={"receive":["BSVS"]}),
    }
    def identity(c,token):
        if token not in identities:raise HTTPException(401)
        return identities[token]
    def location(c,legal,store):
        return dict(store_id=store,kind="warehouse" if store=="WH" else "store") if store in {"WH","BSVS","BSVT"} else None
    def policy(c,legal,item):
        if item!="SYNTH-P":return None
        return dict(item_id=item,name="Synthetic prep",unit="mL",standard_amount="450",recipe_version="R1",sop_version="S1",
                    storage="synthetic storage",usage="synthetic usage",rule=ApprovedRule("E1",True,172800,3600))
    def consume(c,ctx,policy,lots,total,batch):
        assert lots==["LOT-1"]
        result=c.execute("UPDATE fixture_support.raw_lot SET remaining=remaining-%s WHERE id='LOT-1' AND remaining>=%s RETURNING remaining",(total,total)).fetchone()
        if not result:raise HTTPException(409,"fixture raw lot shortage")
    fail_event=[False]
    def event(c,ctx,op,facts):
        if fail_event[0]:raise HTTPException(503,"fixture outbox failure")
        c.execute("INSERT INTO fixture_support.events VALUES (%s,%s,%s,%s::jsonb)",(ctx["rid"],ctx["actor"],op,json.dumps(facts)))
    worker=DWorker(connect=connect,identity=identity,location=location,policy=policy,consume_ingredients=consume,record_event=event,clock=lambda:now[0])
    app=FastAPI()
    def service(request):
        if request.headers.get("X-BSV-Service-Token")!="isolated-service":raise HTTPException(403)
    app.include_router(d_router(worker,authenticate_service=service))
    try:
        yield worker,app,connect,now,identities,fail_event
    finally:
        with connect() as c:
            c.execute("DROP SCHEMA supply CASCADE")
            c.execute("DROP SCHEMA fixture_support CASCADE")


def test_real_postgres_complete_candidate_transaction(scenario):
    worker,app,connect,now,identities,fail_event=scenario
    def headers(actor):
        return {"Authorization":"Bearer "+actor,"X-BSV-Service-Token":"isolated-service"}
    def command(op,actor="hq",expected=200,**body):
        if op!="plan-preview":body.setdefault("request_id",rid())
        with TestClient(app) as client:
            response=client.post("/supply/central/v1/"+op,json=body,headers=headers(actor))
        assert response.status_code==expected,response.text
        if expected==200:
            result=response.json()
            assert result["state"]==("PREVIEW" if op=="plan-preview" else "COMMITTED")
            return result["data"]
        return response
    def read(kind,actor="hq",expected=200,**params):
        with TestClient(app) as client:
            response=client.get("/supply/central/v1/"+kind,params=params,headers=headers(actor))
        assert response.status_code==expected,response.text
        return response.json()
    with TestClient(app) as client:
        assert client.get("/supply/central/v1/inventory",params={"store_id":"BSVS"},headers={"Authorization":"Bearer hq"}).status_code==403
    eta=(now[0]+timedelta(hours=3)).isoformat()
    plan_inputs=dict(source_store_id="WH",dest_store_id="BSVS",item_id="SYNTH-P",next_delivery_at=eta,
                     usage_before_next="0",reserved="0",demand_next_cycle="800",safety_stock="0")
    assert command("plan-preview",**plan_inputs)["packages"]==2
    plan=command("plan",**plan_inputs)
    body=dict(plan_id=plan["plan_id"],produced_at=now[0].isoformat(),recipe_version="R1",
              ingredient_lot_ids=["LOT-1"],total="800",package_amounts=["450","350"],remainder="0",loss="0",request_id=rid())
    fail_event[0]=True
    command("batch",expected=503,**body)
    with connect() as c:
        assert c.execute("SELECT remaining FROM fixture_support.raw_lot").fetchone()[0]==4000
        assert c.execute("SELECT count(*) FROM supply.shipment_package").fetchone()[0]==0
    fail_event[0]=False
    batch=command("batch",**body)
    assert command("batch",**body)==batch
    first,second=[x["package_id"] for x in batch["packages"]]
    with connect() as c:
        assert c.execute("SELECT remaining FROM fixture_support.raw_lot").fetchone()[0]==3200
    print_id=rid()
    command("label",request_id=print_id,package_ids=[first,second],store_id="WH",operation="PRINT")
    command("label",package_ids=[first,second],store_id="WH",operation="CONFIRM",print_request_id=print_id)
    assert len(read("labels",store_id="WH")["history"])==4
    create=dict(source_store_id="WH",dest_store_id="BSVS",package_ids=[first,second],eta=eta,request_id=rid())
    ship=command("create",**create); sid=ship["id"]
    command("prepare",shipment_id=sid,expected_version=1)
    sent=command("dispatch",shipment_id=sid,expected_version=2,scanned_codes=[first,second])
    assert sent["state"]=="DISPATCHED"
    assert command("create",**create)==ship
    receive=dict(shipment_id=sid,expected_version=3,accepted_ids=[first],hold_ids=[],exception_reasons={},request_id=rid())
    command("receive",actor="other",expected=403,**receive)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one,two=pool.map(lambda _:command("receive",actor="shop",**receive),[1,2])
    assert one==two and one["state"]=="PARTIAL_RECEIVED"
    command("receive",actor="shop",expected=409,**{**receive,"request_id":rid()})
    closed=command("receive",actor="shop",shipment_id=sid,expected_version=4,accepted_ids=[],hold_ids=[second],
                   exception_reasons={second:"synthetic temperature failure"})
    assert closed["state"]=="RECEIVED"
    current=read("inventory",actor="shop",store_id="BSVS")["packages"]
    p=next(x for x in current if x["package_id"]==first)
    held=next(x for x in current if x["package_id"]==second)
    assert p["usable"] and not held["usable"] and held["state"]=="HOLD"
    assert read("inventory",actor="foreign",store_id="BSVS")["packages"]==[]
    read("shipment",actor="foreign",shipment_id=sid,expected=404)
    opened=command("open",actor="shop",store_id="BSVS",package_id=first,expected_version=p["version"])
    amount=dict(store_id="BSVS",package_id=first,expected_version=opened["version"],amount="120",request_id=rid())
    consumed=command("consume",actor="shop",**amount)
    assert Decimal(consumed["remaining"])==330 and consumed["usable"]
    assert command("consume",actor="shop",**amount)==consumed
    command("consume",actor="shop",expected=409,**{**amount,"request_id":rid(),"expected_version":consumed["version"],"amount":"331"})
    identities["shop"]["role_stores"]={}
    command("consume",actor="shop",expected=403,**amount)
    identities["shop"]["role_stores"]={"receive":["BSVS"]}
    now[0]+=timedelta(hours=1)
    command("consume",actor="shop",expected=409,**{**amount,"request_id":rid(),"expected_version":consumed["version"]})
    disposed=command("dispose",actor="shop",store_id="BSVS",package_id=second,expected_version=held["version"],amount="350",reason="synthetic disposal")
    assert disposed["state"]=="SCRAPPED"
    history=read("shipment",actor="shop",shipment_id=sid)
    assert sum(Decimal(x["accepted"]) for x in history["receipts"])==450
    assert sum(Decimal(x["held"]) for x in history["receipts"])==350
    assert any(x["kind"]=="EXPIRY_REVIEW" for x in read("tasks",actor="shop",store_id="BSVS",phase="END")["tasks"])
    with connect() as c:
        assert c.execute("SELECT sum(qty_base) FROM supply.movement WHERE central_kind='CONSUMED'").fetchone()[0]==120
        assert c.execute("SELECT count(*) FROM fixture_support.events WHERE operation='consume'").fetchone()[0]==1
        assert c.execute("SELECT sum(remaining_base) FROM supply.shipment_package").fetchone()[0]==330
