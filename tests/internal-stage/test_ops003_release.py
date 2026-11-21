#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "platform/lighthouse/internal-stage"))
import ops003_release as release


def valid_run():
    return {"url": release.CI_RUN_URL, "headSha": release.TARGET_SHA, "event": "pull_request",
            "status": "completed", "conclusion": "success", "workflowName": "validate-architecture"}


def valid_jobs():
    return [{"name": name, "status": "completed", "conclusion": "success"}
            for name in sorted(release.REQUIRED_JOBS)]


class ReleaseBundleTests(unittest.TestCase):
    def test_only_exact_successful_ci_run_is_accepted(self):
        proof = release.validate_ci(valid_run(), valid_jobs())
        self.assertEqual(proof["run_id"], 44922120417)
        self.assertEqual(len(proof["jobs"]), 9)
        wrong_sha = valid_run()
        wrong_sha["headSha"] = "a" * 40
        with self.assertRaisesRegex(release.ReleaseError, "pinned successful PR run"):
            release.validate_ci(wrong_sha, valid_jobs())
        failed_jobs = valid_jobs()
        failed_jobs[0] = dict(failed_jobs[0], conclusion="failure")
        with self.assertRaisesRegex(release.ReleaseError, "failed"):
            release.validate_ci(valid_run(), failed_jobs)
        with self.assertRaisesRegex(release.ReleaseError, "job set mismatch"):
            release.validate_ci(valid_run(), valid_jobs()[:-1])

    def test_exact_sha_build_reproduces_and_offline_verifies_package(self):
        with tempfile.TemporaryDirectory(prefix="bsv-ops003-test-") as temporary:
            output = Path(temporary) / "private"
            result = release.build(valid_run(), valid_jobs(), output)
            bundle = Path(result["bundle"])
            checksum = bundle.with_name(bundle.name + ".sha256")
            self.assertEqual(result["target_sha"], release.TARGET_SHA)
            self.assertEqual(result["ci_run_id"], release.CI_RUN_ID)
            self.assertGreater(result["source_entries"], 500)
            self.assertLess(result["size_bytes"], 10_000_000)
            self.assertEqual(bundle.stat().st_mode & 0o777, 0o600)
            self.assertEqual(release.verify(bundle, checksum)["bundle_sha256"], result["sha256"])
            files = release._read_bundle(bundle)
            manifest = json.loads(files["release-manifest.json"])
            self.assertEqual(len(manifest["source_file_sha256"]),
                             sum(row["kind"] == "file" for row in manifest["source_manifest"]["entries"].values()))
            self.assertTrue(all(len(digest) == 64 for digest in manifest["source_file_sha256"].values()))
            first = bundle.read_bytes()
            with self.assertRaisesRegex(release.ReleaseError, "Refusing to overwrite"):
                release.build(valid_run(), valid_jobs(), output)
            self.assertEqual(bundle.read_bytes(), first)

    def test_bundle_corruption_and_ci_proof_tampering_fail_offline(self):
        with tempfile.TemporaryDirectory(prefix="bsv-ops003-test-") as temporary:
            output = Path(temporary) / "private"
            result = release.build(valid_run(), valid_jobs(), output)
            bundle = Path(result["bundle"])
            data = bytearray(bundle.read_bytes())
            data[-1] ^= 0x01
            tampered = Path(temporary) / "tampered.tar"
            tampered.write_bytes(data)
            checksum = bundle.with_name(bundle.name + ".sha256")
            with self.assertRaisesRegex(release.ReleaseError, "SHA-256"):
                release.verify(tampered, checksum)
            checksum.write_text("0" * 64 + "  " + bundle.name + "\n")
            with self.assertRaisesRegex(release.ReleaseError, "SHA-256"):
                release.verify(bundle, checksum)

    def test_manifest_matches_json_schema(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema is installed in the GitHub release workflow")
        schema = json.loads((ROOT / "contracts/ops-bridge/release-bundle.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        with tempfile.TemporaryDirectory(prefix="bsv-ops003-schema-") as temporary:
            result = release.build(valid_run(), valid_jobs(), Path(temporary) / "private")
            files = release._read_bundle(Path(result["bundle"]))
            Draft202012Validator(schema).validate(json.loads(files["release-manifest.json"]))


if __name__ == "__main__":
    unittest.main()
