"""Exercise release switching and failure handling without systemd or host mutations."""
import importlib.util
import json
from pathlib import Path
import os
import sqlite3
from subprocess import CompletedProcess
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import call, patch

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
                patch.object(stage, "activation_checkpoint") as checkpoint, patch.object(stage, "host_evidence"), \
                patch.object(stage, "switch_services") as services, patch.object(stage, "verify"):
            for sha in (OLD, NEW):
                (stage.ROOT / "releases" / sha).mkdir(parents=True)
            preserved = stage.ROOT / "orders.sqlite3"
            preserved.write_bytes(b"existing")
            stage.link("current", OLD)
            with patch.object(stage, "migration_compatibility") as compatibility:
                stage.deploy(NEW)
                self.assertEqual(stage.sha_at(stage.ROOT / "current"), NEW)
                self.assertEqual(stage.sha_at(stage.ROOT / "previous"), OLD)
                stage.rollback()
            compatibility.assert_has_calls([
                call(stage.ROOT / "releases" / OLD / "src", stage.REPO),
                call(stage.ROOT / "releases" / OLD / "src", stage.ROOT / "releases" / NEW / "src"),
            ])
            self.assertEqual(stage.sha_at(stage.ROOT / "current"), OLD)
            self.assertEqual(preserved.read_bytes(), b"existing")
            self.assertEqual([entry.args for entry in services.call_args_list], [(False,), (True,)] * 2)
            self.assertEqual(checkpoint.call_args_list, [call(OLD, "pre_deploy"), call(NEW, "pre_rollback")])

    def test_failed_verification_recovers_previous_release(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "ROOT", Path(tmp)), \
                patch.object(stage, "UNIT_FILE", path), patch.object(stage, "run"), \
                patch.object(stage, "preflight"), patch.object(stage, "prepare_config", return_value=({}, {}, "", "")), \
                patch.object(stage, "build"), patch.object(stage, "prepare_pg"), patch.object(stage, "bootstrap"), \
                patch.object(stage, "migration_compatibility"), \
                patch.object(stage, "activation_checkpoint") as checkpoint, patch.object(stage, "host_evidence"), \
                patch.object(stage, "switch_services") as services, \
                patch.object(stage, "verify", side_effect=[RuntimeError("intentionally failed"), None]):
            for sha in (OLD, NEW):
                (stage.ROOT / "releases" / sha).mkdir(parents=True)
            stage.link("current", OLD)
            with self.assertRaisesRegex(RuntimeError, "intentionally failed"):
                stage.deploy(NEW)
            self.assertEqual(stage.sha_at(stage.ROOT / "current"), OLD)
            self.assertIsNone(stage.sha_at(stage.ROOT / "previous"))
            self.assertEqual([entry.args for entry in services.call_args_list], [(False,), (True,)] * 2)
            self.assertEqual(checkpoint.call_args_list, [call(OLD, "pre_deploy")])

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


    def test_backup_failure_keeps_current_release(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "ROOT", Path(tmp)), \
                patch.object(stage, "UNIT_FILE", path), patch.object(stage, "run"), \
                patch.object(stage, "preflight"), patch.object(stage, "prepare_config", return_value=({}, {}, "", "")), \
                patch.object(stage, "build"), patch.object(stage, "prepare_pg") as prepare_pg, \
                patch.object(stage, "migration_compatibility"), \
                patch.object(stage, "activation_checkpoint", side_effect=RuntimeError("backup failed")), \
                patch.object(stage, "switch_services") as services, patch.object(stage, "verify"):
            for sha in (OLD, NEW):
                (stage.ROOT / "releases" / sha).mkdir(parents=True)
            stage.link("current", OLD)
            with self.assertRaisesRegex(RuntimeError, "backup failed"):
                stage.deploy(NEW)
            self.assertEqual(stage.sha_at(stage.ROOT / "current"), OLD)
            self.assertFalse((stage.ROOT / "activation.pending").exists())
            prepare_pg.assert_not_called()
            self.assertEqual(services.call_args_list, [call(False), call(True)])

    def test_upgrade_only_permits_known_additive_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            v3, v4 = Path(tmp) / "v3", Path(tmp) / "v4"
            for repo in (v3, v4):
                (repo / stage.MIGRATIONS / "versions").mkdir(parents=True)
                (repo / stage.MIGRATIONS / "env.py").write_text("existing config")
                (repo / stage.MIGRATIONS / "versions/prior.py").write_text("existing schema")
            new = v4 / stage.MIGRATIONS / stage.ACADEMY_MIGRATION
            new.write_text("additive V4.1 schema")
            stage.migration_compatibility(v3, v4)
            self.assertEqual(stage.migration_revisions(v4), [stage.IDENTITY_REVISION, stage.ACADEMY_REVISION])
            with self.assertRaisesRegex(RuntimeError, "differ outside"):
                stage.migration_compatibility(v4, v3)
            (v4 / stage.MIGRATIONS / "versions/prior.py").write_text("replacement")
            with self.assertRaisesRegex(RuntimeError, "differ outside"):
                stage.migration_compatibility(v3, v4)
            (v4 / stage.MIGRATIONS / "versions/prior.py").write_text("existing schema")
            (v4 / stage.MIGRATIONS / "versions/unapproved.py").touch()
            with self.assertRaisesRegex(RuntimeError, "differ outside"):
                stage.migration_compatibility(v3, v4)

    def test_private_academy_checkpoint_copies_immutable_media_only(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "DATA", Path(tmp)), \
                patch.object(stage.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=os.getuid())):
            media = stage.DATA / "identity" / "academy-media"
            media.mkdir(parents=True, mode=0o700)
            valid = media / "12345678-1234-1234-1234-123456789abc.bin"
            valid.touch(mode=0o600)
            valid.write_bytes(b"synthetic Academy lesson")
            (media / ".scan-live").touch(mode=0o600)
            recovered = Path(tmp) / "recovered"
            result = stage.academy_media_snapshot(recovered)
            self.assertEqual(result, [{"name": valid.name, "filesize": valid.stat().st_size,
                                       "sha256": stage.file_sha256(valid)}])
            self.assertEqual((recovered / valid.name).stat().st_mode & 0o777, 0o600)
            self.assertEqual((recovered / valid.name).read_bytes(), valid.read_bytes())
            (media / "22345678-1234-1234-1234-123456789abc.bin").symlink_to(valid)
            with self.assertRaises(OSError):
                stage.academy_media_snapshot(Path(tmp) / "blocked")

    def test_recovery_check_rejects_altered_checkpoint_without_restoring(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "DATA", Path(tmp)), \
                patch.object(stage, "sha_at", return_value=OLD), \
                patch.object(stage, "private_directory"), patch.object(stage, "private_file"), \
                patch.object(stage.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=os.getuid())):
            checkpoint = Path(tmp) / "recovery" / "20261120T080000Z-abc1234abc"
            checkpoint.mkdir(parents=True)
            pos = checkpoint / "pos.sqlite3"
            with sqlite3.connect(pos) as db:
                db.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY)")
                db.execute("INSERT INTO orders DEFAULT VALUES")
            archives = Path(tmp) / "identity" / "archives"
            archives.mkdir(parents=True)
            archive = archives / "identity-A-20261120T080000Z-aabbcc.bsvenc"
            archive.write_bytes(b"synthetic digest fixture")
            receipt = checkpoint / "receipt.json"
            receipt.write_text(json.dumps({
                "version": 2, "mode": "isolated", "status": "CHECKPOINT_READY", "checkpoint": str(receipt),
                "postgres": {"archive": str(archive), "sha256": stage.file_sha256(archive)},
                "pos_sqlite": {"sha256": stage.file_sha256(pos)},
            }))
            config = {"BSV_APP_ENV": "isolated", "BSV_LOCAL_ARCHIVE_DIR": str(archives),
                      "BSV_BACKUP_KEY_FILE": str(archives.parent / "archive.key")}
            pg = CompletedProcess([], 0, stdout=json.dumps({"integrity": "AES_GCM_VERIFIED",
                                  "restore": "DRY_RUN_NO_WRITE", "meta": {"type": "postgresql"}}))
            with patch.object(stage, "service_config", return_value=config), \
                    patch.object(stage, "identity_tool", return_value=pg) as identity:
                stage.recovery_check(receipt)
                self.assertNotIn("--apply-isolated", identity.call_args.args)
                pos.write_bytes(b"tampered")
                with self.assertRaisesRegex(RuntimeError, "POS checkpoint checksum mismatch"):
                    stage.recovery_check(receipt)

    def test_activation_quiesces_isolated_writers_before_checkpoint(self):
        with patch.object(stage, "switch_services") as services, patch.object(stage, "active", return_value=True), \
                patch.object(stage.subprocess, "run", return_value=CompletedProcess([], 0)), \
                patch.object(stage, "backup") as backup:
            stage.activation_checkpoint(OLD, "pre_deploy")
            services.assert_called_once_with(False, keep_postgres=True)
            backup.assert_called_once_with(OLD, "pre_deploy")

    def test_sqlite_checkpoint_permits_existing_private_app_file_mode(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "DATA", Path(tmp)):
            pos_dir = Path(tmp) / "pos"
            backups = pos_dir / "backups"
            backups.mkdir(parents=True)
            live = pos_dir / "synthetic.sqlite3"
            live.touch(mode=0o644)
            saved = backups / "synthetic_backup_20261120T080000123456Z.sqlite3"
            with sqlite3.connect(saved) as db:
                db.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY)")
                db.execute("INSERT INTO orders DEFAULT VALUES")
            saved.chmod(0o600)
            destination = Path(tmp) / "snapshot.sqlite3"
            configuration = {"BSV_DB_PATH": str(live), "BSV_BACKUP_DIR": str(backups), "BSV_MODE": "staging",
                             "BSV_POS_INTERNAL_STAGE": "1"}
            result = CompletedProcess([], 0, stdout=f"备份成功： {saved}\n")
            with patch.object(stage, "service_config", return_value=configuration), \
                    patch.object(stage.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=os.getuid())), \
                    patch.object(stage, "as_user", return_value=result):
                verification = stage.sqlite_snapshot(OLD, destination)
            self.assertEqual(verification["integrity"], "QUICK_CHECK_OK")
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(verification["sha256"], stage.file_sha256(saved))
            with sqlite3.connect(destination) as db:
                self.assertEqual(db.execute("SELECT * FROM orders").fetchall(), [(1,)])

    def test_health_evidence_rejects_public_or_unmanaged_listeners(self):
        reported = {port: ["127.0.0.1"] for port in (*stage.PORTS.values(), *stage.LEGACY_UNITS)}
        with patch.object(stage, "listening_ports", return_value=reported), \
                patch.object(stage, "sha_at", return_value=OLD), patch.object(stage, "unit_active", return_value=True):
            self.assertEqual(stage.host_evidence()["deployed_sha"], OLD)
            reported[18764].append("0.0.0.0")
            with self.assertRaisesRegex(RuntimeError, "non-loopback listener"):
                stage.host_evidence()
            reported[18764].remove("0.0.0.0")
            with patch.object(stage, "active", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "outside managed service"):
                    stage.host_evidence(require_all=False)


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
            "$('#people-form')", 1)[0]
        self.assertIn("正在核对编码", handler)
        self.assertIn("此次核对未取得结果", handler)
        self.assertIn("output.prepend", handler)
        self.assertIn("output.scrollIntoView", handler)
        self.assertIn("submit.disabled=false", handler)



if __name__ == "__main__":
    unittest.main()
