from __future__ import annotations

import json
import re

from protocol import REPOSITORY, sign_result, verify_result

SENSITIVE = [
    re.compile(r"(?i)(?:AKID|TENCENTCLOUD_SECRET_ID)[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(?:tencentcloud_)?(?:secret(?:_key|_id)?|token|password|authorization)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"(?<![A-Za-z0-9])/(?:[^\s]+/)*[^\s]+"),
]


def redact(text: str) -> str:
    value = str(text)[:1000]
    for pattern in SENSITIVE:
        value = pattern.sub("[已隐藏]", value)
    return value[:240]


class GitHubCompatibleReporter:
    """Produces only a signed, schema-limited summary; no GitHub write capability."""
    def __init__(self, *, key_id: str, key: bytes):
        self.key_id = key_id
        self.key = key
        self.reports = []

    def publish(self, task: dict, result: dict) -> dict:
        if task.get("repository") != REPOSITORY or not verify_result(result, self.key_id, self.key):
            raise ValueError("Cannot publish an unverified bridge result")
        report = {field: result[field] for field in (
            "schema_version", "task_id", "request_id", "operation", "state", "result_code",
            "target_sha", "current_sha", "rollback_sha", "environment", "evidence_location",
            "occurred_at", "host_contacted", "signature")}
        report["summary"] = redact(result["summary"])
        report = sign_result(report, self.key_id, self.key)
        encoded = json.dumps(report, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > 4096:
            raise ValueError("Redacted bridge report exceeds size limit")
        self.reports.append(report)
        return report
