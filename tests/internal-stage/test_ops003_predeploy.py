#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "platform/lighthouse/internal-stage"))
import ops003_predeploy as predeploy


class PredeploySupplementTests(unittest.TestCase):
    def test_target_lock_set_and_supported_architectures_are_explicit(self):
        self.assertEqual(set(predeploy.REQUIRED_LOCKS), {
            "services/api/identity/requirements.lock",
            "services/api/customer_growth/requirements.stage.lock",
            "services/api/supply/requirements.lock",
        })
        self.assertEqual(predeploy.EXPECTED_ARCH, {"x86_64": "amd64", "aarch64": "arm64"})
        self.assertEqual(predeploy.TARGET_SHA, "cb06be66e78d92b8921fc3103b12bdbdc55284f8")

    def test_previous_amd64_wheelhouse_locks_are_byte_identical_at_h(self):
        proof = predeploy.lock_compatibility(
            "f00371ccd1c233caf8eea97398bf981cf7d65dd0", predeploy.TARGET_SHA)
        self.assertEqual(proof["wheelhouse_reuse"], "BYTE_IDENTICAL_LOCKS_ONLY")
        self.assertEqual(proof["previous_supplement_artifact_id"], 14710029781)
        self.assertEqual(len(proof["locks"]), 3)
        self.assertTrue(all(row["identical"] for row in proof["locks"].values()))

    def test_supplement_file_inventory_and_tamper_detection(self):
        with tempfile.TemporaryDirectory(prefix="bsv-ops003-supplement-test-") as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            (root / "wheels").mkdir()
            (root / "wheels/sample.whl").write_bytes(b"synthetic wheel bytes")
            out = Path(tmp) / "supplement.tar"
            metadata = {"target_sha": predeploy.TARGET_SHA,
                        "source_ci_run_id": predeploy.SOURCE_CI_RUN,
                        "source_artifact_run_id": predeploy.SOURCE_ARTIFACT_RUN,
                        "host_architecture_confirmed": True,
                        "release_signature": "OFFLINE_SIGNATURE_PASS",
                        "offline_dependencies": "PASS"}
            package = predeploy.pack_supplement(root, arch="amd64", metadata=metadata, output=out)
            self.assertTrue(out.is_file())
            self.assertEqual(package["target_arch"], "amd64")
            self.assertEqual(predeploy.verify_supplement_tree(root)["file_inventory"], "PASS")
            self.assertEqual(predeploy.verify_supplement_archive(out)["archive_inventory"], "PASS")
            (root / "wheels/sample.whl").write_bytes(b"tampered")
            with self.assertRaisesRegex(predeploy.PredeployError, "integrity mismatch"):
                predeploy.verify_supplement_tree(root)

    def test_offline_install_rejects_missing_wheels(self):
        # The same failure path used by stage.create_release_venv is checked with an empty
        # PIP_FIND_LINKS directory. This is safe and never reaches an external index.
        with tempfile.TemporaryDirectory(prefix="bsv-ops003-missing-wheel-") as tmp:
            scratch = Path(tmp)
            empty = scratch / "wheelhouse"
            empty.mkdir()
            predeploy.prove_missing_wheel_rejected(empty, scratch=scratch / "missing")

    @unittest.skipUnless(os.environ.get("OPS003_RELEASE_DIR") and os.environ.get("OPS003_COSIGN")
                         and os.environ.get("OPS003_TRUSTED_ROOT") and os.environ.get("OPS003_WHEELHOUSE"),
                         "requires the authenticated GitHub release artifact and matrix wheelhouse")
    def test_actual_offline_signature_and_full_locked_install(self):
        base = Path(os.environ["OPS003_RELEASE_DIR"])
        cosign = Path(os.environ["OPS003_COSIGN"])
        root = Path(os.environ["OPS003_TRUSTED_ROOT"])
        bundle = base / f"bsv-all-{predeploy.TARGET_SHA}.tar"
        with tempfile.TemporaryDirectory(prefix="bsv-ops003-real-test-") as tmp:
            scratch = Path(tmp)
            signed = predeploy.verify_source_package(
                cosign, root, bundle, bundle.with_name(bundle.name + ".sha256"),
                bundle.with_name(bundle.name + ".sigstore.json"))
            self.assertEqual(signed["signature"], "OFFLINE_SIGNATURE_PASS")
            predeploy.prove_tamper_rejection(cosign, root, bundle,
                                              bundle.with_name(bundle.name + ".sigstore.json"),
                                              scratch / "tamper")
            wheel_result = predeploy.exercise_offline_venvs(Path(os.environ["OPS003_WHEELHOUSE"]),
                                                            scratch=scratch / "venvs")
            self.assertEqual(wheel_result["network_access"], "DISABLED_BY_PIP_NO_INDEX")
            predeploy.prove_missing_wheel_rejected(Path(os.environ["OPS003_WHEELHOUSE"]), scratch=scratch / "missing")


if __name__ == "__main__":
    unittest.main()
