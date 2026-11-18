"""URL registry. Names A..G are stable; their endpoints are replaceable configuration."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]

@dataclass(frozen=True)
class Source:
    key: str
    name: str
    primary: str
    standby_read: str
    credential_env: str
    read_only: bool
    backup_paths: tuple[str, ...]

@dataclass(frozen=True)
class Settings:
    mode: str
    backup_dir: Path
    cache_dir: Path
    timeout_seconds: float
    max_snapshot_age_hours: int
    sources: dict[str, Source]


def load_settings(path: str | None = None) -> Settings:
    f = Path(path or os.environ.get("BSV_SOURCES_CONFIG", ROOT / "config/modules/supply-sources.example.json"))
    c = json.loads(f.read_text(encoding="utf-8"))
    mode = os.environ.get("BSV_MODE", c["mode"]).strip().lower()
    if mode not in {"demo", "remote"}:
        raise ValueError("BSV_MODE 必须为 demo 或 remote")
    sources = {}
    for k, v in c["sources"].items():
        for field in ("primary", "standby_read"):
            u = v.get(field, "")
            if u:
                p = urlsplit(u)
                if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
                    raise ValueError(f"数据源 {k}.{field} 必须为 HTTPS URL")
                if mode == "remote" and p.hostname and p.hostname.endswith(".invalid"):
                    raise ValueError(f"数据源 {k}.{field} 仍为示例URL")
        sources[k] = Source(k, v["name"], v.get("primary", "").rstrip("/"),
                            v.get("standby_read", "").rstrip("/"),
                            v.get("credential_env", ""), bool(v.get("read_only", True)),
                            tuple(v.get("backup_paths", [])))
    if set(sources) != set("ABCDEFG"):
        raise ValueError("必须保留 A-G 七个可配置数据源别名")
    for key in "ABCDE":
        if mode == "remote" and not sources[key].primary:
            raise ValueError(f"正式模式缺失 {key} 主地址")
    state_dir = os.environ.get("BSV_SUPPLY_STATE_DIR")
    def resolve(v: str):
        p = Path(v)
        return p if p.is_absolute() else ((Path(state_dir) if state_dir else ROOT / "work") / p).resolve()
    return Settings(mode, resolve(c["backup_dir"]), resolve(c["cache_dir"]),
                    float(c.get("timeout_seconds", 6)), int(c.get("max_snapshot_age_hours",72)), sources)


def auth_header(source: Source, user_token: str | None = None) -> dict[str,str]:
    # The identity service gets the end-user credential; internal service tokens are server-only.
    token = os.environ.get(source.credential_env, "") if source.credential_env else ""
    hdr = {"Accept":"application/json"}
    if token: hdr["X-BSV-Service-Token"] = token
    if user_token: hdr["Authorization"] = "Bearer " + user_token
    return hdr
