#!/usr/bin/env python3
"""Versioned deployment for the private internal stage on a systemd host."""
import argparse
import base64
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shlex
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

ROOT = Path("/opt/bsv-all-internal-stage")
DATA = Path("/var/lib/bsv-all-internal-stage")
PG = Path("/usr/lib/postgresql/17/bin")
TOOL = Path("platform/lighthouse/internal-stage")
UNIT = "bsv-all-internal-stage"
UNIT_FILE = Path("/etc/systemd/system") / f"{UNIT}@.service"
PORTS = {"ingress": 18760, "identity": 18761, "pos": 18762, "supply": 18763, "postgres": 18764}
START_ORDER = ("postgres", "identity", "pos", "supply", "ingress")
LEGACY_UNITS = {8765: "bsv1-preview.service", 8767: "bsv-all-bsv1-stage.service"}
REPO = Path(__file__).resolve().parents[3]
DB = "bsv_identity_isolated_internal"
DB_USER = "bsv_internal_app"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
MIGRATIONS = Path("platform/lighthouse/identity/migrations")
IDENTITY_REVISION = "bsv_identity_0001"
ACADEMY_REVISION = "bsv_academy_0002"
ACADEMY_MIGRATION = "versions/20261120_0002_academy.py"
MEDIA_FILE = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\.bin")


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def output(*args):
    return run(*args, stdout=subprocess.PIPE).stdout.strip()


def unit(name):
    return f"{UNIT}@{name}.service"


def unit_active(name):
    return subprocess.run(("systemctl", "is-active", "--quiet", name)).returncode == 0


def active(name):
    return unit_active(unit(name))


def user(name):
    return "bsvint-" + name


def as_user(name, *args, **kwargs):
    return run("/usr/sbin/runuser", "-u", user(name), "--", *args, **kwargs)


def git(*args):
    return ("git", "-c", f"safe.directory={REPO}", "-C", str(REPO), *args)


def sha_at(path):
    if not path.is_symlink():
        if path.exists():
            raise RuntimeError(f"Expected a managed release symlink: {path}")
        return None
    dest = path.resolve(strict=True)
    if dest.parent != ROOT / "releases" or not re.fullmatch(r"[a-f0-9]{40}", dest.name):
        raise RuntimeError(f"Unexpected release target: {path}")
    return dest.name


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def migration_files(source):
    directory = source / MIGRATIONS
    if not directory.is_dir() or directory.is_symlink():
        raise RuntimeError("Missing managed isolated migration directory")
    files = {}
    for path in directory.rglob("*"):
        relative = path.relative_to(directory)
        if "__pycache__" in relative.parts:
            continue
        if path.is_symlink():
            raise RuntimeError("Unexpected symlink in isolated migrations")
        if path.is_file():
            files[relative.as_posix()] = path.read_bytes()
    return files


def migration_revisions(source):
    revisions = [IDENTITY_REVISION]
    if ACADEMY_MIGRATION in migration_files(source):
        revisions.append(ACADEMY_REVISION)
    return revisions


def migration_compatibility(older, newer):
    """Allow release-only swaps across the reviewed additive V3 → V4.1 revision."""
    old_files, new_files = migration_files(older), migration_files(newer)
    if old_files == new_files:
        return
    if (all(new_files.get(path) == content for path, content in old_files.items())
            and new_files.keys() - old_files.keys() == {ACADEMY_MIGRATION}):
        return
    raise RuntimeError("Isolated migrations differ outside the approved additive V4.1 revision")


def database_revision():
    result = as_user(
        "postgres", PG / "psql", "-XAt", "-h", DATA / "postgres", "-p", str(PORTS["postgres"]),
        "-U", user("postgres"), "-d", DB, "-v", "ON_ERROR_STOP=1",
        "-c", "SELECT version_num FROM alembic_version;", stdout=subprocess.PIPE, timeout=15,
    )
    revision = result.stdout.strip()
    if revision not in {IDENTITY_REVISION, ACADEMY_REVISION}:
        raise RuntimeError("Unknown isolated PostgreSQL migration revision")
    return revision


def link(name, sha):
    tmp = ROOT / ("." + name + ".next")
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(ROOT / "releases" / sha)
    tmp.replace(ROOT / name)
    sync_directory(ROOT)


def listening_ports():
    listeners = {port: [] for port in (*PORTS.values(), *LEGACY_UNITS)}
    for line in output("ss", "-H", "-ltn").splitlines():
        address, _, port = line.split()[3].rpartition(":")
        if port.isdecimal() and int(port) in listeners:
            listeners[int(port)].append(address.removeprefix("[").removesuffix("]"))
    return listeners


def host_evidence(require_all=True):
    current = sha_at(ROOT / "current")
    listeners = listening_ports()
    legacy = {}
    for port, name in LEGACY_UNITS.items():
        if not unit_active(name) or not listeners[port]:
            raise RuntimeError(f"Legacy service baseline missing: {name} on {port}")
        legacy[str(port)] = {"unit": name, "state": "active"}

    managed = {}
    for name, port in PORTS.items():
        addresses = listeners[port]
        running = bool(current and active(name))
        if addresses and any(address != "127.0.0.1" for address in addresses):
            raise RuntimeError(f"Unexpected non-loopback listener on {port} ({name})")
        if addresses and not running:
            raise RuntimeError(f"Port {port} already in use outside managed service ({name})")
        if require_all and not (addresses and running):
            raise RuntimeError(f"Managed loopback service is not ready on {port} ({name})")
        managed[str(port)] = {"unit": unit(name), "state": "active" if running else "inactive",
                              "listen": addresses}
    return {"deployed_sha": current, "legacy_services": legacy, "managed_services": managed}


def preflight(sha):
    if output(*git("rev-parse", "HEAD")) != sha:
        raise RuntimeError("Checkout HEAD must match the approved 40-character SHA")
    run(*git("diff", "--quiet", "HEAD", "--"))
    if not Path("/run/systemd/system").is_dir():
        raise RuntimeError("A live systemd host is required")
    if output("/usr/bin/python3", "-c", "import sys; print('ok' if sys.version_info >= (3,12) else 'no')") != "ok":
        raise RuntimeError("Requires Python 3.12 or newer")
    run("/usr/bin/python3", "-c", "import ensurepip, venv")
    if not os.access("/usr/sbin/runuser", os.X_OK):
        raise RuntimeError("Missing host dependency: /usr/sbin/runuser")
    for required in ("git", "tar", "useradd", "systemctl", "diff", "ss"):
        if not shutil.which(required):
            raise RuntimeError(f"Missing host dependency: {required}")
    if not output("tar", "--version").startswith("tar (GNU tar)"):
        raise RuntimeError("Safe release extraction requires Ubuntu GNU tar")
    for executable in ("postgres", "initdb", "psql", "pg_isready", "pg_dump", "pg_restore"):
        if not os.access(PG / executable, os.X_OK):
            raise RuntimeError(f"Install approved native PostgreSQL 17 binaries: missing {executable}")
    if "PostgreSQL) 17." not in output(PG / "postgres", "--version"):
        raise RuntimeError("Native PostgreSQL 17 is required")
    host_evidence(require_all=False)
    if UNIT_FILE.exists() and UNIT_FILE.read_bytes() != (REPO / TOOL / UNIT_FILE.name).read_bytes():
        raise RuntimeError("Unexpected existing systemd template; inspect it manually")
    for path in (ROOT, DATA, ROOT / "config", ROOT / "releases"):
        if path.is_symlink() or (path.exists() and (path.stat().st_uid != 0 or path.stat().st_mode & 0o022)):
            raise RuntimeError(f"Unsafe directory ownership or permissions: {path}")
    print(f"PREFLIGHT_OK {sha} (dedicated loopback ports 18760–18764)", flush=True)


def write_secret(path, value, uid=0, gid=0):
    if path.is_symlink():
        raise RuntimeError(f"Unexpected secret symlink: {path}")
    if path.exists():
        st = path.stat()
        if st.st_uid != uid or st.st_mode & 0o077:
            raise RuntimeError(f"Unsafe secret ownership or permissions: {path}")
        return path.read_text().strip()
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        os.fchown(stream.fileno(), uid, gid)
        stream.write(value + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)
    return value


def environment(name, values):
    path = ROOT / "config" / f"{name}.env"
    payload = "\n".join(f"{key}={shlex.quote(str(value))}" for key, value in sorted(values.items()))
    if write_secret(path, payload) != payload:
        raise RuntimeError(f"Managed config mismatch: {path}")
    return values


def _read_managed_environment(name):
    path = ROOT / "config" / f"{name}.env"
    if path.is_symlink():
        raise RuntimeError("Unexpected managed environment symlink")
    if not path.exists():
        return {}
    private_file(path, 0)
    parsed = {}
    for line in path.read_text().splitlines():
        if "=" not in line:
            raise RuntimeError("Managed environment has invalid line")
        key, value = line.split("=", 1)
        if key in parsed:
            raise RuntimeError("Duplicate managed environment key")
        words = shlex.split(value)
        if len(words) != 1:
            raise RuntimeError("Invalid managed environment quoting")
        parsed[key] = words[0]
    return parsed


def _managed_config_snapshot(names=("identity", "pos", "ingress", "postgres", "supply")):
    snapshot = {}
    for name in names:
        path = ROOT / "config" / f"{name}.env"
        if path.is_symlink():
            raise RuntimeError("Unexpected managed environment symlink")
        if not path.exists():
            snapshot[name] = None
            continue
        private_file(path, 0)
        info = path.stat()
        snapshot[name] = (path.read_bytes(), info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
    return snapshot


def _restore_managed_config(snapshot):
    errors = []
    for name, prior in reversed(list(snapshot.items())):
        path = ROOT / "config" / f"{name}.env"
        try:
            if path.is_symlink():
                raise RuntimeError(f"Managed environment became a symlink: {path}")
            if prior is None:
                path.unlink(missing_ok=True)
                if path.parent.exists():
                    sync_directory(path.parent)
                if path.exists():
                    raise RuntimeError(f"Could not remove new managed environment: {path}")
                continue
            data, uid, gid, mode = prior
            tmp = path.with_name(path.name + ".g1-rollback")
            if tmp.exists() or tmp.is_symlink():
                raise RuntimeError(f"Unreviewed config rollback marker: {tmp}")
            fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), mode)
            with os.fdopen(fd, "wb") as stream:
                if os.geteuid() != uid or os.getegid() != gid:
                    os.fchown(stream.fileno(), uid, gid)
                os.fchmod(stream.fileno(), mode)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
            sync_directory(path.parent)
            if path.read_bytes() != data:
                raise RuntimeError(f"Managed environment rollback verification failed: {path}")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        raise RuntimeError("Managed config rollback failed; keep services stopped: " + "; ".join(errors))


def _three_store_scope_change(name, key, target, approved):
    current = _read_managed_environment(name)
    if key not in current or current[key] == str(target):
        return {}
    old = current[key]
    triple = "BSVM,BSVS,BSVT"
    if key == "BSV_POS_STORE_LEGAL_JSON":
        try:
            old_map, new_map = json.loads(old), json.loads(str(target))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Invalid managed POS store mapping") from exc
        one = {"BSVT": "DEMO_LEGAL"}
        three = {"BSVM": "DEMO_LEGAL", "BSVS": "DEMO_LEGAL", "BSVT": "DEMO_LEGAL"}
        if old_map not in (one, three) or new_map not in (one, three):
            raise RuntimeError("Unknown or non-synthetic managed POS store mapping")
        widening = old_map == one and new_map == three
        narrowing = old_map == three and new_map == one
    else:
        allowed = {"BSVT", triple}
        if key == "BSV_POS_G1_TEST_STORES":
            allowed.add("disabled")
        if old not in allowed or str(target) not in allowed:
            raise RuntimeError("Unknown managed store scope; refuse migration")
        widening = old != triple and str(target) == triple
        narrowing = old == triple and str(target) != triple
        if old == "disabled" and str(target) == "BSVT":
            raise RuntimeError("Unexpected store scope transition")
    if widening and not approved:
        raise RuntimeError("Three-store synthetic scope requires explicit approval")
    if not widening and not narrowing:
        raise RuntimeError("Unapproved managed store scope change")
    return {key: (old, str(target))}


def upgrade_managed_environment(name, values, allowed_additions, *, allow_blank=False,
                                approved_changes=None):
    """Atomically migrate an exact managed env while preserving all unapproved values."""
    path = ROOT / "config" / f"{name}.env"
    if not path.exists():
        environment(name, values)
        return values
    private_file(path, 0)
    raw = path.read_text().strip()
    parsed = _read_managed_environment(name)
    if not raw and not allow_blank:
        raise RuntimeError("Unexpected empty managed environment")
    if set(values) - set(parsed) - set(allowed_additions) and raw:
        raise RuntimeError("Unapproved environment keys requested")
    changed = {}
    for key, value in parsed.items():
        if key not in values:
            raise RuntimeError("Unexpected managed environment key")
        desired = str(values[key])
        if value != desired:
            changed[key] = (value, desired)
    approved_changes = approved_changes or {}
    if changed != approved_changes:
        raise RuntimeError("Existing managed environment has changed; refuse overwrite")
    payload = "\n".join(f"{key}={shlex.quote(str(value))}" for key, value in sorted(values.items()))
    if raw == payload:
        return values
    tmp = path.with_name(path.name + ".next")
    if tmp.exists() or tmp.is_symlink():
        raise RuntimeError("Unreviewed config migration marker")
    try:
        write_secret(tmp, payload)
        tmp.replace(path)
        sync_directory(path.parent)
    finally:
        tmp.unlink(missing_ok=True)
    return values


def upgrade_identity_environment(values, *, approve_synthetic_three_store=False):
    """Migrate only the approved isolated store-scope transition; retain token secrets."""
    path = ROOT / "config" / "identity.env"
    if not path.exists():
        return environment("identity", values)
    parsed = _read_managed_environment("identity")
    desired = {key: str(value) for key, value in values.items()}
    # Older callers that only migrate the layout-admin token keep the safe H default.
    desired.setdefault("BSV_ACADEMY_STORE_IDS", "BSVT")
    additions = {"BSV_ACADEMY_STORE_IDS"}
    if set(parsed) - set(desired) or set(desired) - set(parsed) - additions:
        raise RuntimeError("Missing or additional managed identity environment keys")
    target_scope = desired.get("BSV_ACADEMY_STORE_IDS", "")
    if target_scope not in ("BSVT", "BSVM,BSVS,BSVT"):
        raise RuntimeError("Academy store scope must be the BSVT default or approved synthetic stores")
    current_scope = parsed.get("BSV_ACADEMY_STORE_IDS")
    if current_scope is not None and current_scope != target_scope:
        if current_scope not in ("BSVT", "BSVM,BSVS,BSVT"):
            raise RuntimeError("Unknown Academy store scope; refuse migration")
        if target_scope == "BSVM,BSVS,BSVT" and not approve_synthetic_three_store:
            raise RuntimeError("Academy three-store scope requires explicit approval")
    special = "BSV_SERVICE_TOKENS_JSON"
    for key, value in parsed.items():
        if key in {special, "BSV_ACADEMY_STORE_IDS"}:
            continue
        if value != desired[key]:
            raise RuntimeError("Existing identity secrets or settings changed; refuse overwrite")
    try:
        old_tokens = json.loads(parsed[special])
        new_tokens = json.loads(desired[special])
    except (ValueError, TypeError, KeyError) as exc:
        raise RuntimeError("Invalid managed identity service token map") from exc
    if (not isinstance(old_tokens, dict) or not isinstance(new_tokens, dict)
            or set(old_tokens) not in ({"pos", "supply"}, {"pos", "supply", "layout-admin"})
            or set(new_tokens) != {"pos", "supply", "layout-admin"}
            or old_tokens["supply"] != new_tokens["supply"]):
        raise RuntimeError("Unapproved identity token-map modification")
    target_stores = target_scope.split(",")
    old_pos, new_pos = old_tokens["pos"], new_tokens["pos"]
    if (not isinstance(old_pos, dict) or not isinstance(new_pos, dict)
            or set(old_pos) != set(new_pos)
            or {k: v for k, v in old_pos.items() if k != "stores"}
                != {k: v for k, v in new_pos.items() if k != "stores"}
            or old_pos.get("legal_entities") != ["DEMO_LEGAL"]
            or old_pos.get("stores") not in (["BSVT"], ["BSVM", "BSVS", "BSVT"])
            or new_pos.get("stores") != target_stores):
        raise RuntimeError("Unapproved identity POS token scope")
    if old_pos.get("stores") != target_stores:
        widening = old_pos["stores"] == ["BSVT"] and target_stores == ["BSVM", "BSVS", "BSVT"]
        narrowing = old_pos["stores"] == ["BSVM", "BSVS", "BSVT"] and target_stores == ["BSVT"]
        if (widening and not approve_synthetic_three_store) or not (widening or narrowing):
            raise RuntimeError("Identity POS three-store scope requires explicit approval")
    if "layout-admin" in old_tokens:
        if old_tokens["layout-admin"] != new_tokens["layout-admin"]:
            raise RuntimeError("Existing layout-admin token or scope changed")
    else:
        layout = new_tokens["layout-admin"]
        if (not isinstance(layout, dict) or layout.get("actions") != ["hq.layout.read"]
                or layout.get("stores") != ["BSVT"] or layout.get("legal_entities") != ["DEMO_LEGAL"]
                or len(layout.get("token", "")) < 32):
            raise RuntimeError("Unapproved identity token-map addition")
    payload = "\n".join(f"{key}={shlex.quote(str(value))}" for key, value in sorted(desired.items()))
    if path.read_text().strip() == payload:
        return values
    tmp = path.with_name(path.name + ".next")
    if tmp.exists() or tmp.is_symlink():
        raise RuntimeError("Unreviewed config migration marker")
    try:
        write_secret(tmp, payload)
        tmp.replace(path)
        sync_directory(path.parent)
    finally:
        tmp.unlink(missing_ok=True)
    return values


def upgrade_blank_ingress_environment(values, *, approved_changes=None):
    """Backwards-compatible ingress upgrade with exact approved scope transitions."""
    return upgrade_managed_environment(
        "ingress", values,
        {"BSV_GROWTH_POS_CONTEXT_KEY", "BSV_GROWTH_LINK_KEY",
         "BSV_GROWTH_POS_VERIFY_TOKEN", "BSV_GROWTH_POS_VERIFY_URL"},
        allow_blank=True, approved_changes=approved_changes)


def prepare_config(approve_synthetic_three_store=False):
    """Apply the complete managed scope transition or restore every env file on failure."""
    snapshot = _managed_config_snapshot()
    try:
        return _prepare_config(approve_synthetic_three_store)
    except BaseException:
        try:
            _restore_managed_config(snapshot)
        except Exception as rollback_error:
            raise RuntimeError("Managed config upgrade failed and rollback verification failed") from rollback_error
        raise


def _prepare_config(approve_synthetic_three_store=False):
    for path, mode in ((ROOT, 0o755), (ROOT / "releases", 0o755), (ROOT / "config", 0o700), (DATA, 0o755)):
        path.mkdir(mode=mode, exist_ok=True)
    for name in START_ORDER:
        try:
            account = pwd.getpwnam(user(name))
        except KeyError:
            run("useradd", "--system", "--user-group", "--no-create-home", "--home-dir", DATA / name,
                "--shell", "/usr/sbin/nologin", user(name))
            account = pwd.getpwnam(user(name))
        if account.pw_uid == 0 or account.pw_shell != "/usr/sbin/nologin" or account.pw_dir != str(DATA / name):
            raise RuntimeError(f"Existing service user is incompatible: {user(name)}")
        path = DATA / name
        if path.is_symlink():
            raise RuntimeError(f"Unexpected data directory symlink: {path}")
        if not path.exists():
            path.mkdir(mode=0o700)
            os.chown(path, account.pw_uid, account.pw_gid)
        if path.stat().st_uid != account.pw_uid or path.stat().st_mode & 0o077:
            raise RuntimeError(f"Unsafe service data directory: {path}")
    config = ROOT / "config"
    dbpw, pos_token, layout_token, supply_token, session, pepper, reviewer1, reviewer2 = [
        write_secret(config / key, secrets.token_urlsafe(36)) for key in
        ("pg-password", "pos-token", "layout-token", "supply-token", "session-key", "privacy-pepper", "reviewer1", "reviewer2")]
    pin = write_secret(config / "pos-pin", str(10**10 + secrets.randbelow(9 * 10**10)))
    # Three distinct secrets: guest authorization, POS visit context and the
    # private POS-to-growth verification channel. Never share payment secrets.
    growth_link = write_secret(config / "growth-link-key", secrets.token_urlsafe(48))
    growth_context = write_secret(config / "growth-pos-context-key", secrets.token_urlsafe(48))
    growth_verify = write_secret(config / "growth-pos-verify-token", secrets.token_urlsafe(48))
    store_ids = ["BSVM", "BSVS", "BSVT"] if approve_synthetic_three_store else ["BSVT"]
    store_csv = ",".join(store_ids)
    store_map = {store_id: "DEMO_LEGAL" for store_id in store_ids}
    store_map_json = json.dumps(store_map, separators=(",", ":"))
    token_map = {
        "pos": {"token": pos_token, "actions": ["pos.order.read", "pos.order.create"],
                "legal_entities": ["DEMO_LEGAL"], "stores": store_ids},
        "layout-admin": {"token": layout_token, "actions": ["hq.layout.read"],
                         "legal_entities": ["DEMO_LEGAL"], "stores": ["BSVT"]},
        "supply": {"token": supply_token, "legal_entity_id": "DEMO_LEGAL",
                   "stores": ["BSVM", "BSVS", "BSVT"], "isolated_test_department": "SYNTH-STAGE",
                   "actions": ["supply.dispatch", "supply.receive", "quality.self_check",
                               "quality.independent.submit", "quality.independent.review"]},
    }
    identity = upgrade_identity_environment({
        "BSV_APP_ENV": "isolated", "BSV_AUTH_PROVIDER": "isolated",
        "BSV_DB_A_URL": f"postgresql+psycopg://{DB_USER}:{dbpw}@127.0.0.1:18764/{DB}",
        "BSV_DB_SSLMODE": "disable", "BSV_SESSION_SECRET": session, "BSV_PRIVACY_PEPPER": pepper,
        "BSV_COOKIE_SECURE": "0", "BSV_REGISTRATION_ENTITIES_JSON": '["DEMO_LEGAL"]',
        "BSV_LOCAL_ARCHIVE_DIR": str(DATA / "identity" / "archives"),
        "BSV_BACKUP_KEY_FILE": str(DATA / "identity" / "archive.key"),
        "BSV_DEMO_ADMIN_1_PASSWORD": reviewer1, "BSV_DEMO_ADMIN_2_PASSWORD": reviewer2,
        "BSV_ACADEMY_STORE_IDS": store_csv,
        "BSV_SERVICE_TOKENS_JSON": json.dumps(token_map, separators=(",", ":")),
    }, approve_synthetic_three_store=approve_synthetic_three_store)
    pos = upgrade_managed_environment("pos", {
        "BSV_MODE": "staging", "BSV_PORT": "18762", "BSV_PRIVATE_SSH_TUNNEL": "1",
        "BSV_DB_PATH": str(DATA / "pos" / "synthetic.sqlite3"),
        "BSV_V9_XLSX": str(DATA / "pos" / "synthetic-v9.xlsx"),
        "BSV_BACKUP_DIR": str(DATA / "pos" / "backups"),
        "BSV_POS_IDENTITY_REQUIRED": "1", "BSV_POS_IDENTITY_URL": "http://127.0.0.1:18761",
        "BSV_POS_IDENTITY_TOKEN": pos_token, "BSV_POS_INTERNAL_STAGE": "1",
        "BSV_POS_STORE_LEGAL_JSON": store_map_json,
        "BSV_POS_G1_TEST_STORES": store_csv if approve_synthetic_three_store else "disabled",
        "BSV_POS_LAYOUT_SERVICE_TOKEN": layout_token, "BSV_POS_LAYOUT_SCOPE_MODE": "isolated-synthetic",
        "BSV_APP_ENV": "isolated",
        "BSV_POS_GROWTH_INTEGRATION": "1",
        "BSV_GROWTH_LINK_KEY": growth_link,
        "BSV_GROWTH_POS_CONTEXT_KEY": growth_context,
        "BSV_GROWTH_POS_VERIFY_TOKEN": growth_verify,
    }, {"BSV_POS_LAYOUT_SERVICE_TOKEN", "BSV_POS_LAYOUT_SCOPE_MODE",
        "BSV_APP_ENV", "BSV_POS_GROWTH_INTEGRATION", "BSV_GROWTH_LINK_KEY",
        "BSV_GROWTH_POS_CONTEXT_KEY", "BSV_GROWTH_POS_VERIFY_TOKEN",
        "BSV_POS_G1_TEST_STORES"}, approved_changes={
            **_three_store_scope_change("pos", "BSV_POS_STORE_LEGAL_JSON", store_map_json,
                                       approve_synthetic_three_store),
            **_three_store_scope_change("pos", "BSV_POS_G1_TEST_STORES",
                                       store_csv if approve_synthetic_three_store else "disabled",
                                       approve_synthetic_three_store),
        })
    environment("postgres", {"BSV_STAGE_COMPONENT_DATA": str(DATA / "postgres")})
    # Isolated, synthetic candidate only; no additional public service or authority.
    # The original ingress.env is an empty, root-owned environment file on older
    # releases. Only that exact baseline may be upgraded atomically.
    growth_signing = write_secret(config / "growth-signing-key", secrets.token_urlsafe(40))
    growth_signature = write_secret(
        config / "growth-signature-key", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    ingress_settings = {
        "BSV_STAGE_GROWTH_ENABLED": "1", "BSV_GROWTH_ENV": "isolated",
        "BSV_GROWTH_TRUST_IDENTITY": "1",
        "BSV_GROWTH_DB_URL": "sqlite:///" + str(DATA / "ingress" / "growth-candidate.sqlite3"),
        "BSV_GROWTH_IDENTITY_ME_URL": "http://127.0.0.1:18761/api/v1/identity/me",
        "BSV_GROWTH_SIGNING_KEY": growth_signing,
        "BSV_GROWTH_SIGNATURE_KEY": growth_signature,
        "BSV_GROWTH_LINK_KEY": growth_link,
        "BSV_GROWTH_POS_CONTEXT_KEY": growth_context,
        "BSV_GROWTH_POS_VERIFY_TOKEN": growth_verify,
        "BSV_GROWTH_POS_VERIFY_URL": "http://127.0.0.1:18762/api/v1/visits/customer-context/verify",
        "BSV_GROWTH_LEGAL_ENTITY_ID": "DEMO_LEGAL",
        "BSV_GROWTH_STORE_IDS": store_csv,
        "BSV_GROWTH_PUBLIC_BASE_URL": "http://127.0.0.1:18760",
        "BSV_GROWTH_MENU_URL": "/cocktail/",
        "BSV_GROWTH_PRIVACY_APPROVED": "0",
    }
    upgrade_blank_ingress_environment(ingress_settings, approved_changes=
        _three_store_scope_change("ingress", "BSV_GROWTH_STORE_IDS", store_csv,
                                  approve_synthetic_three_store))
    sources = json.loads((REPO / "config/modules/supply-sources.example.json").read_text())
    for value in sources["sources"].values():
        value["primary"] = value["standby_read"] = ""
    sources["sources"]["B"]["primary"] = "http://127.0.0.1:18761/api/v1"
    # This file contains no credentials and must be readable by the supply process.
    supply_config = DATA / "supply" / "supply-sources.json"
    account = pwd.getpwnam(user("supply"))
    payload = json.dumps(sources, sort_keys=True)
    if write_secret(supply_config, payload, account.pw_uid, account.pw_gid) != payload:
        raise RuntimeError("Existing supply source configuration differs")
    environment("supply", {"BSV_MODE": "internal-stage", "BSV_SUPPLY_STATE_DIR": str(DATA / "supply"),
                           "BSV_SOURCE_B_TOKEN": supply_token, "BSV_SOURCES_CONFIG": str(supply_config)})
    return identity, pos, dbpw, pin


def _restore_default_store_scope_if_enabled():
    pos_path = ROOT / "config" / "pos.env"
    if not pos_path.exists():
        return
    pos = _read_managed_environment("pos")
    identity_path = ROOT / "config" / "identity.env"
    ingress_path = ROOT / "config" / "ingress.env"
    identity = _read_managed_environment("identity") if identity_path.exists() else {}
    ingress = _read_managed_environment("ingress") if ingress_path.exists() else {}
    three_map = {"BSVM": "DEMO_LEGAL", "BSVS": "DEMO_LEGAL", "BSVT": "DEMO_LEGAL"}
    try:
        current_map = json.loads(pos.get("BSV_POS_STORE_LEGAL_JSON", "{}"))
    except (TypeError, ValueError):
        raise RuntimeError("Invalid POS store map during rollback; keep services stopped")
    if (pos.get("BSV_POS_G1_TEST_STORES") == "BSVM,BSVS,BSVT"
            or current_map == three_map
            or identity.get("BSV_ACADEMY_STORE_IDS") == "BSVM,BSVS,BSVT"
            or ingress.get("BSV_GROWTH_STORE_IDS") == "BSVM,BSVS,BSVT"):
        prepare_config(False)


def git_blob_sha(data):
    digest = hashlib.sha1()
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest()


def verified_source_manifest(sha):
    """Resolve an immutable commit and enumerate every path/blob before extraction."""
    if not re.fullmatch(r"[a-f0-9]{40}", sha or ""):
        raise RuntimeError("A full immutable Git commit SHA is required")
    env = {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}
    try:
        commit = subprocess.run(git("rev-parse", "--verify", f"{sha}^{{commit}}"),
                                check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env).stdout.strip()
        if commit != sha:
            raise RuntimeError("Release SHA does not resolve to the exact requested commit")
        tree = subprocess.run(git("rev-parse", "--verify", f"{sha}^{{tree}}"),
                              check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env).stdout.strip()
        if not re.fullmatch(r"[a-f0-9]{40}", tree):
            raise RuntimeError("Release commit has an invalid Git tree identity")
        listing = subprocess.run(git("ls-tree", "-r", "-t", "-z", "--full-tree", sha),
                                 check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env).stdout
    except subprocess.CalledProcessError as error:
        raise RuntimeError("Release SHA or tree is unavailable in the verified Git object store") from error
    entries = {}
    for record in listing.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split(" ")
        path = raw_path.decode("utf-8", "strict")
        parts = path.split("/")
        if (not path or path.startswith("/") or "\\" in path
                or any(part in {"", ".", ".."} for part in parts)
                or any(len(part.encode("utf-8")) > 255 for part in parts)):
            raise RuntimeError("Git tree contains a path unsafe for release extraction")
        if path in entries:
            raise RuntimeError("Git tree contains duplicate paths")
        if mode == "040000" and kind == "tree":
            entries[path] = {"kind": "directory"}
        elif mode in {"100644", "100755"} and kind == "blob" and re.fullmatch(r"[a-f0-9]{40}", oid):
            entries[path] = {"kind": "file", "mode": mode, "oid": oid}
        else:
            # There are no reviewed source symlinks, submodules, or special files.
            raise RuntimeError(f"Unsupported tracked release entry: {path}")
    if not entries:
        raise RuntimeError("Release commit has an empty source tree")
    return {"format": 1, "commit": sha, "tree": tree, "entries": dict(sorted(entries.items()))}


def _safe_tar_path(name):
    path = name.rstrip("/")
    parts = path.split("/")
    if (not path or path.startswith("/") or "\\" in path
            or any(part in {"", ".", ".."} for part in parts)):
        raise RuntimeError("Unsafe path in release archive")
    return path


def validate_source_archive(archive_path, manifest):
    """Validate tar member names, types, executable bits, and blob IDs before extraction."""
    seen = set()
    with tarfile.open(archive_path, "r:") as archive:
        for member in archive:
            path = _safe_tar_path(member.name)
            if path in seen or path not in manifest["entries"]:
                raise RuntimeError("Release archive paths do not match the immutable Git tree")
            seen.add(path)
            expected = manifest["entries"][path]
            if member.mode & 0o7000:
                raise RuntimeError("Release archive contains special permission bits")
            if expected["kind"] == "directory":
                if not member.isdir():
                    raise RuntimeError("Release archive directory type differs from Git tree")
            else:
                if not member.isreg() or bool(member.mode & stat.S_IXUSR) != (expected["mode"] == "100755"):
                    raise RuntimeError("Release archive file type or executable bit differs from Git tree")
                stream = archive.extractfile(member)
                if stream is None:
                    raise RuntimeError("Release archive file has no content")
                digest = hashlib.sha1()
                digest.update(f"blob {member.size}\0".encode("ascii"))
                size = 0
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(chunk)
                    digest.update(chunk)
                if size != member.size or digest.hexdigest() != expected["oid"]:
                    raise RuntimeError("Release archive file content differs from immutable Git blob")
    if seen != set(manifest["entries"]):
        raise RuntimeError("Release archive is incomplete for the immutable Git tree")


def verify_source_tree(source, manifest):
    if source.is_symlink() or not source.is_dir():
        raise RuntimeError("Release source root is not a real directory")
    seen = set()
    stack = [source]
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as children:
            for item in children:
                path = Path(item.path)
                relative = path.relative_to(source).as_posix()
                expected = manifest["entries"].get(relative)
                if expected is None or relative in seen:
                    raise RuntimeError("Release source paths differ from the immutable Git tree")
                seen.add(relative)
                info = path.lstat()
                if info.st_uid != os.geteuid() or info.st_mode & 0o7000:
                    raise RuntimeError("Unsafe release source owner or special permission bits")
                if expected["kind"] == "directory":
                    if not stat.S_ISDIR(info.st_mode):
                        raise RuntimeError("Release source directory differs from immutable Git tree")
                    stack.append(path)
                else:
                    if not stat.S_ISREG(info.st_mode):
                        raise RuntimeError("Release source file is not a regular file")
                    with path.open("rb") as stream:
                        digest = hashlib.sha1()
                        size = info.st_size
                        digest.update(f"blob {size}\0".encode("ascii"))
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != expected["oid"]:
                        raise RuntimeError("Release source file differs from immutable Git blob")
    if seen != set(manifest["entries"]):
        raise RuntimeError("Release source is incomplete for the immutable Git tree")


def _managed_release_directory(dest):
    """Return the resolved, SHA-named direct child of the managed releases directory."""
    releases = ROOT / "releases"
    try:
        if (releases.is_symlink() or not releases.is_dir()
                or dest.parent != releases
                or not re.fullmatch(r"[a-f0-9]{40}", dest.name)
                or dest.is_symlink() or not dest.is_dir()):
            return None
        releases_real = releases.resolve(strict=True)
        dest_real = dest.resolve(strict=True)
        if releases_real != releases or dest_real.parent != releases_real or dest_real != dest:
            return None
        return dest_real
    except (OSError, RuntimeError):
        return None


def _allowed_venv_symlink(dest, path, target):
    release = _managed_release_directory(dest)
    if release is None:
        return False
    try:
        relative = path.relative_to(dest).as_posix()
        parent = path.parent.resolve(strict=True)
        parent.relative_to(release)
        if not path.is_symlink():
            return False
    except (OSError, RuntimeError, ValueError):
        return False
    if relative in {"identity/lib64", "supply/lib64"}:
        return target == "lib"
    if relative in {"identity/bin/python", "supply/bin/python"}:
        return target == "python3"
    if relative in {"identity/bin/python3.12", "supply/bin/python3.12"}:
        return target == "python3"
    if relative in {"identity/bin/python3", "supply/bin/python3"}:
        resolved = os.path.realpath("/usr/bin/python3")
        return target in {"/usr/bin/python3", "/usr/bin/python3.12", resolved} and os.path.realpath(target) == resolved
    return False


def normalize_release_permissions(dest, manifest=None):
    """Grant service identities read/traverse access to versioned code and venvs.

    ROOT/config and DATA contain private credentials and are never traversed.
    This also repairs a completed release built under a root systemd umask 077.
    """
    if _managed_release_directory(dest) is None:
        raise RuntimeError("Unexpected managed release directory")
    source = dest / "src"
    source_directories = {path for path, entry in (manifest or {}).get("entries", {}).items()
                          if entry["kind"] == "directory"}
    source_files = {path: entry for path, entry in (manifest or {}).get("entries", {}).items()
                    if entry["kind"] == "file"}
    if manifest:
        verify_source_tree(source, manifest)
    stack = [dest]
    while stack:
        folder = stack.pop()
        info = folder.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o7000):
            raise RuntimeError("Unsafe release directory ownership or type")
        in_source = folder == source or source in folder.parents
        rel_dir = folder.relative_to(source).as_posix() if folder != source and in_source else ""
        if info.st_mode & 0o022 and not (manifest and in_source and rel_dir in source_directories):
            raise RuntimeError("Unexpected writable release directory")
        folder.chmod(0o755)
        with os.scandir(folder) as children:
            for item in children:
                path = Path(item.path)
                child = path.lstat()
                if child.st_uid != os.geteuid() or child.st_mode & 0o7000:
                    raise RuntimeError("Unsafe release entry ownership or special permissions")
                if stat.S_ISDIR(child.st_mode):
                    stack.append(path)
                elif stat.S_ISLNK(child.st_mode):
                    if not _allowed_venv_symlink(dest, path, os.readlink(path)):
                        raise RuntimeError("Unapproved release symlink")
                elif stat.S_ISREG(child.st_mode):
                    rel = path.relative_to(source).as_posix() if in_source else None
                    if path == dest / ".built":
                        if child.st_mode & 0o077:
                            raise RuntimeError("Release build marker must remain private")
                        continue
                    if manifest:
                        if in_source:
                            expected = source_files.get(rel)
                            if expected is None:
                                raise RuntimeError("Unexpected release source file")
                            executable = expected["mode"] == "100755"
                        else:
                            if child.st_mode & 0o022:
                                raise RuntimeError("Unexpected writable generated release file")
                            executable = bool(child.st_mode & stat.S_IXUSR)
                    else:
                        if child.st_mode & 0o022:
                            raise RuntimeError("Unsafe release file ownership or permissions")
                        executable = bool(child.st_mode & stat.S_IXUSR)
                    path.chmod(0o755 if executable else 0o644)
                else:
                    raise RuntimeError("Unsupported file type in release")
    if manifest:
        verify_source_tree(source, manifest)


def release_inventory_sha256(dest):
    """Attest every generated source/venv path, type, mode, link target, and content."""
    if _managed_release_directory(dest) is None:
        raise RuntimeError("Unexpected managed release directory")
    records = []
    stack = [dest]
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as children:
            for item in children:
                path = Path(item.path)
                if path == dest / ".built":
                    continue
                info = path.lstat()
                if info.st_uid != os.geteuid() or info.st_mode & 0o7000:
                    raise RuntimeError("Unsafe owner or special permissions in built release")
                relative = path.relative_to(dest).as_posix()
                mode = stat.S_IMODE(info.st_mode)
                if stat.S_ISDIR(info.st_mode):
                    if mode & 0o022:
                        raise RuntimeError("Writable directory in built release")
                    records.append([relative, "directory", mode])
                    stack.append(path)
                elif stat.S_ISREG(info.st_mode):
                    if mode & 0o022:
                        raise RuntimeError("Writable file in built release")
                    digest = hashlib.sha256()
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    records.append([relative, "file", mode, digest.hexdigest()])
                elif stat.S_ISLNK(info.st_mode):
                    target = os.readlink(path)
                    if not _allowed_venv_symlink(dest, path, target):
                        raise RuntimeError("Unapproved symlink in built release")
                    records.append([relative, "symlink", target])
                else:
                    raise RuntimeError("Unsupported file type in built release")
    encoded = json.dumps(sorted(records), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def release_marker(manifest, inventory_sha):
    return json.dumps({"manifest": manifest, "inventory_sha256": inventory_sha},
                      sort_keys=True, separators=(",", ":")) + "\n"


def create_release_venv(dest, source, name):
    directory = dest / name
    run("/usr/bin/python3", "-m", "venv", directory)
    run(directory / "bin/python", "-m", "pip", "--disable-pip-version-check", "install",
        "--no-deps", "-r", source / f"services/api/{name}/requirements.lock")
    if name == "identity":
        run(directory / "bin/python", "-m", "pip", "--disable-pip-version-check", "install",
            "--no-deps", "-r", source / "services/api/customer_growth/requirements.stage.lock")
    run(directory / "bin/python", "-m", "pip", "check")


def build(sha):
    manifest = verified_source_manifest(sha)
    dest = ROOT / "releases" / sha
    if dest.is_symlink():
        raise RuntimeError("Release directory is a symlink")
    marker = dest / ".built"
    if marker.is_symlink():
        raise RuntimeError("Release build marker is a symlink")
    if marker.is_file():
        info = marker.lstat()
        if info.st_uid != os.geteuid() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise RuntimeError("Existing release marker does not attest this immutable commit and tree")
        try:
            attestation = json.loads(marker.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("Existing release build marker is invalid") from error
        inventory = attestation.get("inventory_sha256") if isinstance(attestation, dict) else None
        if (not isinstance(attestation, dict)
                or set(attestation) != {"manifest", "inventory_sha256"}
                or attestation.get("manifest") != manifest
                or not isinstance(inventory, str)
                or not re.fullmatch(r"[a-f0-9]{64}", inventory)):
            raise RuntimeError("Existing release marker references another immutable commit or tree")
        verify_source_tree(dest / "src", manifest)
        if attestation.get("inventory_sha256") != release_inventory_sha256(dest):
            raise RuntimeError("Built release files differ from their per-file inventory attestation")
        normalize_release_permissions(dest, manifest)
        return dest
    if dest.exists():
        if dest.is_symlink() or sha in (sha_at(ROOT / "current"), sha_at(ROOT / "previous")):
            raise RuntimeError("Incomplete release is active or has an unexpected path")
        dest.rename(dest.with_name(f".failed-{sha}-{secrets.token_hex(4)}"))
    dest.mkdir(mode=0o700)
    source = dest / "src"
    source.mkdir(mode=0o700)
    archive_path = dest / ".source.tar"
    fd = os.open(archive_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as archive_stream:
            env = {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}
            with subprocess.Popen(git("archive", "--format=tar", sha), stdout=archive_stream, env=env) as archive:
                if archive.wait() != 0:
                    raise RuntimeError("git archive failed")
            archive_stream.flush()
            os.fsync(archive_stream.fileno())
        validate_source_archive(archive_path, manifest)
        run("tar", "--no-same-owner", "--no-same-permissions", "-xf", archive_path, "-C", source)
        verify_source_tree(source, manifest)
    finally:
        archive_path.unlink(missing_ok=True)
    for name in ("identity", "supply"):
        create_release_venv(dest, source, name)
    normalize_release_permissions(dest, manifest)
    inventory_sha = release_inventory_sha256(dest)
    with marker.open("x", encoding="utf-8") as stream:
        stream.write(release_marker(manifest, inventory_sha))
        stream.flush()
        os.fsync(stream.fileno())
    marker.chmod(0o600)
    normalize_release_permissions(dest, manifest)
    return dest


def verify_release_access(dest):
    """Check the candidate source and runtime interpreters as their real service users."""
    def assert_readable_tree(service_name, path):
        result = as_user(
            service_name, "/usr/bin/find", "-P", path,
            "(", "-type", "d", "!", "-executable", "-o", "-type", "f", "!", "-readable", ")",
            "-print", "-quit", stdout=subprocess.PIPE,
        )
        if result.stdout.strip():
            raise RuntimeError(f"Release files are not traversable/readable by {user(service_name)}")

    for service_name in START_ORDER:
        as_user(service_name, "/usr/bin/test", "-x", dest / "src")
        assert_readable_tree(service_name, dest / "src")
    for service_name in ("identity", "supply"):
        python = dest / service_name / "bin/python"
        as_user(service_name, "/usr/bin/test", "-x", python)
        assert_readable_tree(service_name, dest / service_name)


def prepare_pg(dbpw):
    directory = DATA / "postgres"
    cluster = directory / "pg"
    if not (cluster / "PG_VERSION").is_file():
        as_user("postgres", PG / "initdb", "-D", cluster, "--auth-local=peer", "--auth-host=scram-sha-256",
                "--encoding=UTF8", "--locale=C.UTF-8")
    if (cluster / "PG_VERSION").read_text().strip() != "17":
        raise RuntimeError("Existing cluster is not PostgreSQL 17")
    hba = "local all all peer\nhost " + DB + " " + DB_USER + " 127.0.0.1/32 scram-sha-256\n"
    path = cluster / "pg_hba.conf"
    marker = directory / ".hba-initialized"
    if marker.exists() and path.read_text() != hba:
        raise RuntimeError("Private PostgreSQL authentication configuration drift")
    if not marker.exists():
        # Write through the cluster owner and never replace a different managed policy.
        as_user("postgres", "/usr/bin/tee", path, input=hba, stdout=subprocess.DEVNULL)
        as_user("postgres", "/usr/bin/touch", marker)
    run("systemctl", "start", unit("postgres"))
    for _ in range(35):
        status = subprocess.run((PG / "pg_isready", "-h", directory, "-p", "18764"), stdout=subprocess.DEVNULL)
        if status.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Private PostgreSQL did not become ready")
    psql = (PG / "psql", "-h", directory, "-p", "18764", "-d", "postgres", "-X", "-v", "ON_ERROR_STOP=1")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", dbpw):
        raise RuntimeError("Invalid managed database secret")
    as_user("postgres", *psql, input=f"""
SET log_min_error_statement = 'panic';
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', '{DB_USER}', '{dbpw}')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{DB_USER}')
\\gexec
SELECT format('CREATE DATABASE %I OWNER %I', '{DB}', '{DB_USER}')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{DB}')
\\gexec
REVOKE CONNECT ON DATABASE "{DB}" FROM PUBLIC;
""", stdout=subprocess.DEVNULL)


def identity_tool(dest, identity, *args, **kwargs):
    source = dest / "src"
    env = {"PATH": str(PG) + ":/usr/bin:/bin", "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"}
    return as_user("identity", dest / "identity/bin/python", *args, env={**env, **identity}, cwd=source, **kwargs)


def bootstrap(dest, identity, pos, pin):
    source = dest / "src"
    identity_tool(dest, identity, "-m", "alembic", "-c",
                  source / "platform/lighthouse/identity/alembic.ini", "upgrade", "head")
    revision = database_revision()
    if revision != migration_revisions(source)[-1]:
        raise RuntimeError("Unexpected isolated database revision after release migration")
    print(f"IDENTITY_SCHEMA {revision}", flush=True)
    if revision == ACADEMY_REVISION:
        media = DATA / "identity" / "academy-media"
        if not media.exists() and not media.is_symlink():
            as_user("identity", "/usr/bin/install", "-d", "-m", "0700", media)
        private_directory(media, pwd.getpwnam(user("identity")).pw_uid)
    reviewer3 = write_secret(ROOT / "config" / "reviewer3", secrets.token_urlsafe(36))
    identity_tool(dest, {**identity, "BSV_DEMO_ADMIN_3_PASSWORD": reviewer3}, "-m",
                  "services.api.identity.seed_isolated", "--i-understand-isolated")
    archive_key = DATA / "identity" / "archive.key"
    if not archive_key.exists():
        identity_tool(dest, identity, "-m", "services.api.identity.backup", "generate-key", "--path", archive_key)
    child = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"}
    as_user("pos", "/usr/bin/python3", source / TOOL / "seed_pos.py",
            env={**child, **pos, "BSV_STAGE_POS_PIN": pin}, cwd=source)


def private_file(path, owner):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != owner or st.st_mode & 0o077:
        raise RuntimeError(f"Unsafe recovery file: {path}")


def private_directory(path, owner):
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != owner or st.st_mode & 0o077:
        raise RuntimeError(f"Unsafe private recovery directory: {path}")


def file_sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def service_config(name):
    config = ROOT / "config" / f"{name}.env"
    private_file(config, 0)
    parsed = {}
    for line in config.read_text().splitlines():
        key, value = line.split("=", 1)
        parsed[key], = shlex.split(value)
    return parsed


def postgres_snapshot(current):
    if not active("postgres"):
        raise RuntimeError("Start the managed private PostgreSQL service before backup")
    identity = service_config("identity")
    archive_dir = DATA / "identity" / "archives"
    archive_key = DATA / "identity" / "archive.key"
    if not re.fullmatch(
        rf"postgresql\+psycopg://{DB_USER}:[A-Za-z0-9_-]+@127\.0\.0\.1:18764/{DB}",
        identity.get("BSV_DB_A_URL", ""),
    ) or identity.get("BSV_APP_ENV") != "isolated" or identity.get("BSV_AUTH_PROVIDER") != "isolated":
        raise RuntimeError("Backup requires the dedicated isolated loopback PostgreSQL database")
    if (identity.get("BSV_LOCAL_ARCHIVE_DIR") != str(archive_dir)
            or identity.get("BSV_BACKUP_KEY_FILE") != str(archive_key) or archive_dir.is_symlink()):
        raise RuntimeError("Backup requires the managed identity archive location and key")
    owner = pwd.getpwnam(user("identity")).pw_uid
    private_file(archive_key, owner)
    dest = ROOT / "releases" / current
    module = ("-m", "services.api.identity.backup")
    created = identity_tool(dest, identity, *module, "create", stdout=subprocess.PIPE, timeout=120)
    report = json.loads(created.stdout)
    archive = Path(report["archive"])
    if archive.parent != archive_dir or not archive.name.startswith("identity-A-") or archive.suffix != ".bsvenc":
        raise RuntimeError("Identity backup returned an unexpected archive")
    private_file(archive, owner)
    if report.get("encrypted") is not True or report.get("sha256") != file_sha256(archive):
        raise RuntimeError("Identity backup checksum or encryption metadata mismatch")
    checked = identity_tool(dest, identity, *module, "restore", "--archive", archive, stdout=subprocess.PIPE, timeout=120)
    integrity = json.loads(checked.stdout)
    if (integrity.get("integrity") != "AES_GCM_VERIFIED" or integrity.get("restore") != "DRY_RUN_NO_WRITE"
            or integrity.get("meta", {}).get("type") != "postgresql"):
        raise RuntimeError("Identity backup integrity check did not confirm PostgreSQL ciphertext")
    sync_directory(archive_dir)
    return {"archive": str(archive), "sha256": report["sha256"], "key_file": str(archive_key),
            "integrity": "AES_GCM_VERIFIED", "restore_rehearsal": "HOST_NOT_RUN"}


def sqlite_snapshot(current, destination):
    pos = service_config("pos")
    live = DATA / "pos" / "synthetic.sqlite3"
    backups = DATA / "pos" / "backups"
    st = live.lstat()
    owner = pwd.getpwnam(user("pos")).pw_uid
    if (pos.get("BSV_MODE") != "staging" or pos.get("BSV_POS_INTERNAL_STAGE") != "1"
            or pos.get("BSV_DB_PATH") != str(live) or pos.get("BSV_BACKUP_DIR") != str(backups)
            or not stat.S_ISREG(st.st_mode) or st.st_uid != owner or st.st_mode & 0o022
            or live.parent.is_symlink() or backups.is_symlink()):
        raise RuntimeError("POS backup requires the dedicated isolated SQLite database")
    source_dir = ROOT / "releases" / current / "src"
    env = {**pos, "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    capture = as_user("pos", "/usr/bin/python3", source_dir / "services/api/bsv1/backup_db.py",
                      env=env, cwd=source_dir, stdout=subprocess.PIPE, timeout=45)
    line = capture.stdout.strip().split("\n")[-1]
    prefix = "备份成功："
    if not line.startswith(prefix):
        raise RuntimeError("POS backup did not return an archive")
    archive = Path(line.removeprefix(prefix).strip())
    if archive.parent != backups or not re.fullmatch(r"synthetic_backup_[0-9TZ]+\.sqlite3", archive.name):
        raise RuntimeError("POS backup returned an unexpected archive")
    private_file(archive, owner)
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as target, archive.open("rb") as complete:
            shutil.copyfileobj(complete, target)
            target.flush()
            os.fsync(target.fileno())
        with closing(sqlite3.connect(destination.as_uri() + "?mode=ro", uri=True)) as snapshot:
            if snapshot.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RuntimeError("POS SQLite snapshot failed integrity checking")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return {"archive": str(destination), "sha256": file_sha256(destination), "integrity": "QUICK_CHECK_OK"}


def growth_candidate_snapshot(current, destination):
    """Back up the *isolated* customer candidate SQLite with a consistent copy."""
    source = ROOT / "releases" / current / "src/services/api/customer_growth/app.py"
    if not source.is_file():
        return None  # older releases predate growth; not a missing business record
    env = service_config("ingress")
    if env.get("BSV_STAGE_GROWTH_ENABLED") != "1" or env.get("BSV_GROWTH_ENV") != "isolated":
        raise RuntimeError("Growth backup must remain isolated and explicitly enabled")
    live = DATA / "ingress" / "growth-candidate.sqlite3"
    if env.get("BSV_GROWTH_DB_URL") != "sqlite:///" + str(live):
        raise RuntimeError("Unexpected growth candidate source")
    owner = pwd.getpwnam(user("ingress")).pw_uid
    private_directory(live.parent, owner)
    private_file(live, owner)
    with closing(sqlite3.connect("file:" + str(live) + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(destination)) as snapshot:
            original.backup(snapshot)
            if snapshot.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RuntimeError("Growth candidate SQLite snapshot failed integrity check")
            snapshot.commit()
    os.chmod(destination, 0o600)
    return {"archive": str(destination), "sha256": file_sha256(destination),
            "integrity": "QUICK_CHECK_OK", "classification": "ISOLATED_CANDIDATE_ONLY"}


def academy_media_snapshot(directory):
    source = DATA / "identity" / "academy-media"
    if not source.exists() and not source.is_symlink():
        return []
    owner = pwd.getpwnam(user("identity")).pw_uid
    private_directory(source, owner)
    result = []
    for path in sorted(source.iterdir()):
        if path.name.startswith(".scan-"):
            continue
        if not MEDIA_FILE.fullmatch(path.name):
            raise RuntimeError("Unexpected file in managed Academy media storage")
        if not directory.exists():
            directory.mkdir(mode=0o700)
        target = directory / path.name
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW), "rb") as original:
            st = os.fstat(original.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid != owner or st.st_mode & 0o077 or st.st_nlink != 1:
                raise RuntimeError("Unsafe file in managed Academy media storage")
            with os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as copy:
                shutil.copyfileobj(original, copy)
                copy.flush()
                os.fsync(copy.fileno())
        result.append({"name": path.name, "filesize": target.stat().st_size, "sha256": file_sha256(target)})
    if result:
        sync_directory(directory)
    return result


def backup(current=None, purpose="manual"):
    if DATA.is_symlink() or DATA.stat().st_uid != 0 or DATA.stat().st_mode & 0o022:
        raise RuntimeError("Unsafe private data directory")
    current = current or sha_at(ROOT / "current")
    if not current:
        raise RuntimeError("A managed private stage release is required before backup")
    recovery = DATA / "recovery"
    recovery.mkdir(mode=0o700, exist_ok=True)
    private_directory(recovery, 0)
    stamp = datetime.now(timezone.utc)
    dest = recovery / f"{stamp:%Y%m%dT%H%M%SZ}-{secrets.token_hex(5)}"
    dest.mkdir(mode=0o700)
    postgres = postgres_snapshot(current)
    pos = sqlite_snapshot(current, dest / "pos.sqlite3")
    growth = growth_candidate_snapshot(current, dest / "growth-candidate.sqlite3")
    media = academy_media_snapshot(dest / "academy-media")
    receipt = dest / "receipt.json"
    record = {"version": 2, "time": stamp.isoformat(), "mode": "isolated", "purpose": purpose,
              "status": "CHECKPOINT_READY", "checkpoint": str(receipt), "release_sha": current,
              "postgres": postgres, "pos_sqlite": pos, "academy_media": media,
              "growth_candidate_sqlite": growth,
              "isolated_db_revision": database_revision()}
    write_secret(receipt, json.dumps(record, ensure_ascii=False))
    sync_directory(recovery)
    print(json.dumps(record, ensure_ascii=False), flush=True)
    return record


def recovery_check(receipt):
    """Verify a managed checkpoint and its key without writing a live database."""
    recovery = DATA / "recovery"
    if (receipt.name != "receipt.json" or receipt.parent.parent != recovery
            or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{10}", receipt.parent.name)):
        raise RuntimeError("Specify a managed isolated checkpoint receipt")
    private_directory(recovery, 0)
    private_directory(receipt.parent, 0)
    private_file(receipt, 0)
    record = json.loads(receipt.read_text())
    if (record.get("version") not in {1, 2} or record.get("mode") != "isolated"
            or record.get("status") != "CHECKPOINT_READY" or record.get("checkpoint") != str(receipt)):
        raise RuntimeError("Invalid isolated checkpoint receipt")
    current = sha_at(ROOT / "current")
    if not current:
        raise RuntimeError("No isolated application release available to verify PostgreSQL ciphertext")
    identity = service_config("identity")
    pg = record.get("postgres", {})
    archive = Path(pg.get("archive", ""))
    archive_dir = DATA / "identity" / "archives"
    archive_key = DATA / "identity" / "archive.key"
    owner = pwd.getpwnam(user("identity")).pw_uid
    if (archive.parent != archive_dir
            or not re.fullmatch(r"identity-A-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{6}\.bsvenc", archive.name)
            or identity.get("BSV_LOCAL_ARCHIVE_DIR") != str(archive_dir)
            or identity.get("BSV_BACKUP_KEY_FILE") != str(archive_key)
            or identity.get("BSV_APP_ENV") != "isolated"):
        raise RuntimeError("Checkpoint references an unmanaged PostgreSQL archive or key")
    private_directory(archive_dir, owner)
    private_file(archive, owner)
    private_file(archive_key, owner)
    if pg.get("sha256") != file_sha256(archive):
        raise RuntimeError("PostgreSQL checkpoint checksum mismatch")
    verified = identity_tool(ROOT / "releases" / current, identity, "-m", "services.api.identity.backup",
                             "restore", "--archive", archive, stdout=subprocess.PIPE, timeout=120)
    pg_result = json.loads(verified.stdout)
    if (pg_result.get("integrity") != "AES_GCM_VERIFIED" or pg_result.get("restore") != "DRY_RUN_NO_WRITE"
            or pg_result.get("meta", {}).get("type") != "postgresql"):
        raise RuntimeError("PostgreSQL checkpoint did not pass its no-write verification")
    pos = receipt.parent / "pos.sqlite3"
    private_file(pos, 0)
    if record.get("pos_sqlite", {}).get("sha256") != file_sha256(pos):
        raise RuntimeError("POS checkpoint checksum mismatch")
    with closing(sqlite3.connect(pos.as_uri() + "?mode=ro", uri=True)) as snapshot:
        if snapshot.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise RuntimeError("POS checkpoint integrity check failed")
    growth = record.get("growth_candidate_sqlite")
    if growth is not None:
        snapshot = receipt.parent / "growth-candidate.sqlite3"
        private_file(snapshot, 0)
        if (growth.get("archive") != str(snapshot)
                or growth.get("classification") != "ISOLATED_CANDIDATE_ONLY"
                or growth.get("sha256") != file_sha256(snapshot)):
            raise RuntimeError("Growth candidate checkpoint checksum/ownership mismatch")
        with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as candidate:
            if candidate.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RuntimeError("Growth candidate checkpoint integrity failed")
    files = record.get("academy_media", [])
    names = set()
    directory = receipt.parent / "academy-media"
    if files:
        private_directory(directory, 0)
    for entry in files:
        name = entry.get("name", "")
        if name in names or not MEDIA_FILE.fullmatch(name):
            raise RuntimeError("Unexpected Academy media checkpoint file")
        path = directory / name
        private_file(path, 0)
        if entry.get("filesize") != path.stat().st_size or entry.get("sha256") != file_sha256(path):
            raise RuntimeError("Academy media checkpoint checksum mismatch")
        names.add(name)
    print(json.dumps({"status": "RECOVERY_CHECK_READY", "mode": "isolated", "checkpoint": str(receipt),
                      "postgres": "AES_GCM_VERIFIED", "pos_sqlite": "QUICK_CHECK_OK",
                      "academy_media_files": len(names), "live_restore": "NOT_RUN"}), flush=True)


def http_check(path, expected):
    try:
        with OPENER.open(f"http://127.0.0.1:18760{path}", timeout=3) as response:
            return response.status == expected
    except urllib.error.HTTPError as error:
        return error.code == expected
    except (OSError, urllib.error.URLError):
        return False


def verify():
    deployed = sha_at(ROOT / "current")
    routes = [
        ("/health/ready", 200), ("/api/health", 200), ("/staff", 200), ("/pos", 200),
        ("/supply-ui/api/health", 200), ("/api/state", 401), ("/supply-ui/api/me", 401),
        ("/api/v1/identity/pos-session", 404), ("/cocktail/", 200), ("/craft/", 404),
        ("/__bsv_unknown_release_route__", 404),
    ]
    if deployed and (ROOT / "releases" / deployed / "src/services/api/customer_growth/app.py").exists():
        routes.extend((
            ("/member/", 200), ("/staff/growth/", 200),
            ("/api/v1/growth/public/config", 200),
            ("/api/v1/growth/staff/store-options", 401),
            ("/api/v1/growth/internal/payment-event", 404),
        ))
    if deployed and ACADEMY_REVISION in migration_revisions(ROOT / "releases" / deployed / "src"):
        routes.append(("/api/v1/academy/work", 401))
    for _ in range(35):
        if (all(active(name) for name in START_ORDER) and
                all(http_check(path, status) for path, status in routes)):
            evidence = host_evidence()
            print(json.dumps({"status": "RELEASE_HEALTH_OK", "mode": "isolated",
                              "time": datetime.now(timezone.utc).isoformat(), **evidence}), flush=True)
            print("VERIFY_OK: loopback routing, health and anonymous access checks", flush=True)
            return evidence
        time.sleep(1)
    raise RuntimeError("Private stage HTTP checks failed; examine dedicated systemd journal")


def switch_services(start, *, keep_postgres=False):
    names = START_ORDER if start else tuple(reversed(START_ORDER))
    if keep_postgres:
        names = tuple(name for name in names if name != "postgres")
    for name in names:
        run("systemctl", "start" if start else "stop", unit(name))


@contextmanager
def locked():
    lock = Path("/run/lock/bsv-all-internal-stage.lock")
    fd = os.open(lock, os.O_CREAT | os.O_NOFOLLOW | os.O_WRONLY, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def recover_pending():
    marker = ROOT / "activation.pending"
    if not marker.exists():
        return
    previous = marker.read_text().strip()
    if previous and not re.fullmatch(r"[a-f0-9]{40}", previous):
        raise RuntimeError("Invalid managed activation journal")
    switch_services(False)
    _restore_default_store_scope_if_enabled()
    if previous:
        link("current", previous)
        switch_services(True)
        verify()
    else:
        (ROOT / "current").unlink(missing_ok=True)
    marker.unlink()


def activation_checkpoint(current, purpose):
    switch_services(False, keep_postgres=True)
    if not active("postgres"):
        run("systemctl", "start", unit("postgres"))
    for _ in range(20):
        probe = subprocess.run((PG / "pg_isready", "-h", "127.0.0.1", "-p", str(PORTS["postgres"]),
                                "-t", "1", "-q"))
        if probe.returncode == 0:
            backup(current, purpose)
            return
        time.sleep(1)
    raise RuntimeError("Private PostgreSQL is not accepting connections for backup")


def deploy(sha, *, approve_synthetic_three_store=False):
    recover_pending()
    preflight(sha)
    previous = sha_at(ROOT / "current")
    if previous and previous != sha:
        migration_compatibility(ROOT / "releases" / previous / "src", REPO)
    if not previous and ((DATA / "postgres" / "pg" / "PG_VERSION").exists()
                         or (DATA / "pos" / "synthetic.sqlite3").exists()):
        raise RuntimeError("Existing private data has no managed active release; investigate before deployment")
    dest = build(sha)
    config_snapshot = _managed_config_snapshot()
    try:
        identity, pos, dbpw, pin = prepare_config(approve_synthetic_three_store)
        # Fail while the old release still runs if any service cannot read/traverse the candidate.
        verify_release_access(dest)
        if not UNIT_FILE.exists():
            UNIT_FILE.write_bytes((REPO / TOOL / UNIT_FILE.name).read_bytes())
        run("systemctl", "daemon-reload")
        if previous == sha and all(active(name) for name in START_ORDER):
            verify()
            return
    except BaseException:
        _restore_managed_config(config_snapshot)
        raise
    marker = ROOT / "activation.pending"
    write_secret(marker, previous or "")
    try:
        if previous:
            activation_checkpoint(previous, "pre_deploy")
        switch_services(False)
        link("current", sha)
        prepare_pg(dbpw)
        bootstrap(dest, identity, pos, pin)
        switch_services(True)
        verify()
        if previous and previous != sha:
            link("previous", previous)
    except (Exception, KeyboardInterrupt):
        _restore_managed_config(config_snapshot)
        recover_pending()
        raise
    marker.unlink()
    print(f"DEPLOYED_INTERNAL_STAGE {sha}", flush=True)


def rollback():
    if (ROOT / "activation.pending").exists():
        recover_pending()
        return
    current, previous = sha_at(ROOT / "current"), sha_at(ROOT / "previous")
    if not current:
        raise RuntimeError("No managed private stage release is active")
    if previous:
        migration_compatibility(ROOT / "releases" / previous / "src",
                                ROOT / "releases" / current / "src")
    host_evidence(require_all=False)
    marker = ROOT / "activation.pending"
    write_secret(marker, current)
    try:
        activation_checkpoint(current, "pre_rollback")
        switch_services(False)
        _restore_default_store_scope_if_enabled()
        if previous:
            link("current", previous)
            switch_services(True)
            verify()
            link("previous", current)
        else:
            (ROOT / "current").unlink()
    except (Exception, KeyboardInterrupt):
        recover_pending()
        raise
    marker.unlink()
    if previous:
        print(f"ROLLED_BACK {previous}", flush=True)
    else:
        print("Stopped first release. Private databases and files preserved.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    for operation in ("preflight", "deploy", "verify", "rollback", "backup"):
        group.add_argument("--" + operation, action="store_const", dest="operation", const=operation)
    group.add_argument("--recovery-check", type=Path, metavar="RECEIPT")
    parser.add_argument("--sha")
    parser.add_argument("--approve-synthetic-three-store", action="store_true",
                        help="explicitly enable only DEMO_LEGAL BSVM/BSVS/BSVT isolated test scope")
    args = parser.parse_args()
    if args.approve_synthetic_three_store and args.operation != "deploy":
        parser.error("--approve-synthetic-three-store is valid only with --deploy")
    if args.operation in {"preflight", "deploy"} and not re.fullmatch(r"[a-f0-9]{40}", args.sha or ""):
        parser.error("A full approved --sha is required")
    if (args.operation in {"deploy", "rollback", "backup"} or args.recovery_check) and os.geteuid() != 0:
        parser.error("Use sudo for systemd changes")
    if args.operation == "preflight":
        preflight(args.sha)
    elif args.operation == "verify":
        verify()
    else:
        with locked():
            if args.operation == "deploy":
                deploy(args.sha, approve_synthetic_three_store=args.approve_synthetic_three_store)
            elif args.operation == "rollback":
                rollback()
            elif args.recovery_check:
                recovery_check(args.recovery_check)
            else:
                backup()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
        sys.exit(f"Internal stage stopped: {error}")
