"""Exercise release switching and failure handling without systemd or host mutations."""
import importlib.util
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[2] / "platform/lighthouse/internal-stage/stage.py"
spec = importlib.util.spec_from_file_location("internal_stage", path)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)

OLD = "1" * 40
NEW = "2" * 40


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        original = stage.write_secret
        fixture_writer = patch.object(stage, "write_secret", side_effect=lambda path, value:
                                      original(path, value, os.getuid(), os.getgid()))
        fixture_writer.start()
        self.addCleanup(fixture_writer.stop)

    def test_success_and_rollback_preserve_state(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "ROOT", Path(tmp)), \
                patch.object(stage, "UNIT_FILE", path), patch.object(stage, "run"), \
                patch.object(stage, "preflight"), patch.object(stage, "prepare_config", return_value=({}, {}, "", "")), \
                patch.object(stage, "build"), patch.object(stage, "prepare_pg"), patch.object(stage, "bootstrap"), \
                patch.object(stage, "switch_services") as services, patch.object(stage, "verify"):
            for sha in (OLD, NEW):
                (stage.ROOT / "releases" / sha).mkdir(parents=True)
            preserved = stage.ROOT / "orders.sqlite3"
            preserved.write_bytes(b"existing")
            stage.link("current", OLD)
            stage.deploy(NEW)
            self.assertEqual(stage.sha_at(stage.ROOT / "current"), NEW)
            self.assertEqual(stage.sha_at(stage.ROOT / "previous"), OLD)
            stage.rollback()
            self.assertEqual(stage.sha_at(stage.ROOT / "current"), OLD)
            self.assertEqual(preserved.read_bytes(), b"existing")
            self.assertEqual([call.args for call in services.call_args_list], [(False,), (True,)] * 2)

    def test_failed_verification_recovers_previous_release(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "ROOT", Path(tmp)), \
                patch.object(stage, "UNIT_FILE", path), patch.object(stage, "run"), \
                patch.object(stage, "preflight"), patch.object(stage, "prepare_config", return_value=({}, {}, "", "")), \
                patch.object(stage, "build"), patch.object(stage, "prepare_pg"), patch.object(stage, "bootstrap"), \
                patch.object(stage, "switch_services") as services, \
                patch.object(stage, "verify", side_effect=[RuntimeError("intentionally failed"), None]):
            for sha in (OLD, NEW):
                (stage.ROOT / "releases" / sha).mkdir(parents=True)
            stage.link("current", OLD)
            with self.assertRaisesRegex(RuntimeError, "intentionally failed"):
                stage.deploy(NEW)
            self.assertEqual(stage.sha_at(stage.ROOT / "current"), OLD)
            self.assertIsNone(stage.sha_at(stage.ROOT / "previous"))
            self.assertEqual([call.args for call in services.call_args_list], [(False,), (True,)] * 2)

    def test_interrupted_activation_recovers_previous_version(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "ROOT", Path(tmp)), \
                patch.object(stage, "switch_services") as services, patch.object(stage, "verify"):
            for sha in (OLD, NEW):
                (stage.ROOT / "releases" / sha).mkdir(parents=True)
            stage.link("current", NEW)
            marker = stage.ROOT / "activation.pending"
            marker.write_text(OLD + "\n")
            stage.recover_pending()
            self.assertEqual(stage.sha_at(stage.ROOT / "current"), OLD)
            self.assertFalse(marker.exists())
            self.assertEqual([call.args for call in services.call_args_list], [(False,), (True,)])


    def test_systemd_runner_targets_release_src(self):
        repo = Path(__file__).resolve().parents[2]
        template = (repo / "platform/lighthouse/internal-stage/bsv-all-internal-stage@.service").read_text()
        self.assertTrue((repo / "platform/lighthouse/internal-stage/run.sh").is_file())
        self.assertIn("WorkingDirectory=/opt/bsv-all-internal-stage/current/src", template)
        self.assertIn(
            "ExecStart=/bin/bash /opt/bsv-all-internal-stage/current/src/platform/lighthouse/internal-stage/run.sh %i",
            template,
        )
        self.assertNotIn(
            "ExecStart=/bin/bash /opt/bsv-all-internal-stage/current/platform/",
            template,
        )

    def test_runuser_absolute_with_restricted_environment(self):
        restricted_env = {"PATH": "/usr/bin:/bin"}
        with patch.object(stage, "run") as mock_run:
            stage.as_user("identity", "/bin/true", env=restricted_env)
        mock_run.assert_called_once_with(
            "/usr/sbin/runuser", "-u", "bsvint-identity", "--", "/bin/true",
            env=restricted_env,
        )


    def test_legacy_preview_feedback_is_inline(self):
        repo = Path(__file__).resolve().parents[2]
        script = (repo / "apps/hq-console/identity/hq.js").read_text(encoding="utf-8")
        handler = script.split("$('#legacy-form').addEventListener", 1)[1].split(
            "$('#people-form').addEventListener", 1)[0]
        self.assertIn("正在执行只读预检", handler)
        self.assertIn("只读预检失败", handler)
        self.assertIn("output.prepend", handler)
        self.assertIn("output.scrollIntoView", handler)
        self.assertIn("submit.disabled=false", handler)



if __name__ == "__main__":
    unittest.main()
