#!/usr/bin/env python3
"""Build a private, exact-SHA PR #40 test candidate after successful CI."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
WORKBUDDY_SHA256 = "3f98fbe12eacdca481d1e7b3350a59410da7f1116c74a75a1c7b93fe63a0e5a1"
PACKAGE_FILES = (
    "ACCEPTANCE_TEMPLATE.md", "DEPLOYMENT_REHEARSAL_REPORT.md",
    "TRANSFER_AND_EXECUTION.md", "ci-proof.json", "repo.bundle",
    "run-once.sh", "workbuddy-v22.zip",
)


def run(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_report(sha: str, proof: dict, data_sha: str) -> dict[str, bytes]:
    run_url = proof["url"]
    return {
        "ACCEPTANCE_TEMPLATE.md": (
            "# PR #40 test-candidate acceptance\n\n"
            f"Status: **UNAPPROVED_TEST_CANDIDATE**\n\nTarget SHA: `{sha}`\n\n"
            "All host and owner acceptance rows remain NOT_RUN until independently evidenced.\n"
        ).encode(),
        "TRANSFER_AND_EXECUTION.md": (
            "# Private PR #40 test candidate\n\n"
            "Status: **UNAPPROVED_TEST_CANDIDATE — DO NOT EXECUTE**\n\n"
            f"Target SHA: `{sha}`\nCI: {run_url}\nWorkBuddy ZIP SHA-256: `{data_sha}`\n\n"
            "This private archive is prepared for isolated rehearsal only. It is not an approval "
            "to alter Lighthouse or production data. Do not invoke `run-once.sh` until the owner "
            "separately approves M3 for this exact SHA and archive.\n"
        ).encode(),
        "DEPLOYMENT_REHEARSAL_REPORT.md": (
            "# PR #40 exact-package rehearsal report\n\n"
            "Status: **UNAPPROVED_TEST_CANDIDATE**\n\n"
            f"Candidate SHA: `{sha}`\nCI proof: {run_url}\n"
            f"WorkBuddy ZIP SHA-256: `{data_sha}`\n\n"
            "Completed: package structure/hash/source-bundle checks, source CI, and the PG17 CI "
            "job named `bsv1`.\n\n"
            "NOT_RUN: a full systemd upgrade of this exact outer archive, sudo/operator identity "
            "path, Lighthouse browser acceptance, host backup/recovery, and host rollback. CI "
            "does not substitute for these host checks. No real host was modified.\n"
        ).encode(),
    }


def build(sha: str, workbuddy: Path, proof_file: Path, output: Path) -> str:
    if run("git", "rev-parse", "HEAD") != sha:
        raise SystemExit("HEAD does not equal the requested candidate SHA")
    if run("git", "status", "--porcelain"):
        raise SystemExit("candidate worktree must be clean")
    if not workbuddy.is_file() or workbuddy.is_symlink() or sha256(workbuddy) != WORKBUDDY_SHA256:
        raise SystemExit("WorkBuddy source ZIP is absent or its pinned SHA-256 differs")
    sys.path.insert(0, str(ROOT / "platform/lighthouse/internal-stage"))
    import bsvctl

    proof = json.loads(proof_file.read_text(encoding="utf-8"))
    bsvctl.validate_ci(proof, sha)
    proof = {**proof, "candidateStatus": "UNAPPROVED_TEST_CANDIDATE"}
    proof_bytes = (json.dumps(proof, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if output.exists() or output.is_symlink():
        raise SystemExit("refusing to overwrite a prior candidate archive")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pr40-candidate-") as temp:
        bundle = Path(temp) / "repo.bundle"
        subprocess.run(["git", "bundle", "create", str(bundle), sha], cwd=ROOT, check=True)
        files: dict[str, bytes] = {
            "repo.bundle": bundle.read_bytes(),
            "ci-proof.json": proof_bytes,
            "workbuddy-v22.zip": workbuddy.read_bytes(),
            "run-once.sh": (ROOT / "platform/lighthouse/internal-stage/run-once.sh").read_bytes(),
            **make_report(sha, proof, WORKBUDDY_SHA256),
        }
        if set(files) != set(PACKAGE_FILES):
            raise SystemExit("candidate member inventory does not match the runner contract")
        checksums = "".join(f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
                            for name in sorted(files))
        files["SHA256SUMS"] = checksums.encode()

        raw = io.BytesIO()
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0, compresslevel=9) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for name in sorted(files):
                    content = files[name]
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = 0o755 if name == "run-once.sh" else 0o644
                    archive.addfile(info, io.BytesIO(content))
        payload = raw.getvalue()
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(payload)
        target.flush()
        os.fsync(target.fileno())
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--workbuddy", type=Path, required=True)
    parser.add_argument("--ci-proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(args.sha) != 40 or any(ch not in "0123456789abcdef" for ch in args.sha):
        parser.error("--sha must be a full lowercase Git SHA")
    digest = build(args.sha, args.workbuddy.resolve(), args.ci_proof.resolve(), args.output.resolve())
    print(json.dumps({"status": "UNAPPROVED_TEST_CANDIDATE", "sha": args.sha,
                      "archive": str(args.output.resolve()), "sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
