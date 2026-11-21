#!/usr/bin/env python3
"""Build and validate the offline host supplement for the pinned OPS-003 release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import ops003_release  # noqa: E402

TARGET_SHA = ops003_release.TARGET_SHA
SOURCE_CI_RUN = ops003_release.CI_RUN_ID
SOURCE_ARTIFACT_RUN = 44899535240
COSIGN_VERSION = "v2.4.1"
COSIGN_RELEASE_KEY_SHA256 = "f4cea466e5e887a45da5031757fa1d32655d83420639dc1758749b744179f126"
REQUIRED_LOCKS = (
    "services/api/identity/requirements.lock",
    "services/api/customer_growth/requirements.stage.lock",
    "services/api/supply/requirements.lock",
)
EXPECTED_ARCH = {"x86_64": "amd64", "aarch64": "arm64"}
MAX_SUPPLEMENT_BYTES = 700 * 1024 * 1024


class PredeployError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(args: list[str], *, env=None, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, env=env)


def verify_cosign_bootstrap(cosign: Path, public_key: Path, signature: Path,
                            *, expected_arch: str) -> dict:
    if platform.machine() not in EXPECTED_ARCH or EXPECTED_ARCH[platform.machine()] != expected_arch:
        raise PredeployError("Cosign binary architecture does not match the runner")
    if any(path.is_symlink() or not path.is_file() for path in (cosign, public_key, signature)):
        raise PredeployError("Cosign bootstrap files must be regular files")
    if sha256(public_key) != COSIGN_RELEASE_KEY_SHA256:
        raise PredeployError("Official Cosign release public key digest mismatch")
    version = _run([str(cosign), "version"]).stdout
    if f"GitVersion:    {COSIGN_VERSION}" not in version or f"Platform:      linux/{expected_arch}" not in version:
        raise PredeployError("Cosign version or architecture does not match the pinned release")
    _run(["openssl", "dgst", "-sha256", "-verify", str(public_key), "-signature", str(signature), str(cosign)])
    return {"version": COSIGN_VERSION, "arch": expected_arch,
            "binary_sha256": sha256(cosign), "release_key_sha256": sha256(public_key),
            "verification": "OFFICIAL_RELEASE_SIGNATURE_PASS"}


def verify_source_package(cosign: Path, root: Path, bundle: Path, sidecar: Path,
                          signature_bundle: Path) -> dict:
    if any(path.is_symlink() or not path.is_file() for path in (root, bundle, sidecar, signature_bundle)):
        raise PredeployError("Source release evidence must be regular files")
    # The release artifact is signed by this repository's PR #34 release workflow.
    _run([str(cosign), "verify-blob", "--offline", "--trusted-root", str(root),
          "--bundle", str(signature_bundle),
          "--certificate-oidc-issuer", "https://token.actions.githubusercontent.com",
          "--certificate-identity",
          "https://github.com/Ethancao258/bsv-all-platform/.github/workflows/bsv-ops-003-release.yml@refs/pull/34/merge",
          str(bundle)])
    try:
        release = ops003_release.verify(bundle, sidecar)
    except (ops003_release.ReleaseError, OSError, subprocess.SubprocessError) as error:
        raise PredeployError("Signed release failed exact-SHA, Git tree, CI proof or SHA256 verification") from error
    if (release.get("target_sha") != TARGET_SHA or release.get("ci_run_id") != SOURCE_CI_RUN
            or release.get("host_contacted") is not False):
        raise PredeployError("Source release is not the pinned synthetic-only target")
    return {"signature": "OFFLINE_SIGNATURE_PASS", "source_verifier": "PASS",
            **release, "source_sigstore_sha256": sha256(signature_bundle),
            "trusted_root_sha256": sha256(root)}


def prove_tamper_rejection(cosign: Path, root: Path, bundle: Path,
                           signature_bundle: Path, temp_dir: Path) -> None:
    temp_dir.mkdir(parents=True, exist_ok=True)
    tampered = temp_dir / "tampered-source.tar"
    shutil.copyfile(bundle, tampered)
    with tampered.open("ab") as stream:
        stream.write(b"tamper")
    command = [str(cosign), "verify-blob", "--offline", "--trusted-root", str(root),
               "--bundle", str(signature_bundle),
               "--certificate-oidc-issuer", "https://token.actions.githubusercontent.com",
               "--certificate-identity",
               "https://github.com/Ethancao258/bsv-all-platform/.github/workflows/bsv-ops-003-release.yml@refs/pull/34/merge",
               str(tampered)]
    result = _run(command, check=False)
    if result.returncode == 0:
        raise PredeployError("Tampered signed release unexpectedly passed offline verification")
    tampered.unlink()


def _offline_env(wheelhouse: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update({"PIP_NO_INDEX": "1", "PIP_FIND_LINKS": str(wheelhouse.resolve()),
                "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_CONFIG_FILE": os.devnull,
                "PYTHONDONTWRITEBYTECODE": "1"})
    return env


def exercise_offline_venvs(wheelhouse: Path, *, scratch: Path) -> dict:
    if wheelhouse.is_symlink() or not wheelhouse.is_dir():
        raise PredeployError("Wheelhouse is not a regular directory")
    scratch.mkdir(parents=True, exist_ok=True)
    wheels = [p for p in wheelhouse.iterdir() if p.suffix == ".whl" and p.is_file() and not p.is_symlink()]
    if not wheels:
        raise PredeployError("Wheelhouse is empty")
    python = Path(sys.executable)
    env = _offline_env(wheelhouse)
    installs = {}
    for name, locks in (
        ("identity", (REPO / REQUIRED_LOCKS[0], REPO / REQUIRED_LOCKS[1])),
        ("supply", (REPO / REQUIRED_LOCKS[2],)),
    ):
        venv = scratch / name
        _run([str(python), "-m", "venv", str(venv)], env=env)
        pip = venv / "bin/python"
        packages = []
        for lock in locks:
            if lock.is_symlink() or not lock.is_file():
                raise PredeployError(f"Missing locked dependency file: {lock.name}")
            _run([str(pip), "-m", "pip", "--disable-pip-version-check", "install", "--no-deps", "-r", str(lock)], env=env)
            packages.extend(line.split("==", 1)[0].lower().replace("_", "-")
                            for line in lock.read_text().splitlines()
                            if line.strip() and not line.lstrip().startswith("#"))
        _run([str(pip), "-m", "pip", "check"], env=env)
        smoke = ("import fastapi, pydantic, uvicorn; "
                 "import cryptography, psycopg, sqlalchemy, httpx; "
                 "print('IMPORTS_OK')")
        if name == "supply":
            smoke += "; import cv2, numpy; print('SUPPLY_NATIVE_WHEELS_OK')"
        else:
            smoke += "; import qrcode, PIL; print('GROWTH_MEDIA_WHEELS_OK')"
        result = _run([str(pip), "-c", smoke], env=env)
        installs[name] = {"locked_packages": len(packages), "wheel_count": len(wheels),
                          "pip_check": "PASS", "imports": result.stdout.strip().splitlines()}
    return {"python": sys.version.split()[0], "machine": platform.machine(),
            "wheelhouse_sha256": wheelhouse_digest(wheelhouse), "venvs": installs,
            "network_access": "DISABLED_BY_PIP_NO_INDEX"}


def prove_missing_wheel_rejected(wheelhouse: Path, *, scratch: Path) -> None:
    scratch.mkdir(parents=True, exist_ok=True)
    empty = scratch / "empty-wheelhouse"
    empty.mkdir(parents=True, exist_ok=True)
    env = _offline_env(empty)
    venv = scratch / "missing-wheel-venv"
    _run([sys.executable, "-m", "venv", str(venv)], env=env)
    result = _run([str(venv / "bin/python"), "-m", "pip", "--disable-pip-version-check",
                   "install", "--no-deps", "-r", str(REPO / REQUIRED_LOCKS[0])], env=env, check=False)
    if result.returncode == 0:
        raise PredeployError("Missing wheelhouse dependency unexpectedly installed")


def wheelhouse_digest(wheelhouse: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(wheelhouse.iterdir(), key=lambda item: item.name):
        if path.is_symlink() or not path.is_file() or path.suffix != ".whl":
            continue
        digest.update(path.name.encode() + b"\0" + sha256(path).encode() + b"\n")
    return digest.hexdigest()


def _inventory(root: Path) -> list[dict]:
    entries = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise PredeployError("Supplement cannot contain symlinks")
        if path.is_dir():
            continue
        if not path.is_file():
            raise PredeployError("Supplement contains a special file")
        rel = path.relative_to(root).as_posix()
        if PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
            raise PredeployError("Unsafe supplement path")
        entries.append({"path": rel, "size_bytes": path.stat().st_size,
                        "sha256": sha256(path), "mode": path.stat().st_mode & 0o777})
    return entries


def pack_supplement(root: Path, *, arch: str, metadata: dict, output: Path) -> dict:
    if arch not in {"amd64", "arm64"} or root.is_symlink() or not root.is_dir():
        raise PredeployError("Invalid target architecture or supplement staging directory")
    if (metadata.get("target_sha") != TARGET_SHA or metadata.get("source_ci_run_id") != SOURCE_CI_RUN
            or metadata.get("source_artifact_run_id") != SOURCE_ARTIFACT_RUN
            or metadata.get("host_architecture_confirmed") is not False):
        raise PredeployError("Supplement metadata does not preserve the pinned target boundary")
    entries = _inventory(root)
    if not entries or sum(e["size_bytes"] for e in entries) > MAX_SUPPLEMENT_BYTES:
        raise PredeployError("Supplement is empty or exceeds 700 MiB")
    manifest = {"schema_version": "1.0", "request_id": "ISSUE-32", "repository": "Ethancao258/bsv-all-platform",
                "target_sha": TARGET_SHA, "source_ci_run_id": SOURCE_CI_RUN,
                "source_artifact_run_id": SOURCE_ARTIFACT_RUN,
                "target_os": "Ubuntu 24.04", "python": "3.12", "target_arch": arch,
                "host_architecture_confirmed": False,
                "cosign_version": COSIGN_VERSION,
                "cosign_release_key_sha256": COSIGN_RELEASE_KEY_SHA256,
                "source_artifact_run_id": SOURCE_ARTIFACT_RUN,
                "source_release_artifact": "bsv-ops-003-f00371ccd1c233caf8eea97398bf981cf7d65dd0",
                "contents": entries, "predeploy_evidence": metadata}
    manifest_path = root / "supplement-manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        raise PredeployError("Refusing to overwrite supplement manifest")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    manifest_path.chmod(0o644)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise PredeployError("Refusing to overwrite supplement archive")
    with tarfile.open(output, "w", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            rel = path.relative_to(root).as_posix()
            info = archive.gettarinfo(str(path), arcname=f"bsv-ops003-host-supplement/{rel}")
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            if path.is_dir():
                archive.addfile(info)
            else:
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
    if output.stat().st_size > MAX_SUPPLEMENT_BYTES:
        output.unlink()
        raise PredeployError("Packed supplement exceeds 700 MiB")
    return {"archive": str(output), "sha256": sha256(output), "size_bytes": output.stat().st_size,
            "target_arch": arch, "file_count": len(entries) + 1}


def verify_supplement_tree(root: Path) -> dict:
    manifest_path = root / "supplement-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PredeployError("Supplement manifest is missing or unsafe")
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("schema_version") != "1.0" or manifest.get("request_id") != "ISSUE-32"
            or manifest.get("target_sha") != TARGET_SHA or manifest.get("source_ci_run_id") != SOURCE_CI_RUN
            or manifest.get("source_artifact_run_id") != SOURCE_ARTIFACT_RUN
            or manifest.get("host_architecture_confirmed") is not False):
        raise PredeployError("Supplement manifest does not match the pinned target")
    paths = list(root.rglob("*"))
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in paths):
        raise PredeployError("Supplement contains a symlink")
    expected = {entry["path"]: entry for entry in manifest.get("contents", [])}
    actual = {path.relative_to(root).as_posix(): path for path in paths if path.is_file()}
    if set(actual) != set(expected) | {"supplement-manifest.json"}:
        raise PredeployError("Supplement contents differ from its file inventory")
    for rel, entry in expected.items():
        path = actual[rel]
        if (path.is_symlink() or not path.is_file() or path.stat().st_size != entry.get("size_bytes")
                or path.stat().st_mode & 0o777 != entry.get("mode") or sha256(path) != entry.get("sha256")):
            raise PredeployError(f"Supplement file integrity mismatch: {rel}")
    return {"target_sha": TARGET_SHA, "arch": manifest.get("target_arch"),
            "file_count": len(expected), "file_inventory": "PASS"}


def verify_supplement_archive(archive_path: Path) -> dict:
    if archive_path.is_symlink() or not archive_path.is_file() or archive_path.stat().st_size > MAX_SUPPLEMENT_BYTES:
        raise PredeployError("Supplement archive is missing, unsafe, or oversized")
    files = {}
    members = set()
    directories = set()
    try:
        with tarfile.open(archive_path, "r:") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                if (path.is_absolute() or ".." in path.parts or "." in path.parts or "" in path.parts
                        or not member.name.startswith("bsv-ops003-host-supplement/")
                        or member.issym() or member.islnk()
                        or not (member.isdir() or member.isreg()) or member.name in members):
                    raise PredeployError("Supplement archive contains an unsafe member")
                members.add(member.name)
                if member.isdir():
                    directories.add(member.name.rstrip("/"))
                    continue
                stream = archive.extractfile(member)
                if stream is None or member.size > MAX_SUPPLEMENT_BYTES:
                    raise PredeployError("Supplement archive member is invalid")
                if sum(len(item) for item in files.values()) + member.size > MAX_SUPPLEMENT_BYTES:
                    raise PredeployError("Supplement archive expands beyond 700 MiB")
                body = stream.read(MAX_SUPPLEMENT_BYTES + 1)
                if len(body) != member.size:
                    raise PredeployError("Supplement archive member size mismatch")
                files[member.name] = body
    except (tarfile.TarError, OSError) as error:
        raise PredeployError("Supplement is not a valid tar archive") from error
    prefix = "bsv-ops003-host-supplement/"
    manifest_name = prefix + "supplement-manifest.json"
    if manifest_name not in files:
        raise PredeployError("Supplement archive manifest is missing")
    manifest = json.loads(files[manifest_name])
    if (manifest.get("schema_version") != "1.0" or manifest.get("request_id") != "ISSUE-32"
            or manifest.get("target_sha") != TARGET_SHA or manifest.get("source_ci_run_id") != SOURCE_CI_RUN
            or manifest.get("source_artifact_run_id") != SOURCE_ARTIFACT_RUN
            or manifest.get("host_architecture_confirmed") is not False
            or manifest.get("target_arch") not in {"amd64", "arm64"}):
        raise PredeployError("Supplement archive manifest does not match the pinned target")
    expected = {prefix + entry["path"]: entry for entry in manifest.get("contents", [])}
    if set(files) != set(expected) | {manifest_name}:
        raise PredeployError("Supplement archive file set differs from manifest")
    expected_dirs = set()
    for name in expected:
        parent = PurePosixPath(name).parent
        while parent.as_posix() not in {".", prefix.rstrip("/")}:
            expected_dirs.add(parent.as_posix().rstrip("/"))
            parent = parent.parent
    if directories != expected_dirs:
        raise PredeployError("Supplement archive directory list differs from its file inventory")
    with tarfile.open(archive_path, "r:") as archive:
        modes = {item.name: item.mode & 0o777 for item in archive if item.isreg()}
    for name, entry in expected.items():
        mode = modes.get(name)
        if (len(files[name]) != entry.get("size_bytes") or hashlib.sha256(files[name]).hexdigest() != entry.get("sha256")
                or mode != entry.get("mode")):
            raise PredeployError(f"Supplement archive file hash mismatch: {name}")
    return {"arch": manifest.get("target_arch"), "target_sha": manifest.get("target_sha"),
            "file_count": len(expected), "archive_inventory": "PASS"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("verify-source")
    inspect.add_argument("--cosign", type=Path, required=True)
    inspect.add_argument("--trusted-root", type=Path, required=True)
    inspect.add_argument("--bundle", type=Path, required=True)
    inspect.add_argument("--sha256", type=Path, required=True)
    inspect.add_argument("--sigstore", type=Path, required=True)
    assemble = commands.add_parser("assemble")
    assemble.add_argument("--root", type=Path, required=True)
    assemble.add_argument("--arch", choices=("amd64", "arm64"), required=True)
    assemble.add_argument("--metadata", type=Path, required=True)
    assemble.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify-supplement-tree")
    check.add_argument("--root", type=Path, required=True)
    check_archive = commands.add_parser("verify-supplement-archive")
    check_archive.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "verify-source":
        result = verify_source_package(args.cosign, args.trusted_root, args.bundle, args.sha256, args.sigstore)
    elif args.command == "assemble":
        metadata = json.loads(args.metadata.read_text())
        result = pack_supplement(args.root, arch=args.arch, metadata=metadata, output=args.output)
    elif args.command == "verify-supplement-tree":
        result = verify_supplement_tree(args.root)
    else:
        result = verify_supplement_archive(args.archive)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PredeployError, OSError, subprocess.SubprocessError, tarfile.TarError) as error:
        raise SystemExit(f"OPS-003 offline predeploy validation blocked: {error}")
