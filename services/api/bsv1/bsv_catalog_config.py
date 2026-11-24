"""BSV ALL V9 Excel source configuration.

A managed catalog version in the private data directory takes precedence when
present. Otherwise the existing BSV_V9_XLSX/EXCEL_SOURCE_FILE fallback remains.
"""
from pathlib import Path
import hashlib
import json
import os
import re

EXCEL_SOURCE_FILE = r"resources/BSV_ALL_V9.xlsx"
ENV_NAME = "BSV_V9_XLSX"
CATALOG_DIR_ENV = "BSV_CATALOG_DIR"
SHOW_LOCAL_TRAINING_ITEMS = True


def _active_catalog(root):
    raw = os.environ.get(CATALOG_DIR_ENV)
    if not raw:
        return None
    directory = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not directory.is_absolute():
        directory = root / directory
    if directory.is_symlink():
        raise ValueError("私有Excel目录不能是符号链接")
    directory = directory.resolve()
    marker = directory / "current.json"
    if marker.is_symlink():
        raise ValueError("当前Excel版本标记不能是符号链接")
    if not marker.exists():
        return None
    try:
        state = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("当前Excel版本标记损坏，已停止读取") from exc
    sha = state.get("active_sha256") if isinstance(state, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
        raise ValueError("当前Excel版本哈希无效，已停止读取")
    versions = directory / "versions"
    candidate = versions / (sha + ".xlsx")
    if versions.is_symlink() or candidate.is_symlink() or not candidate.is_file():
        raise FileNotFoundError("当前有效Excel版本缺失或路径异常，已停止读取")
    resolved = candidate.resolve()
    if resolved.parent != versions.resolve():
        raise ValueError("当前Excel版本越出私有版本目录")
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if digest != sha:
        raise ValueError("当前Excel版本哈希不匹配，已停止读取")
    return resolved


def get_excel_path(root=None):
    root = Path(root or Path(__file__).resolve().parent).resolve()
    managed = _active_catalog(root)
    if managed is not None:
        return managed
    raw = (os.environ.get(ENV_NAME) or EXCEL_SOURCE_FILE).strip()
    if not raw:
        raise ValueError("未配置V9 Excel文件位置")
    path = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if path.suffix.lower() != ".xlsx":
        raise ValueError("数据源必须是.xlsx文件")
    if not path.is_file():
        raise FileNotFoundError("找不到V9 Excel数据源：" + str(path))
    return path
