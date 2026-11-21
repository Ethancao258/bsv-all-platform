from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import time

from protocol import authenticate_task, sign_result, utcnow
from transports.base import TransportError


class PolicyBlocked(RuntimeError):
    pass


def load_policy(path):
    with open(path, encoding="utf-8") as source:
        policy = json.load(source)
    if (policy.get("version") != "1.0" or policy.get("repository") != "Ethancao258/bsv-all-platform"
            or policy.get("default_mode") != "mock" or policy.get("cloud_transport_enabled") is not False):
        raise PolicyBlocked("Bridge policy is invalid or not mock-only")
    return policy


def _check_policy(task, policy, mode):
    if task["environment"] == "production":
        raise PolicyBlocked("Production operations are prohibited by BSV-OPS-002")
    if mode == "cloud" and (task["ci"]["status"] != "completed"
                             or task["ci"]["conclusion"] != "success"
                             or task["ci"]["workflow"] != "validate-architecture"):
        raise PolicyBlocked("Cloud execution requires successful real CI on the pinned SHA")
    operation = policy.get("operations", {}).get(task["operation"])
    if not isinstance(operation, dict) or operation.get("enabled") is not True:
        raise PolicyBlocked("Requested bridge operation is disabled")
    if task["environment"] not in operation.get("environments", []):
        raise PolicyBlocked("Operation is not allowed in this environment")
    if mode == "mock":
        if operation.get("mock_enabled") is not True:
            raise PolicyBlocked("Operation is disabled in mock mode")
    elif mode == "cloud":
        if policy.get("cloud_transport_enabled") is not True or operation.get("cloud_enabled") is not True:
            raise PolicyBlocked("Cloud transport is disabled pending separate owner authorization")
    else:
        raise PolicyBlocked("Unsupported bridge execution mode")
    if task["operation"] == "STAGING_DEPLOY":
        raise PolicyBlocked("STAGING_DEPLOY remains disabled until separate approval")


def _retry(callable_, retries: int, sleep=time.sleep):
    attempts = 0
    while True:
        try:
            return callable_()
        except TransportError as error:
            if not error.retryable or attempts >= retries:
                raise
            attempts += 1
            sleep(min(0.1 * (2 ** (attempts - 1)), 0.4))


def execute_task(task: dict, *, key_id: str, key: bytes, policy: dict, transport,
                 reporter, journal, mode: str = "mock", now: datetime | None = None,
                 sleep=time.sleep) -> dict:
    authenticate_task(task, key_id, key, now=now,
                      max_ttl_seconds=int(policy.get("max_task_ttl_seconds", 600)))
    _check_policy(task, policy, mode)
    timestamp = now or utcnow()
    journal.reserve(task["task_id"], task["nonce"], timestamp.astimezone(timezone.utc).isoformat())
    try:
        if task["operation"] == "READ_DIAGNOSE":
            outcome = _retry(lambda: transport.read_diagnose(task), int(policy.get("max_retries", 0)), sleep)
        elif task["operation"] == "VERIFY_ARTIFACT":
            outcome = _retry(lambda: transport.verify_artifact(task), int(policy.get("max_retries", 0)), sleep)
        else:
            raise PolicyBlocked("Operation is not implemented")
        result = sign_result(_make_result(task, outcome, "SUCCEEDED", now), key_id, key)
    except TransportError as error:
        result = sign_result(_make_result(task, {
            "result_code": _safe_code(error.code),
            "summary": "云端通道未完成诊断；未确认任何远程变更。",
            "target_sha": task["target_sha"], "current_sha": task["expected_current_sha"],
            "rollback_sha": task["rollback_sha"], "evidence_location": f"memory://mock/{task['task_id']}",
            "host_contacted": bool(getattr(transport, "host_contacted", False)),
        }, "BLOCKED", now), key_id, key)
    except Exception:
        journal.finish(task["task_id"], "FAILED", "BRIDGE_INTERNAL_ERROR", timestamp.astimezone(timezone.utc).isoformat())
        raise
    journal.finish(task["task_id"], result["state"], result["result_code"], timestamp.astimezone(timezone.utc).isoformat())
    reporter.publish(task, result)
    return result


def _safe_code(code: object) -> str:
    value = str(code).upper()
    return value if re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", value) else "PROVIDER_ERROR"


def _make_result(task: dict, outcome: dict, state: str, now: datetime | None) -> dict:
    allowed = {"result_code", "summary", "target_sha", "current_sha", "rollback_sha", "evidence_location", "host_contacted"}
    if not isinstance(outcome, dict) or set(outcome) != allowed:
        raise ValueError("Provider response is not a bounded redacted bridge result")
    if (outcome["target_sha"] != task["target_sha"]
            or outcome["current_sha"] != task["expected_current_sha"]
            or outcome["rollback_sha"] != task["rollback_sha"]):
        raise ValueError("Provider result does not match the pinned task state")
    if not isinstance(outcome["summary"], str) or len(outcome["summary"]) > 240:
        raise ValueError("Provider summary exceeds its public report limit")
    if not isinstance(outcome["evidence_location"], str) or not re.fullmatch(
            r"(?:memory|cos)://[A-Za-z0-9._/-]+", outcome["evidence_location"]):
        raise ValueError("Provider evidence location is invalid")
    result = {
        "schema_version": "1.0", "task_id": task["task_id"], "request_id": task["request_id"],
        "operation": task["operation"], "state": state, "result_code": _safe_code(outcome["result_code"]),
        "target_sha": task["target_sha"], "current_sha": outcome["current_sha"],
        "rollback_sha": outcome["rollback_sha"], "environment": task["environment"],
        "evidence_location": outcome["evidence_location"], "summary": outcome["summary"],
        "occurred_at": (now or utcnow()).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "host_contacted": bool(outcome["host_contacted"]),
    }
    return result
