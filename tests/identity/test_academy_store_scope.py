"""G1 regression: Academy may show only registered, explicitly enabled stores.

Do not mistake Academy eligibility for company-wide POS/device authorization.
The current H stage is intentionally limited to BSVT for POS operations.
"""
import json

from services.api.identity import academy_policy as policy


def test_default_academy_scope_keeps_current_h_behavior(monkeypatch):
    monkeypatch.delenv("BSV_ACADEMY_STORE_IDS", raising=False)
    assert set(policy.available_stores()) == {"BSVS", "BSVT"}
    assert policy.training_reason(None, None, "BSVM") == "STORE_UNAUTHORIZED"


def test_three_store_scope_can_be_enabled_without_reissuing_store_ids(monkeypatch):
    monkeypatch.setenv("BSV_ACADEMY_STORE_IDS", "BSVM,BSVS,BSVT")
    assert set(policy.available_stores()) == {"BSVM", "BSVS", "BSVT"}


def test_unpublished_store_and_unknown_ids_fail_closed(monkeypatch):
    for requested in ("BSVF", "UNKNOWN", "BSVM,UNKNOWN", "", "BSVM,BSVM",
                      "BSVM, BSVT", "BSVM,"):
        monkeypatch.setenv("BSV_ACADEMY_STORE_IDS", requested)
        assert policy.available_stores() == {}, requested


def test_duplicate_registry_ids_fail_closed(monkeypatch, tmp_path):
    records = json.loads(policy.REGISTRY.read_text(encoding="utf-8"))
    registry = tmp_path / "stores.json"
    registry.write_text(json.dumps(records + [records[0]], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(policy, "REGISTRY", registry)
    monkeypatch.setenv("BSV_ACADEMY_STORE_IDS", "BSVM,BSVS,BSVT")
    assert policy.available_stores() == {}
