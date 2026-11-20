#!/usr/bin/env python3
"""Versioned deployment for the private internal stage on a systemd host."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
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
REPO = Path(__file__).resolve().parents[3]
DB = "bsv_identity_isolated_internal"
DB_USER = "bsv_internal_app"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def output(*args):
    return run(*args, stdout=subprocess.PIPE).stdout.strip()


def unit(name):
    return f"{UNIT}@{name}.service"


def active(name):
    return subprocess.run(("systemctl", "is-active", "--quiet", unit(name))).returncode == 0


def user(name):
    return "bsvint-" + name


def as_user(name, *args, **kwargs):
    return run("runuser", "-u", user(name), "--", *args, **kwargs)


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


def link(name, sha):
    tmp = ROOT / ("." + name + ".next")
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(ROOT / "releases" / sha)
    tmp.replace(ROOT / name)


def preflight(sha):
    if output(*git("rev-parse", "HEAD")) != sha:
        raise RuntimeError("Checkout HEAD must match the approved 40-character SHA")
    run(*git("diff", "--quiet", "HEAD", "--"))
    if not Path("/run/systemd/system").is_dir():
        raise RuntimeError("A live systemd host is required")
    if output("/usr/bin/python3", "-c", "import sys; print('ok' if sys.version_info >= (3,12) else 'no')") != "ok":
        raise RuntimeError("Requires Python 3.12 or newer")
    run("/usr/bin/python3", "-c", "import ensurepip, venv")
    for required in ("git", "tar", "useradd", "runuser", "systemctl", "diff"):
        if not shutil.which(required):
            raise RuntimeError(f"Missing host dependency: {required}")
    for executable in ("postgres", "initdb", "psql", "pg_isready", "pg_dump", "pg_restore"):
        if not os.access(PG / executable, os.X_OK):
            raise RuntimeError(f"Install approved native PostgreSQL 17 binaries: missing {executable}")
    if "PostgreSQL) 17." not in output(PG / "postgres", "--version"):
        raise RuntimeError("Native PostgreSQL 17 is required")
    current = sha_at(ROOT / "current")
    for name, port in PORTS.items():
        if current and active(name):
            continue
        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"Port {port} already in use ({name})") from exc
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
    return value


def environment(name, values):
    path = ROOT / "config" / f"{name}.env"
    payload = "\n".join(f"{key}={shlex.quote(str(value))}" for key, value in sorted(values.items()))
    if write_secret(path, payload) != payload:
        raise RuntimeError(f"Managed config mismatch: {path}")
    return values


def prepare_config():
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
    dbpw, pos_token, supply_token, session, pepper, reviewer1, reviewer2 = [
        write_secret(config / key, secrets.token_urlsafe(36)) for key in
        ("pg-password", "pos-token", "supply-token", "session-key", "privacy-pepper", "reviewer1", "reviewer2")]
    pin = write_secret(config / "pos-pin", str(10**10 + secrets.randbelow(9 * 10**10)))
    store_map = {"BSVT": "DEMO_LEGAL"}
    token_map = {
        "pos": {"token": pos_token, "actions": ["pos.order.read", "pos.order.create"],
                "legal_entities": ["DEMO_LEGAL"], "stores": ["BSVT"]},
        "supply": {"token": supply_token, "legal_entity_id": "DEMO_LEGAL",
                   "stores": ["BSVM", "BSVS", "BSVT"], "isolated_test_department": "SYNTH-STAGE",
                   "actions": ["supply.dispatch", "supply.receive", "quality.self_check",
                               "quality.independent.submit", "quality.independent.review"]},
    }
    identity = environment("identity", {
        "BSV_APP_ENV": "isolated", "BSV_AUTH_PROVIDER": "isolated",
        "BSV_DB_A_URL": f"postgresql+psycopg://{DB_USER}:{dbpw}@127.0.0.1:18764/{DB}",
        "BSV_DB_SSLMODE": "disable", "BSV_SESSION_SECRET": session, "BSV_PRIVACY_PEPPER": pepper,
        "BSV_COOKIE_SECURE": "0", "BSV_REGISTRATION_ENTITIES_JSON": '["DEMO_LEGAL"]',
        "BSV_LOCAL_ARCHIVE_DIR": str(DATA / "identity" / "archives"),
        "BSV_BACKUP_KEY_FILE": str(DATA / "identity" / "archive.key"),
        "BSV_DEMO_ADMIN_1_PASSWORD": reviewer1, "BSV_DEMO_ADMIN_2_PASSWORD": reviewer2,
        "BSV_SERVICE_TOKENS_JSON": json.dumps(token_map, separators=(",", ":")),
    })
    pos = environment("pos", {
        "BSV_MODE": "staging", "BSV_PORT": "18762", "BSV_PRIVATE_SSH_TUNNEL": "1",
        "BSV_DB_PATH": str(DATA / "pos" / "synthetic.sqlite3"),
        "BSV_V9_XLSX": str(DATA / "pos" / "synthetic-v9.xlsx"),
        "BSV_BACKUP_DIR": str(DATA / "pos" / "backups"),
        "BSV_POS_IDENTITY_REQUIRED": "1", "BSV_POS_IDENTITY_URL": "http://127.0.0.1:18761",
        "BSV_POS_IDENTITY_TOKEN": pos_token, "BSV_POS_INTERNAL_STAGE": "1",
        "BSV_POS_STORE_LEGAL_JSON": json.dumps(store_map, separators=(",", ":")),
    })
    environment("postgres", {"BSV_STAGE_COMPONENT_DATA": str(DATA / "postgres")})
    environment("ingress", {})
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


def build(sha):
    dest = ROOT / "releases" / sha
    if dest.is_symlink():
        raise RuntimeError("Release directory is a symlink")
    if (dest / ".built").is_file():
        return dest
    if dest.exists():
        if dest.is_symlink() or sha in (sha_at(ROOT / "current"), sha_at(ROOT / "previous")):
            raise RuntimeError("Incomplete release is active or has an unexpected path")
        dest.rename(dest.with_name(f".failed-{sha}-{secrets.token_hex(4)}"))
    dest.mkdir(mode=0o755)
    source = dest / "src"
    source.mkdir()
    with subprocess.Popen(git("archive", sha), stdout=subprocess.PIPE) as archive:
        run("tar", "-xf", "-", "-C", source, stdin=archive.stdout)
        if archive.wait() != 0:
            raise RuntimeError("git archive failed")
    for name in ("identity", "supply"):
        directory = dest / name
        run("/usr/bin/python3", "-m", "venv", directory)
        run(directory / "bin/python", "-m", "pip", "--disable-pip-version-check", "install",
            "--no-deps", "-r", source / f"services/api/{name}/requirements.lock")
        run(directory / "bin/python", "-m", "pip", "check")
    (dest / ".built").touch()
    return dest


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


def identity_tool(dest, identity, *args):
    source = dest / "src"
    env = {"PATH": str(PG) + ":/usr/bin:/bin", "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"}
    return as_user("identity", dest / "identity/bin/python", *args, env={**env, **identity}, cwd=source)


def bootstrap(dest, identity, pos, pin):
    source = dest / "src"
    identity_tool(dest, identity, "-m", "alembic", "-c",
                  source / "platform/lighthouse/identity/alembic.ini", "upgrade", "head")
    identity_tool(dest, identity, "-m", "services.api.identity.seed_isolated", "--i-understand-isolated")
    archive_key = DATA / "identity" / "archive.key"
    if not archive_key.exists():
        identity_tool(dest, identity, "-m", "services.api.identity.backup", "generate-key", "--path", archive_key)
    child = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"}
    as_user("pos", "/usr/bin/python3", source / TOOL / "seed_pos.py",
            env={**child, **pos, "BSV_STAGE_POS_PIN": pin}, cwd=source)


def backup():
    current = sha_at(ROOT / "current")
    if not current or not active("postgres"):
        raise RuntimeError("Start the managed private stage before backing it up")
    config = ROOT / "config" / "identity.env"
    if config.is_symlink() or config.stat().st_uid != 0 or config.stat().st_mode & 0o077:
        raise RuntimeError("Unsafe identity configuration")
    identity = {}
    for line in config.read_text().splitlines():
        key, value = line.split("=", 1)
        identity[key], = shlex.split(value)
    if not re.fullmatch(
        rf"postgresql\+psycopg://{DB_USER}:[A-Za-z0-9_-]+@127\.0\.0\.1:18764/{DB}",
        identity.get("BSV_DB_A_URL", ""),
    ):
        raise RuntimeError("Backup only allows the dedicated loopback PostgreSQL database")
    identity_tool(ROOT / "releases" / current, identity, "-m", "services.api.identity.backup", "create")


def http_check(path, expected):
    try:
        with OPENER.open(f"http://127.0.0.1:18760{path}", timeout=3) as response:
            return response.status == expected
    except urllib.error.HTTPError as error:
        return error.code == expected
    except (OSError, urllib.error.URLError):
        return False


def verify():
    for _ in range(35):
        if (all(active(name) for name in START_ORDER) and
                all(http_check(path, status) for path, status in (
                    ("/health/ready", 200), ("/api/health", 200), ("/staff", 200), ("/pos", 200),
                    ("/supply-ui/api/health", 200), ("/api/state", 401), ("/supply-ui/api/me", 401),
                    ("/api/v1/identity/pos-session", 404), ("/cocktail/", 200), ("/craft/", 404)))):
            print("VERIFY_OK: loopback routing, health and anonymous access checks", flush=True)
            return
        time.sleep(1)
    raise RuntimeError("Private stage HTTP checks failed; examine dedicated systemd journal")


def switch_services(start):
    names = START_ORDER if start else tuple(reversed(START_ORDER))
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
    if previous:
        link("current", previous)
        switch_services(True)
        verify()
    else:
        (ROOT / "current").unlink(missing_ok=True)
    marker.unlink()


def deploy(sha):
    recover_pending()
    preflight(sha)
    previous = sha_at(ROOT / "current")
    if previous and previous != sha:
        run("diff", "-qr", ROOT / "releases" / previous / "src/platform/lighthouse/identity/migrations",
            REPO / "platform/lighthouse/identity/migrations", stdout=subprocess.DEVNULL)
    identity, pos, dbpw, pin = prepare_config()
    dest = build(sha)
    if not UNIT_FILE.exists():
        UNIT_FILE.write_bytes((REPO / TOOL / UNIT_FILE.name).read_bytes())
    run("systemctl", "daemon-reload")
    if previous == sha and all(active(name) for name in START_ORDER):
        verify()
        return
    marker = ROOT / "activation.pending"
    write_secret(marker, previous or "")
    try:
        switch_services(False)
        link("current", sha)
        prepare_pg(dbpw)
        bootstrap(dest, identity, pos, pin)
        switch_services(True)
        verify()
        if previous and previous != sha:
            link("previous", previous)
    except (Exception, KeyboardInterrupt):
        recover_pending()
        raise
    marker.unlink()
    print(f"DEPLOYED_INTERNAL_STAGE {sha}", flush=True)


def rollback():
    if (ROOT / "activation.pending").exists():
        recover_pending()
        return
    current, previous = sha_at(ROOT / "current"), sha_at(ROOT / "previous")
    switch_services(False)
    if not current:
        return
    if not previous:
        (ROOT / "current").unlink()
        print("Stopped first release. Private databases and files preserved.")
        return
    try:
        link("current", previous)
        switch_services(True)
        verify()
    except (Exception, KeyboardInterrupt):
        switch_services(False)
        link("current", current)
        switch_services(True)
        raise
    link("previous", current)
    print(f"ROLLED_BACK {previous}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    for operation in ("preflight", "deploy", "verify", "rollback", "backup"):
        group.add_argument("--" + operation, action="store_const", dest="operation", const=operation)
    parser.add_argument("--sha")
    args = parser.parse_args()
    if args.operation in {"preflight", "deploy"} and not re.fullmatch(r"[a-f0-9]{40}", args.sha or ""):
        parser.error("A full approved --sha is required")
    if args.operation in {"deploy", "rollback", "backup"} and os.geteuid() != 0:
        parser.error("Use sudo for systemd changes")
    if args.operation == "preflight":
        preflight(args.sha)
    elif args.operation == "verify":
        verify()
    else:
        with locked():
            if args.operation == "deploy":
                deploy(args.sha)
            elif args.operation == "rollback":
                rollback()
            else:
                backup()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"Internal stage stopped: {error}")
