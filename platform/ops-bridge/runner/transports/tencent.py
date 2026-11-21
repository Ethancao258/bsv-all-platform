from __future__ import annotations

from protocol import verify_result
from transports.base import TransportError


class TencentCloudTransport:
    """Composition for the reviewed task→private COS→fixed TAT runner→COS result path."""
    def __init__(self, *, tat, cos, key_id: str, task_key: bytes):
        self.tat = tat
        self.cos = cos
        self.key_id = key_id
        self.task_key = task_key
        self.host_contacted = False

    def _execute(self, task: dict) -> dict:
        self.cos.put_task(task)
        receipt = self.tat.invoke(task)
        if not isinstance(receipt, dict) or receipt.get("task_id") != task["task_id"]:
            raise TransportError("TAT_RECEIPT_INVALID", "TAT did not return the pinned task receipt")
        if receipt.get("state") not in {"SUCCESS", "COMPLETED"}:
            raise TransportError("TAT_EXECUTION_FAILED", "Fixed read-only TAT operation did not complete")
        result = self.cos.fetch_result(task["task_id"])
        if not verify_result(result, self.key_id, self.task_key):
            raise TransportError("RESULT_SIGNATURE_INVALID", "COS result signature did not verify")
        if (result.get("target_sha") != task["target_sha"]
                or result.get("request_id") != task["request_id"]
                or result.get("operation") != task["operation"]
                or result.get("environment") != task["environment"]):
            raise TransportError("RESULT_BINDING_INVALID", "COS result is not bound to the pinned task")
        self.host_contacted = True
        return {field: result[field] for field in (
            "result_code", "summary", "target_sha", "current_sha", "rollback_sha",
            "evidence_location", "host_contacted")}

    def read_diagnose(self, task: dict) -> dict:
        if task.get("operation") != "READ_DIAGNOSE":
            raise TransportError("OPERATION_MISMATCH", "TAT bridge operation mismatch")
        return self._execute(task)

    def verify_artifact(self, task: dict) -> dict:
        if task.get("operation") != "VERIFY_ARTIFACT":
            raise TransportError("OPERATION_MISMATCH", "TAT bridge operation mismatch")
        self.cos.fetch_artifact(task)
        return self._execute(task)
