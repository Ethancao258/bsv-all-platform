from __future__ import annotations

import hashlib
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

RUNNER = Path(__file__).resolve().parents[2] / "platform/ops-bridge/runner"
sys.path.insert(0, str(RUNNER))

from cli import run_mock_roundtrip
from credentials import CredentialError, TemporaryTencentCredentials, credentials_from_environment
from executor import PolicyBlocked, execute_task, load_policy
from journal import TaskJournal
from protocol import ProtocolError, ReplayDetected, authenticate_task, create_task, verify_result
from transports.base import TransportError
from transports.cos import TencentCOSAdapter
from transports.github import GitHubCompatibleReporter, redact
from transports.mock import MockCloudTransport
from transports.noop import NoOpCloudTransport
from transports.tat import TencentTATAdapter
from transports.tencent import TencentCloudTransport


ROOT = RUNNER.parents[2]
POLICY = load_policy(RUNNER.parent / "policy.yaml")
SHA = "a" * 40
CURRENT = "b" * 40
ROLLBACK = "c" * 40
KEY_ID = "unit-test"
KEY = b"x" * 32
FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def make_task(operation="READ_DIAGNOSE", *, now=FIXED_NOW, artifact=None, ci_sha=SHA,
              environment="isolated", ttl=300):
    return create_task(
        request_id="BSV-OPS-002", operation=operation, environment=environment,
        target_sha=SHA, expected_current_sha=CURRENT, rollback_sha=ROLLBACK,
        ci={"run_id": 44, "run_url": "https://github.com/Ethancao258/bsv-all-platform/actions/runs/44",
            "head_sha": ci_sha, "status": "simulated", "conclusion": "simulated",
            "workflow": "bsv-ops-bridge-dry-run"},
        key_id=KEY_ID, key=KEY, artifact=artifact, now=now, ttl_seconds=ttl)


class FakeCOS:
    def __init__(self, artifacts=None, results=None):
        self.artifacts = artifacts or {}
        self.results = results or {}
        self.objects = {}
        self.put_options = []

    def put_object(self, *, key, body, private, encryption, forbid_overwrite):
        self.put_options.append((key, private, encryption, forbid_overwrite))
        if forbid_overwrite and key in self.objects:
            raise RuntimeError("overwrite refused")
        self.objects[key] = body

    def get_object(self, *, key):
        if key in self.artifacts:
            return self.artifacts[key]
        if key in self.results:
            return self.results[key]
        if key in self.objects:
            return self.objects[key]
        raise TransportError("NOT_FOUND", "synthetic missing object")


class FakeTAT:
    def __init__(self, receipt=None):
        self.receipt = receipt
        self.calls = []

    def invoke_fixed_runner(self, *, command_id, instance_ids, parameters):
        self.calls.append((command_id, instance_ids, parameters))
        return self.receipt or {"task_id": parameters["task_id"], "state": "SUCCESS"}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = TaskJournal(Path(self.temp.name) / "journal.sqlite3")
        self.reporter = GitHubCompatibleReporter(key_id=KEY_ID, key=KEY)

    def execute(self, task, transport=None):
        return execute_task(task, key_id=KEY_ID, key=KEY, policy=POLICY,
                            transport=transport or MockCloudTransport(), reporter=self.reporter,
                            journal=self.journal, mode="mock", now=FIXED_NOW, sleep=lambda _: None)

    def test_read_diagnose_closed_loop_redacts_raw_logs_and_never_contacts_host(self):
        transport = MockCloudTransport(raw_log_fixture="TENCENTCLOUD_SECRET_KEY=abc123 /srv/private 10.0.0.1")
        result = self.execute(make_task(), transport)
        self.assertEqual(result["state"], "SUCCEEDED")
        self.assertFalse(result["host_contacted"])
        self.assertTrue(verify_result(result, KEY_ID, KEY))
        report = self.reporter.reports[-1]
        self.assertTrue(verify_result(report, KEY_ID, KEY))
        self.assertNotIn("abc123", json.dumps(report))
        self.assertNotIn("10.0.0.1", json.dumps(report))
        self.assertEqual(transport.calls, ["READ_DIAGNOSE"])
        self.assertEqual(self.journal.state(result["task_id"])[0], "SUCCEEDED")

    def test_verify_artifact_digest_and_tamper_are_enforced(self):
        body = b"synthetic release fixture"
        key = f"releases/{SHA}/release.tar"
        artifact = {"object_key": key, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
        good = make_task("VERIFY_ARTIFACT", artifact=artifact)
        ok = self.execute(good, MockCloudTransport(artifacts={key: body}))
        self.assertEqual(ok["result_code"], "MOCK_ARTIFACT_VERIFIED")
        bad = make_task("VERIFY_ARTIFACT", artifact=artifact)
        blocked = self.execute(bad, MockCloudTransport(artifacts={key: b"tampered"}))
        self.assertEqual(blocked["state"], "BLOCKED")
        self.assertEqual(blocked["result_code"], "ARTIFACT_INTEGRITY_FAILED")

    def test_expired_wrong_ci_and_tampered_signature_are_rejected_before_transport(self):
        expired = make_task(ttl=1)
        transport = MockCloudTransport()
        with self.assertRaisesRegex(ProtocolError, "expired"):
            execute_task(expired, key_id=KEY_ID, key=KEY, policy=POLICY, transport=transport,
                         reporter=self.reporter, journal=self.journal, now=FIXED_NOW + timedelta(seconds=2))
        self.assertEqual(transport.calls, [])
        with self.assertRaisesRegex(ProtocolError, "CI evidence"):
            make_task(ci_sha="d" * 40)
        modified = make_task()
        modified["target_sha"] = "d" * 40
        modified["ci"]["head_sha"] = "d" * 40
        with self.assertRaisesRegex(ProtocolError, "signature"):
            authenticate_task(modified, KEY_ID, KEY, now=FIXED_NOW)
        malformed = make_task()
        malformed["operation"] = []
        with self.assertRaises(ProtocolError):
            authenticate_task(malformed, KEY_ID, KEY, now=FIXED_NOW)

    def test_production_and_staging_deploy_are_refused(self):
        for task in (make_task(environment="production"), make_task("STAGING_DEPLOY", environment="staging")):
            with self.assertRaises(PolicyBlocked):
                execute_task(task, key_id=KEY_ID, key=KEY, policy=POLICY,
                             transport=MockCloudTransport(), reporter=self.reporter,
                             journal=self.journal, mode="mock", now=FIXED_NOW)

    def test_task_replay_is_rejected_and_concurrent_duplicate_runs_once(self):
        task = make_task()
        transport = MockCloudTransport()
        self.execute(task, transport)
        with self.assertRaises(ReplayDetected):
            self.execute(task, transport)
        self.assertEqual(transport.calls, ["READ_DIAGNOSE"])

        concurrent_task = make_task()
        concurrent_transport = MockCloudTransport()
        barrier = threading.Barrier(8)
        outcomes = []
        def run():
            barrier.wait()
            try:
                self.execute(concurrent_task, concurrent_transport)
                outcomes.append("ok")
            except ReplayDetected:
                outcomes.append("replay")
        threads = [threading.Thread(target=run) for _ in range(8)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=5)
        self.assertEqual(outcomes.count("ok"), 1)
        self.assertEqual(outcomes.count("replay"), 7)
        self.assertEqual(concurrent_transport.calls, ["READ_DIAGNOSE"])

    def test_retry_limit_is_two_retries_then_blocked(self):
        transport = MockCloudTransport(fail_reads=5)
        result = self.execute(make_task(), transport)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["result_code"], "TIMEOUT")
        self.assertEqual(len(transport.calls), 3)

    def test_journal_refuses_symlink_and_group_access(self):
        link = Path(self.temp.name) / "link.sqlite3"
        link.symlink_to(Path(self.temp.name) / "journal.sqlite3")
        with self.assertRaisesRegex(ValueError, "symlink"):
            TaskJournal(link)
        broad = Path(self.temp.name) / "broad.sqlite3"
        broad.write_bytes(b"")
        broad.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "Unsafe bridge journal file"):
            TaskJournal(broad)

    def test_cloud_mode_is_closed_and_noop_fails_without_contact(self):
        self.assertFalse(POLICY["cloud_transport_enabled"])
        task = make_task()
        with self.assertRaises(PolicyBlocked):
            execute_task(task, key_id=KEY_ID, key=KEY, policy=POLICY,
                         transport=NoOpCloudTransport(), reporter=self.reporter,
                         journal=self.journal, mode="cloud", now=FIXED_NOW)
        with self.assertRaises(TransportError) as caught:
            NoOpCloudTransport().read_diagnose(task)
        self.assertEqual(caught.exception.code, "CLOUD_AUTH_NOT_CONFIGURED")
        with self.assertRaises(TransportError) as tat_error:
            TencentTATAdapter(None, command_id=None, command_sha256=None).invoke(task)
        self.assertEqual(tat_error.exception.code, "TAT_NOT_CONFIGURED")
        with self.assertRaises(TransportError) as cos_error:
            TencentCOSAdapter(None, bucket_name=None, region=None).put_task(task)
        self.assertEqual(cos_error.exception.code, "COS_NOT_CONFIGURED")
        enabled_policy = copy.deepcopy(POLICY)
        enabled_policy["cloud_transport_enabled"] = True
        enabled_policy["operations"]["READ_DIAGNOSE"]["cloud_enabled"] = True
        with self.assertRaisesRegex(PolicyBlocked, "real CI"):
            execute_task(task, key_id=KEY_ID, key=KEY, policy=enabled_policy,
                         transport=NoOpCloudTransport(), reporter=self.reporter,
                         journal=self.journal, mode="cloud", now=FIXED_NOW)

    def test_credentials_require_complete_temporary_set_and_never_repr_secrets(self):
        self.assertIsNone(credentials_from_environment({}))
        with self.assertRaises(CredentialError):
            credentials_from_environment({"TENCENTCLOUD_SECRET_ID": "AKID12345678"})
        values = {"TENCENTCLOUD_SECRET_ID": "AKID12345678", "TENCENTCLOUD_SECRET_KEY": "s" * 40,
                  "TENCENTCLOUD_SESSION_TOKEN": "t" * 30,
                  "TENCENTCLOUD_CREDENTIAL_EXPIRES_AT": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
        creds = credentials_from_environment(values)
        rendered = repr(creds)
        self.assertNotIn("s" * 20, rendered)
        self.assertNotIn("t" * 20, rendered)

    def test_fixed_tat_allowlist_and_private_immutable_cos_adapter(self):
        task = make_task()
        invoker = FakeTAT()
        tat = TencentTATAdapter(invoker, command_id="cmd-diagnostic-v1", command_sha256="e" * 64,
                                instance_ids=("ins-stage-v1",))
        tat.invoke(task)
        self.assertEqual(invoker.calls[0][0], "cmd-diagnostic-v1")
        self.assertEqual(invoker.calls[0][2]["operation"], "READ_DIAGNOSE")
        self.assertEqual(invoker.calls[0][2]["expected_command_sha256"], "e" * 64)
        self.assertNotIn("shell", json.dumps(invoker.calls))
        with self.assertRaises(TransportError):
            tat.invoke(make_task("STAGING_DEPLOY"))
        bucket = FakeCOS()
        cos = TencentCOSAdapter(bucket, bucket_name="private-stage-bucket", region="ap-shanghai")
        cos.put_task(task)
        key, private, encryption, no_overwrite = bucket.put_options[-1]
        self.assertEqual(key, f"bsv-ops-bridge/tasks/{task['task_id']}/task.json")
        self.assertTrue(private)
        self.assertEqual(encryption, "AES256")
        self.assertTrue(no_overwrite)

    def test_tencent_transport_binds_and_verifies_cos_result(self):
        task = make_task()
        unsigned = {"schema_version": "1.0", "task_id": task["task_id"], "request_id": task["request_id"],
                    "operation": task["operation"], "state": "SUCCEEDED", "result_code": "DIAGNOSE_OK",
                    "target_sha": SHA, "current_sha": CURRENT, "rollback_sha": ROLLBACK,
                    "environment": "isolated", "evidence_location": f"cos://private/{task['task_id']}/log.txt",
                    "summary": "诊断通过", "occurred_at": "2026-01-02T03:04:05Z", "host_contacted": True}
        from protocol import sign_result
        signed = sign_result(unsigned, KEY_ID, KEY)
        result_key = f"bsv-ops-bridge/results/{task['task_id']}/result.json"
        bucket = FakeCOS(results={result_key: json.dumps(signed).encode()})
        cos = TencentCOSAdapter(bucket, bucket_name="private-stage-bucket", region="ap-shanghai")
        tat = TencentTATAdapter(FakeTAT(), command_id="cmd-diagnostic-v1", command_sha256="e" * 64,
                                instance_ids=("ins-stage-v1",))
        transport = TencentCloudTransport(tat=tat, cos=cos, key_id=KEY_ID, task_key=KEY)
        self.assertEqual(transport.read_diagnose(task)["result_code"], "DIAGNOSE_OK")
        self.assertTrue(transport.host_contacted)
        task2 = make_task()
        wrong = dict(signed, task_id=task2["task_id"], target_sha="d" * 40)
        result_key2 = f"bsv-ops-bridge/results/{task2['task_id']}/result.json"
        bucket2 = FakeCOS(results={result_key2: json.dumps(wrong).encode()})
        cos2 = TencentCOSAdapter(bucket2, bucket_name="private-stage-bucket", region="ap-shanghai")
        transport2 = TencentCloudTransport(tat=tat, cos=cos2, key_id=KEY_ID, task_key=KEY)
        with self.assertRaises(TransportError):
            transport2.read_diagnose(task2)

    def test_report_redaction_and_cli_both_operations(self):
        value = redact("TENCENTCLOUD_SECRET_KEY=secretvalue admin@example.com 192.0.2.4 /srv/private")
        for forbidden in ("secretvalue", "admin@example.com", "192.0.2.4", "/srv/private"):
            self.assertNotIn(forbidden, value)
        self.assertEqual(run_mock_roundtrip("READ_DIAGNOSE", SHA)["state"], "SUCCEEDED")
        self.assertEqual(run_mock_roundtrip("VERIFY_ARTIFACT", SHA)["state"], "SUCCEEDED")

    def test_json_schemas_are_parseable_and_workflow_is_least_privilege(self):
        for name in ("task.schema.json", "result.schema.json"):
            schema = json.loads((ROOT / "contracts/ops-bridge" / name).read_text())
            self.assertEqual(schema["additionalProperties"], False)
        workflow = (ROOT / ".github/workflows/bsv-ops-bridge-dry-run.yml").read_text()
        self.assertIn("permissions:", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("TENCENTCLOUD_SECRET_KEY", workflow)
        self.assertNotIn("STAGING_DEPLOY", workflow)


if __name__ == "__main__":
    unittest.main()
