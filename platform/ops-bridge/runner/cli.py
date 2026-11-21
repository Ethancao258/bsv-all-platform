#!/usr/bin/env python3
"""Run one explicitly local synthetic bridge roundtrip; this CLI never creates cloud clients."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile

from executor import execute_task, load_policy
from journal import TaskJournal
from protocol import create_task, verify_result
from transports.github import GitHubCompatibleReporter
from transports.mock import MockCloudTransport

POLICY = Path(__file__).resolve().parents[1] / "policy.yaml"


def run_mock_roundtrip(operation: str, target_sha: str, *, run_id: int = 1,
                       run_url: str | None = None, now=None) -> dict:
    key = secrets.token_bytes(32)
    key_id = "ephemeral-mock"
    if operation == "VERIFY_ARTIFACT":
        body = b"BSV OPS bridge synthetic artifact v1\n"
        artifact_key = f"releases/{target_sha}/synthetic.tar"
        artifact = {"object_key": artifact_key, "sha256": hashlib.sha256(body).hexdigest(),
                    "size_bytes": len(body)}
        artifacts = {artifact_key: body}
    else:
        artifact = None
        artifacts = {}
    task = create_task(
        request_id="BSV-OPS-002", operation=operation, environment="isolated", target_sha=target_sha,
        ci={"run_id": run_id, "run_url": run_url or f"https://github.com/Ethancao258/bsv-all-platform/actions/runs/{run_id}",
            "head_sha": target_sha, "status": "simulated", "conclusion": "simulated",
            "workflow": "bsv-ops-bridge-dry-run"},
        key_id=key_id, key=key, artifact=artifact, now=now)
    reporter = GitHubCompatibleReporter(key_id=key_id, key=key)
    transport = MockCloudTransport(artifacts=artifacts)
    with tempfile.TemporaryDirectory(prefix="bsv-ops-bridge-") as journal_dir:
        journal = TaskJournal(Path(journal_dir) / "tasks.sqlite3")
        result = execute_task(task, key_id=key_id, key=key, policy=load_policy(POLICY),
                              transport=transport, reporter=reporter, journal=journal,
                              mode="mock", now=now)
        if (not verify_result(result, key_id, key)
                or not verify_result(reporter.reports[-1], key_id, key)):
            raise RuntimeError("Mock result or redacted report signature did not verify")
        if transport.host_contacted:
            raise RuntimeError("Mock transport unexpectedly contacted a host")
        return reporter.reports[-1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-roundtrip", action="store_true", required=True)
    parser.add_argument("--operation", choices=("READ_DIAGNOSE", "VERIFY_ARTIFACT"), default="READ_DIAGNOSE")
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--run-id", type=int, default=int(os.environ.get("GITHUB_RUN_ID", "1")))
    parser.add_argument("--run-url", default=os.environ.get("GITHUB_SERVER_URL", "https://github.com") +
                        "/" + os.environ.get("GITHUB_REPOSITORY", "Ethancao258/bsv-all-platform") +
                        "/actions/runs/" + os.environ.get("GITHUB_RUN_ID", "1"))
    args = parser.parse_args(argv)
    try:
        if os.environ.get("GITHUB_REPOSITORY", "Ethancao258/bsv-all-platform") != "Ethancao258/bsv-all-platform":
            raise ValueError("Workflow repository is not the approved BSV ALL repository")
        report = run_mock_roundtrip(args.operation, args.sha, run_id=args.run_id, run_url=args.run_url)
    except Exception:
        # Emit an error category only. Provider and environment values are never echoed.
        print(json.dumps({"state": "BLOCKED", "result_code": "MOCK_ROUNDTRIP_FAILED",
                          "summary": "模拟闭环未完成；未连接云端主机。"}, ensure_ascii=False))
        return 1
    encoded = json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2)
    print(encoded)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## BSV OPS Bridge · MOCK_ONLY\n\n")
            summary.write("本次为自动化模拟；没有访问 TAT、COS 或腾讯云主机。\n\n")
            summary.write("```json\n" + encoded + "\n```\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
