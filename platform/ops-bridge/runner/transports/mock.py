from __future__ import annotations

import hashlib

from transports.base import TransportError


class MockCloudTransport:
    """Deterministic fixtures only. Never contacts TAT, COS, or a host."""
    def __init__(self, artifacts: dict[str, bytes] | None = None, *, fail_reads: int = 0,
                 fail_code: str = "TIMEOUT", raw_log_fixture: str = ""):
        self.artifacts = artifacts or {}
        self.fail_reads = fail_reads
        self.fail_code = fail_code
        self.raw_log_fixture = raw_log_fixture
        self.calls = []
        self.host_contacted = False

    def _maybe_fail(self, operation: str) -> None:
        self.calls.append(operation)
        if self.fail_reads:
            self.fail_reads -= 1
            raise TransportError(self.fail_code, "Synthetic provider unavailable",
                                 retryable=self.fail_code in {"TIMEOUT", "CONNECTION_RESET", "THROTTLED"})

    def read_diagnose(self, task: dict) -> dict:
        self._maybe_fail("READ_DIAGNOSE")
        # raw_log_fixture is deliberately dropped; it can never enter public results.
        _ = self.raw_log_fixture
        return {"result_code": "MOCK_DIAGNOSE_OK", "summary": "模拟诊断完成；未连接云端主机。",
                "target_sha": task["target_sha"], "current_sha": task["expected_current_sha"],
                "rollback_sha": task["rollback_sha"], "evidence_location": f"memory://mock/{task['task_id']}",
                "host_contacted": False}

    def verify_artifact(self, task: dict) -> dict:
        self._maybe_fail("VERIFY_ARTIFACT")
        artifact = task["artifact"]
        body = self.artifacts.get(artifact["object_key"])
        if body is None:
            raise TransportError("ARTIFACT_NOT_FOUND", "Mock artifact is unavailable")
        valid = (len(body) == artifact["size_bytes"]
                 and hashlib.sha256(body).hexdigest() == artifact["sha256"])
        if not valid:
            raise TransportError("ARTIFACT_INTEGRITY_FAILED", "Artifact digest or size differs")
        return {"result_code": "MOCK_ARTIFACT_VERIFIED", "summary": "模拟构件校验通过；未读取 COS。",
                "target_sha": task["target_sha"], "current_sha": task["expected_current_sha"],
                "rollback_sha": task["rollback_sha"], "evidence_location": f"memory://mock/{task['task_id']}",
                "host_contacted": False}
