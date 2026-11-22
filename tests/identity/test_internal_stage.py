"""Real ingress, POS, supply and identity sockets over disposable PostgreSQL 17."""
from contextlib import contextmanager
import base64
import hashlib
import hmac
from dataclasses import replace
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest

from services.api.identity import api
from .conftest import admin_post, create_person, grant_action, onboard
from .test_consumers import certificate, identity_http

ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / "platform/lighthouse/internal-stage"


def test_internal_ingress_has_no_pos_catchall():
    """Route ownership is explicit before touching any backend or database."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("bsv_a1_ingress", STAGE / "ingress.py")
    ingress = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ingress)
    for path, owner in (
        ("/hq", "identity"), ("/hq/stores/layout", "pos"),
        ("/staff", "identity"), ("/pos", "pos"),
        ("/api/hq/layout/revision", "pos"), ("/api/state", "pos"),
        ("/api/v1/identity/registrations", "identity"),
        ("/supply-ui/api/me", "supply"),
    ):
        resolved = ingress.upstream(path)
        assert resolved and resolved[0] == owner, (path, resolved)
    for path in (
        "/totally-unknown", "/hq/random", "/hq/stores/layout/assets/no.js",
        "/api/unknown", "/work/craft", "/pos/unknown", "/supply-ui",
    ):
        assert ingress.upstream(path) is None, path
    assert ingress.routed_methods("/api/orders/submit") == {"POST"}
    assert ingress.routed_methods("/api/hq/layout/revision") == {"GET", "HEAD"}


@contextmanager
def process(argv, port_env, env, tmp_path, name):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {**os.environ, **env, port_env: str(port), "PYTHONPATH": str(ROOT)}
    logfile = tmp_path / (name + ".log")
    command = [str(port) if arg == "$PORT" else str(arg) for arg in argv]
    with logfile.open("w") as log:
        child = subprocess.Popen(command, env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(80):
                if child.poll() is not None:
                    break
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        yield port
                        return
                except ConnectionRefusedError:
                    time.sleep(0.1)
            pytest.fail(f"{name} did not start: {logfile.read_text()}")
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=15)


def test_internal_stage_live_ingress(identity_http, tmp_path, monkeypatch):
    supply_python = os.environ.get("BSV_STAGE_SUPPLY_PYTHON")
    if not supply_python or not os.environ.get("BSV_DB_PREFLIGHT_CLIENT_URL"):
        pytest.skip("Run the dedicated isolated PG17 and independent supply-venv job")
    assert api.router.a.dialect.name == "postgresql"
    person, first, second, tr, _ = create_person("internal-stage-user")
    onboard(tr, first, second, bm=True)
    certificate(tr, first, "SUPPLY_SAFETY")
    certificate(tr, first, "QUALITY_INSPECTOR")
    grant_action(tr, first, second, "learning.course.read", store="BSVT", role="staff")
    pos_grant = grant_action(tr, first, second, "pos.order.read")
    grant_action(tr, first, second, "pos.order.create")
    growth_grant = grant_action(tr, first, second, "marketing.task.write")
    supply_grant = grant_action(tr, first, second, "supply.receive")
    inspection_grant = grant_action(tr, first, second, "quality.independent.submit")
    actions = ["supply.receive", "quality.independent.submit"]
    tokens = {
        "pos": {"token": "test-local-pos", "actions": ["pos.order.read", "pos.order.create"],
                "legal_entities": ["DEMO_LEGAL"], "stores": ["BSVT"]},
        "supply": {"token": "test-local-supply", "actions": actions, "stores": ["BSVT", "BSVS"],
                   "legal_entity_id": "DEMO_LEGAL", "isolated_test_department": "SYNTH-STAGE"},
    }
    monkeypatch.setattr(api, "settings", replace(api.settings, service_tokens=tokens))
    alias = admin_post(second, "/api/v1/identity/legacy-import/commit", {
        "legal_entity_id": "DEMO_LEGAL", "rows": [{"tr_code": tr, "source_system": "bsv1_pos",
                                                  "legacy_value": "SYNTH-STAGE-POS-01"}],
        "reason": "isolated internal staging test", "evidence_ref": "SYNTHETIC-TEST",
    })
    assert alias.status_code == 200, alias.text

    data = tmp_path / "bsv-all-internal-stage" / "pos"
    data.mkdir(parents=True)
    env = {"BSV_MODE": "staging", "BSV_DB_PATH": str(data / "synthetic.sqlite3"),
           "BSV_V9_XLSX": str(data / "synthetic-v9.xlsx"), "BSV_STAGE_POS_PIN": "81351593300",
           "BSV_PRIVATE_SSH_TUNNEL": "1", "BSV_POS_INTERNAL_STAGE": "1",
           "BSV_POS_STORE_LEGAL_JSON": '{"BSVT":"DEMO_LEGAL"}', "BSV_POS_IDENTITY_URL": identity_http,
           "BSV_POS_IDENTITY_TOKEN": "test-local-pos", "BSV_POS_IDENTITY_REQUIRED": "1"}
    for _ in range(2):
        subprocess.run([sys.executable, "-B", STAGE / "seed_pos.py"], check=True, env={**os.environ, **env})

    sources = json.loads((ROOT / "config/modules/supply-sources.example.json").read_text())
    for value in sources["sources"].values():
        value["primary"] = value["standby_read"] = ""
    sources["sources"]["B"]["primary"] = identity_http + "/api/v1"
    config = tmp_path / "sources.json"
    config.write_text(json.dumps(sources))
    server_args = ("--host", "127.0.0.1", "--port", "$PORT", "--no-proxy-headers")
    supply = (supply_python, "-m", "uvicorn", "services.api.supply.main:app", *server_args)
    ingress = (sys.executable, "-m", "uvicorn", "--app-dir", STAGE, "ingress:app", *server_args)
    with process((sys.executable, ROOT / "services/api/bsv1/app.py"), "BSV_PORT", env, tmp_path, "pos") as pos_port:
        with process(supply, "BSV_SUPPLY_PORT", {"BSV_MODE": "internal-stage", "BSV_SOURCES_CONFIG": str(config),
                                              "BSV_SUPPLY_STATE_DIR": str(tmp_path / "supply"),
                                              "BSV_SOURCE_B_TOKEN": "test-local-supply"}, tmp_path, "supply") as supply_port:
            with process(ingress, "BSV_STAGE_INGRESS_PORT", {"BSV_STAGE_POS_PORT": str(pos_port),
                         "BSV_STAGE_SUPPLY_PORT": str(supply_port), "BSV_STAGE_IDENTITY_PORT": identity_http.rsplit(":", 1)[1],
                          "BSV_STAGE_GROWTH_ENABLED": "1", "BSV_GROWTH_ENV": "isolated",
                          "BSV_GROWTH_TRUST_IDENTITY": "1",
                          "BSV_GROWTH_DB_URL": "sqlite:///" + str(tmp_path / "growth-candidate.sqlite3"),
                          "BSV_GROWTH_SIGNING_KEY": "ISOLATED-PG17-INTEGRATION-SIGNING-1234567890123456",
                          "BSV_GROWTH_POS_CONTEXT_KEY": "ISOLATED-POS-TASTE-SIGNING-KEY-TEST-12345678",
                          "BSV_GROWTH_IDENTITY_ME_URL": identity_http + "/api/v1/identity/me",
                          "BSV_GROWTH_LEGAL_ENTITY_ID": "DEMO_LEGAL", "BSV_GROWTH_STORE_IDS": "BSVT"},
                         tmp_path, "ingress") as port:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as browser:
                    exercise(browser, first, tr, pos_grant, supply_grant, inspection_grant, growth_grant)


def exercise(browser, first, tr, pos_grant, supply_grant, inspection_grant, growth_grant):
    base_origin = str(browser.base_url).rstrip("/")
    assert browser.get("/health/ready").json()["database"] == "A"
    assert browser.get("/", headers={"Host": "external.invalid"}).status_code == 400
    for path in ("/", "/staff", "/hq", "/pos", "/supply-ui/hq/supply",
                 "/supply-ui/inspector/supply", "/supply-ui/assets/app.js", "/cocktail/"):
        assert browser.get(path).status_code == 200, path
    assert browser.get("/craft/").status_code == 404
    for path in ("/member/", "/member/privacy", "/member/app.js",
                 "/staff/growth/", "/staff/growth/pos-entry.js", "/growth/health"):
        assert browser.get(path).status_code == 200, path
    assert browser.get("/api/v1/growth/public/config").status_code == 200
    assert browser.get("/api/v1/growth/staff/store-options").status_code == 401
    assert browser.post("/api/v1/growth/dev/staff-login", json={}).status_code == 404
    assert browser.post("/api/v1/growth/internal/payment-event", json={}).status_code == 404
    for path in ("/totally-unknown", "/hq/random",
                 "/hq/stores/layout/assets/no.js", "/api/unknown", "/work/craft"):
        assert browser.get(path).status_code == 404, path
    assert browser.post("/pos", json={}).status_code == 405
    assert browser.get("/api/orders/submit").status_code == 405
    assert browser.post("/api/hq/layout/revision", json={}).status_code == 405
    assert browser.get("/supply-ui/api/me").status_code == 401
    assert browser.get("/api/state").status_code == 401
    assert browser.post("/api/v1/identity/pos-session", json={}).status_code == 404
    assert browser.post("/api/v1/auth/isolated/login", headers={"Origin": base_origin},
                        json={"username": "internal-stage-user", "password": "example-only-password-22222"}).status_code == 200
    growth_shops = browser.get("/api/v1/growth/staff/store-options")
    assert growth_shops.status_code == 200, growth_shops.text
    assert growth_shops.json()["stores"] == ["BSVT"]
    growth_staff = browser.get("/api/v1/growth/staff/me?store_id=BSVT")
    assert growth_staff.status_code == 200, growth_staff.text
    assert growth_staff.json()["actor_tr"] == tr
    assert browser.get("/api/v1/growth/staff/me?store_id=BSVS").status_code == 422
    guest_login = browser.post("/api/v1/growth/dev/guest-login",
                               json={"subject": "synthetic-v43-guest", "store_id": "BSVT"})
    assert guest_login.status_code == 200, guest_login.text
    member_headers = {"X-Growth-CSRF": browser.cookies["bsv_growth_csrf"]}
    registration = browser.post("/api/v1/growth/public/register",
        json={"display_name": "虚构会员", "privacy_accepted": True},
        headers=member_headers)
    assert registration.status_code == 200, registration.text
    customer_id = registration.json()["customer_id"]
    repeated = browser.post("/api/v1/growth/public/register",
        json={"display_name": "重复入会", "privacy_accepted": True},
        headers=member_headers)
    assert repeated.status_code == 200 and repeated.json()["customer_id"] == customer_id
    assert browser.get("/api/v1/growth/public/me").json()["customer_id"] == customer_id
    # Even with a valid two-minute HMAC and current staff grant, POS must independently
    # attest the same visit, linked member, current shift and store ownership.
    context = {"customer_id": customer_id, "store_id": "BSVT", "visit_id": "SYNTH-VISIT-01",
               "iat": int(time.time()), "exp": int(time.time()) + 90}
    packed = base64.urlsafe_b64encode(json.dumps(context, separators=(",", ":")).encode()).decode().rstrip("=")
    key = "ISOLATED-POS-TASTE-SIGNING-KEY-TEST-12345678"
    sig = hmac.new(key.encode(), packed.encode(), hashlib.sha256).hexdigest()
    assert browser.get("/api/v1/growth/staff/guest-context",
                       params={"context": packed + "." + sig}).status_code == 503
    # Isolated visits and fake paid facts cannot become a real commission payable.
    scope = browser.get("/supply-ui/api/me")
    assert scope.status_code == 200, scope.text
    assert scope.json()["employee_id"] == "EMP" + tr[2:]
    assert scope.json()["role_stores"] == {"inspect_independent": ["BSVT"], "receive": ["BSVT"]}
    credentials = {"store_id": "BSVT", "confirmed_store_id": "BSVT", "staff_code": "STAGEPOS01", "pin": "81351593300"}
    wrong_store = dict(credentials, store_id="BSVS", confirmed_store_id="BSVS")
    assert browser.post("/api/login", json=wrong_store).status_code == 401
    login = browser.post("/api/login", json=credentials)
    assert login.status_code == 200, login.text
    state = browser.get("/api/state")
    assert state.status_code == 200, state.text
    headers = {"X-BSV-CSRF": state.json()["csrf"]}
    run_id = str(uuid4())
    seat = {"seat_id": "BSVT-SEAT-0001", "acceptance_run": run_id}
    opened = browser.post("/api/seats/open", json=seat, headers=headers)
    assert opened.status_code == 200, opened.text
    visit = opened.json()["visit_id"]
    visit_args = {"visit_id": visit, "acceptance_run": run_id}
    assert browser.post("/api/seats/open", json=seat, headers=headers).json() == {"visit_id": visit, "new": False}
    assert browser.post("/api/seats/open", json={**seat, "acceptance_run": str(uuid4())}, headers=headers).status_code == 409
    assert browser.post("/api/drafts/add", json={"visit_id": visit, "product_id": "C000001"}, headers=headers).status_code == 403
    draft = browser.post("/api/drafts/add", json={**visit_args, "product_id": "C000001"}, headers=headers)
    assert draft.status_code == 200, draft.text
    assert browser.post("/api/orders/submit", json={**visit_args, "pay_now": True},
                        headers=headers).status_code == 403
    submit = browser.post("/api/orders/submit", json={**visit_args, "pay_now": False}, headers=headers)
    assert submit.status_code == 200, submit.text
    assert submit.json()["pay_now"] is False and submit.json()["payment_verified"] is False
    assert browser.post("/api/visits/cancel", json={**visit_args, "acceptance_run": str(uuid4())},
                        headers=headers).status_code == 403
    assert browser.post("/api/visits/cancel", json={"visit_id": visit}, headers=headers).status_code == 403
    for _ in range(2):
        archived = browser.post("/api/visits/cancel", json=visit_args, headers=headers)
        assert archived.json() == {"ok": True, "archived": True, "visit_id": visit}
    receipt = browser.get("/api/receipt", params={"visit_id": visit})
    assert receipt.status_code == 200 and receipt.json()["visit"]["status"] == "CANCELLED"
    assert len(receipt.json()["visit"]["lines"]) == 1
    assert not receipt.json()["visit"]["checkouts"]
    assert browser.post("/api/seats/open", json=seat, headers=headers).status_code == 409
    next_seat = {**seat, "acceptance_run": str(uuid4())}
    next_visit = browser.post("/api/seats/open", json=next_seat, headers=headers)
    assert next_visit.json()["new"] is True
    assert browser.post("/api/visits/cancel", json={"visit_id": next_visit.json()["visit_id"],
                        "acceptance_run": next_seat["acceptance_run"]}, headers=headers).status_code == 200

    inspection = {"request_id": "2a898042-f13f-48aa-a89b-357c514dc39b", "store_id": "BSVT",
                  "kind": "independent", "results": {}}
    assert browser.post("/supply-ui/api/inspections", json=inspection).status_code == 403
    csrf = {"X-CSRF-Token": browser.cookies["bsv_csrf"], "Origin": base_origin}
    assert browser.post("/supply-ui/api/inspections", json=inspection,
                        headers=dict(csrf, Origin="https://external.invalid")).status_code == 403
    assert browser.post("/supply-ui/api/inspections", json=dict(inspection, store_id="BSVS"),
                        headers=csrf).status_code == 403
    blocked = browser.post("/supply-ui/api/inspections", json=inspection, headers=csrf)
    assert blocked.status_code == 503 and "未提交且未排队" in blocked.text
    if os.getenv("BSV_STAGE_BROWSER") == "1":
        ui = runpy.run_path(str(ROOT / "tests/ui/stage_browser.py"))
        ui["check"](str(browser.base_url), username="internal-stage-user",
                    password="example-only-password-22222", expected_tr=tr)

    for grant in (supply_grant, inspection_grant, pos_grant):
        assert admin_post(first, f"/api/v1/identity/grants/{grant}/revoke",
                          {"legal_entity_id": "DEMO_LEGAL", "reason": "isolated staging revoke"}).status_code == 200
    assert browser.get("/supply-ui/api/me").status_code == 403
    assert browser.get("/api/state").status_code == 401
    assert browser.post("/api/v1/auth/logout", json={}, headers=csrf).status_code == 200
    assert browser.get("/api/state").status_code == 401
