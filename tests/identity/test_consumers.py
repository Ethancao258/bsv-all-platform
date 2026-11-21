"""Exercise shared identity against the existing POS and supply HTTP handlers."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import http.client
import importlib
import json
from pathlib import Path
import runpy
import secrets
import threading
from uuid import uuid4

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import select

from domains.workforce.identity.models import AuditEvent, AuthLink, LegacyAlias, now
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
    normalized={**base,"rows":[{"source_system":" bsv1_pos ","legacy_value":" SYNTH-OLD ","tr_code":tr.lower()}]}
    committed=admin_post(two,path+"commit",{**normalized,"evidence_ref":"SYNTH-EVIDENCE","reason":"Approved legacy mapping"})
    assert committed.status_code == 200, committed.text
    assert admin_post(one,path+"dry-run",base).json()["records"][0]["issues"] == ["ALREADY_MAPPED"]
    ids=committed.json()["created_alias_ids"]
    undone=admin_post(two,path+"rollback",{"alias_ids":ids,"legal_entity_id":"DEMO_LEGAL","reason":"Isolated rollback check"})
    assert undone.json() == {"removed":1,"identities_changed":False}
    assert admin_post(one,path+"dry-run",base).json()["records"][0]["issues"] == []
    with api.router.session() as db:
        assert db.scalar(select(AuthLink).where(AuthLink.tr_code==tr))



def test_same_legacy_mapping_retries_and_conflicts_over_http(identity_http, monkeypatch):
    _, one, two, tr, _ = create_person("legacyretry")
    endpoint = identity_http + "/api/v1/identity/legacy-import/commit"
    row = {"source_system": "bsv1_pos", "legacy_value": "SYNTH-STAGE-POS-01", "tr_code": tr}
    base = {"legal_entity_id": "DEMO_LEGAL", "rows": [row],
            "reason": "Retry the exact synthetic alias", "evidence_ref": "ISOLATED-REPLAY"}

    def submit(reviewer, payload=base):
        return httpx.post(endpoint, json=payload, cookies=dict(reviewer.cookies),
                          headers={"X-CSRF-Token": reviewer.cookies["bsv_csrf"]}, timeout=10, trust_env=False)

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(submit, (one, two)))
    assert [r.status_code for r in outcomes] == [200, 200]
    created, unchanged = sorted([r.json() for r in outcomes], key=lambda result: -result["write_count"])
    assert created["write_count"] == 1 and created["already_mapped_count"] == 0
    assert unchanged["write_count"] == 0 and unchanged["already_mapped_count"] == 1
    assert unchanged["created_alias_ids"] == []
    assert unchanged["records"] == [{**row, "status": "reviewed", "issues": ["ALREADY_MAPPED"]}]
    conflicts = [dict(row, tr_code="TRA0001"), dict(row, legacy_value="OTHER-SYNTH-ALIAS")]
    assert submit(one, {**base, "rows": conflicts}).status_code == 409
    with api.router.session() as db:
        assert [(r.legacy_value, r.tr_code) for r in db.scalars(select(LegacyAlias))] == [(row["legacy_value"], tr)]
        logged = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "legacy.alias.committed")).all()
        assert len(logged) == 1
    monkeypatch.setattr(api, "settings", replace(api.settings, env="production"))
    denied = submit(one)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "MIGRATION_LOCKED"


def test_hq_layout_read_uses_identity_a_and_never_writes_pos_sqlite(identity_http, tmp_path, monkeypatch):
    user, one, two, tr, _ = create_person("hqmap-read-http")
    onboard(tr, one, two, bm=True)
    grant_action(tr, one, two, "hq.layout.read", store=None, role="hq")
    fixture = tmp_path / "hq-read.xlsx"
    runpy.run_path(str(ROOT / "tests/bsv1/make_fixture.py"))["write_fixture"](fixture)
    monkeypatch.setenv("BSV_V9_XLSX", str(fixture))
    monkeypatch.setenv("BSV_DB_PATH", str(tmp_path / "hq-read.sqlite3"))
    monkeypatch.setenv("BSV_MODE", "staging")
    monkeypatch.setenv("BSV_APP_ENV", "isolated")
    monkeypatch.setenv("BSV_POS_LAYOUT_SCOPE_MODE", "isolated-synthetic")
    monkeypatch.setenv("BSV_POS_STORE_LEGAL_JSON", '{"BSVT":"DEMO_LEGAL"}')
    monkeypatch.syspath_prepend(str(ROOT / "services/api/bsv1"))
    pos = importlib.import_module("services.api.bsv1.app")
    monkeypatch.setattr(pos, "DB_PATH", tmp_path / "hq-read.sqlite3")
    monkeypatch.setattr(pos, "MODE", "staging")
    pos.init_db()
    layout_token = "synthetic-layout-read-token-1234567890"
    service = {"token": layout_token, "actions": ["hq.layout.read"],
               "legal_entities": ["DEMO_LEGAL"], "stores": ["BSVT"]}
    monkeypatch.setattr(api, "settings", replace(api.settings,
        service_tokens={**api.settings.service_tokens, "layout-admin": service}))
    monkeypatch.setenv("BSV_POS_IDENTITY_URL", identity_http)
    monkeypatch.setenv("BSV_POS_LAYOUT_SERVICE_TOKEN", layout_token)
    monkeypatch.setenv("BSV_POS_IDENTITY_REQUIRED", "1")
    with pos.db_read() as db:
        before = db.execute("SELECT COUNT(*) FROM bsv_layout_revisions").fetchone()[0]
    with pos.ThreadingHTTPServer(("127.0.0.1", 0), pos.Handler) as server:
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            connection = http.client.HTTPConnection(*server.server_address, timeout=5)
            cookie = f"{api.SESSION_COOKIE}={user.cookies.get(api.SESSION_COOKIE)}"
            connection.request("GET", "/api/hq/layout?store_id=BSVT", headers={"Cookie": cookie})
            response = connection.getresponse()
            payload = json.loads(response.read())
            assert response.status == 200, payload
            assert payload["store_id"] == "BSVT"
            connection.request("GET", "/api/hq/layout?store_id=BSVS", headers={"Cookie": cookie})
            denied = connection.getresponse()
            denied.read()
            assert denied.status == 403

            # Exercise every existing HQ read endpoint under the same live
            # identity.A session. No new SQLite writer or POS login involved.
            def read_hq(url, *, authorized=True):
                headers = {"Cookie": cookie} if authorized else {}
                connection.request("GET", url, headers=headers)
                result = connection.getresponse()
                body = result.read()
                return result, body

            status, body = read_hq("/api/hq/status")
            assert status.status == 200
            assert json.loads(body)["actor"] == tr

            stores, body = read_hq("/api/hq/stores")
            assert stores.status == 200
            assert [item["id"] for item in json.loads(body)["stores"]] == ["BSVT"]

            modules, body = read_hq("/api/hq/modules")
            assert modules.status == 200
            assert isinstance(json.loads(body)["modules"], list)

            art, body = read_hq("/api/hq/art?store_id=BSVT")
            assert art.status == 200 and body
            assert art.getheader("X-Content-Type-Options") == "nosniff"
            assert art.getheader("Content-Security-Policy") == (
                "sandbox; default-src 'none'; style-src 'unsafe-inline'"
            )
            assert art.getheader("Cache-Control") == "private, no-store"

            missing_image, body = read_hq(
                "/api/hq/image?store_id=BSVT&asset_id=IMG-missing"
            )
            assert missing_image.status == 404
            assert json.loads(body)["error"]

            for other_store_path in (
                "/api/hq/art?store_id=BSVS",
                "/api/hq/image?store_id=BSVS&asset_id=IMG-missing",
            ):
                denied_path, _ = read_hq(other_store_path)
                assert denied_path.status == 403
            anonymous, _ = read_hq("/api/hq/layout?store_id=BSVT",
                                   authorized=False)
            assert anonymous.status == 401
            unknown, _ = read_hq("/api/hq/not-a-real-route?store_id=BSVT")
            assert unknown.status == 403

            # A caller cannot self-select the synthetic scope in production-
            # style mode, or point the trusted identity client at a dead A.
            monkeypatch.setenv("BSV_POS_LAYOUT_SCOPE_MODE", "disabled")
            no_scope, _ = read_hq("/api/hq/layout?store_id=BSVT")
            assert no_scope.status == 403
            monkeypatch.setenv("BSV_POS_LAYOUT_SCOPE_MODE", "isolated-synthetic")
            monkeypatch.setenv("BSV_POS_IDENTITY_URL", "http://127.0.0.1:1")
            offline, _ = read_hq("/api/hq/layout?store_id=BSVT")
            assert offline.status == 503
            monkeypatch.setenv("BSV_POS_IDENTITY_URL", identity_http)

            monkeypatch.delenv("BSV_POS_LAYOUT_SERVICE_TOKEN")
            connection.request("GET", "/api/hq/layout?store_id=BSVT", headers={"Cookie": cookie})
            unavailable = connection.getresponse()
            unavailable.read()
            assert unavailable.status == 503
            connection.close()
        finally:
            server.shutdown()
            worker.join(5)
    with pos.db_read() as db:
        after = db.execute("SELECT COUNT(*) FROM bsv_layout_revisions").fetchone()[0]
    assert after == before


def test_hq_layout_draft_isolated_edit_grant_audit_and_no_pos_access(identity_http, tmp_path, monkeypatch):
    from domains.workforce.identity.models import Grant

    user, one, two, tr, _ = create_person("hqmap-draft-http")
    onboard(tr, one, two, bm=True)
    fixture = tmp_path / "hq-draft.xlsx"
    runpy.run_path(str(ROOT / "tests/bsv1/make_fixture.py"))["write_fixture"](fixture)
    monkeypatch.setenv("BSV_V9_XLSX", str(fixture))
    monkeypatch.setenv("BSV_DB_PATH", str(tmp_path / "hq-draft.sqlite3"))
    monkeypatch.setenv("BSV_MODE", "staging")
    monkeypatch.setenv("BSV_APP_ENV", "isolated")
    monkeypatch.setenv("BSV_POS_LAYOUT_SCOPE_MODE", "isolated-synthetic")
    monkeypatch.setenv("BSV_POS_STORE_LEGAL_JSON", '{"BSVT":"DEMO_LEGAL","BSVS":"DEMO_LEGAL"}')
    monkeypatch.syspath_prepend(str(ROOT / "services/api/bsv1"))
    pos = importlib.import_module("services.api.bsv1.app")
    monkeypatch.setattr(pos, "DB_PATH", tmp_path / "hq-draft.sqlite3")
    monkeypatch.setattr(pos, "MODE", "staging")
    pos.init_db()

    # Backfill the newly defined alias schema on an already valid canonical
    # SQLite database, with an atomic pre-migration backup.
    import sqlite3
    with pos.db_read() as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='bsv_hq_actor_aliases'").fetchone()
    with pos.tx() as db:
        db.execute("DROP TABLE bsv_hq_actor_aliases")
    backups_before = set(tmp_path.glob("*总部地图审计表迁移前备份*.sqlite3"))
    pos.init_db()
    backups_after = set(tmp_path.glob("*总部地图审计表迁移前备份*.sqlite3"))
    created_backups = backups_after - backups_before
    assert len(created_backups) == 1
    with sqlite3.connect(str(next(iter(created_backups)))) as snapshot:
        assert snapshot.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert snapshot.execute(
            "SELECT 1 FROM sqlite_master WHERE name='bsv_hq_actor_aliases'"
        ).fetchone() is None
    with pos.db_read() as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='bsv_hq_actor_aliases'").fetchone()
        assert db.execute("PRAGMA user_version").fetchone()[0] == 28

    layout_token = "synthetic-layout-edit-token-1234567890"
    service = {"token": layout_token, "actions": ["hq.layout.read", "hq.layout.edit"],
               "legal_entities": ["DEMO_LEGAL"], "stores": ["BSVT", "BSVS"]}
    monkeypatch.setattr(api, "settings", replace(api.settings,
        service_tokens={**api.settings.service_tokens, "layout-admin": service}))
    monkeypatch.setenv("BSV_POS_IDENTITY_URL", identity_http)
    monkeypatch.setenv("BSV_POS_LAYOUT_SERVICE_TOKEN", layout_token)
    monkeypatch.setenv("BSV_POS_IDENTITY_REQUIRED", "1")

    with pos.db_read() as db:
        formal_before = pos.bsv_one.current(db, "BSVT")
        revisions_before = db.execute("SELECT COUNT(*) FROM bsv_layout_revisions").fetchone()[0]
        work_access_before = db.execute("SELECT COUNT(*) FROM staff_store_access").fetchone()[0]

    with pos.ThreadingHTTPServer(("127.0.0.1", 0), pos.Handler) as server:
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        identity_cookie = (f"{api.SESSION_COOKIE}={user.cookies.get(api.SESSION_COOKIE)}; "
                           f"bsv_csrf={user.cookies.get('bsv_csrf')}")
        csrf = user.cookies.get("bsv_csrf")
        origin = f"http://127.0.0.1:{server.server_address[1]}"

        def save(store_id="BSVT", *, include_csrf=True):
            with pos.db_read() as db:
                current = pos.bsv_one.current(db, store_id)
            layout = current["layout"]
            if layout["seats"]:
                layout["seats"][0]["x"] = min(99, layout["seats"][0]["x"] + 1)
            headers = {"Cookie": identity_cookie, "Content-Type": "application/json", "Origin": origin}
            if include_csrf:
                headers["X-CSRF-Token"] = csrf
            connection.request("POST", "/api/hq/layout/draft", json.dumps({
                "store_id": store_id, "layout": layout, "base_version": current["version"],
            }), headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())

        try:
            # A real identity with no edit Grant, a cross-store scope, and a missing CSRF all fail before SQLite writes.
            denied, _ = save()
            assert denied == 403
            assert save("BSVS")[0] == 403
            assert save(include_csrf=False)[0] == 403
            with pos.db_read() as db:
                assert db.execute("SELECT COUNT(*) FROM bsv_layout_revisions").fetchone()[0] == revisions_before
                assert db.execute("SELECT COUNT(*) FROM staff_store_access").fetchone()[0] == work_access_before

            grant_id = grant_action(tr, one, two, "hq.layout.edit", store="BSVT", role="hq")
            status, body = save()
            assert status == 200, body
            assert body["ok"] is True
            with pos.db_read() as db:
                revision = db.execute("SELECT * FROM bsv_layout_revisions WHERE revision_id=?",
                                      (body["revision_id"],)).fetchone()
                audit_staff = db.execute("SELECT * FROM staff WHERE id=?", (revision["created_by"],)).fetchone()
                alias = db.execute("SELECT tr_code,staff_id FROM bsv_hq_actor_aliases WHERE tr_code=?", (tr,)).fetchone()
                assert revision["status"] == "DRAFT"
                assert alias["staff_id"] == revision["created_by"]
                assert audit_staff["staff_code"] == tr and audit_staff["role"] == "STAFF"
                assert audit_staff["enabled"] == 0
                assert db.execute("SELECT 1 FROM staff_store_access WHERE staff_id=?", (audit_staff["id"],)).fetchone() is None
                assert db.execute("SELECT 1 FROM bsv_hq_roles WHERE staff_id=?", (audit_staff["id"],)).fetchone() is None
                event = db.execute("SELECT actor_staff_id,payload_json FROM bsv_platform_events "
                                   "WHERE action='SAVE_DRAFT' AND entity_id='BSVT' ORDER BY event_id DESC LIMIT 1").fetchone()
                assert event["actor_staff_id"] == revision["created_by"]
                assert json.loads(event["payload_json"])["actor_tr_code"] == tr
                assert db.execute("SELECT COUNT(*) FROM staff_store_access").fetchone()[0] == work_access_before
                assert pos.bsv_one.current(db, "BSVT") == formal_before
                assert db.execute("SELECT COUNT(*) FROM bsv_layout_revisions").fetchone()[0] == revisions_before + 1

            connection.request("POST", "/api/hq/layout/publish", json.dumps({
                "store_id": "BSVT", "revision_id": body["revision_id"],
            }), {"Cookie": identity_cookie, "Content-Type": "application/json", "Origin": origin,
                "X-CSRF-Token": csrf})
            publish = connection.getresponse()
            publish.read()
            assert publish.status in (401, 403)

            with api.router.session(write=True) as db:
                db.get(Grant, grant_id).status = "revoked"
            revoked, _ = save()
            assert revoked == 403
            with pos.db_read() as db:
                assert db.execute("SELECT COUNT(*) FROM bsv_layout_revisions").fetchone()[0] == revisions_before + 1
                assert db.execute("SELECT COUNT(*) FROM staff_store_access").fetchone()[0] == work_access_before
            connection.close()
        finally:
            server.shutdown()
            worker.join(5)
