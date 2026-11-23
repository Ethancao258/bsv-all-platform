"""Exercise release switching and failure handling without systemd or host mutations."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import os
import sqlite3
import subprocess
import tarfile
from io import BytesIO
from subprocess import CompletedProcess
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import call, patch
import venv

path = Path(__file__).resolve().parents[2] / "platform/lighthouse/internal-stage/stage.py"
spec = importlib.util.spec_from_file_location("internal_stage", path)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)

OLD = "1" * 40
NEW = "2" * 40


class ReleaseTest(unittest.TestCase):
    def test_catalog_hba_upgrade_is_additive_and_refuses_drift(self):
        baseline, target = stage._catalog_hba_policies()
        self.assertEqual(stage._catalog_hba_target(baseline), target)
        self.assertEqual(stage._catalog_hba_target(target), target)
        with self.assertRaisesRegex(RuntimeError, "configuration drift"):
            stage._catalog_hba_target(baseline + "host all all 0.0.0.0/0 trust\n")
        self.assertEqual(stage._catalog_hba_target("# fresh initdb policy\n", fresh_cluster=True), target)

    def setUp(self):
        original = stage.write_secret
        fixture_writer = patch.object(stage, "write_secret", side_effect=lambda path, value, uid=0, gid=0:
                                      original(path, value, uid or os.getuid(), gid or os.getgid()))
        fixture_writer.start()
        self.addCleanup(fixture_writer.stop)

    def test_success_and_rollback_preserve_state(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "ROOT", Path(tmp)), \
                patch.object(stage, "UNIT_FILE", path), patch.object(stage, "run"), \
                patch.object(stage, "preflight"), patch.object(stage, "prepare_config", return_value=({}, {}, "", "", "", "")), \
                patch.object(stage, "build"), patch.object(stage, "prepare_pg"), patch.object(stage, "bootstrap"), \
                patch.object(stage, "verify_release_access"), \
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

    def test_real_venv_lib64_link_is_allowed_inside_managed_release(self):
        """Regression proof: the release SHA prefix must not invalidate a standard venv link."""
        with tempfile.TemporaryDirectory(prefix="bsv-real-venv-regression-") as tmp:
            root = Path(tmp)
            dest = root / "releases" / NEW
            (dest / "identity").mkdir(parents=True)
            venv.EnvBuilder(with_pip=False, symlinks=True).create(dest / "identity")
            link = dest / "identity" / "lib64"
            self.assertTrue(link.is_symlink(), "the test requires a real Python venv lib64 symlink")
            with patch.object(stage, "ROOT", root):
                self.assertTrue(stage._allowed_venv_symlink(dest, link, os.readlink(link)))

    def test_real_standard_venv_build_inventory_and_marker_under_umasks(self):
        python = Path("/usr/bin/python3")
        if not python.exists() or not subprocess.check_output([python, "--version"], text=True).strip().startswith("Python 3.12."):
            self.skipTest("requires Ubuntu 24.04 system Python 3.12")
        sha = stage.output(*stage.git("rev-parse", "HEAD"))
        for mask in (0o077, 0o022):
            with self.subTest(umask=oct(mask)), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "releases").mkdir(mode=0o700)
                old = root / "releases" / OLD
                old.mkdir(mode=0o700)
                (root / "current").symlink_to(old)

                def real_venv(dest, source, name):
                    subprocess.run([python, "-m", "venv", "--without-pip", dest / name], check=True)

                previous_mask = os.umask(mask)
                try:
                    with patch.object(stage, "ROOT", root), patch.object(stage, "create_release_venv", side_effect=real_venv):
                        release = stage.build(sha)
                        for name in ("identity", "supply"):
                            self.assertTrue((release / name / "lib64").is_symlink())
                        attestation = json.loads((release / ".built").read_text())
                        self.assertEqual(attestation["manifest"], stage.verified_source_manifest(sha))
                        self.assertEqual(attestation["inventory_sha256"], stage.release_inventory_sha256(release))
                        self.assertEqual((release / ".built").stat().st_mode & 0o777, 0o600)
                        self.assertEqual(stage.build(sha), release)
                finally:
                    os.umask(previous_mask)

    def test_venv_symlink_allowlist_rejects_unmanaged_or_unexpected_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "releases"
            releases.mkdir()
            dest = releases / NEW
            (dest / "identity").mkdir(parents=True)
            (dest / "identity/lib64").symlink_to("lib")
            link = dest / "identity/lib64"
            with patch.object(stage, "ROOT", root):
                self.assertFalse(stage._allowed_venv_symlink(dest, link, "../other-release/lib"))
                self.assertFalse(stage._allowed_venv_symlink(dest, dest / "identity/extra", "lib"))
                traversal = dest / "identity" / ".." / "identity/lib64"
                self.assertFalse(stage._allowed_venv_symlink(dest, traversal, "lib"))
                other = releases / OLD
                (other / "identity").mkdir(parents=True)
                cross_release = other / "identity/lib64"
                cross_release.symlink_to(dest / "identity/lib64")
                self.assertFalse(stage._allowed_venv_symlink(other, cross_release, str(link)))
                (dest / "supply").mkdir()
                (dest / "supply/bin").symlink_to(other / "identity", target_is_directory=True)
                self.assertFalse(stage._allowed_venv_symlink(
                    dest, dest / "supply/bin/python", "python3"))
                escaped = root / "outside" / NEW
                escaped.parent.mkdir()
                escaped.mkdir()
                self.assertFalse(stage._allowed_venv_symlink(escaped, escaped / "x", "lib"))

    def test_failed_verification_recovers_previous_release(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "ROOT", Path(tmp)), \
                patch.object(stage, "UNIT_FILE", path), patch.object(stage, "run"), \
                patch.object(stage, "preflight"), patch.object(stage, "prepare_config", return_value=({}, {}, "", "", "", "")), \
                patch.object(stage, "build"), patch.object(stage, "prepare_pg"), patch.object(stage, "bootstrap"), \
                patch.object(stage, "verify_release_access"), \
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
                patch.object(stage, "preflight"), patch.object(stage, "prepare_config", return_value=({}, {}, "", "", "", "")), \
                patch.object(stage, "build"), patch.object(stage, "prepare_pg") as prepare_pg, \
                patch.object(stage, "verify_release_access"), \
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

    def test_growth_isolated_candidate_backup_has_integrity_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "managed"
            data = Path(tmp) / "data"
            source = root / "releases" / NEW / "src/services/api/customer_growth/app.py"
            source.parent.mkdir(parents=True)
            source.write_text("# synthetic only")
            growth = data / "ingress"
            growth.mkdir(parents=True, mode=0o700)
            growth.chmod(0o700)
            live = growth / "growth-candidate.sqlite3"
            with sqlite3.connect(live) as db:
                db.execute("CREATE TABLE synthetic_customer (id TEXT PRIMARY KEY)")
                db.execute("INSERT INTO synthetic_customer VALUES ('C-FAKE')")
            live.chmod(0o600)
            target = Path(tmp) / "snapshot.sqlite3"
            cfg = {"BSV_STAGE_GROWTH_ENABLED": "1", "BSV_GROWTH_ENV": "isolated",
                   "BSV_GROWTH_DB_URL": "sqlite:///" + str(live)}
            with patch.object(stage, "ROOT", root), patch.object(stage, "DATA", data), \
                    patch.object(stage, "service_config", return_value=cfg), \
                    patch.object(stage.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=os.getuid())):
                receipt = stage.growth_candidate_snapshot(NEW, target)
                self.assertEqual(receipt["classification"], "ISOLATED_CANDIDATE_ONLY")
                self.assertEqual(receipt["sha256"], stage.file_sha256(target))
                self.assertEqual(receipt["integrity"], "QUICK_CHECK_OK")
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
                with sqlite3.connect(target) as read:
                    self.assertEqual(read.execute("SELECT id FROM synthetic_customer").fetchall(),
                                     [("C-FAKE",)])
                with patch.object(stage, "service_config", return_value={"BSV_GROWTH_ENV": "production"}):
                    with self.assertRaisesRegex(RuntimeError, "isolated"):
                        stage.growth_candidate_snapshot(NEW, Path(tmp) / "blocked.sqlite3")

    def test_ingress_blank_config_migration_refuses_unknown_changes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "ROOT", Path(tmp)), \
                patch.object(stage, "private_file"):
            config = stage.ROOT / "config"
            config.mkdir()
            blank = config / "ingress.env"
            blank.touch(mode=0o600)
            blank.chmod(0o600)
            stage.upgrade_blank_ingress_environment({"BSV_STAGE_GROWTH_ENABLED": "1"})
            self.assertIn("BSV_STAGE_GROWTH_ENABLED=1", blank.read_text())
            stage.upgrade_blank_ingress_environment({"BSV_STAGE_GROWTH_ENABLED": "1"})
            with self.assertRaisesRegex(RuntimeError, "Existing managed environment has changed"):
                stage.upgrade_blank_ingress_environment({"BSV_STAGE_GROWTH_ENABLED": "0"})
            self.assertIn("BSV_STAGE_GROWTH_ENABLED=1", blank.read_text())

    def test_pos_managed_env_allows_explicit_additions_only(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "ROOT", Path(tmp)), \
                patch.object(stage, "private_file"):
            config = stage.ROOT / "config"
            config.mkdir()
            pos = config / "pos.env"
            pos.write_text("BSV_MODE=staging\nBSV_PORT=18762\n")
            pos.chmod(0o600)
            values = {"BSV_MODE":"staging", "BSV_PORT":"18762",
                      "BSV_GROWTH_LINK_KEY":"isolated_test_key"}
            stage.upgrade_managed_environment(
                "pos", values, {"BSV_GROWTH_LINK_KEY"})
            self.assertIn("BSV_GROWTH_LINK_KEY=isolated_test_key", pos.read_text())
            stage.upgrade_managed_environment(
                "pos", values, {"BSV_GROWTH_LINK_KEY"})
            with self.assertRaisesRegex(RuntimeError,"changed"):
                stage.upgrade_managed_environment(
                    "pos", dict(values, BSV_GROWTH_LINK_KEY="different_key"),
                    {"BSV_GROWTH_LINK_KEY"})
            with self.assertRaisesRegex(RuntimeError,"Unapproved environment keys"):
                stage.upgrade_managed_environment(
                    "pos", dict(values, UNREVIEWED_KEY="secret"), set())
            self.assertNotIn("UNREVIEWED_KEY", pos.read_text())

    def test_h_scope_upgrade_requires_approval_preserves_secrets_and_rolls_back(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            data = Path(tmp) / "data"
            root.mkdir()
            data.mkdir()
            service_uid = os.geteuid() or 1000
            service_gid = os.getegid() or 1000
            users = lambda name: SimpleNamespace(
                pw_uid=service_uid, pw_gid=service_gid, pw_shell="/usr/sbin/nologin",
                pw_dir=str(data / name.removeprefix("bsvint-")))
            real_write = stage.write_secret
            def local_write(path, value, uid=0, gid=0):
                if uid == 0 and os.geteuid() != 0:
                    uid, gid = os.geteuid(), os.getegid()
                return real_write(path, value, uid, gid)
            with patch.object(stage, "ROOT", root), patch.object(stage, "DATA", data), \
                    patch.object(stage.pwd, "getpwnam", side_effect=users), \
                    patch.object(stage, "private_file"), patch.object(stage, "write_secret", side_effect=local_write), \
                    patch.object(stage, "run") as run:
                db = data / "pos" / "synthetic.sqlite3"
                db.parent.mkdir(mode=0o700)
                db.write_bytes(b"published-map-and-existing-business-records")
                db.chmod(0o600)
                layout_root = stage.REPO / "services/api/bsv1/store_layouts"
                layout_hashes = {
                    p.relative_to(layout_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in layout_root.rglob("*") if p.is_file()
                }
                stage.prepare_config()
                identity_path = root / "config/identity.env"
                pos_path = root / "config/pos.env"
                ingress_path = root / "config/ingress.env"
                secret_bytes = {name: (root / "config" / name).read_bytes()
                                for name in ("pos-token", "supply-token", "session-key", "privacy-pepper",
                                             "catalog-runtime-password", "catalog-import-password", "catalog-approval.key")}
                catalog_backup_key = (data / "catalog" / "backup.key").read_bytes()
                identity = stage.service_config("identity")
                pos = stage.service_config("pos")
                ingress = stage.service_config("ingress")
                self.assertEqual(pos["BSV_PRODUCT_MEDIA_ROOT"], str(data / "pos" / "product-media"))
                self.assertEqual(pos["BSV_IMPORT_ROOT"], str(data / "pos" / "imports"))
                self.assertRegex(pos["BSV_DB_URL"], r"^postgresql\+psycopg://bsv_catalog_runtime:[A-Za-z0-9_-]+@127\.0\.0\.1:18764/bsv_all_prod$")
                self.assertEqual(pos["BSV_CATALOG_READ_SOURCE"], "postgres")
                self.assertNotIn("BSV_DB_URL", identity)
                importer_config = stage.service_config("catalog-import")
                self.assertRegex(importer_config["BSV_CATALOG_ADMIN_DB_URL"], r"bsv_catalog_importer:[A-Za-z0-9_-]+@127\.0\.0\.1:18764/bsv_all_prod$")
                self.assertEqual(importer_config["BSV_CATALOG_APPROVAL_KEY_FILE"], str(root / "config/catalog-approval.key"))
                self.assertEqual(identity["BSV_ACADEMY_STORE_IDS"], "BSVT")
                self.assertEqual(json.loads(identity["BSV_SERVICE_TOKENS_JSON"])["pos"]["stores"], ["BSVT"])
                self.assertEqual(json.loads(pos["BSV_POS_STORE_LEGAL_JSON"]), {"BSVT": "DEMO_LEGAL"})
                self.assertEqual(pos["BSV_POS_G1_TEST_STORES"], "disabled")
                self.assertEqual(ingress["BSV_GROWTH_STORE_IDS"], "BSVT")
                default_bytes = {p: p.read_bytes() for p in (identity_path, pos_path, ingress_path)}
                default_tokens = json.loads(identity["BSV_SERVICE_TOKENS_JSON"])
                # A normal H-style config pass remains BSVT-only without the explicit switch.
                stage.prepare_config(approve_synthetic_three_store=False)
                self.assertEqual({p: p.read_bytes() for p in default_bytes}, default_bytes)
                stage.prepare_config(approve_synthetic_three_store=True)
                identity = stage.service_config("identity")
                pos = stage.service_config("pos")
                ingress = stage.service_config("ingress")
                self.assertEqual(identity["BSV_ACADEMY_STORE_IDS"], "BSVM,BSVS,BSVT")
                tokens = json.loads(identity["BSV_SERVICE_TOKENS_JSON"])
                self.assertEqual(tokens["pos"]["stores"], ["BSVM", "BSVS", "BSVT"])
                self.assertEqual(tokens["pos"]["legal_entities"], ["DEMO_LEGAL"])
                self.assertEqual(tokens["layout-admin"]["stores"], ["BSVT"])
                self.assertEqual(tokens["supply"]["token"], default_tokens["supply"]["token"])
                self.assertEqual(json.loads(pos["BSV_POS_STORE_LEGAL_JSON"]),
                                 {"BSVM": "DEMO_LEGAL", "BSVS": "DEMO_LEGAL", "BSVT": "DEMO_LEGAL"})
                self.assertEqual(pos["BSV_POS_G1_TEST_STORES"], "BSVM,BSVS,BSVT")
                self.assertEqual(ingress["BSV_GROWTH_STORE_IDS"], "BSVM,BSVS,BSVT")
                self.assertEqual({name: (root / "config" / name).read_bytes()
                                  for name in secret_bytes}, secret_bytes)
                self.assertEqual((data / "catalog" / "backup.key").read_bytes(), catalog_backup_key)
                self.assertEqual(db.read_bytes(), b"published-map-and-existing-business-records")
                self.assertEqual(layout_hashes, {
                    p.relative_to(layout_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in layout_root.rglob("*") if p.is_file()
                })
                self.assertFalse(any(call.args and call.args[0] == "systemctl" for call in run.call_args_list))
                stage.prepare_config(approve_synthetic_three_store=False)
                self.assertEqual(stage.service_config("identity")["BSV_ACADEMY_STORE_IDS"], "BSVT")
                self.assertEqual(json.loads(stage.service_config("identity")["BSV_SERVICE_TOKENS_JSON"])["pos"]["stores"], ["BSVT"])
                self.assertEqual(json.loads(stage.service_config("pos")["BSV_POS_STORE_LEGAL_JSON"]), {"BSVT": "DEMO_LEGAL"})
                self.assertEqual(stage.service_config("pos")["BSV_POS_G1_TEST_STORES"], "disabled")
                self.assertEqual(stage.service_config("ingress")["BSV_GROWTH_STORE_IDS"], "BSVT")
                self.assertEqual({name: (root / "config" / name).read_bytes()
                                  for name in secret_bytes}, secret_bytes)
                before_failure = {p: p.read_bytes() for p in (identity_path, pos_path, ingress_path)}
                with patch.object(stage, "upgrade_blank_ingress_environment",
                                  side_effect=RuntimeError("injected config write failure")):
                    with self.assertRaisesRegex(RuntimeError, "injected config write failure"):
                        stage.prepare_config(approve_synthetic_three_store=True)
                self.assertEqual({p: p.read_bytes() for p in before_failure}, before_failure)
                raw = pos_path.read_text()
                pos_path.write_text(raw.replace('{"BSVT":"DEMO_LEGAL"}', '{"BSVF":"DEMO_LEGAL"}'))
                drift = pos_path.read_bytes()
                with self.assertRaisesRegex(RuntimeError, "Unknown or non-synthetic"):
                    stage.prepare_config(approve_synthetic_three_store=True)
                self.assertEqual(pos_path.read_bytes(), drift)


    def test_real_c51_identity_env_migrates_only_layout_admin_token(self):
        """Existing deployed identity.env has POS and supply; preserve both exactly."""
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "ROOT", Path(tmp)), \
                patch.object(stage, "private_file"):
            (stage.ROOT / "config").mkdir()
            old_tokens = {
                "pos": {"token": "P" * 42, "actions": ["pos.order.read", "pos.order.create"],
                        "legal_entities": ["DEMO_LEGAL"], "stores": ["BSVT"]},
                "supply": {"token": "S" * 42, "legal_entity_id": "DEMO_LEGAL",
                           "stores": ["BSVM", "BSVS", "BSVT"],
                           "isolated_test_department": "SYNTH-STAGE",
                           "actions": ["supply.dispatch", "supply.receive"]},
            }
            old = {"BSV_APP_ENV": "isolated", "BSV_AUTH_PROVIDER": "isolated",
                   "BSV_SESSION_SECRET": "unaltered-session-secret",
                   "BSV_SERVICE_TOKENS_JSON": json.dumps(old_tokens, separators=(",", ":"))}
            cfg = stage.ROOT / "config" / "identity.env"
            stage.environment("identity", old)
            layout = {"token": "L" * 48, "actions": ["hq.layout.read"],
                      "legal_entities": ["DEMO_LEGAL"], "stores": ["BSVT"]}
            newer_tokens = dict(old_tokens, **{"layout-admin": layout})
            new = dict(old, BSV_SERVICE_TOKENS_JSON=json.dumps(newer_tokens, separators=(",", ":")))
            stage.upgrade_identity_environment(new)
            migrated = stage.service_config("identity")
            self.assertEqual(migrated["BSV_SESSION_SECRET"], old["BSV_SESSION_SECRET"])
            self.assertEqual(json.loads(migrated["BSV_SERVICE_TOKENS_JSON"]), newer_tokens)
            self.assertEqual(cfg.stat().st_mode & 0o777, 0o600)
            self.assertFalse((cfg.with_name("identity.env.next")).exists())
            first = cfg.read_bytes()
            stage.upgrade_identity_environment(new)
            self.assertEqual(cfg.read_bytes(), first, "Subsequent deploy may not rewrite managed secrets")
            with self.assertRaisesRegex(RuntimeError, "Existing identity secrets"):
                stage.upgrade_identity_environment(dict(new, BSV_SESSION_SECRET="altered"))
            with self.assertRaisesRegex(RuntimeError, "Unapproved identity token-map"):
                injected = dict(newer_tokens, arbitrary={"token": "X" * 48,
                                                          "actions": ["hq.people.read"]})
                stage.upgrade_identity_environment(
                    dict(new, BSV_SERVICE_TOKENS_JSON=json.dumps(injected)))
            self.assertEqual(cfg.read_bytes(), first, "Rejected drift must not mutate config")

    def test_c51_pos_layout_and_growth_keys_upgrade_additively(self):
        """Only the exact new isolated POS keys may be added on top of c51."""
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "ROOT", Path(tmp)), \
                patch.object(stage, "private_file"):
            config = stage.ROOT / "config"
            config.mkdir()
            old = {"BSV_MODE": "staging", "BSV_PORT": "18762",
                   "BSV_POS_IDENTITY_TOKEN": "old-pos-token"}
            stage.environment("pos", old)
            additions = {"BSV_POS_LAYOUT_SERVICE_TOKEN": "layout-test-token",
                         "BSV_POS_LAYOUT_SCOPE_MODE": "isolated-synthetic",
                         "BSV_APP_ENV": "isolated",
                         "BSV_POS_GROWTH_INTEGRATION": "1",
                         "BSV_GROWTH_LINK_KEY": "isolated-link-test"}
            allowed = {"BSV_POS_LAYOUT_SERVICE_TOKEN", "BSV_POS_LAYOUT_SCOPE_MODE",
                       "BSV_APP_ENV", "BSV_POS_GROWTH_INTEGRATION",
                       "BSV_GROWTH_LINK_KEY", "BSV_GROWTH_POS_CONTEXT_KEY",
                       "BSV_GROWTH_POS_VERIFY_TOKEN"}
            merged = {**old, **additions}
            stage.upgrade_managed_environment("pos", merged, allowed)
            self.assertEqual(stage.service_config("pos"), merged)
            stage.upgrade_managed_environment("pos", merged, allowed)
            with self.assertRaisesRegex(RuntimeError, "changed"):
                stage.upgrade_managed_environment(
                    "pos", dict(merged, BSV_POS_IDENTITY_TOKEN="other-token"), allowed)
            with self.assertRaisesRegex(RuntimeError, "Unapproved environment keys"):
                stage.upgrade_managed_environment(
                    "pos", dict(merged, UNKNOWN_SECURITY_OVERRIDE="1"), allowed)

    def test_git_archive_build_normalizes_root_umasks_and_revalidates_marker(self):
        """Exercise the actual immutable archive and cached-release path under both common umasks."""
        sha = stage.output(*stage.git("rev-parse", "HEAD"))
        for mask in (0o077, 0o022):
            with self.subTest(umask=oct(mask)), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "releases").mkdir(mode=0o700)
                old = root / "releases" / OLD
                old.mkdir(mode=0o700)
                (root / "current").symlink_to(old)

                def fake_venv(dest, source, name):
                    folder = dest / name
                    (folder / "bin").mkdir(parents=True, mode=0o700)
                    python = folder / "bin/python"
                    python.write_text("#!/bin/sh\nexit 0\n")
                    python.chmod(0o700)
                    (folder / "lib/python3.12/site-packages").mkdir(parents=True, mode=0o700)
                    (folder / "lib/python3.12/site-packages/sample.py").write_text("value = 1\n")

                old_mask = os.umask(mask)
                try:
                    with patch.object(stage, "ROOT", root), patch.object(stage, "create_release_venv", side_effect=fake_venv) as venv:
                        release = stage.build(sha)
                        self.assertEqual(stage.sha_at(root / "current"), OLD)
                        manifest = stage.verified_source_manifest(sha)
                        self.assertEqual((release / ".built").stat().st_mode & 0o777, 0o600)
                        self.assertEqual((release / "src").stat().st_mode & 0o777, 0o755)
                        for relative, entry in manifest["entries"].items():
                            path = release / "src" / relative
                            if entry["kind"] == "directory":
                                self.assertEqual(path.stat().st_mode & 0o777, 0o755, relative)
                            else:
                                expected = 0o755 if entry["mode"] == "100755" else 0o644
                                self.assertEqual(path.stat().st_mode & 0o777, expected, relative)
                        venv.reset_mock()
                        stage.build(sha)
                        venv.assert_not_called()
                        sample = release / "identity/lib/python3.12/site-packages/sample.py"
                        sample.write_text("tampered = True\n")
                        with self.assertRaisesRegex(RuntimeError, "per-file inventory"):
                            stage.build(sha)
                        sample.write_text("value = 1\n")
                        changed = next(path for path, entry in manifest["entries"].items()
                                       if entry["kind"] == "file")
                        source_file = release / "src" / changed
                        source_file.write_bytes(source_file.read_bytes() + b"tampered")
                        with self.assertRaisesRegex(RuntimeError, "immutable Git blob"):
                            stage.build(sha)
                        self.assertEqual(stage.sha_at(root / "current"), OLD)
                finally:
                    os.umask(old_mask)

    def test_archive_accepts_git_permission_metadata_but_rejects_unsafe_members(self):
        content = b"print('fixture')\n"
        executable = b"#!/bin/sh\nexit 0\n"
        manifest = {"entries": {
            "app": {"kind": "directory"},
            "app/main.py": {"kind": "file", "mode": "100644", "oid": stage.git_blob_sha(content)},
            "app/run": {"kind": "file", "mode": "100755", "oid": stage.git_blob_sha(executable)},
        }}
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "source.tar"
            with tarfile.open(archive, "w") as tar:
                directory = tarfile.TarInfo("app")
                directory.type, directory.mode = tarfile.DIRTYPE, 0o775
                tar.addfile(directory)
                for name, data, mode in (("app/main.py", content, 0o664), ("app/run", executable, 0o775)):
                    entry = tarfile.TarInfo(name)
                    entry.mode, entry.size = mode, len(data)
                    tar.addfile(entry, BytesIO(data))
            stage.validate_source_archive(archive, manifest)
            release = Path(tmp) / "releases" / NEW
            source = release / "src"
            source.mkdir(parents=True, mode=0o700)
            old_mask = os.umask(0o077)
            try:
                stage.run("tar", "--no-same-owner", "--no-same-permissions", "-xf", archive, "-C", source)
            finally:
                os.umask(old_mask)
            with patch.object(stage, "ROOT", Path(tmp)):
                stage.normalize_release_permissions(release, manifest)
            self.assertEqual((source / "app").stat().st_mode & 0o777, 0o755)
            self.assertEqual((source / "app/main.py").stat().st_mode & 0o777, 0o644)
            self.assertEqual((source / "app/run").stat().st_mode & 0o777, 0o755)

            with tarfile.open(archive, "w") as tar:
                entry = tarfile.TarInfo("../escape")
                entry.size = len(content)
                tar.addfile(entry, BytesIO(content))
            with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
                stage.validate_source_archive(archive, manifest)

            with tarfile.open(archive, "w") as tar:
                entry = tarfile.TarInfo("app/main.py")
                entry.type, entry.linkname = tarfile.SYMTYPE, "../../etc/passwd"
                tar.addfile(entry)
            with self.assertRaisesRegex(RuntimeError, "type or executable bit"):
                stage.validate_source_archive(archive, manifest)

            with tarfile.open(archive, "w") as tar:
                entry = tarfile.TarInfo("app/main.py")
                entry.type, entry.linkname = tarfile.LNKTYPE, "app/run"
                tar.addfile(entry)
            with self.assertRaisesRegex(RuntimeError, "type or executable bit"):
                stage.validate_source_archive(archive, manifest)

            corrupted = {"entries": dict(manifest["entries"])}
            corrupted["entries"]["app/main.py"] = dict(corrupted["entries"]["app/main.py"], oid="0" * 40)
            with tarfile.open(archive, "w") as tar:
                directory = tarfile.TarInfo("app")
                directory.type = tarfile.DIRTYPE
                tar.addfile(directory)
                for name, data, mode in (("app/main.py", content, 0o644), ("app/run", executable, 0o755)):
                    entry = tarfile.TarInfo(name)
                    entry.mode, entry.size = mode, len(data)
                    tar.addfile(entry, BytesIO(data))
            with self.assertRaisesRegex(RuntimeError, "content differs"):
                stage.validate_source_archive(archive, corrupted)

            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                stage.verified_source_manifest("0" * 40)

    def test_runtime_account_access_gate_checks_each_user_and_refuses_before_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "releases" / NEW
            (dest / "src").mkdir(parents=True)
            (dest / "identity/bin").mkdir(parents=True)
            (dest / "supply/bin").mkdir(parents=True)
            (dest / "identity/bin/python").touch(mode=0o755)
            (dest / "supply/bin/python").touch(mode=0o755)
            success = CompletedProcess([], 0, stdout="")
            with patch.object(stage, "ROOT", root), patch.object(stage, "as_user", return_value=success) as account_call:
                stage.verify_release_access(dest)
                self.assertEqual(sum("/usr/bin/find" in call.args for call in account_call.call_args_list),
                                 len(stage.START_ORDER) + 2)
                denied = CompletedProcess([], 0, stdout="/private/path")
                account_call.reset_mock()
                account_call.side_effect = lambda service, *args, **kwargs: denied if args[0] == "/usr/bin/find" else success
                with self.assertRaisesRegex(RuntimeError, "not traversable/readable"):
                    stage.verify_release_access(dest)

        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "ROOT", Path(tmp)), \
                patch.object(stage, "UNIT_FILE", Path(tmp) / "unit"), patch.object(stage, "run"), \
                patch.object(stage, "preflight"), patch.object(stage, "prepare_config", return_value=({}, {}, "", "", "", "")), \
                patch.object(stage, "build", return_value=dest), patch.object(stage, "verify_release_access", side_effect=RuntimeError("access denied")), \
                patch.object(stage, "migration_compatibility"), \
                patch.object(stage, "switch_services") as services, patch.object(stage, "activation_checkpoint") as checkpoint:
            for sha in (OLD, NEW):
                (stage.ROOT / "releases" / sha).mkdir(parents=True)
            stage.link("current", OLD)
            with self.assertRaisesRegex(RuntimeError, "access denied"):
                stage.deploy(NEW)
            self.assertEqual(stage.sha_at(stage.ROOT / "current"), OLD)
            services.assert_not_called()
            checkpoint.assert_not_called()

    def test_release_permission_gate_rejects_unexpected_writable_or_symlink_release(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stage, "ROOT", Path(tmp)):
            releases = stage.ROOT / "releases"
            releases.mkdir()
            dest = releases / OLD
            dest.mkdir(mode=0o755)
            (dest / "src").mkdir()
            bad = dest / "src" / "untrusted.py"
            bad.write_text("x=1")
            bad.chmod(0o666)
            with self.assertRaisesRegex(RuntimeError, "Unsafe release file"):
                stage.normalize_release_permissions(dest)
            bad.chmod(0o600)
            stage.normalize_release_permissions(dest)
            self.assertEqual(bad.stat().st_mode & 0o777, 0o644)
            elsewhere = stage.ROOT / "external"
            elsewhere.mkdir()
            with self.assertRaisesRegex(RuntimeError, "Unexpected managed release"):
                stage.normalize_release_permissions(elsewhere)

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
