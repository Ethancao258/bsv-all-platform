"""G1-B synthetic end-to-end identity → Academy → POS acceptance.

All writes target disposable SQLite fixtures and the identity test database.
The H-stage permissions, real company records, payment and production databases
are not used or broadened by these tests.
"""
from __future__ import annotations

import http.client
import importlib
import json
import os
import runpy
import sqlite3
import socket
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import httpx
import uvicorn

from domains.learning.academy_models import AcademyBase
from domains.workforce.identity.models import now
from services.api.identity import api
from .conftest import admin_post, create_person, grant_action, onboard

ROOT = Path(__file__).resolve().parents[2]
STORES = ("BSVM", "BSVS", "BSVT")


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


def _course(owner, approver, course_id, store_id):
    body = {
        "course_id": course_id, "version": 1, "title": "Synthetic G1 POS qualification",
        "store_id": store_id, "role": "bartender", "passing_score": 100,
        "questions": [{"prompt": "Synthetic check", "options": ["ready", "not ready"], "correct_index": 0}],
        "rights_ref": "SYNTHETIC-RIGHTS", "practical_requirements": "Synthetic practical check",
    }
    drafted = admin_post(owner, "/api/v1/academy/courses", body)
    assert drafted.status_code == 201, drafted.text
    published = admin_post(approver, f"/api/v1/academy/courses/{course_id}/1/publish", {})
    assert published.status_code == 200, published.text


def _complete(user, course_id):
    path = f"/api/v1/academy/courses/{course_id}/1"
    enrolled = admin_post(user, path + "/enroll", {})
    assert enrolled.status_code == 200, enrolled.text
    completed = admin_post(user, path + "/complete", {})
    assert completed.status_code == 200, completed.text
    exam = admin_post(user, path + "/exam", {"answers": [0], "request_id": str(uuid4())})
    assert exam.status_code == 200 and exam.json()["passed"] is True, exam.text
    return exam.json()


def _http_request(server, method, path, cookie, body=None, csrf=""):
    connection = http.client.HTTPConnection(*server.server_address, timeout=5)
    try:
        connection.request(method, path, None if body is None else json.dumps(body), {
            "Cookie": cookie, "Content-Type": "application/json", "Origin": "http://127.0.0.1:%d" % server.server_port,
            "X-CSRF-Token": csrf, "X-BSV-CSRF": csrf,
        })
        response = connection.getresponse()
        return response.status, response.getheaders(), json.loads(response.read())
    finally:
        connection.close()


@pytest.mark.parametrize("store_id", STORES, ids=[f"G1B-{n:02d}-{store}" for n, store in enumerate(STORES, 1)])
def test_g1b_three_store_identity_academy_device_pos_http(store_id, monkeypatch, tmp_path, request, identity_http):
    """A real HTTP chain for each registered cocktail store; orders stay unpaid."""
    monkeypatch.setenv("BSV_ACADEMY_STORE_IDS", ",".join(STORES))
    AcademyBase.metadata.drop_all(api.router.a)
    request.addfinalizer(lambda: AcademyBase.metadata.drop_all(api.router.a))
    AcademyBase.metadata.create_all(api.router.a)
    importlib.invalidate_caches()

    user, owner, approver, tr, _ = create_person("g1-" + store_id.lower())
    onboard(tr, owner, approver)
    grant_action(tr, owner, approver, "learning.course.read", store=store_id, role="staff")
    common = f"G1-COMMON-{store_id}"
    local = f"G1-LOCAL-{store_id}"
    _course(owner, approver, common, None)
    _course(owner, approver, local, store_id)
    _complete(user, common)
    _complete(user, local)
    practical = admin_post(approver, f"/api/v1/academy/courses/{local}/1/practical", {
        "tr_code": tr, "decision": "verified", "evidence_ref": "SYNTH-PRACTICAL-" + store_id,
        "reason": "Independent synthetic practical verification",
    })
    assert practical.status_code == 200 and practical.json()["credential_id"], practical.text
    work = user.get("/api/v1/academy/work")
    assert work.status_code == 200 and store_id in {row["store_id"] for row in work.json()["stores"]}

    pos_grants = {action: grant_action(tr, owner, approver, action, store=store_id, role="staff")
                  for action in ("pos.order.read", "pos.order.create")}
    grant_action(tr, owner, approver, "marketing.task.write", store=store_id, role="staff")
    manager_user, manager_owner, manager_approver, manager_tr, _ = create_person("g1-sched-a-" + store_id.lower())
    onboard(manager_tr, manager_owner, manager_approver, bm=True)
    grant_action(manager_tr, manager_owner, manager_approver, "store.shift.write", store=store_id, role="manager")
    reviewer_user, reviewer_owner, reviewer_approver, reviewer_tr, _ = create_person("g1-sched-b-" + store_id.lower())
    onboard(reviewer_tr, reviewer_owner, reviewer_approver, bm=True)
    grant_action(reviewer_tr, reviewer_owner, reviewer_approver, "store.shift.write", store=store_id, role="manager")
    start = now() - timedelta(minutes=3)
    end = now() + timedelta(hours=2)
    scheduled = admin_post(manager_user, "/api/v1/academy/shifts", {
        "tr_code": tr, "store_id": store_id, "role": "bartender", "start": start.isoformat(),
        "end": end.isoformat(), "timezone": "Asia/Shanghai", "request_id": str(uuid4()),
    })
    assert scheduled.status_code == 201, scheduled.text
    shift_id = scheduled.json()["shift_id"]
    approved = admin_post(reviewer_user, f"/api/v1/academy/shifts/{shift_id}/approve", {})
    assert approved.status_code == 200, approved.text
    confirmed = admin_post(user, f"/api/v1/academy/shifts/{shift_id}/confirm", {})
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed", confirmed.text

    from fastapi.testclient import TestClient
    admin = TestClient(api.app)
    login = admin.post("/api/v1/auth/isolated/login", json={
        "username": "reviewer1", "password": os.environ["BSV_DEMO_ADMIN_1_PASSWORD"]})
    assert login.status_code == 200, login.text
    device_id = "G1-" + store_id + "-TERM-01"
    registered = admin_post(admin, "/api/v1/academy/devices", {"device_id": device_id, "store_id": store_id})
    assert registered.status_code == 201, registered.text
    device_token = registered.json()["device_token"]

    # Build an independent POS SQLite database using the repository's existing
    # catalog fixture and unchanged canonical store/seat registry.
    fixture = tmp_path / "catalog.xlsx"
    runpy.run_path(str(ROOT / "tests/bsv1/make_fixture.py"))["write_fixture"](fixture)
    monkeypatch.setenv("BSV_V9_XLSX", str(fixture))
    monkeypatch.setenv("BSV_POS_IDENTITY_REQUIRED", "1")
    monkeypatch.setenv("BSV_POS_DEVICE_REQUIRED", "1")
    monkeypatch.setenv("BSV_POS_INTERNAL_STAGE", "1")
    monkeypatch.setenv("BSV_POS_G1_TEST_STORES", ",".join(STORES))
    monkeypatch.setenv("BSV_APP_ENV", "isolated")
    monkeypatch.setenv("BSV_PRIVATE_SSH_TUNNEL", "1")
    monkeypatch.setenv("BSV_POS_IDENTITY_URL", identity_http)
    monkeypatch.setenv("BSV_POS_IDENTITY_TOKEN", "synthetic-g1-service-token")
    monkeypatch.setenv("BSV_POS_STORE_LEGAL_JSON", json.dumps({s: "DEMO_LEGAL" for s in STORES}))
    monkeypatch.setenv("BSV_POS_LAYOUT_SERVICE_TOKEN", "synthetic-unused-layout-token")
    monkeypatch.setenv("BSV_POS_GROWTH_INTEGRATION", "1")
    monkeypatch.setenv("BSV_GROWTH_LINK_KEY", "SYNTHETIC-G1-GROWTH-LINK-KEY-0123456789")
    monkeypatch.setenv("BSV_GROWTH_POS_CONTEXT_KEY", "SYNTHETIC-G1-GROWTH-CONTEXT-KEY-0123456789")
    verify_token = "SYNTHETIC-G1-POS-VERIFY-TOKEN-0123456789"
    monkeypatch.setenv("BSV_GROWTH_POS_VERIFY_TOKEN", verify_token)
    monkeypatch.setenv("BSV_DB_PATH", str(tmp_path / "pos.sqlite3"))
    monkeypatch.setenv("BSV_POS_PORT", "0")
    from dataclasses import replace
    monkeypatch.setattr(api, "settings", replace(api.settings, service_tokens={
        "pos": {"token": "synthetic-g1-service-token", "actions": ["pos.order.read", "pos.order.create"],
                "legal_entities": ["DEMO_LEGAL"], "stores": list(STORES), "academy_stores": list(STORES)}}))

    monkeypatch.syspath_prepend(str(ROOT / "services/api/bsv1"))
    pos = importlib.import_module("services.api.bsv1.app")
    monkeypatch.setattr(pos, "DB_PATH", tmp_path / "pos.sqlite3")
    monkeypatch.setattr(pos, "MODE", "staging")
    pos.init_db()
    session_cookie = user.cookies.get(api.SESSION_COOKIE)
    identity_csrf = user.cookies.get("bsv_csrf")
    with pos.ThreadingHTTPServer(("127.0.0.1", 0), pos.Handler) as server:
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            cookie = f"{api.SESSION_COOKIE}={session_cookie}; bsv_csrf={identity_csrf}"
            status, headers, body = _http_request(server, "POST", "/api/pos/device-login", cookie, {
                "store_id": store_id, "confirmed_store_id": store_id,
                "device_id": device_id, "device_token": device_token,
            }, identity_csrf)
            assert status == 200, body
            pos_cookies = [value.split(";", 1)[0] for key, value in headers
                           if key.lower() == "set-cookie"]
            assert any(value.startswith("bsv_pos_v4_session=") for value in pos_cookies)
            assert any(value.startswith("bsv_pos_device=") for value in pos_cookies)
            cookie += "; " + "; ".join(pos_cookies)
            status, _, state = _http_request(server, "GET", "/api/state", cookie)
            assert status == 200 and state["staff"]["shift"]["tr_code"] == tr, state
            csrf = state["csrf"]
            seat_id = f"{store_id}-SEAT-0001"
            run = str(uuid4())
            status, _, opened = _http_request(server, "POST", "/api/seats/open", cookie,
                {"seat_id": seat_id, "acceptance_run": run, "_action_id": "g1-open-" + store_id.lower()}, csrf)
            assert status == 200, opened
            status, _, added = _http_request(server, "POST", "/api/drafts/add", cookie,
                {"visit_id": opened["visit_id"], "product_id": "C000001", "acceptance_run": run,
                 "_action_id": "g1-draft-" + store_id.lower()}, csrf)
            assert status == 200, added
            status, _, order = _http_request(server, "POST", "/api/orders/submit", cookie,
                {"visit_id": opened["visit_id"], "acceptance_run": run, "pay_now": False,
                 "_action_id": "g1-order-" + store_id.lower()}, csrf)
            assert status == 200 and order["payment_verified"] is False and order["pay_now"] is False, order
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                growth_port = probe.getsockname()[1]
            growth_db = tmp_path / "growth.sqlite3"
            growth_env = {**os.environ, "BSV_GROWTH_ENV": "isolated", "BSV_GROWTH_TRUST_IDENTITY": "1",
                "BSV_GROWTH_DB_URL": "sqlite:///" + str(growth_db),
                "BSV_GROWTH_SIGNING_KEY": "SYNTHETIC-G1-GROWTH-SIGNING-KEY-0123456789",
                "BSV_GROWTH_IDENTITY_ME_URL": identity_http + "/api/v1/identity/me",
                "BSV_GROWTH_LEGAL_ENTITY_ID": "DEMO_LEGAL", "BSV_GROWTH_STORE_IDS": ",".join(STORES),
                "BSV_GROWTH_POS_VERIFY_URL": f"http://127.0.0.1:{server.server_port}/api/v1/visits/customer-context/verify",
                "BSV_GROWTH_POS_VERIFY_TOKEN": verify_token}
            growth_log_path = tmp_path / "growth.log"
            with growth_log_path.open("w") as growth_log:
                growth = subprocess.Popen([sys.executable, "-m", "uvicorn", "services.api.customer_growth.app:app",
                    "--host", "127.0.0.1", "--port", str(growth_port), "--log-level", "warning"],
                    cwd=ROOT, env=growth_env, stdout=growth_log, stderr=subprocess.STDOUT)
                try:
                    growth_url = f"http://127.0.0.1:{growth_port}"
                    with httpx.Client(base_url=growth_url, trust_env=False) as guest:
                        for _ in range(60):
                            if growth.poll() is not None:
                                pytest.fail("isolated Growth API did not start: " + growth_log_path.read_text())
                            try:
                                guest.get("/api/v1/growth/public/config", timeout=0.2)
                                break
                            except httpx.HTTPError:
                                time.sleep(0.1)
                        assert guest.post("/api/v1/growth/dev/guest-login",
                            json={"subject": "g1-guest-" + store_id, "store_id": store_id}).status_code == 200
                        growth_csrf = guest.cookies["bsv_growth_csrf"]
                        growth_headers = {"X-Growth-CSRF": growth_csrf}
                        registration = guest.post("/api/v1/growth/public/register",
                            json={"display_name": "合成测试会员", "privacy_accepted": True}, headers=growth_headers)
                        assert registration.status_code == 200, registration.text
                        taste = guest.post("/api/v1/growth/public/taste",
                            json={"tags": ["果香酸爽"], "share_for_service": True}, headers=growth_headers)
                        assert taste.status_code == 200, taste.text
                        proof = guest.post("/api/v1/growth/public/pos-link", json={"store_id": store_id}, headers=growth_headers)
                        assert proof.status_code == 200, proof.text
                        linked = _http_request(server, "POST", "/api/visits/customer-link", cookie, {
                            "visit_id": opened["visit_id"], "proof": proof.json()["token"],
                            "_action_id": "g1-growth-link-" + store_id.lower()}, csrf)
                        assert linked[0] == 200 and linked[2]["linked"] is True, linked
                        assert _http_request(server, "POST", "/api/visits/customer-link", cookie, {
                            "visit_id": opened["visit_id"], "proof": proof.json()["token"],
                            "_action_id": "g1-growth-link-" + store_id.lower()}, csrf)[0] == 200
                        context = _http_request(server, "GET", "/api/visits/customer-context?visit_id=" + opened["visit_id"], cookie)
                        assert context[0] == 200, context
                        staff_headers = {"Cookie": cookie + f"; bsv_growth_sid={guest.cookies['bsv_growth_sid']}; bsv_growth_csrf={growth_csrf}"}
                        service_view = guest.get("/api/v1/growth/staff/guest-context",
                            params={"context": context[2]["context"]}, headers=staff_headers)
                        assert service_view.status_code == 200, service_view.text
                        assert service_view.json()["view"] == "ON_VISIT_ONLY"
                        assert service_view.json()["tags"] == ["果香酸爽"] and service_view.json()["share_for_service"] is True
                        wrong_store = next(value for value in STORES if value != store_id)
                        foreign_proof = guest.post("/api/v1/growth/public/pos-link",
                            json={"store_id": wrong_store}, headers=growth_headers)
                        assert foreign_proof.status_code == 200, foreign_proof.text
                        cross = _http_request(server, "POST", "/api/visits/customer-link", cookie, {
                            "visit_id": opened["visit_id"], "proof": foreign_proof.json()["token"],
                            "_action_id": "g1-growth-cross-" + store_id.lower()}, csrf)
                        assert cross[0] in (403, 409), cross
                    with sqlite3.connect(growth_db) as db:
                        assert db.execute("SELECT COUNT(*) FROM bsv_growth_verified_payment_projection").fetchone()[0] == 0
                        assert db.execute("SELECT COUNT(*) FROM bsv_operating_finance_commission_candidate").fetchone()[0] == 0
                finally:
                    growth.terminate()
                    growth.wait(timeout=10)
            assert _http_request(server, "POST", "/api/seats/open", cookie,
                {"seat_id": "BSVT-SEAT-0001" if store_id != "BSVT" else "BSVS-SEAT-0001",
                 "acceptance_run": str(uuid4()), "_action_id": "g1-cross-" + store_id.lower()}, csrf)[0] in (403, 409)
            with pos.db_read() as db:
                assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
                assert db.execute("SELECT COUNT(*) FROM demo_checkouts").fetchone()[0] == 0
                assert db.execute("SELECT COUNT(*) FROM staff_store_access").fetchone()[0] == 1
                assert db.execute("SELECT store_id FROM visits WHERE id=?", (opened["visit_id"],)).fetchone()[0] == store_id
                assert db.execute("SELECT id FROM seats WHERE id=?", (seat_id,)).fetchone()
            other_store = next(store for store in STORES if store != store_id)
            assert _http_request(server, "POST", "/api/pos/device-login", cookie, {
                "store_id": other_store, "confirmed_store_id": other_store,
                "device_id": device_id, "device_token": device_token,
            }, identity_csrf)[0] in (401, 403, 503)
            replayed = cookie.replace(f"{api.SESSION_COOKIE}={session_cookie}",
                                      f"{api.SESSION_COOKIE}={manager_user.cookies.get(api.SESSION_COOKIE)}")
            assert _http_request(server, "GET", "/api/state", replayed)[0] == 403
            revoked = admin_post(owner, f"/api/v1/identity/grants/{pos_grants['pos.order.create']}/revoke", {
                "legal_entity_id": "DEMO_LEGAL", "reason": "Synthetic mid-session revocation"})
            assert revoked.status_code == 200, revoked.text
            assert _http_request(server, "POST", "/api/orders/submit", cookie, {
                "visit_id": opened["visit_id"], "pay_now": False, "_action_id": "g1-revoked-" + store_id.lower()}, csrf)[0] == 403
            device_revoked = admin_post(admin, f"/api/v1/academy/devices/{device_id}/revoke", {})
            assert device_revoked.status_code == 200, device_revoked.text
            assert _http_request(server, "GET", "/api/state", cookie)[0] == 403
        finally:
            server.shutdown()
            worker.join(timeout=5)
            admin.close()


@pytest.mark.parametrize("store_id", STORES, ids=[f"G1B-04-deny-{store}" for store in STORES])
def test_g1b_store_scope_denies_without_explicit_test_opt_in(store_id, monkeypatch):
    monkeypatch.delenv("BSV_ACADEMY_STORE_IDS", raising=False)
    from services.api.identity.academy_policy import available_stores
    allowed = available_stores()
    if store_id == "BSVM":
        assert store_id not in allowed
    else:
        assert store_id in allowed  # Existing G1-A default remains BSVS + BSVT only.
