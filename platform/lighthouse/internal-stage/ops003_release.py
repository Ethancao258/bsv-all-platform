#!/usr/bin/env python3
"""Build and verify the immutable, signed BSV-OPS-003 source bundle (no host access)."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import stage  # noqa: E402

REPOSITORY = "Ethancao258/bsv-all-platform"
REQUEST_ID = "ISSUE-32"
TARGET_SHA = "cb06be66e78d92b8921fc3103b12bdbdc55284f8"
CI_RUN_ID = 44922120417
CI_RUN_URL = f"https://github.com/{REPOSITORY}/actions/runs/{CI_RUN_ID}"
REQUIRED_JOBS = {
    "architecture", "bsv1", "menu-v13-1", "supply-v2", "identity-r2",
    "db-contract-preflight", "lighthouse-internal-stage", "v4-1-integration",
    "customer-growth-v43",
}
BUNDLE_MEMBERS = {"source.gitbundle", "ci-proof.json", "release-manifest.json"}
MAX_BUNDLE_BYTES = 100 * 1024 * 1024


class ReleaseError(ValueError):
    pass


def _git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(REPO), *args], check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"})
    return result.stdout.strip()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def validate_ci(run: dict, jobs: list[dict]) -> dict:
    if not isinstance(run, dict) or not isinstance(jobs, list):
        raise ReleaseError("GitHub CI evidence has the wrong shape")
    expected = {
        "url": CI_RUN_URL, "headSha": TARGET_SHA, "event": "pull_request",
        "status": "completed", "conclusion": "success", "workflowName": "validate-architecture",
    }
    if any(run.get(key) != value for key, value in expected.items()):
        raise ReleaseError("CI evidence is not the pinned successful PR run for the target SHA")
    if type(run.get("databaseId")) is int and run["databaseId"] != CI_RUN_ID:
        raise ReleaseError("GitHub returned an unexpected CI run ID")
    seen = set()
    normalized = []
    for job in jobs:
        if (not isinstance(job, dict) or not isinstance(job.get("name"), str)
                or job.get("status") != "completed" or job.get("conclusion") != "success"
                or job["name"] in seen):
            raise ReleaseError("Pinned CI run contains a failed, incomplete or duplicate job")
        seen.add(job["name"])
        normalized.append({"name": job["name"], "status": job["status"], "conclusion": job["conclusion"]})
    if seen != REQUIRED_JOBS:
        missing, extra = sorted(REQUIRED_JOBS - seen), sorted(seen - REQUIRED_JOBS)
        raise ReleaseError(f"Pinned CI job set mismatch (missing={missing}, extra={extra})")
    return {**expected, "run_id": CI_RUN_ID,
            "jobs": sorted(normalized, key=lambda row: row["name"])}


def _source_tarball() -> tuple[bytes, dict]:
    manifest = stage.verified_source_manifest(TARGET_SHA)
    raw = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", TARGET_SHA],
                         check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}).stdout
    with tempfile.NamedTemporaryFile(prefix="bsv-ops003-source-", suffix=".tar") as temporary:
        temporary.write(raw)
        temporary.flush()
        stage.validate_source_archive(Path(temporary.name), manifest)
    return gzip.compress(raw, compresslevel=9, mtime=0), manifest


def _git_bundle() -> bytes:
    ref = "refs/heads/bsv-ops003-release-target"
    prior = subprocess.run(["git", "-C", str(REPO), "show-ref", "--verify", "--hash", ref],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    created = prior.returncode != 0
    if not created and prior.stdout.strip() != TARGET_SHA:
        raise ReleaseError("Temporary release ref already points to another commit")
    subprocess.run(["git", "-C", str(REPO), "update-ref", ref, TARGET_SHA], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with tempfile.TemporaryDirectory(prefix="bsv-ops003-bundle-check-") as directory:
            bundle_path = Path(directory) / "source.bundle"
            clone = Path(directory) / "repository.git"
            subprocess.run(["git", "-C", str(REPO), "bundle", "create", str(bundle_path), ref],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "clone", "--bare", "--quiet", "--branch", "bsv-ops003-release-target",
                            str(bundle_path), str(clone)], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            commit = subprocess.run(["git", "--git-dir", str(clone), "rev-parse", f"{TARGET_SHA}^{{commit}}"],
                                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()
            tree = subprocess.run(["git", "--git-dir", str(clone), "rev-parse", f"{TARGET_SHA}^{{tree}}"],
                                  check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()
            if commit != TARGET_SHA or tree != _git("rev-parse", f"{TARGET_SHA}^{{tree}}"):
                raise ReleaseError("Git bundle does not preserve the exact target commit and tree")
            return bundle_path.read_bytes()
    finally:
        if created:
            subprocess.run(["git", "-C", str(REPO), "update-ref", "-d", ref], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _tar_bundle(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, body in sorted(files.items()):
            info = tarfile.TarInfo(name=name)
            info.size = len(body)
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            archive.addfile(info, io.BytesIO(body))
    return stream.getvalue()


def build(run: dict, jobs: list[dict], output_dir: Path) -> dict:
    proof = validate_ci(run, jobs)
    source_gz, source_manifest = _source_tarball()
    git_bundle = _git_bundle()
    manifest = {
        "schema_version": "1.0", "request_id": REQUEST_ID, "repository": REPOSITORY,
        "target_sha": TARGET_SHA, "tree_sha": source_manifest["tree"],
        "source_manifest": source_manifest,
        "source_archive": {"sha256": hashlib.sha256(source_gz).hexdigest(),
                           "size_bytes": len(source_gz), "entry_count": len(source_manifest["entries"])},
        "git_bundle": {"name": "source.gitbundle", "sha256": hashlib.sha256(git_bundle).hexdigest(),
                       "size_bytes": len(git_bundle)},
        "ci": proof,
        "deployment_boundary": {"environment": "isolated", "no_payment": True,
                                "no_prod_db": True, "host_contacted": False},
    }
    manifest_bytes = _canonical(manifest) + b"\n"
    proof_bytes = _canonical(proof) + b"\n"
    bundle = _tar_bundle({"source.gitbundle": git_bundle, "ci-proof.json": proof_bytes,
                          "release-manifest.json": manifest_bytes})
    if len(bundle) > MAX_BUNDLE_BYTES:
        raise ReleaseError("Release bundle exceeds the 100 MiB safety bound")
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_stat = output_dir.lstat()
    if output_dir.is_symlink() or not output_dir.is_dir() or output_stat.st_uid != os.geteuid() or output_stat.st_mode & 0o077:
        raise ReleaseError("Release output directory must be private and owned by the current user")
    bundle_path = output_dir / f"bsv-all-{TARGET_SHA}.tar"
    checksum_path = output_dir / f"bsv-all-{TARGET_SHA}.tar.sha256"
    for path in (bundle_path, checksum_path):
        if path.exists() or path.is_symlink():
            raise ReleaseError("Refusing to overwrite a release output")
    bundle_path.write_bytes(bundle)
    bundle_path.chmod(0o600)
    digest = hashlib.sha256(bundle).hexdigest()
    checksum_path.write_text(f"{digest}  {bundle_path.name}\n", encoding="ascii")
    checksum_path.chmod(0o600)
    verify(bundle_path)
    return {"bundle": str(bundle_path), "sha256": digest, "size_bytes": len(bundle),
            "source_entries": len(source_manifest["entries"]), "target_sha": TARGET_SHA,
            "ci_run_id": CI_RUN_ID}


def _read_bundle(bundle_path: Path) -> dict[str, bytes]:
    data = bundle_path.read_bytes()
    if len(data) > MAX_BUNDLE_BYTES:
        raise ReleaseError("Release bundle exceeds the 100 MiB safety bound")
    files = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                if (path.is_absolute() or len(path.parts) != 1 or path.name in {"", ".", ".."}
                        or member.name in files or path.name not in BUNDLE_MEMBERS
                        or not member.isreg() or member.size > MAX_BUNDLE_BYTES):
                    raise ReleaseError("Release bundle contains an unsafe or unexpected member")
                total += member.size
                if total > MAX_BUNDLE_BYTES:
                    raise ReleaseError("Release bundle expands beyond the 100 MiB safety bound")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ReleaseError("Release bundle member has no data")
                files[path.name] = stream.read(MAX_BUNDLE_BYTES + 1)
                if len(files[path.name]) != member.size:
                    raise ReleaseError("Release bundle member size changed while reading")
    except (tarfile.TarError, OSError) as error:
        raise ReleaseError("Release bundle is not a valid tar archive") from error
    if set(files) != BUNDLE_MEMBERS:
        raise ReleaseError("Release bundle is incomplete")
    return files


def verify(bundle_path: Path, checksum_path: Path | None = None) -> dict:
    if bundle_path.is_symlink() or not bundle_path.is_file():
        raise ReleaseError("Release bundle must be a regular non-symlink file")
    data = bundle_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if checksum_path is not None:
        expected = checksum_path.read_text(encoding="ascii").strip()
        if expected != f"{digest}  {bundle_path.name}":
            raise ReleaseError("Release bundle SHA-256 does not match its sidecar")
    files = _read_bundle(bundle_path)
    try:
        manifest = json.loads(files["release-manifest.json"])
        proof = json.loads(files["ci-proof.json"])
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ReleaseError("Release metadata is invalid JSON") from error
    if (manifest.get("schema_version") != "1.0" or manifest.get("request_id") != REQUEST_ID
            or manifest.get("repository") != REPOSITORY or manifest.get("target_sha") != TARGET_SHA
            or manifest.get("tree_sha") != manifest.get("source_manifest", {}).get("tree")
            or manifest.get("source_manifest", {}).get("commit") != TARGET_SHA
            or manifest.get("ci", {}).get("run_id") != CI_RUN_ID
            or proof != manifest.get("ci")
            or manifest.get("deployment_boundary") != {"environment": "isolated", "no_payment": True,
                                                       "no_prod_db": True, "host_contacted": False}):
        raise ReleaseError("Release manifest does not match its pinned target or safe environment")
    source_meta = manifest.get("source_archive", {})
    git_bundle = files["source.gitbundle"]
    bundle_meta = manifest.get("git_bundle", {})
    if (bundle_meta.get("name") != "source.gitbundle" or bundle_meta.get("size_bytes") != len(git_bundle)
            or bundle_meta.get("sha256") != hashlib.sha256(git_bundle).hexdigest()):
        raise ReleaseError("Git bundle digest or length differs from its manifest")
    with tempfile.TemporaryDirectory(prefix="bsv-ops003-git-verify-") as directory:
        bundle_file = Path(directory) / "source.bundle"
        clone = Path(directory) / "repository.git"
        bundle_file.write_bytes(git_bundle)
        try:
            subprocess.run(["git", "clone", "--bare", "--quiet", "--branch", "bsv-ops003-release-target",
                            str(bundle_file), str(clone)], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            commit = subprocess.run(["git", "--git-dir", str(clone), "rev-parse", f"{TARGET_SHA}^{{commit}}"],
                                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()
            tree = subprocess.run(["git", "--git-dir", str(clone), "rev-parse", f"{TARGET_SHA}^{{tree}}"],
                                  check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()
            source_tar = subprocess.run(["git", "--git-dir", str(clone), "archive", "--format=tar", TARGET_SHA],
                                        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        except subprocess.CalledProcessError as error:
            raise ReleaseError("Git bundle cannot be cloned without network access") from error
        if commit != TARGET_SHA or tree != manifest.get("tree_sha"):
            raise ReleaseError("Git bundle does not contain the pinned SHA and Git tree")
        source_gz = gzip.compress(source_tar, compresslevel=9, mtime=0)
        with tempfile.NamedTemporaryFile(prefix="bsv-ops003-verify-", suffix=".tar") as temporary:
            temporary.write(source_tar)
            temporary.flush()
            try:
                stage.validate_source_archive(Path(temporary.name), manifest["source_manifest"])
            except (KeyError, RuntimeError, TypeError) as error:
                raise ReleaseError("Git bundle source does not match exact Git blob inventory") from error
    if (source_meta.get("size_bytes") != len(source_gz)
            or source_meta.get("sha256") != hashlib.sha256(source_gz).hexdigest()):
        raise ReleaseError("Reconstructed source digest or length differs from manifest")
    validate_ci(proof, proof.get("jobs"))
    return {"bundle_sha256": digest, "target_sha": TARGET_SHA,
            "source_entries": source_meta.get("entry_count"), "ci_run_id": CI_RUN_ID,
            "host_contacted": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    package = commands.add_parser("build")
    package.add_argument("--run-json", required=True, type=Path)
    package.add_argument("--output", required=True, type=Path)
    check = commands.add_parser("verify")
    check.add_argument("--bundle", required=True, type=Path)
    check.add_argument("--sha256", type=Path)
    args = parser.parse_args(argv)
    if args.command == "build":
        run = json.loads(args.run_json.read_text(encoding="utf-8"))
        result = build(run, run.get("jobs"), args.output)
    else:
        result = verify(args.bundle, args.sha256)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReleaseError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise SystemExit(f"BSV-OPS-003 release blocked: {error}")
