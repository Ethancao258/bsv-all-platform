#!/usr/bin/env python3
"""Build and validate the offline host supplement for the pinned OPS-003 release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import ops003_release  # noqa: E402

TARGET_SHA = ops003_release.TARGET_SHA
SOURCE_CI_RUN = ops003_release.CI_RUN_ID
SOURCE_ARTIFACT_RUN = int(os.environ.get("OPS003_SOURCE_ARTIFACT_RUN", "0"))
COSIGN_VERSION = "v2.4.1"
COSIGN_RELEASE_KEY_SHA256 = "f4cea466e5e887a45da5031757fa1d32655d83420639dc1758749b744179f126"
REQUIRED_LOCKS = (
    "services/api/identity/requirements.lock",
    "services/api/customer_growth/requirements.stage.lock",
    "services/api/supply/requirements.lock",
)
EXPECTED_ARCH = {"x86_64": "amd64", "aarch64": "arm64"}
MAX_SUPPLEMENT_BYTES = 95 * 1024 * 1024
SIGSTORE_TUF_URL = "https://tuf-repo-cdn.sigstore.dev"
WHEELHOUSE_REUSE_SOURCE_RUN = 44913890434
WHEELHOUSE_REUSE_ARTIFACT_ID = 14710029781
WHEELHOUSE_REUSE_ARTIFACT_SHA256 = "2b65e83493594d2bc1948e407499169264a44c36ba66510bb498a7515eff750a"


class PredeployError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(args: list[str], *, env=None, check=True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env)
    if check and result.returncode:
        detail = (result.stderr or result.stdout or "(no subprocess output)")[-4000:]
        raise PredeployError(f"Command failed ({result.returncode}): {args[0]} {args[1:]}\n{detail}")
    return result


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
    _run([str(cosign), "verify-blob", "--new-bundle-format", "--offline", "--trusted-root", str(root),
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
    command = [str(cosign), "verify-blob", "--new-bundle-format", "--offline", "--trusted-root", str(root),
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
                 "import cryptography, httpx; "
                 "print('IMPORTS_OK')")
        if name == "supply":
            smoke += "; import cv2, numpy; print('SUPPLY_NATIVE_WHEELS_OK')"
        else:
            smoke += "; import psycopg, sqlalchemy, jwt, argon2, qrcode, PIL; print('IDENTITY_AND_GROWTH_IMPORTS_OK')"
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


def fetch_tuf_mirror(destination: Path) -> dict:
    """Fetch a complete Sigstore TUF mirror; trust is established later by offline Cosign."""
    if destination.exists() or destination.is_symlink():
        raise PredeployError("Refusing to overwrite the Sigstore TUF mirror directory")
    destination.mkdir(mode=0o700, parents=True)

    def get(name: str) -> bytes:
        path = PurePosixPath(name)
        if (path.is_absolute() or ".." in path.parts or "." in path.parts or len(path.parts) > 2
                or (len(path.parts) == 2 and path.parts[0] != "targets")):
            raise PredeployError("Unexpected TUF metadata or target path")
        request = urllib.request.Request(f"{SIGSTORE_TUF_URL}/{name}", headers={"User-Agent": "bsv-ops-003-predeploy/1"})
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 200:
                raise PredeployError("Sigstore TUF mirror returned a non-200 response")
            return response.read(MAX_SUPPLEMENT_BYTES + 1)

    request = urllib.request.Request(f"{SIGSTORE_TUF_URL}/", headers={"User-Agent": "bsv-ops-003-predeploy/1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        html = response.read(1024 * 1024).decode("utf-8", errors="strict")
    root_matches = re.findall(r'href="([1-9][0-9]*)\.root\.json"', html)
    if len(root_matches) != 1:
        raise PredeployError("Cannot identify a single current Sigstore TUF root version")
    root_version = int(root_matches[0])
    if not 1 <= root_version <= 100:
        raise PredeployError("Sigstore TUF root version is outside the supported bound")
    root_dir = destination
    total = 0

    def save(name: str, body: bytes, *, subdir: str | None = None) -> None:
        nonlocal total
        total += len(body)
        if len(body) > 16 * 1024 * 1024 or total > 64 * 1024 * 1024:
            raise PredeployError("Sigstore TUF metadata mirror exceeds its size bound")
        parent = root_dir if subdir is None else root_dir / subdir
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = parent / name
        if path.exists() or path.is_symlink():
            raise PredeployError("Duplicate TUF metadata path")
        path.write_bytes(body)
        path.chmod(0o600)

    for version in range(1, root_version + 1):
        save(f"{version}.root.json", get(f"{version}.root.json"))
    timestamp = get("timestamp.json")
    save("timestamp.json", timestamp)
    try:
        timestamp_doc = json.loads(timestamp)
        snapshot_meta = timestamp_doc["signed"]["meta"]["snapshot.json"]
        snapshot_version = int(snapshot_meta["version"])
        expected = snapshot_meta.get("hashes", {}).get("sha256")
        snapshot_length = snapshot_meta.get("length")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise PredeployError("Sigstore timestamp metadata is malformed") from error
    if not 1 <= snapshot_version <= 10000:
        raise PredeployError("Sigstore snapshot version is outside the supported bound")
    snapshot = get(f"{snapshot_version}.snapshot.json")
    if ((snapshot_length is not None and len(snapshot) != snapshot_length)
            or (expected is not None and hashlib.sha256(snapshot).hexdigest() != expected)):
        raise PredeployError("Sigstore snapshot digest does not match signed timestamp metadata")
    save(f"{snapshot_version}.snapshot.json", snapshot)
    try:
        targets_meta = json.loads(snapshot)["signed"]["meta"]["targets.json"]
        targets_version = int(targets_meta["version"])
        expected_targets = targets_meta.get("hashes", {}).get("sha256")
        targets_length = targets_meta.get("length")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise PredeployError("Sigstore snapshot metadata is malformed") from error
    if not 1 <= targets_version <= 10000:
        raise PredeployError("Sigstore targets version is outside the supported bound")
    targets = get(f"{targets_version}.targets.json")
    if ((targets_length is not None and len(targets) != targets_length)
            or (expected_targets is not None and hashlib.sha256(targets).hexdigest() != expected_targets)):
        raise PredeployError("Sigstore targets digest does not match signed snapshot metadata")
    save(f"{targets_version}.targets.json", targets)
    try:
        target_rows = json.loads(targets)["signed"]["targets"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise PredeployError("Sigstore targets metadata is malformed") from error
    if not 1 <= len(target_rows) <= 128 or "trusted_root.json" not in target_rows:
        raise PredeployError("Sigstore targets metadata lacks the trusted root")
    for name, metadata in target_rows.items():
        digest = metadata.get("hashes", {}).get("sha256")
        length = metadata.get("length")
        if (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or type(length) is not int or length < 0 or length > 16 * 1024 * 1024
                or PurePosixPath(name).name != name):
            raise PredeployError("Sigstore target metadata is malformed")
        body = get(f"targets/{digest}.{name}")
        if len(body) != length or hashlib.sha256(body).hexdigest() != digest:
            raise PredeployError(f"Sigstore TUF target digest mismatch: {name}")
        save(f"{digest}.{name}", body, subdir="targets")
    return {"root_version": root_version, "snapshot_version": snapshot_version,
            "targets_version": targets_version, "target_count": len(target_rows),
            "trusted_root_sha256": hashlib.sha256(
                (destination / "targets" / f"{target_rows['trusted_root.json']['hashes']['sha256']}.trusted_root.json").read_bytes()
            ).hexdigest(), "metadata_bytes": total}


def wheelhouse_digest(wheelhouse: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(wheelhouse.iterdir(), key=lambda item: item.name):
        if path.is_symlink() or not path.is_file() or path.suffix != ".whl":
            continue
        digest.update(path.name.encode() + b"\0" + sha256(path).encode() + b"\n")
    return digest.hexdigest()


def lock_compatibility(base_sha: str, target_sha: str) -> dict:
    """Prove the signed f003 wheelhouse lock inputs remain byte-identical at H."""
    if not re.fullmatch(r"[a-f0-9]{40}", base_sha) or target_sha != TARGET_SHA:
        raise PredeployError("Wheelhouse compatibility proof must target the pinned release SHA")
    files = {}
    for relative in REQUIRED_LOCKS:
        old = _run(["git", "-C", str(REPO), "show", f"{base_sha}:{relative}"]).stdout.encode()
        path = REPO / relative
        if path.is_symlink() or not path.is_file():
            raise PredeployError(f"Missing target dependency lock: {relative}")
        new = path.read_bytes()
        old_digest, new_digest = hashlib.sha256(old).hexdigest(), hashlib.sha256(new).hexdigest()
        if old_digest != new_digest:
            raise PredeployError(f"Dependency lock changed; wheelhouse cannot be reused: {relative}")
        files[relative] = {"base_sha256": old_digest, "target_sha256": new_digest, "identical": True}
    return {
        "schema_version": "1.0", "base_sha": base_sha, "target_sha": target_sha,
        "wheelhouse_reuse": "BYTE_IDENTICAL_LOCKS_ONLY",
        "previous_supplement_run_id": WHEELHOUSE_REUSE_SOURCE_RUN,
        "previous_supplement_artifact_id": WHEELHOUSE_REUSE_ARTIFACT_ID,
        "previous_supplement_sha256": WHEELHOUSE_REUSE_ARTIFACT_SHA256,
        "locks": files,
        "host_wheelhouse_integrity": "MUST_REVERIFY_PREVIOUS_SIGNED_MANIFEST_AND_FILE_HASHES",
    }


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
            or metadata.get("host_architecture_confirmed") is not True):
        raise PredeployError("Supplement metadata does not preserve the pinned target boundary")
    entries = _inventory(root)
    if not entries or sum(e["size_bytes"] for e in entries) > MAX_SUPPLEMENT_BYTES:
        raise PredeployError("Supplement is empty or exceeds 700 MiB")
    manifest = {"schema_version": "1.0", "request_id": "ISSUE-32", "repository": "Ethancao258/bsv-all-platform",
                "target_sha": TARGET_SHA, "source_ci_run_id": SOURCE_CI_RUN,
                "source_artifact_run_id": SOURCE_ARTIFACT_RUN,
                "target_os": "Ubuntu 24.04", "python": "3.12", "target_arch": arch,
                "host_architecture_confirmed": True,
                "cosign_version": COSIGN_VERSION,
                "cosign_release_key_sha256": COSIGN_RELEASE_KEY_SHA256,
                "source_artifact_run_id": SOURCE_ARTIFACT_RUN,
                "source_release_artifact": f"bsv-ops-003-{TARGET_SHA}",
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
            or manifest.get("host_architecture_confirmed") is not True):
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
            or manifest.get("host_architecture_confirmed") is not True
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
    tuf = commands.add_parser("fetch-tuf-mirror")
    tuf.add_argument("--destination", type=Path, required=True)
    check = commands.add_parser("verify-supplement-tree")
    check.add_argument("--root", type=Path, required=True)
    check_archive = commands.add_parser("verify-supplement-archive")
    check_archive.add_argument("--archive", type=Path, required=True)
    locks = commands.add_parser("lock-compatibility")
    locks.add_argument("--base-sha", required=True)
    locks.add_argument("--target-sha", required=True)
    locks.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "verify-source":
        result = verify_source_package(args.cosign, args.trusted_root, args.bundle, args.sha256, args.sigstore)
    elif args.command == "assemble":
        metadata = json.loads(args.metadata.read_text())
        result = pack_supplement(args.root, arch=args.arch, metadata=metadata, output=args.output)
    elif args.command == "fetch-tuf-mirror":
        result = fetch_tuf_mirror(args.destination)
    elif args.command == "verify-supplement-tree":
        result = verify_supplement_tree(args.root)
    elif args.command == "lock-compatibility":
        result = lock_compatibility(args.base_sha, args.target_sha)
        if args.output.exists() or args.output.is_symlink():
            raise PredeployError("Refusing to overwrite wheelhouse compatibility proof")
        args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    else:
        result = verify_supplement_archive(args.archive)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PredeployError, OSError, subprocess.SubprocessError, tarfile.TarError) as error:
        raise SystemExit(f"OPS-003 offline predeploy validation blocked: {error}")
