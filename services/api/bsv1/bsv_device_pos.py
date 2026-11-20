"""Local V4 POS bindings. Academy is the sole authority for devices and working scope."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from threading import Lock
import time


SESSION_COOKIE = "bsv_pos_v4_session"
DEVICE_COOKIE = "bsv_pos_device"
DEVICE_COOKIE_SECONDS = 24 * 3600
DEVICE_SESSION_SECONDS = 20 * 60
DEVICE_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
DEVICE_TOKEN = re.compile(r"[A-Za-z0-9_-]{24,200}")
FAIL_REASONS = {
    "AUTH_REQUIRED": ("请先在员工中心登录，再返回门店点单。", 401),
    "ENGAGEMENT_INACTIVE": ("任职尚未生效。请联系负责人核对任职状态。", 403),
    "COMMON_TRAINING_REQUIRED": ("请先在文森特学院完成基础培训与测验。", 403),
    "STORE_TRAINING_REQUIRED": ("请先完成这家门店当前版本的岗位课程。", 403),
    "PRACTICAL_REQUIRED": ("本店实操尚未通过。请预约培训官核验。", 403),
    "CREDENTIAL_INACTIVE": ("本店资格尚未生效或已失效。请核对复训和资格状态。", 403),
    "POS_GRANT_REQUIRED": ("当前账号没有本店点单权限。请向负责人申请。", 403),
    "SHIFT_UNCONFIRMED": ("班次尚未确认。请在工作台核对并确认班次。", 403),
    "SHIFT_INACTIVE": ("当前不在本店已确认的班次内。请核对今天的排班。", 403),
    "DEVICE_UNVERIFIED": ("此终端未在本店通过核验。请联系负责人检查设备。", 403),
    "STORE_UNAUTHORIZED": ("这家门店暂未开放。请在工作台核对可用门店。", 403),
    "IDENTITY_UNAVAILABLE": ("暂时无法核验权限。请检查连接后重新进入点单台。", 503),
    "POS_SESSION_CHANGED": ("工作身份、班次或终端已变化。请重新核验门店。", 403),
}
_attempts = {}
_attempts_lock = Lock()


def schema(db):
    """Additive tables keep the V3 SQLite reader and user_version compatible."""
    db.executescript("""
      CREATE TABLE IF NOT EXISTS bsv_pos_tr_projection (
        tr_code TEXT PRIMARY KEY, staff_id TEXT NOT NULL UNIQUE REFERENCES staff(id)
      );
      CREATE TABLE IF NOT EXISTS bsv_pos_device_sessions (
        session_digest TEXT PRIMARY KEY REFERENCES sessions(token_digest) ON DELETE CASCADE,
        identity_digest TEXT NOT NULL, tr_code TEXT NOT NULL REFERENCES bsv_pos_tr_projection(tr_code),
        device_id TEXT NOT NULL, device_digest TEXT NOT NULL, shift_id TEXT NOT NULL, role TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS ix_pos_device_session_device ON bsv_pos_device_sessions(device_id);
      CREATE TABLE IF NOT EXISTS bsv_pos_device_commands (
        action_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, scope_digest TEXT NOT NULL,
        response_json TEXT NOT NULL, created_at TEXT NOT NULL
      );
    """)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def credentials(device_id, device_token):
    if (isinstance(device_id, str) and isinstance(device_token, str)
            and DEVICE_ID.fullmatch(device_id) and DEVICE_TOKEN.fullmatch(device_token)):
        return device_id, device_token
    return None


def parse_device_cookie(value):
    return credentials(*value.split(".", 1)) if value and "." in value else None


def login_allowed(device_id, identity_session):
    """Bound attempts per device and per authenticated browser without retaining tokens."""
    keys = ("device:" + device_id, "browser:" + digest(identity_session))
    now = time.monotonic()
    with _attempts_lock:
        for key, (expires, _) in tuple(_attempts.items()):
            if expires <= now:
                del _attempts[key]
        if len(_attempts) >= 4096 and any(key not in _attempts for key in keys):
            return False
        values = [_attempts.get(key, (now + 600, 0)) for key in keys]
        if any(count >= limit for (_, count), limit in zip(values, (24, 8))):
            return False
        for key, (expires, count) in zip(keys, values):
            _attempts[key] = (expires, count + 1)
    return True


def bind_actor(db, authority, store_id):
    """Project the authoritative TR solely to carry existing SQLite staff foreign keys."""
    tr = authority["tr_code"]
    found = db.execute("SELECT staff_id FROM bsv_pos_tr_projection WHERE tr_code=?", (tr,)).fetchone()
    if found:
        staff_id = found["staff_id"]
    else:
        alias = authority.get("legacy_staff_id")
        legacy = db.execute("SELECT id FROM staff WHERE id=?", (alias,)).fetchone() if isinstance(alias, str) else None
        staff_id = legacy["id"] if legacy else tr
        if not legacy:
            # Generated verifier has no known PIN. This row never provides authentication.
            db.execute("""INSERT INTO staff(id,staff_code,pin_salt,pin_digest,role)
                VALUES (?,?,?,?,'STAFF')""", (staff_id, tr, secrets.token_hex(16), secrets.token_hex(32)))
        db.execute("INSERT INTO bsv_pos_tr_projection(tr_code,staff_id) VALUES (?,?)", (tr, staff_id))
    staff = db.execute("SELECT * FROM staff WHERE id=? AND enabled=1", (staff_id,)).fetchone()
    if not staff:
        return None
    db.execute("INSERT OR IGNORE INTO staff_store_access(staff_id,store_id) VALUES (?,?)", (staff_id, store_id))
    return dict(staff)


def scope_from(authority):
    return {key: authority[key] for key in ("tr_code", "device_id", "shift_id", "role", "store_id")}


def remember(db, token_digest, identity_session, device_token, scope):
    db.execute("""INSERT INTO bsv_pos_device_sessions
                  (session_digest,identity_digest,tr_code,device_id,device_digest,shift_id,role)
                  VALUES (?,?,?,?,?,?,?)""",
               (token_digest, digest(identity_session), scope["tr_code"], scope["device_id"],
                digest(device_token), scope["shift_id"], scope["role"]))


def same_binding(row, identity_session, device):
    return bool(row and identity_session and device and row["device_id"] == device[0]
                and hmac.compare_digest(row["identity_digest"], digest(identity_session))
                and hmac.compare_digest(row["device_digest"], digest(device[1])))


def same_authority(row, authority):
    return all(row[key] == authority[key] for key in ("tr_code", "device_id", "shift_id", "role"))


def scope_digest(scope):
    return digest(json.dumps(scope, ensure_ascii=False, sort_keys=True))


def fingerprint(path, data, scope):
    body = {key: value for key, value in data.items() if key != "_action_id"}
    return digest(json.dumps({"path": path, "body": body, "scope": scope}, ensure_ascii=False, sort_keys=True))
