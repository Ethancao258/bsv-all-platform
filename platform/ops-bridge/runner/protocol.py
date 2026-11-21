from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import secrets
import uuid

REPOSITORY = "Ethancao258/bsv-all-platform"
SHA40 = re.compile(r"^[a-f0-9]{40}$")
SHA64 = re.compile(r"^[a-f0-9]{64}$")
OPERATIONS = {"READ_DIAGNOSE", "VERIFY_ARTIFACT", "STAGING_DEPLOY"}
TASK_KEYS = {"schema_version", "task_id", "request_id", "operation", "environment", "repository",
             "target_sha", "expected_current_sha", "rollback_sha", "created_at", "expires_at", "nonce",
             "ci", "artifact", "auth"}


class ProtocolError(ValueError):
    """Invalid or unauthorized bridge protocol message."""


class ReplayDetected(ProtocolError):
    pass


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ProtocolError("Timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as error:
        raise ProtocolError("Invalid task timestamp") from error
    if parsed.tzinfo is None:
        raise ProtocolError("Task timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _signature(payload: dict, key: bytes) -> str:
    if not key or len(key) < 32:
        raise ProtocolError("Bridge signing key must contain at least 32 bytes")
    return hmac.new(key, canonical_json(payload), hashlib.sha256).hexdigest()


def create_task(*, request_id: str, operation: str, environment: str, target_sha: str,
                ci: dict, key_id: str, key: bytes, artifact: dict | None = None,
                expected_current_sha: str | None = None, rollback_sha: str | None = None,
                now: datetime | None = None, ttl_seconds: int = 300) -> dict:
    created = now or utcnow()
    if created.tzinfo is None:
        raise ProtocolError("Task creation time must be timezone-aware")
    task = {
        "schema_version": "1.0", "task_id": str(uuid.uuid4()), "request_id": request_id,
        "operation": operation, "environment": environment, "repository": REPOSITORY,
        "target_sha": target_sha, "expected_current_sha": expected_current_sha,
        "rollback_sha": rollback_sha, "created_at": _iso(created),
        "expires_at": _iso(created + timedelta(seconds=ttl_seconds)),
        "nonce": secrets.token_urlsafe(32), "ci": ci, "artifact": artifact,
    }
    task["auth"] = {"key_id": key_id, "algorithm": "HMAC-SHA256", "signature": "0" * 64}
    validate_task_shape(task)
    unsigned = {name: value for name, value in task.items() if name != "auth"}
    task["auth"] = {"key_id": key_id, "algorithm": "HMAC-SHA256", "signature": _signature(unsigned, key)}
    return task


def validate_task_shape(task: object) -> None:
    if not isinstance(task, dict) or set(task) != TASK_KEYS:
        raise ProtocolError("Task fields do not match the versioned schema")
    if task["schema_version"] != "1.0" or task["repository"] != REPOSITORY:
        raise ProtocolError("Unsupported bridge protocol or repository")
    try:
        uuid.UUID(task["task_id"])
    except (ValueError, TypeError, AttributeError) as error:
        raise ProtocolError("Invalid task ID") from error
    request_id = task["request_id"]
    if not isinstance(request_id, str) or not re.fullmatch(
            r"(?:BSV-OPS-[0-9]{3}|BSV-CHG-[0-9]{8}-[A-Za-z0-9-]{1,24})", request_id):
        raise ProtocolError("Invalid request ID")
    if not isinstance(task["operation"], str) or task["operation"] not in OPERATIONS:
        raise ProtocolError("Unsupported operation")
    if not isinstance(task["environment"], str) or task["environment"] not in {"isolated", "staging", "production"}:
        raise ProtocolError("Unsupported environment")
    if not isinstance(task["target_sha"], str) or not SHA40.fullmatch(task["target_sha"]):
        raise ProtocolError("Target must be a full immutable SHA")
    for field in ("expected_current_sha", "rollback_sha"):
        if task[field] is not None and (not isinstance(task[field], str) or not SHA40.fullmatch(task[field])):
            raise ProtocolError(f"{field} must be null or a full immutable SHA")
    if not isinstance(task["created_at"], str) or not isinstance(task["expires_at"], str):
        raise ProtocolError("Task timestamps must be strings")
    created, expires = _parse_time(task["created_at"]), _parse_time(task["expires_at"])
    lifetime = (expires - created).total_seconds()
    if lifetime <= 0 or lifetime > 600:
        raise ProtocolError("Task lifetime must be between 1 and 600 seconds")
    if not isinstance(task["nonce"], str) or not 32 <= len(task["nonce"]) <= 128:
        raise ProtocolError("Invalid replay nonce")
    ci = task["ci"]
    if not isinstance(ci, dict) or set(ci) != {"run_id", "run_url", "head_sha", "status", "conclusion", "workflow"}:
        raise ProtocolError("CI evidence shape is invalid")
    if any(not isinstance(ci[field], str) for field in ("run_url", "head_sha", "status", "conclusion", "workflow")):
        raise ProtocolError("CI evidence values must be strings")
    if (type(ci["run_id"]) is not int or ci["run_id"] < 1 or ci["head_sha"] != task["target_sha"]
            or not isinstance(ci["run_url"], str)
            or not re.fullmatch(rf"https://github\.com/{re.escape(REPOSITORY)}/actions/runs/[1-9][0-9]*", ci["run_url"])):
        raise ProtocolError("CI evidence does not match this repository and exact SHA")
    if ci["run_url"].rsplit("/", 1)[-1] != str(ci["run_id"]):
        raise ProtocolError("CI run URL does not match its run ID")
    valid_real = ci["status"] == "completed" and ci["conclusion"] == "success"
    valid_mock = ci["status"] == "simulated" and ci["conclusion"] == "simulated"
    if not (valid_real or valid_mock) or ci["workflow"] not in {"validate-architecture", "bsv-ops-bridge-dry-run"}:
        raise ProtocolError("CI evidence is not completed successfully for this task")
    artifact = task["artifact"]
    if artifact is not None:
        if not isinstance(artifact, dict) or set(artifact) != {"object_key", "sha256", "size_bytes"}:
            raise ProtocolError("Artifact manifest shape is invalid")
        if (not isinstance(artifact["object_key"], str)
                or not re.fullmatch(rf"releases/{task['target_sha']}/[A-Za-z0-9._-]+", artifact["object_key"])
                or not isinstance(artifact["sha256"], str) or not SHA64.fullmatch(artifact["sha256"])
                or type(artifact["size_bytes"]) is not int or not 1 <= artifact["size_bytes"] <= 52_428_800):
            raise ProtocolError("Artifact manifest is invalid")
        if artifact["object_key"].rsplit("/", 1)[-1] in {".", ".."}:
            raise ProtocolError("Artifact object key is invalid")
    if task["operation"] == "VERIFY_ARTIFACT" and artifact is None:
        raise ProtocolError("VERIFY_ARTIFACT requires a pinned artifact manifest")
    if task["operation"] == "READ_DIAGNOSE" and artifact is not None:
        raise ProtocolError("READ_DIAGNOSE does not accept artifact payloads")
    auth = task["auth"]
    if not isinstance(auth, dict) or set(auth) != {"key_id", "algorithm", "signature"}:
        raise ProtocolError("Task authentication envelope is invalid")
    if (not isinstance(auth["key_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", auth["key_id"])
            or auth["algorithm"] != "HMAC-SHA256" or not isinstance(auth["signature"], str)
            or not SHA64.fullmatch(auth["signature"])):
        raise ProtocolError("Task authentication fields are invalid")


def authenticate_task(task: dict, key_id: str, key: bytes, *, now: datetime | None = None,
                      max_ttl_seconds: int = 600) -> None:
    validate_task_shape(task)
    if task["auth"]["key_id"] != key_id:
        raise ProtocolError("Unknown bridge key ID")
    unsigned = {name: value for name, value in task.items() if name != "auth"}
    expected = _signature(unsigned, key)
    if not hmac.compare_digest(expected, task["auth"]["signature"]):
        raise ProtocolError("Task signature verification failed")
    current = now or utcnow()
    if current.tzinfo is None:
        raise ProtocolError("Current time must be timezone-aware")
    created, expires = _parse_time(task["created_at"]), _parse_time(task["expires_at"])
    if expires <= current.astimezone(timezone.utc):
        raise ProtocolError("Task has expired")
    if created > current.astimezone(timezone.utc).replace(microsecond=0):
        raise ProtocolError("Task creation time is in the future")
    if (expires - created).total_seconds() > max_ttl_seconds:
        raise ProtocolError("Task lifetime exceeds policy")


def sign_result(result: dict, key_id: str, key: bytes) -> dict:
    unsigned = {name: value for name, value in result.items() if name != "signature"}
    return {**unsigned, "signature": {"key_id": key_id, "algorithm": "HMAC-SHA256",
                                      "value": _signature(unsigned, key)}}


def verify_result(result: dict, key_id: str, key: bytes) -> bool:
    signature = result.get("signature") if isinstance(result, dict) else None
    if not isinstance(signature, dict) or set(signature) != {"key_id", "algorithm", "value"}:
        return False
    if signature.get("key_id") != key_id or signature.get("algorithm") != "HMAC-SHA256":
        return False
    if not isinstance(signature.get("value"), str) or not SHA64.fullmatch(signature["value"]):
        return False
    unsigned = {name: value for name, value in result.items() if name != "signature"}
    return hmac.compare_digest(_signature(unsigned, key), signature["value"])
