"""Isolated, synthetic HQ layout authorization contract tests.

These tests deliberately expose unfinished authorization semantics in PR #17.
Do not remove assertions merely to make CI green.
No POS, real personnel, real maps, or production credentials are accessed.
"""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy.exc import OperationalError

from services.api.identity import api
from domains.workforce.identity.models import Grant
from .conftest import admin_post, create_person, grant_action, onboard

LAYOUT_TOKEN = "synthetic-layout-admin-service-token-111122223333"


@pytest.fixture
def layout_service(monkeypatch):
    service = {
        "token": LAYOUT_TOKEN,
        "actions": [
            "hq.layout.read", "hq.layout.edit",
            "hq.layout.publish", "hq.store.register",
        ],
        "legal_entities": ["DEMO_LEGAL"],
        "stores": ["BSVT"],
    }
    monkeypatch.setattr(
        api, "settings",
        replace(api.settings, service_tokens={**api.settings.service_tokens, "layout-admin": service}),
    )
    return service


def _headers(client, *, token=LAYOUT_TOKEN, csrf=True):
    headers = {
        "X-BSV-Service-Token": token,
        "Authorization": "Bearer " + client.cookies.get("bsv_identity_session", ""),
    }
    if csrf:
        headers["X-CSRF-Token"] = client.cookies.get("bsv_csrf", "")
    return headers


def _check(user, action="hq.layout.read", *, store="BSVT", legal="DEMO_LEGAL",
           csrf=True, token=LAYOUT_TOKEN):
    body = {"action": action, "legal_entity_id": legal}
    if store is not None:
        body["store_id"] = store
    return user.post("/api/v1/identity/hq-layout-session",
                     json=body, headers=_headers(user, token=token, csrf=csrf))


def test_internal_service_auth_scope_and_active_bm_grant(layout_service):
    user, one, two, tr, _ = create_person("hqscope-user")
    onboard(tr, one, two, bm=True)
    gid = grant_action(tr, one, two, "hq.layout.read", store=None, role="hq")
    assert gid

    yes = _check(user)
    assert yes.status_code == 200, yes.text
    assert yes.json()["allowed"] is True
    assert yes.json()["actor_tr_code"] == tr
    assert yes.json()["cache_ttl_seconds"] == 0

    assert _check(user, token="wrong-token").status_code == 401
    assert _check(user, legal="OTHER_COMPANY").status_code == 403
    assert _check(user, store="BSVS").status_code == 403
    assert _check(user, action="hq.layout.publish").json()["allowed"] is False

    with api.router.session(write=True) as db:
        db.get(Grant, gid).status = "revoked"
    revoked = _check(user)
    assert revoked.status_code in (200, 403), revoked.text
    assert revoked.status_code == 403 or revoked.json()["allowed"] is False


def test_non_bm_employee_is_never_authorized_for_layout(layout_service):
    user, one, two, tr, _ = create_person("layout-nonbm")
    onboard(tr, one, two, bm=False)
    result = _check(user)
    assert result.status_code in (200, 403), result.text
    assert result.status_code == 403 or result.json()["allowed"] is False


def test_store_scoped_hq_layout_grant_can_be_issued_without_pos_access(layout_service):
    user, one, two, tr, _ = create_person("hqscoped-user")
    onboard(tr, one, two, bm=True)
    start = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    request = admin_post(one, "/api/v1/identity/grants", {
        "tr_code": tr, "legal_entity_id": "DEMO_LEGAL", "store_id": "BSVT",
        "role": "hq", "action": "hq.layout.edit", "valid_from": start,
        "reason": "Synthetic store-scoped map permission request",
    })
    # Must not widen this to global company HQ rights to bypass a failing test.
    assert request.status_code == 201, request.text
    approved = admin_post(two,
        f"/api/v1/identity/grants/{request.json()['grant_id']}/approve", {
            "legal_entity_id": "DEMO_LEGAL", "reason": "Independent scoped approval",
        })
    assert approved.status_code == 200, approved.text
    assert _check(user, action="hq.layout.edit").json()["allowed"] is True
    # Service scope is independently constrained in layout_service to BSVT.
    assert _check(user, action="hq.layout.edit", store="BSVS").status_code == 403


def test_map_mutation_requires_specific_store_and_csrf(layout_service):
    user, one, two, tr, _ = create_person("hqmutation-user")
    onboard(tr, one, two, bm=True)
    grant_action(tr, one, two, "hq.layout.publish", store=None, role="hq")
    # The read-only legal-entity list may omit store_id; publish may not.
    missing_store = _check(user, action="hq.layout.publish", store=None)
    assert missing_store.status_code in (403, 422), missing_store.text
    no_csrf = _check(user, action="hq.layout.publish", csrf=False)
    assert no_csrf.status_code == 403, no_csrf.text
    assert _check(user, action="hq.layout.publish", csrf=True).json()["allowed"] is True


def test_authorization_fails_closed_when_source_a_is_down(layout_service, monkeypatch):
    user, one, two, tr, _ = create_person("layout-db-down")
    onboard(tr, one, two, bm=True)
    grant_action(tr, one, two, "hq.layout.read", store=None, role="hq")

    @contextmanager
    def broken(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("synthetic source A outage"))
        yield

    monkeypatch.setattr(api.router, "session", broken)
    response = _check(user)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "DB_UNAVAILABLE"
