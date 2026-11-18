"""Contract double backed by real PG17. It is never imported by the applications."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import os

from fastapi import HTTPException
from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from services.api.supply.gateway import Unreachable

ROOT = Path(__file__).resolve().parents[2]
ACTORS = {
    "sender": ("EMP-A", {"dispatch": ["BSVM"]}),
    "receiver": ("EMP-B", {"receive": ["BSVS"], "inspect": ["BSVS"], "inspect_independent": ["BSVS"], "review_independent": ["BSVS"]}),
    "reviewer": ("EMP-C", {"receive": ["BSVS"], "review_independent": ["BSVS"]}),
    "outsider": ("EMP-D", {"receive": ["BSVT"]}),
}


class CentralFixture:
    def __init__(self, dsn):
        self.dsn = dsn
        self.identity_up = self.ledger_up = True
        with self.connect() as db:
            db.execute((ROOT / "contracts/supply/central_schema_proposal.sql").read_text())
            db.execute((ROOT / "tests/db_preflight/quality_fixture.sql").read_text())

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def read(self, key, path, *, user_token, **_):
        if key == "B":
            if not self.identity_up:
                raise Unreachable()
            employee, grants = ACTORS[user_token]
            return {"data":{"employee_id":employee, "department_id":"SYNTH",
                            "legal_entity_id":"SYNTH", "stores":list({s for v in grants.values() for s in v}),
                            "role_stores":grants, "roles":list(grants)}}
        if not self.ledger_up:
            raise Unreachable()
        with self.connect() as db:
            row = db.execute("SELECT * FROM supply.shipment WHERE shipment_id=%s",(path.rsplit("/",1)[-1],)).fetchone()
            if not row:
                raise HTTPException(404)
            _, grants = ACTORS[user_token]
            if not {row["source_location_id"],row["dest_location_id"]} & {s for v in grants.values() for s in v}:
                raise HTTPException(403)
            packages = db.execute("SELECT package_id,item_id,state FROM supply.shipment_package WHERE shipment_id=%s ORDER BY package_id",(row["shipment_id"],)).fetchall()
            return {"data":{"shipment_id":str(row["shipment_id"]),"state":row["state"],"version":row["version"],
                            "source_store_id":row["source_location_id"],"dest_store_id":row["dest_location_id"],
                            "packages":[dict(p,package_id=str(p["package_id"])) for p in packages]},
                    "meta":{"source":"PRIMARY","stale":False}}

    def write(self, key, path, payload, *, user_token):
        if not self.ledger_up:
            raise Unreachable()
        employee, grants = ACTORS[user_token]
        rid = payload["request_id"]
        with self.connect() as db:
            if key == "E":
                if path == "/inspections":
                    if payload["store_id"] not in grants.get("inspect_independent", []):
                        raise HTTPException(403)
                    db.execute("INSERT INTO preflight_quality.inspection VALUES (%s,%s,%s,%s,%s,%s)",
                               (rid,payload["store_id"],employee,payload.get("subject_employee"),payload["kind"],Jsonb(payload["results"])))
                    return {"inspection_id":rid,"state":"RECORDED"}
                iid = path.split("/")[-2]
                row = db.execute("SELECT * FROM preflight_quality.inspection WHERE inspection_id=%s FOR UPDATE",(iid,)).fetchone()
                if (not row or row["store_id"] not in grants.get("review_independent", [])
                        or employee in (row["inspector"],row["subject_employee"]) or row["kind"] != "independent"):
                    raise HTTPException(403)
                db.execute("INSERT INTO preflight_quality.review VALUES (%s,%s,%s)",(iid,employee,payload["decision"]))
                return {"inspection_id":iid,"state":payload["decision"]}

            if path == "/supply/shipments":
                src,dest = payload["source_store_id"],payload["dest_store_id"]
                if src not in grants.get("dispatch",[]):
                    raise HTTPException(403)
                db.execute("INSERT INTO supply.shipment VALUES (%s,%s,%s,'DRAFT',1,%s,now())",(rid,src,dest,employee))
                for line in payload["lines"]:
                    for _ in range(line["packages"]):
                        db.execute("INSERT INTO supply.shipment_package VALUES (%s,%s,%s,'SYNTH-BATCH','EA',1,'DRAFT')",
                                   (uuid4(),rid,line["item_id"]))
                return {"shipment_id":rid,"state":"DRAFT","version":1}
            if path == "/inventory/counts":
                assert payload["observation"]["exact"] is False
                db.execute("""INSERT INTO supply.stock_count
                    (count_id,location_id,item_id,observer_employee_id,full_package_count,opened_count,
                     opened_bucket_pct,method,observed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'FIVE_BUCKET',now())""",
                    (rid,payload["store_id"],payload["item_id"],employee,payload["full_packages"],
                     payload["opened_count"],payload["opened_percent"]))
                return {"count_id":rid,"inventory_adjusted":False}
            sid, action = path.split("/")[-2:]
            order = db.execute("SELECT * FROM supply.shipment WHERE shipment_id=%s FOR UPDATE",(sid,)).fetchone()
            src,dest = order["source_location_id"],order["dest_location_id"]
            if (dest if action=="receive" else src) not in grants.get("receive" if action=="receive" else "dispatch", []):
                raise HTTPException(403)
            old = db.execute("SELECT fingerprint,response FROM supply.idempotent_result WHERE actor_scope=%s AND request_id=%s",(employee,rid)).fetchone()
            from hashlib import sha256
            import json
            fingerprint = sha256(json.dumps([path,payload],sort_keys=True).encode()).hexdigest()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise HTTPException(409)
                return old["response"]
            if order["version"] != payload["expected_version"]:
                raise HTTPException(409)
            packages = db.execute("SELECT * FROM supply.shipment_package WHERE shipment_id=%s",(sid,)).fetchall()
            by_id = {str(p["package_id"]):p for p in packages}
            transit = "IN_TRANSIT:"+sid
            remaining = None
            if action=="prepare" and order["state"]=="DRAFT":
                db.execute("UPDATE supply.shipment_package SET state='READY' WHERE shipment_id=%s",(sid,))
                state = "READY"
            elif action=="dispatch" and order["state"]=="READY" and set(payload["scanned_codes"])==set(by_id):
                self.post_packages(db, sid, rid, employee, by_id.values(), src, transit, "IN_TRANSIT")
                state = "DISPATCHED"
            elif action=="receive" and order["state"] in ("DISPATCHED","PARTIAL_RECEIVED"):
                codes=payload["scanned_codes"]
                if set(codes)-set(by_id) or any(by_id[code]["state"]!="IN_TRANSIT" for code in codes):
                    raise HTTPException(409)
                self.post_packages(db,sid,rid,employee,(by_id[code] for code in codes),transit,dest,"ACCEPTED")
                remaining=sum(p["state"]=="IN_TRANSIT" for p in packages)-len(codes)
                state="PARTIAL_RECEIVED" if remaining else "RECEIVED"
            else:
                raise HTTPException(409)
            result={"shipment_id":sid,"state":state,"version":order["version"]+1}
            if remaining is not None:
                result["pending_in_transit"]=remaining
            db.execute("UPDATE supply.shipment SET state=%s,version=%s WHERE shipment_id=%s",(state,result["version"],sid))
            db.execute("INSERT INTO supply.idempotent_result VALUES (%s,%s,%s,%s,now())",(employee,rid,fingerprint,Jsonb(result)))
            return result

    @staticmethod
    def post_packages(db,sid,rid,employee,packages,src,dest,state):
        for p in packages:
            db.execute("UPDATE supply.shipment_package SET state=%s WHERE package_id=%s",(state,p["package_id"]))
            db.execute("""INSERT INTO supply.movement (movement_id,request_id,shipment_id,package_id,item_id,lot_id,
                        from_location_id,to_location_id,qty_base,actor_employee_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                       (uuid4(),rid,sid,p["package_id"],p["item_id"],p["lot_id"],src,dest,p["qty_base"],employee))


def test_supply_http_postgres_contract_concurrency_and_outbox(monkeypatch,tmp_path):
    url=os.environ["BSV_DB_PREFLIGHT_CLIENT_URL"]
    assert url.endswith("/bsv_identity_isolated_clients") and "@127.0.0.1:" in url
    central=CentralFixture(url.replace("+psycopg",""))
    monkeypatch.setenv("BSV_SUPPLY_STATE_DIR",str(tmp_path))
    monkeypatch.setenv("BSV_MODE","demo")
    from services.api.supply import main
    from services.api.supply.cache import LocalCache
    monkeypatch.setattr(main,"settings",replace(main.settings,mode="remote"))
    monkeypatch.setattr(main,"demo",None)
    monkeypatch.setattr(main,"cache",LocalCache(tmp_path/"queue"))
    monkeypatch.setattr(main,"gateway",central)

    def get(path,actor):
        with TestClient(main.app) as client:
            return client.get(path,headers={"Authorization":"Bearer "+actor})

    def post(path,actor,**data):
        with TestClient(main.app) as client:
            return client.post(path,json=data,headers={"Authorization":"Bearer "+actor})

    draft=post("/api/shipments","sender",request_id=str(uuid4()),source_store_id="BSVM",
               dest_store_id="BSVS",lines=[{"item_id":"P000015","packages":10}])
    assert draft.status_code==200,draft.text
    sid=draft.json()["data"]["id"]
    path="/api/shipments/"+sid
    assert post(path+"/prepare","sender",request_id=str(uuid4()),expected_version=1).json()["data"]["version"]==2
    detail=get(path,"receiver").json()["data"]
    assert detail["id"]==sid and (detail["src"],detail["dest"])==("BSVM","BSVS")
    codes=[p["code"] for p in detail["packages"]]
    assert post(path+"/dispatch","sender",request_id=str(uuid4()),expected_version=2,scanned_codes=codes).status_code==200
    body=dict(request_id=str(uuid4()),expected_version=3,scanned_codes=codes[:9])
    assert post(path+"/receive","outsider",**body).status_code==403
    central.ledger_up=False
    assert post(path+"/receive","receiver",**body).status_code==202
    assert get("/api/pending","outsider").json()==[]
    central.ledger_up=True
    direct_payload={**body,"request_id":str(uuid4())}
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending=pool.submit(post,"/api/pending/sync","receiver")
        direct=pool.submit(post,path+"/receive","reviewer",**direct_payload)
        synced,other=pending.result(),direct.result()
    assert (synced.json()["results"][0]["state"],other.status_code) in {("COMMITTED",409),("CONFLICT",200)}
    winner,winner_payload=("receiver",body) if other.status_code==409 else (
        "reviewer",direct_payload)
    retry=post(path+"/receive",winner,**winner_payload)
    assert retry.status_code==200 and retry.json()["data"]["pending_in_transit"]==1
    assert post("/api/stock-count","receiver",request_id=str(uuid4()),store_id="BSVS",
                item_id="P000015",full_packages=9,opened_count=0).json()["data"]["inventory_adjusted"] is False
    current=get(path,"receiver").json()["data"]
    assert [p["state"] for p in current["packages"]].count("ACCEPTED")==9
    assert [p["state"] for p in current["packages"]].count("IN_TRANSIT")==1
    with central.connect() as db:
        totals=db.execute("SELECT to_location_id,sum(qty_base) AS n FROM supply.movement GROUP BY 1").fetchall()
        assert {x["to_location_id"]:x["n"] for x in totals}=={"IN_TRANSIT:"+sid:10,"BSVS":9}
    ins=post("/api/inspections","receiver",request_id=str(uuid4()),store_id="BSVS",kind="independent",
             results={k:"OK" for k in ["expiry","temperature","hygiene","equipment","pricing","previous_actions"]})
    review="/api/inspections/"+ins.json()["data"]["inspection_id"]+"/review"
    assert post(review,"receiver",request_id=str(uuid4()),decision="APPROVED").status_code==403
    assert post(review,"reviewer",request_id=str(uuid4()),decision="APPROVED").status_code==200
    central.identity_up=False
    assert get("/api/me","receiver").status_code==503


def test_shipment_alias_rejects_conflicts_and_locations():
    from services.api.supply.shipment_contract import shipment_for_console
    cases=({"shipment_id":"one","id":"two"},
           {"shipment_id":"one","source_location_id":"warehouse","dest_location_id":"dock"})
    for case in cases:
        with pytest.raises(HTTPException) as error:
            shipment_for_console(case,detail=True)
        assert error.value.status_code==502
