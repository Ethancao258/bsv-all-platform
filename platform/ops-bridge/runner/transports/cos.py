from __future__ import annotations

import hashlib
import json
import re

from protocol import canonical_json
from transports.base import COSBucket, TransportError


class TencentCOSAdapter:
    """Private immutable object-key adapter. The injected SDK client owns credentials."""
    def __init__(self, bucket: COSBucket | None, *, bucket_name: str | None, region: str | None,
                 prefix: str = "bsv-ops-bridge"):
        self.bucket = bucket
        self.bucket_name = bucket_name
        self.region = region
        self.prefix = prefix

    def _ready(self):
        if (self.bucket is None or not self.bucket_name or not re.fullmatch(r"[a-z0-9-]{3,63}", self.bucket_name)
                or not self.region or not re.fullmatch(r"[a-z0-9-]{4,32}", self.region)
                or self.prefix != "bsv-ops-bridge"):
            raise TransportError("COS_NOT_CONFIGURED", "Private COS transport authorization is not configured")

    def put_task(self, task: dict) -> str:
        self._ready()
        key = f"{self.prefix}/tasks/{task['task_id']}/task.json"
        self.bucket.put_object(key=key, body=canonical_json(task), private=True,
                               encryption="AES256", forbid_overwrite=True)
        return f"cos://private/{task['task_id']}/task.json"

    def fetch_artifact(self, task: dict) -> bytes:
        self._ready()
        artifact = task.get("artifact")
        if not artifact:
            raise TransportError("ARTIFACT_MANIFEST_REQUIRED", "Artifact manifest is missing")
        key = artifact["object_key"]
        if not key.startswith(f"releases/{task['target_sha']}/"):
            raise TransportError("ARTIFACT_KEY_DENIED", "Artifact key is outside the pinned release prefix")
        body = self.bucket.get_object(key=f"{self.prefix}/{key}")
        if (len(body) != artifact["size_bytes"] or hashlib.sha256(body).hexdigest() != artifact["sha256"]):
            raise TransportError("ARTIFACT_INTEGRITY_FAILED", "Downloaded artifact digest or size differs")
        return body

    def put_result(self, task_id: str, result: dict) -> str:
        self._ready()
        if not re.fullmatch(r"[0-9a-f-]{36}", task_id):
            raise TransportError("TASK_ID_INVALID", "Invalid result task ID")
        key = f"{self.prefix}/results/{task_id}/result.json"
        self.bucket.put_object(key=key, body=canonical_json(result), private=True,
                               encryption="AES256", forbid_overwrite=True)
        return f"cos://private/{task_id}/result.json"

    def fetch_result(self, task_id: str) -> dict:
        self._ready()
        if not re.fullmatch(r"[0-9a-f-]{36}", task_id):
            raise TransportError("TASK_ID_INVALID", "Invalid result task ID")
        key = f"{self.prefix}/results/{task_id}/result.json"
        body = self.bucket.get_object(key=key)
        if len(body) > 4096:
            raise TransportError("RESULT_TOO_LARGE", "Redacted bridge result exceeds size limit")
        try:
            result = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TransportError("RESULT_INVALID", "Bridge result is not valid JSON") from error
        if not isinstance(result, dict) or result.get("task_id") != task_id:
            raise TransportError("RESULT_INVALID", "Bridge result does not match task ID")
        return result
