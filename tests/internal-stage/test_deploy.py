"""Exercise release switching and failure handling without systemd or host mutations."""
import importlib.util
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
