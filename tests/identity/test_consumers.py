"""Exercise shared identity against the existing POS and supply HTTP handlers."""
from dataclasses import replace
from datetime import timedelta
import http.client
import importlib
import json
from pathlib import Path
import runpy
import secrets
import threading
from uuid import uuid4

import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import select

from domains.workforce.identity.models import AuthLink, LegacyAlias, now
from services.api.identity import api
from .conftest import admin_post, create_person, grant_action, onboard

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def identity_http():
    config = uvicorn.Config(api.app, host="127.0.0.1", port=0, log_level="warning", access_log=False)
    listener = config.bind_socket()
    server = uvicorn.Server(config)
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
    worker.start()
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        server.should_exit = True
        worker.join(10)
        listener.close()


def certificate(tr, one, code):
    response = admin_post(one, "/api/v1/identity/qualifications", {
        "tr_code":tr, "legal_entity_id":"DEMO_LEGAL","qualification_code":code,
        "learning_credential_id":"synthetic-" + code + tr, "source_evidence_ref":"SYNTH-COURSE",
        "effective_from":(now()-timedelta(minutes=5)).isoformat(),
    })
    assert response.status_code == 201, response.text


def test_live_pos_login_requires_group_scope_and_revocation(identity_http, tmp_path, monkeypatch):
    user, one, two, tr, _ = create_person("posconsumer")
    fixture = tmp_path / "synthetic.xlsx"
    runpy.run_path(str(ROOT / "tests/bsv1/make_fixture.py"))["write_fixture"](fixture)
    monkeypatch.setenv("BSV_V9_XLSX", str(fixture))
    monkeypatch.setenv("BSV_DB_PATH", str(tmp_path / "pos.sqlite3"))
    monkeypatch.setenv("BSV_MODE", "local")
    monkeypatch.syspath_prepend(str(ROOT / "services/api/bsv1"))
    pos = importlib.import_module("services.api.bsv1.app")
    monkeypatch.setattr(pos, "DB_PATH", tmp_path / "pos.sqlite3")
    pos.init_db()
    staff_id, salt, pin = uuid4().hex, secrets.token_bytes(16), "458291"
    with pos.tx() as db:
        db.execute("INSERT INTO staff(id,staff_code,pin_salt,pin_digest,role,enabled) VALUES (?,?,?,?,?,1)",
                   (staff_id,"SYNTH-POS",salt.hex(),pos.pin_hash(pin,salt),"MANAGER"))
        db.execute("INSERT INTO staff_store_access(staff_id,store_id) VALUES (?,?)",(staff_id,"BSVT"))
        db.execute("INSERT INTO bsv_hq_roles(staff_id,role,granted_at) VALUES (?,'HQ_ADMIN',?)",(staff_id,pos.bsv_one.now()))
        staff = dict(db.execute("SELECT * FROM staff WHERE id=?",(staff_id,)).fetchone())
        layout = pos.bsv_one.current(db,"BSVT")
        draft = pos.bsv_one.draft(db,staff,"BSVT",layout["layout"],layout["version"])
        pos.bsv_one.publish(db,staff,"BSVT",draft["revision_id"])
    with api.router.session(write=True) as db:
        db.add(LegacyAlias(legal_entity_id="DEMO_LEGAL",source_system="bsv1_pos",legacy_value=staff_id,
                          tr_code=tr,approved_by="synthetic",evidence_ref="TEST"))
    ticket = user.cookies.get(api.SESSION_COOKIE)
    token = secrets.token_urlsafe(32)
    monkeypatch.setattr(api, "settings", replace(api.settings, service_tokens={"pos":{
        "token":token,"actions":["pos.order.read","pos.order.create"],
        "legal_entities":["DEMO_LEGAL"],"stores":["BSVT"]}}))
    monkeypatch.setenv("BSV_POS_IDENTITY_REQUIRED","1")
    monkeypatch.setenv("BSV_POS_IDENTITY_URL",identity_http)
    monkeypatch.setenv("BSV_POS_IDENTITY_TOKEN",token)
    monkeypatch.setenv("BSV_POS_STORE_LEGAL_JSON",'{"BSVT":"DEMO_LEGAL"}')
    with pos.ThreadingHTTPServer(("127.0.0.1",0),pos.Handler) as server:
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        cookie = f"{api.SESSION_COOKIE}={ticket}"
        csrf = ""
        conn = http.client.HTTPConnection(*server.server_address,timeout=5)
        def request(path, body=None):
            conn.request("GET" if body is None else "POST",path,
                         None if body is None else json.dumps(body),
                         {"Cookie":cookie,"Content-Type":"application/json","X-BSV-CSRF":csrf})
            result=conn.getresponse()
            return result.status,dict(result.getheaders()),json.loads(result.read())
        try:
            payload={"store_id":"BSVT","confirmed_store_id":"BSVT","staff_code":"SYNTH-POS","pin":pin}
            assert request("/api/login",payload)[0] == 403
            onboard(tr,one,two)
            certificate(tr,one,"POS_SERVICE")
            grant_action(tr,one,two,"pos.order.read")
            grant_action(tr,one,two,"pos.order.create")
            status, headers, body = request("/api/login",payload)
            assert status == 200, body
            cookie += "; " + headers["Set-Cookie"].split(";",1)[0]
            csrf = request("/api/state")[2]["csrf"]
            status, _, opened = request("/api/seats/open",{"seat_id":"BSVT-SEAT-0001"})
            assert status == 200, opened
            assert request("/api/drafts/add",{"visit_id":opened["visit_id"],"product_id":"C000001"})[0] == 200
            assert request("/api/orders/submit",{"visit_id":opened["visit_id"],"pay_now":False})[0] == 200
            assert admin_post(user,"/api/v1/auth/logout",{}).status_code == 200
            assert request("/api/state")[0] == 401
        finally:
            conn.close()
            server.shutdown()
            worker.join()


def test_supply_and_independent_inspection_use_store_scoped_identity(identity_http, tmp_path, monkeypatch):
    monkeypatch.setenv("BSV_SUPPLY_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("BSV_MODE","demo")
    from services.api.supply import main as supply
    from services.api.supply.cache import LocalCache
    from services.api.supply.gateway import Gateway

    user, one, two, tr, _ = create_person("supplyconsumer")
    onboard(tr,one,two)
    certificate(tr,one,"SUPPLY_SAFETY")
    certificate(tr,one,"QUALITY_INSPECTOR")
    grant_action(tr,one,two,"supply.dispatch",store="BSVM")
    grant_action(tr,one,two,"supply.receive",store="BSVS")
    grant_action(tr,one,two,"quality.independent.submit",store="BSVS")
    token=secrets.token_urlsafe(32)
    monkeypatch.setenv("BSV_IDENTITY_TEST_SERVICE_TOKEN",token)
    monkeypatch.setattr(api,"settings",replace(api.settings,service_tokens={"supply":{
        "token":token,"legal_entity_id":"DEMO_LEGAL","stores":["BSVS","BSVM"],
        "department_by_tr":{tr:"SYNTH-SUPPLY"},
        "actions":["supply.dispatch","supply.receive","quality.independent.submit","quality.independent.review"]}}))
    settings=replace(supply.settings,mode="remote",sources={**supply.settings.sources,
        "B":replace(supply.settings.sources["B"],primary=identity_http+"/api/v1",credential_env="BSV_IDENTITY_TEST_SERVICE_TOKEN")})
    calls=[]
    class LedgerStub(Gateway):
        def write(self,key,path,payload,*,user_token):
            calls.append((key,path))
            return {"id":"SYNTH"}
    monkeypatch.setattr(supply,"settings",settings)
    monkeypatch.setattr(supply,"demo",None)
    monkeypatch.setattr(supply,"gateway",LedgerStub(settings,LocalCache(tmp_path/"cache")))
    headers={"Authorization":"Bearer "+user.cookies.get(api.SESSION_COOKIE)}
    with TestClient(supply.app) as client:
        me=client.get("/api/me",headers=headers)
        assert me.status_code==200, me.text
        assert me.json()["employee_id"]=="EMP"+tr[2:]
        assert me.json()["role_stores"]["dispatch"]==["BSVM"]
        draft={"request_id":str(uuid4()),"source_store_id":"BSVS","dest_store_id":"BSVM",
               "lines":[{"item_id":"SYNTH-P","packages":1}]}
        assert client.post("/api/shipments",json=draft,headers=headers).status_code==403
        draft.update(source_store_id="BSVM",dest_store_id="BSVS")
        assert client.post("/api/shipments",json=draft,headers=headers).status_code==200
        ins={"request_id":str(uuid4()),"store_id":"BSVS","kind":"independent",
             "results":{key:"OK" for key in ("expiry","temperature","hygiene","equipment","pricing","previous_actions")}}
        assert client.post("/api/inspections",json=ins,headers=headers).status_code==200
        assert client.post("/api/inspections/SYNTH/review",json={
            "request_id":str(uuid4()),"decision":"APPROVED"},headers=headers).status_code==403
        assert calls==[("D","/supply/shipments"),("E","/inspections")]
        assert admin_post(user,"/api/v1/auth/logout",{}).status_code==200
        assert client.get("/api/me",headers=headers).status_code==401


def test_legacy_preflight_commit_and_isolated_rollback():
    _, one, two, tr, _ = create_person("legacyconsumer")
    base={"legal_entity_id":"DEMO_LEGAL","rows":[{"source_system":"bsv1_pos","legacy_value":"SYNTH-OLD","tr_code":tr}]}
    path="/api/v1/identity/legacy-import/"
    preview=admin_post(one,path+"dry-run",base)
    assert preview.status_code == 200 and preview.json()["write_count"] == 0
    duplicate=admin_post(one,path+"dry-run",{**base,"rows":base["rows"]*2})
    assert duplicate.json()["blocked"] == 1
    committed=admin_post(two,path+"commit",{**base,"evidence_ref":"SYNTH-EVIDENCE","reason":"Approved legacy mapping"})
    assert committed.status_code == 200, committed.text
    ids=committed.json()["created_alias_ids"]
    undone=admin_post(two,path+"rollback",{"alias_ids":ids,"legal_entity_id":"DEMO_LEGAL","reason":"Isolated rollback check"})
    assert undone.json() == {"removed":1,"identities_changed":False}
    assert admin_post(one,path+"dry-run",base).json()["records"][0]["issues"] == []
    with api.router.session() as db:
        assert db.scalar(select(AuthLink).where(AuthLink.tr_code==tr))
