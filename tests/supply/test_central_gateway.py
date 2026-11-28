from types import SimpleNamespace

import httpx
import pytest

from services.api.supply.config import Source
from services.api.supply import gateway
from services.api.supply.central_routes import _authorized, Receipt


def _gateway(monkeypatch, response):
    urls = []

    def transport(request):
        urls.append(str(request.url))
        assert request.headers["Authorization"] == "Bearer isolated"
        return response

    client = httpx.Client(transport=httpx.MockTransport(transport))
    monkeypatch.setattr(gateway.httpx, "Client", lambda **kwargs: client)
    source = Source("D", "D", "https://primary.test", "https://standby.test", "", False, ())
    instance = gateway.Gateway(SimpleNamespace(sources={"D": source}, timeout_seconds=1), None)
    return instance, urls


@pytest.mark.parametrize("state", [None, "QUEUED", "PENDING", "PREVIEW"])
def test_central_rejects_unconfirmed_commit(monkeypatch, state):
    instance, _ = _gateway(monkeypatch, httpx.Response(200, json={"state": state}))
    with pytest.raises(gateway.Unreachable):
        instance.write("D", "/supply/central/v1/receive", {}, user_token="isolated",
                       expected_state="COMMITTED")


def test_central_snapshot_never_uses_standby(monkeypatch):
    instance, urls = _gateway(monkeypatch, httpx.Response(503))
    with pytest.raises(gateway.Unreachable):
        instance.read("D", "/supply/central/v1/inventory", user_token="isolated",
                      allow_cache=False, primary_only=True)
    assert urls == ["https://primary.test/supply/central/v1/inventory"]


def test_central_role_scopes_do_not_union_unrelated_roles():
    person = {"roles": ["dispatch", "receive"], "stores": ["S1", "S2"],
              "role_stores": {"receive": ["S1"], "dispatch": ["S2"]}}
    with pytest.raises(gateway.HTTPException) as exc:
        _authorized(person, {"receive"}, "S2")
    assert exc.value.status_code == 403
    _authorized(person, {"receive"}, "S1")


def test_central_input_rejects_client_actor():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Receipt.model_validate(dict(
            request_id="5d01d667-2154-4821-8c38-7d571c413ce8", expected_version=1,
            accepted_ids=["P1"], hold_ids=[], exception_reasons={}, employee_id="forged",
        ))
