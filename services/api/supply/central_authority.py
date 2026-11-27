"""Integration helpers for the designated D worker, unused by the local demo.

The D owner supplies a connection and its existing per-command authorization
and mutation functions. This module never constructs a connection or schema.
"""
from collections.abc import Mapping
from hashlib import sha256
import json
from uuid import UUID

from .central_production_rules import ApprovedRule, ident, quantity
from .gateway import Unreachable


class RequestConflict(ValueError):
    """A prior committed request used the same ID with different content."""


def approved_catalog_policy(gateway, *, item_id, recipe_version, token):
    """Read the candidate approved-policy view from the sole catalog owner A."""
    item_id, recipe_version = ident(item_id), ident(recipe_version)
    response = gateway.read(
        "A", "/production-policy", params={"item_id": item_id, "recipe_version": recipe_version},
        user_token=token, allow_cache=False, primary_only=True,
    )
    data = response.get("data")
    if not isinstance(data, Mapping) or data.get("item_id") != item_id or (
        data.get("recipe_version") != recipe_version or data.get("duration_basis") != "PRODUCED_AT"
    ):
        raise Unreachable("A 未返回与选定配方一致的批准效期规则")
    rule = ApprovedRule(data.get("rule_version"), data.get("approved"),
                        data.get("elapsed_seconds"), data.get("opened_seconds"))
    unit = data.get("unit")
    return {
        "item_id": item_id, "recipe_version": recipe_version, "rule": rule, "unit": unit,
        "standard_amount": quantity(data.get("standard_amount"), unit),
        **{field: ident(data.get(field)) for field in ("name", "sop_version", "storage", "usage")},
    }


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def commit_d_command(connection, *, operation, payload, authorize, mutate):
    """Execute one command against the reviewed PostgreSQL proposal mapping.

    authorize(cursor) returns the stable owner-scoped actor key. It must check
    the current actor, action and object, including on replays. mutate(cursor)
    locks and writes D-owned facts, audit and outbox using this same cursor.
    The caller supplies a clean psycopg 3 connection; no external side effects
    are permitted in either callback. Response leaves only after commit.
    """
    if connection.info.transaction_status != 0:
        raise ValueError("D command requires a clean top-level connection")
    request_id = str(UUID(payload["request_id"]))
    fingerprint = sha256(_json([operation, payload]).encode()).hexdigest()
    with connection.transaction(), connection.cursor() as cursor:
        scope = ident(authorize(cursor))
        cursor.execute(
            """INSERT INTO supply.idempotent_result (actor_scope,request_id,fingerprint,response)
               VALUES (%s,%s,%s,'null'::jsonb) ON CONFLICT (actor_scope,request_id) DO NOTHING
               RETURNING request_id""",
            (scope, request_id, fingerprint),
        )
        if cursor.fetchone() is None:
            cursor.execute(
                """SELECT fingerprint,response FROM supply.idempotent_result
                   WHERE actor_scope=%s AND request_id=%s""",
                (scope, request_id),
            )
            prior = cursor.fetchone()
            if prior is None or not isinstance(prior[1], dict):
                raise RuntimeError("D idempotency result is unavailable")
            if prior[0] != fingerprint:
                raise RequestConflict("同一请求编号已用于不同操作")
            result = prior[1]
        else:
            data = mutate(cursor)
            if not isinstance(data, dict):
                raise ValueError("D command must return one structured result")
            result = {"state": "COMMITTED", "request_id": request_id, "data": data}
            cursor.execute(
                """UPDATE supply.idempotent_result SET response=%s::jsonb
                   WHERE actor_scope=%s AND request_id=%s""",
                (_json(result), scope, request_id),
            )
    return result
