"""Private, versioned V9 workbook store for the existing POS SQLite mirror.

The workbook remains immutable in versions/<sha256>.xlsx. current.json is an
atomic active-version pointer outside the release tree. All source paths use the
same OOXML validation and sync_v9 transaction, including private-cloud downloads.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile

from bsv_v9_import import sync_v9, unpack_v9

MAX_WORKBOOK_BYTES = 50 * 1024 * 1024


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _private_root(path: Path) -> Path:
    path = Path(path).expanduser()
    if path.is_symlink():
        raise RuntimeError("私有Excel目录不能是符号链接")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = path.resolve()
    if path.stat().st_mode & 0o077:
        raise RuntimeError("私有Excel目录权限必须为0700")
    versions = path / "versions"
    if versions.is_symlink():
        raise RuntimeError("Excel版本目录不能是符号链接")
    versions.mkdir(mode=0o700, exist_ok=True)
    if versions.stat().st_mode & 0o077:
        raise RuntimeError("Excel版本目录权限必须为0700")
    candidates = path / "candidates"
    if candidates.is_symlink():
        raise RuntimeError("导入候选目录不能是符号链接")
    candidates.mkdir(mode=0o700, exist_ok=True)
    if candidates.stat().st_mode & 0o077:
        raise RuntimeError("导入候选目录权限必须为0700")
    return path


def _state_path(root: Path) -> Path:
    return root / "current.json"


def _read_state(root: Path) -> dict | None:
    path = _state_path(root)
    if path.is_symlink():
        raise RuntimeError("当前Excel版本标记不能是符号链接")
    if not path.exists():
        return None
    if path.stat().st_mode & 0o077:
        raise RuntimeError("当前Excel版本标记权限必须为0600")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("当前Excel版本标记无法读取") from exc
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise RuntimeError("当前Excel版本标记版本无效")
    active = state.get("active_sha256")
    previous = state.get("previous_sha256")
    for value in (active, previous):
        if value is not None and (not isinstance(value, str) or len(value) != 64
                                  or any(ch not in "0123456789abcdef" for ch in value)):
            raise RuntimeError("Excel版本哈希无效")
    if not isinstance(state.get("manual_lock"), bool):
        raise RuntimeError("Excel手动锁定状态无效")
    return state


def _version_path(root: Path, digest: str) -> Path:
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise RuntimeError("无效的Excel版本SHA256")
    versions = root / "versions"
    path = versions / (digest + ".xlsx")
    if path.is_symlink():
        raise RuntimeError("私有Excel版本不能是符号链接")
    if not path.is_file():
        raise FileNotFoundError("私有Excel版本文件不存在：" + digest)
    resolved = path.resolve()
    if resolved.parent != versions.resolve() or sha256_file(resolved) != digest:
        raise RuntimeError("私有Excel版本路径或SHA256校验失败")
    return resolved


def _store_version(source: Path, root: Path) -> tuple[str, Path, dict]:
    source = Path(source)
    if source.is_symlink() or not source.is_file() or source.suffix.lower() != ".xlsx":
        raise RuntimeError("来源必须是普通.xlsx文件")
    size = source.stat().st_size
    if not size or size > MAX_WORKBOOK_BYTES:
        raise RuntimeError("Excel文件大小无效或超过50MiB")
    # Validate the complete seven-sheet contract before storing or activating.
    _, _, _, summary = unpack_v9(source)
    digest = sha256_file(source)
    target = root / "versions" / (digest + ".xlsx")
    if target.exists():
        if target.is_symlink() or sha256_file(target) != digest:
            raise RuntimeError("已有同SHA版本文件损坏")
        return digest, target, summary
    fd, temp_name = tempfile.mkstemp(prefix=".incoming-", suffix=".xlsx", dir=root / "versions")
    temp = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        if sha256_file(temp) != digest:
            raise RuntimeError("Excel暂存副本SHA256不一致")
        temp.replace(target)
        _sync_dir(target.parent)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return digest, target, summary


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_state(root: Path, state: dict) -> None:
    path = _state_path(root)
    temp = root / "current.json.next"
    if temp.exists() or temp.is_symlink():
        raise RuntimeError("发现未审核的Excel状态临时文件")
    payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
        _sync_dir(root)
    finally:
        temp.unlink(missing_ok=True)


def _candidate_path(root: Path, digest: str) -> Path:
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise RuntimeError("无效的候选Excel SHA256")
    path = root / "candidates" / (digest + ".json")
    if path.is_symlink():
        raise RuntimeError("候选清单不能是符号链接")
    return path


def _private_import_dirs(catalog_root: Path) -> tuple[Path, Path]:
    raw = os.environ.get("BSV_IMPORT_ROOT", "").strip()
    base = Path(raw).expanduser() if raw else catalog_root.parent / "imports"
    if base.is_symlink():
        raise RuntimeError("导入根目录不能是符号链接")
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    base = base.resolve()
    if base.stat().st_mode & 0o077:
        raise RuntimeError("导入根目录权限必须为0700")
    paths = (base / "incoming", base / "archive")
    for path in paths:
        if path.is_symlink():
            raise RuntimeError("导入目录不能是符号链接")
        path.mkdir(mode=0o700, exist_ok=True)
        if path.stat().st_mode & 0o077:
            raise RuntimeError("导入子目录权限必须为0700")
    return paths


def _archive_source(source: Path, digest: str, catalog_root: Path) -> Path:
    _, archive = _private_import_dirs(catalog_root)
    target = archive / (digest + ".xlsx")
    if target.is_symlink():
        raise RuntimeError("归档工作簿不能是符号链接")
    if target.exists():
        if not target.is_file() or sha256_file(target) != digest:
            raise RuntimeError("已有导入归档损坏")
        return target
    fd, temp_name = tempfile.mkstemp(prefix=".incoming-", suffix=".xlsx", dir=archive)
    temp = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output, Path(source).open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush(); os.fsync(output.fileno())
        if sha256_file(temp) != digest:
            raise RuntimeError("导入归档SHA256不匹配")
        temp.replace(target); _sync_dir(archive)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return target


def _write_candidate(root: Path, candidate: dict) -> None:
    path = _candidate_path(root, candidate["sha256"])
    temp = path.with_suffix(".json.next")
    if temp.exists() or temp.is_symlink():
        raise RuntimeError("发现未审核的候选清单临时文件")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(candidate, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        temp.replace(path); _sync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _read_candidate(root: Path, digest: str) -> dict:
    path = _candidate_path(root, digest)
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError("候选清单缺失或权限过宽")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("sha256") != digest:
        raise RuntimeError("候选清单无效")
    _version_path(root, digest)
    return data


def archive_workbook(source: Path, store_dir: Path) -> dict:
    """Store an immutable candidate without changing the active POS catalog."""
    root = _private_root(Path(store_dir))
    with _store_lock(root):
        digest, _, summary = _store_version(Path(source), root)
        _archive_source(Path(source), digest, root)
        path = _candidate_path(root, digest)
        if path.exists():
            prior = _read_candidate(root, digest)
            return {"status": prior["status"], "sha256": digest, "summary": prior.get("summary", summary)}
        candidate = {"schema_version": 1, "sha256": digest, "status": "ARCHIVED",
                     "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "summary": summary}
        _write_candidate(root, candidate)
        return {"status": candidate["status"], "sha256": digest, "summary": summary}


def preview_candidate(digest: str, store_dir: Path) -> dict:
    root = _private_root(Path(store_dir))
    with _store_lock(root):
        candidate = _read_candidate(root, digest)
        _, _, _, summary = unpack_v9(_version_path(root, digest))
        return {"status": candidate["status"], "sha256": digest, "summary": summary}


def validate_candidate(digest: str, store_dir: Path) -> dict:
    root = _private_root(Path(store_dir))
    with _store_lock(root):
        candidate = _read_candidate(root, digest)
        _, _, _, summary = unpack_v9(_version_path(root, digest))
        candidate.update({"status": "VALIDATED", "validated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "summary": summary})
        _write_candidate(root, candidate)
        return {"status": candidate["status"], "sha256": digest, "summary": summary}


def commit_candidate(digest: str, store_dir: Path) -> dict:
    """Record explicit operator approval; this does not change live SQLite."""
    root = _private_root(Path(store_dir))
    with _store_lock(root):
        candidate = _read_candidate(root, digest)
        if candidate.get("status") != "VALIDATED":
            raise RuntimeError("候选Excel必须先通过校验")
        candidate.update({"status": "COMMITTED", "committed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        _write_candidate(root, candidate)
        return {"status": candidate["status"], "sha256": digest}


def publish_candidate(digest: str, database: Path, store_dir: Path) -> dict:
    root = _private_root(Path(store_dir))
    with _store_lock(root):
        candidate = _read_candidate(root, digest)
        if candidate.get("status") == "PUBLISHED":
            return {"status": "UNCHANGED", "sha256": digest}
        if candidate.get("status") != "COMMITTED":
            raise RuntimeError("候选Excel尚未完成校验和提交审批")
        workbook = _version_path(root, digest)
    result = activate_workbook(workbook, database, root, source_mode="manual")
    with _store_lock(root):
        candidate = _read_candidate(root, digest)
        candidate.update({"status": "PUBLISHED", "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        _write_candidate(root, candidate)
    return {"status": result["status"], "sha256": digest, "activation": result}


@contextmanager
def _store_lock(root: Path):
    path = root / ".catalog.lock"
    if path.is_symlink():
        raise RuntimeError("Excel更新锁不能是符号链接")
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _capture_database_version(database: Path, root: Path, state: dict | None) -> str | None:
    if state and state.get("active_sha256"):
        digest = state["active_sha256"]
        _version_path(root, digest)
        return digest
    if not database.is_file():
        return None
    db = sqlite3.connect(str(database), timeout=10)
    try:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bsv_v9_sync'").fetchone()
        if not exists:
            return None
        row = db.execute("SELECT source_path,source_sha FROM bsv_v9_sync WHERE one=1").fetchone()
    finally:
        db.close()
    if not row:
        return None
    source = Path(row[0])
    digest = str(row[1])
    if not source.is_file() or source.is_symlink() or sha256_file(source) != digest:
        raise RuntimeError("现行Excel版本无法核验，拒绝替换以保留可回退版本")
    stored_sha, _, _ = _store_version(source, root)
    if stored_sha != digest:
        raise RuntimeError("现行Excel版本SHA256与SQLite记录不一致")
    return digest


def _new_state(digest: str, previous: str | None, mode: str, locked: bool, summary: dict) -> dict:
    return {
        "schema_version": 1,
        "active_sha256": digest,
        "previous_sha256": previous,
        "source_mode": mode,
        "manual_lock": locked,
        "activated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summary,
    }


def activate_workbook(source: Path, database: Path, store_dir: Path, *,
                      source_mode: str = "manual") -> dict:
    """Validate, keep the prior valid file, transactionally sync, then activate.

    source_mode='cloudbase' is for a file downloaded by the private CloudBase
    adapter. It deliberately shares exactly the same parser and SQLite import.
    """
    if source_mode not in ("manual", "cloudbase"):
        raise ValueError("不支持的Excel来源模式")
    database = Path(database)
    root = _private_root(Path(store_dir))
    with _store_lock(root):
        state = _read_state(root)
        if source_mode == "cloudbase" and state and state["manual_lock"]:
            return {"status": "MANUAL_LOCKED", "active_sha256": state["active_sha256"]}
        digest, candidate, summary = _store_version(Path(source), root)
        previous = _capture_database_version(database, root, state)
        if state and state["active_sha256"] == digest:
            return {"status": "UNCHANGED", "active_sha256": digest,
                    "manual_lock": state["manual_lock"], "summary": summary}
        old_state = state
        # sync_v9 uses one SQLite transaction for catalogue rows and sale projection.
        # Existing order, member, employee and map rows are never replaced here.
        sync_v9(database, candidate)
        new_state = _new_state(digest, previous, source_mode,
                               source_mode == "manual", summary)
        try:
            _atomic_state(root, new_state)
        except BaseException as state_error:
            if previous:
                try:
                    sync_v9(database, _version_path(root, previous), force=True)
                    if old_state:
                        _atomic_state(root, old_state)
                    else:
                        _state_path(root).unlink(missing_ok=True)
                        _sync_dir(root)
                except Exception as rollback_error:
                    raise RuntimeError("Excel状态写入失败且SQLite回退未完成，请停止服务并检查备份") from rollback_error
            raise RuntimeError("Excel状态写入失败，已恢复到上一有效版本") from state_error
        return {"status": "ACTIVATED", "active_sha256": digest,
                "previous_sha256": previous, "manual_lock": new_state["manual_lock"],
                "summary": summary}


def rollback_catalog(database: Path, store_dir: Path) -> dict:
    database = Path(database)
    root = _private_root(Path(store_dir))
    with _store_lock(root):
        state = _read_state(root)
        if not state or not state.get("previous_sha256"):
            raise RuntimeError("没有可回退的上一有效Excel版本")
        current = state["active_sha256"]
        previous = state["previous_sha256"]
        target = _version_path(root, previous)
        sync_v9(database, target, force=True)
        restored = _new_state(previous, current, "manual-rollback", True,
                              unpack_v9(target)[3])
        _atomic_state(root, restored)
        return {"status": "ROLLED_BACK", "active_sha256": previous,
                "previous_sha256": current, "manual_lock": True}


def status_catalog(store_dir: Path) -> dict:
    root = _private_root(Path(store_dir))
    state = _read_state(root)
    if not state:
        return {"status": "NO_MANAGED_VERSION", "manual_lock": False}
    _version_path(root, state["active_sha256"])
    previous = state.get("previous_sha256")
    if previous:
        _version_path(root, previous)
    return {"status": "ACTIVE", **state}


def resume_cloudbase_sync(store_dir: Path) -> dict:
    root = _private_root(Path(store_dir))
    with _store_lock(root):
        state = _read_state(root)
        if not state:
            raise RuntimeError("必须先启用并核验一个有效Excel版本")
        state["manual_lock"] = False
        state["source_mode"] = "cloudbase-auto-ready"
        state["activated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _atomic_state(root, state)
        return {"status": "AUTO_SYNC_UNLOCKED", "active_sha256": state["active_sha256"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="受控管理BSV V9私有Excel版本")
    sub = parser.add_subparsers(dest="command", required=True)
    stage = sub.add_parser("stage", help="安全归档并校验候选，不切换活动版本")
    stage.add_argument("source", type=Path)
    stage.add_argument("--store-dir", required=True, type=Path)
    archive = sub.add_parser("archive", help="安全归档上传文件为未启用候选")
    archive.add_argument("source", type=Path)
    archive.add_argument("--store-dir", required=True, type=Path)
    for command, help_text in (("preview", "预览已归档候选"), ("validate", "校验候选且不切换当前版本"),
                               ("commit-candidate", "记录人工提交审批，不写入现行SQLite")):
        action = sub.add_parser(command, help=help_text)
        action.add_argument("sha256")
        action.add_argument("--store-dir", required=True, type=Path)
    publish = sub.add_parser("publish", help="发布已审批的候选并同步现有POS SQLite")
    publish.add_argument("sha256")
    publish.add_argument("--database", required=True, type=Path)
    publish.add_argument("--store-dir", required=True, type=Path)
    rollback = sub.add_parser("rollback", help="恢复上一有效Excel并同步原SQLite镜像")
    rollback.add_argument("--database", required=True, type=Path)
    rollback.add_argument("--store-dir", required=True, type=Path)
    status = sub.add_parser("status", help="只读查看当前私有Excel版本")
    status.add_argument("--store-dir", required=True, type=Path)
    resume = sub.add_parser("resume-cloudbase", help="明确解除人工Excel版本锁定")
    resume.add_argument("--store-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "stage":
        # Compatibility command name: staging no longer publishes as a side effect.
        # Operators must explicitly validate, commit-candidate and publish the SHA.
        result = archive_workbook(args.source, args.store_dir)
        if result["status"] == "ARCHIVED":
            result = validate_candidate(result["sha256"], args.store_dir)
    elif args.command == "archive":
        result = archive_workbook(args.source, args.store_dir)
    elif args.command == "preview":
        result = preview_candidate(args.sha256, args.store_dir)
    elif args.command == "validate":
        result = validate_candidate(args.sha256, args.store_dir)
    elif args.command == "commit-candidate":
        result = commit_candidate(args.sha256, args.store_dir)
    elif args.command == "publish":
        result = publish_candidate(args.sha256, args.database, args.store_dir)
    elif args.command == "rollback":
        result = rollback_catalog(args.database, args.store_dir)
    elif args.command == "status":
        result = status_catalog(args.store_dir)
    else:
        result = resume_cloudbase_sync(args.store_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
