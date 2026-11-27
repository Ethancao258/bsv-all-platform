from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4
import json

import pytest

from services.api.supply.central_authority import (
    RequestConflict, approved_catalog_policy, commit_d_command,
)


def test_catalog_uses_exact_approved_version_and_no_cache():
    data = dict(item_id="P1", recipe_version="R1", duration_basis="PRODUCED_AT",
                rule_version="E1", approved=True, elapsed_seconds=43200, opened_seconds=300,
                unit="mL", standard_amount="450", name="Example", sop_version="S1",
                storage="approved storage", usage="approved usage")

    def read(owner, path, **options):
        assert (owner, path) == ("A", "/production-policy")
        assert options == dict(params={"item_id": "P1", "recipe_version": "R1"},
                               user_token="actor", allow_cache=False, primary_only=True)
        return {"data": data}

    def policy():
        return approved_catalog_policy(SimpleNamespace(read=read), item_id="P1",
                                       recipe_version="R1", token="actor")

    assert policy()["rule"].elapsed_seconds == 43200
    data["approved"] = False
    with pytest.raises(ValueError, match="unapproved"):
        policy()


class CandidateConnection:
    """A DB-API double for transaction ordering and replay. It is not Postgres."""

    info = SimpleNamespace(transaction_status=0)

    def __init__(self):
        self.rows = {}
        self.active = False
        self.queries = []

    @contextmanager
    def transaction(self):
        original = self.rows.copy()
        self.active = True
        try:
            yield
        except Exception:
            self.rows = original
            raise
        finally:
            self.active = False

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, query, params):
        assert self.active
        self.queries.append(query)
        if query.startswith("INSERT"):
            scope, request_id, checksum = params
            key = (scope, request_id)
            self.result = None if key in self.rows else (request_id,)
            self.rows.setdefault(key, (checksum, None))
        elif query.startswith("SELECT"):
            self.result = self.rows.get(params)
        else:
            response, scope, request_id = params
            key = (scope, request_id)
            self.rows[key] = (self.rows[key][0], json.loads(response))

    def fetchone(self):
        return self.result


def test_d_idempotency_checks_current_permission_and_rolls_back():
    db = CandidateConnection()
    writes = []
    authorized = True
    should_fail = True

    def authorize(cursor):
        assert cursor.active
        if not authorized:
            raise PermissionError
        return "legal-entity/employee"

    def mutate(cursor):
        assert cursor.active and cursor.queries[-1].startswith("INSERT")
        if should_fail:
            raise RuntimeError("business transaction rejected")
        writes.append("written")
        return {"version": 2}

    def command(payload):
        return commit_d_command(db, operation="receive", payload=payload,
                                authorize=authorize, mutate=mutate)

    payload = {"request_id": str(uuid4()), "expected_version": 1}
    with pytest.raises(RuntimeError, match="business transaction rejected"):
        command(payload)
    assert not db.rows
    should_fail = False
    first = command(payload)
    assert first == command(payload)
    assert first["state"] == "COMMITTED" and writes == ["written"]
    with pytest.raises(RequestConflict):
        command({**payload, "expected_version": 2})
    authorized = False
    with pytest.raises(PermissionError):
        command(payload)
