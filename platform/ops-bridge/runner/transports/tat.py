from __future__ import annotations

import re

from transports.base import TATInvoker, TransportError


class TencentTATAdapter:
    """Narrow adapter for a pre-registered fixed runner command; shell is never task input."""
    def __init__(self, invoker: TATInvoker | None, *, command_id: str | None,
                 command_sha256: str | None, instance_ids: tuple[str, ...] = ()):
        self.invoker = invoker
        self.command_id = command_id
        self.command_sha256 = command_sha256
        self.instance_ids = instance_ids

    def invoke(self, task: dict) -> dict:
        if task.get("operation") not in {"READ_DIAGNOSE", "VERIFY_ARTIFACT"}:
            raise TransportError("OPERATION_DISABLED", "TAT adapter refuses deployment or arbitrary commands")
        if task.get("environment") == "production":
            raise TransportError("ENVIRONMENT_DENIED", "TAT adapter is restricted to isolated/staging")
        if (self.invoker is None or not self.command_id or not re.fullmatch(r"cmd-[A-Za-z0-9-]{4,80}", self.command_id)
                or not self.command_sha256 or not re.fullmatch(r"[a-f0-9]{64}", self.command_sha256)
                or not self.instance_ids or any(not re.fullmatch(r"ins-[A-Za-z0-9-]{4,80}", item)
                                                 for item in self.instance_ids)):
            raise TransportError("TAT_NOT_CONFIGURED", "Fixed TAT runner authorization is not configured")
        parameters = {"task_id": task["task_id"], "request_id": task["request_id"],
                      "operation": task["operation"], "environment": task["environment"],
                      "target_sha": task["target_sha"],
                      "expected_command_sha256": self.command_sha256,
                      "task_object_key": f"bsv-ops-bridge/tasks/{task['task_id']}/task.json"}
        # No command text, path, shell, arbitrary Issue body, or credentials are passed.
        return self.invoker.invoke_fixed_runner(command_id=self.command_id,
                                                instance_ids=self.instance_ids, parameters=parameters)
