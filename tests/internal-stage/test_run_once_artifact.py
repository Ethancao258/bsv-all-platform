"""Checks the exact deployment shell artifact and its embedded Python blocks."""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "platform/lighthouse/internal-stage/run-once.sh"
BUILDER = ROOT / "scripts/build_pr40_candidate.py"
MARKER = re.compile(r"<<'([A-Za-z][A-Za-z0-9_]*)'")


def heredocs() -> list[tuple[str, str]]:
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    found = []
    index = 0
    while index < len(lines):
        match = MARKER.search(lines[index])
        if not match:
            index += 1
            continue
        marker = match.group(1)
        start = index + 1
        index = start
        while index < len(lines) and lines[index] != marker:
            index += 1
        if index == len(lines):
            raise AssertionError(f"unclosed {marker} Python heredoc in run-once.sh")
        found.append((marker, "\n".join(lines[start:index]) + "\n"))
        index += 1
    return found


class RunOnceArtifactTests(unittest.TestCase):
    def test_exact_tracked_script_has_valid_shell_and_all_python_blocks_parse(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
        blocks = heredocs()
        self.assertEqual(len(blocks), 17, "deployment script Python heredocs changed; review the gate")
        self.assertEqual(sum(marker == "PYACTOR" for marker, _ in blocks), 1)
        with tempfile.TemporaryDirectory(prefix="bsv-run-once-heredoc-") as directory:
            out = Path(directory)
            for number, (_marker, source) in enumerate(blocks, 1):
                ast.parse(source, filename=f"run-once-{number}.py")
                (out / f"run-once-{number:02}.py").write_text(source, encoding="utf-8")
            if not shutil.which("ruff"):
                self.skipTest("ruff is installed by the CI job; local binary is unavailable")
            subprocess.run(["ruff", "check", "--isolated", "--select", "F821", str(out)], check=True)

    @unittest.skipUnless(shutil.which("sudo") and os.geteuid() != 0,
                         "requires a non-root CI runner with sudo")
    def test_approver_resolution_covers_sudo_native_root_and_mismatch(self):
        actor = next(source for marker, source in heredocs() if marker == "PYACTOR")
        with tempfile.TemporaryDirectory(prefix="bsv-run-once-actor-") as directory:
            path = Path(directory) / "actor.py"
            path.write_text(actor, encoding="utf-8")
            env = os.environ.copy()

            # A root-originated TAT command has no SUDO_* identity and resolves to root.
            native = subprocess.run(["sudo", "-n", "env", "-u", "SUDO_UID", "-u", "SUDO_USER",
                                     "python3", str(path)], text=True, capture_output=True)
            self.assertEqual(native.returncode, 0, native.stderr)
            self.assertEqual(native.stdout.strip(), "root")

            # OrcaTerm's sudo process must resolve the invoking account, not hard-code root.
            invoked = subprocess.run(["sudo", "-n", "python3", str(path)], text=True, capture_output=True)
            self.assertEqual(invoked.returncode, 0, invoked.stderr)
            self.assertEqual(invoked.stdout.strip(), env["USER"])

            forged = subprocess.run(["sudo", "-n", "env", "SUDO_USER=forged-account",
                                     "python3", str(path)], text=True, capture_output=True)
            self.assertNotEqual(forged.returncode, 0)
            self.assertIn("does not match", forged.stderr)

    def test_post_import_failure_keeps_catalog_and_retry_is_audited(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertLess(script.index("--catalog-preflight --sha"), script.index("DEPLOYMENT_ATTEMPTED=1"))
        self.assertLess(script.index("CATALOG_CONTENT_PREFLIGHT"), script.index("DEPLOYMENT_ATTEMPTED=1"))
        self.assertIn("unregistered schemas", (ROOT / "services/api/bsv1/bsv_catalog_import.py").read_text())
        self.assertIn("SAFE_RESUME_IDEMPOTENT_NOOP", script)
        self.assertIn("candidateStatus", script)
        self.assertIn("UNAPPROVED_TEST_CANDIDATE", script)
        compile(BUILDER.read_text(encoding="utf-8"), str(BUILDER), "exec")
        self.assertIn('"git", "bundle", "create", str(bundle), "HEAD"',
                      BUILDER.read_text(encoding="utf-8"))
        self.assertIn("--audit-existing --approvals-dir", script)
        self.assertIn("CATALOG_CONTENT_ROLLBACK=NOT_PERFORMED", script)
        self.assertIn("Post-deploy failure/interruption", script)
        self.assertNotIn("--approver root", script)
        self.assertIn("max_identifier_length", script)
        self.assertIn("catalog_restore_database_name(source_sha,limit)", script)
        self.assertRegex(script, r"bsvr_\[a-f0-9\]\{8\}_\[0-9\]\{14\}_\[a-f0-9\]\{16\}")
        self.assertIn("SUCCESS_WORKTREE=CLEANED_AFTER_ALL_ACCEPTANCE_GATES", script)
        self.assertIn("flock -n 9", script)
        self.assertIn("bsv_identity_isolated_catalog_restore_", script)
        self.assertNotIn('restore_db="bsv_identity_isolated_catalog_restore_', script)

    def test_candidate_builder_labels_archive_and_documents_host_gates(self):
        module_spec = importlib.util.spec_from_file_location("pr40_candidate_builder", BUILDER)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        proof = {"url": "https://github.com/Ethancao258/bsv-all-platform/actions/runs/123",
                 "headSha": "a" * 40}
        report = module.make_report("a" * 40, proof, module.WORKBUDDY_SHA256)
        self.assertEqual(set(report), {"ACCEPTANCE_TEMPLATE.md", "TRANSFER_AND_EXECUTION.md",
                                      "DEPLOYMENT_REHEARSAL_REPORT.md"})
        self.assertIn(b"UNAPPROVED_TEST_CANDIDATE", report["TRANSFER_AND_EXECUTION.md"])
        self.assertIn(b"NOT_RUN", report["DEPLOYMENT_REHEARSAL_REPORT.md"])


if __name__ == "__main__":
    unittest.main()
