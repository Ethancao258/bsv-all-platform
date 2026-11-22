"""Computed Academy eligibility and POS decisions against authoritative A."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import stat

from sqlalchemy import select

from domains.learning.academy_models import Attempt, Course, CourseVersion, Credential, Enrollment, Media, Practical, Shift
from domains.workforce.identity.core import active_engagement, aware, has_action, is_issued
from domains.workforce.identity.models import AuthLink, Person, now

LEGAL = "DEMO_LEGAL"
ROLE = "bartender"
STORES = frozenset({"BSVT", "BSVS"})
ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "services/api/bsv1/store_layouts/stores.json"
BUSY_REASON = {
    "ENGAGEMENT_INACTIVE": "请联系总部确认任职和员工身份。",
    "COMMON_TRAINING_REQUIRED": "请先完成学院通用课程和理论考核。",
    "STORE_TRAINING_REQUIRED": "请完成这家店当前版本的课程与理论考核。",
    "PRACTICAL_REQUIRED": "请联系这家店的培训负责人核验实操。",
    "CREDENTIAL_INACTIVE": "门店资格已失效或需复训，请联系培训负责人。",
    "POS_GRANT_REQUIRED": "请联系总部为这家店申请岗位授权。",
    "SHIFT_UNCONFIRMED": "请在待办内确认已批准的班次。",
    "SHIFT_INACTIVE": "当前没有正在进行的已确认班次。",
    "DEVICE_UNVERIFIED": "请联系门店负责人核验或重新注册终端。",
    "STORE_UNAUTHORIZED": "这家店尚未开放内部演练。",
    "OK": "可使用已注册的本店终端。",
}


def available_stores():
    """Return only registered, laid-out stores explicitly enabled for Academy.

    The legacy H stage retains its BSVS/BSVT default. Other stores (including
    BSVM) require an explicit scope and their own POS/legal authorization; this
    setting alone must never grant POS permissions.
    """
    records = json.loads(REGISTRY.read_text(encoding="utf-8"))
    configured = os.environ.get("BSV_ACADEMY_STORE_IDS")
    if configured is None:
        allowed = STORES
    else:
        codes = configured.split(",")
        if (any(not code or code != code.strip() or not code.isalnum()
                or not code.isupper() for code in codes)
                or len(codes) != len(set(codes))):
            return {}  # Invalid deployment scope must fail closed.
        allowed = frozenset(codes)
    registered_ids = [row["store_id"] for row in records]
    if len(registered_ids) != len(set(registered_ids)):
        return {}  # An ambiguous company registry must never authorize a store.
    ready = {row["store_id"]: row["name"] for row in records
             if row.get("layout_file") and row["store_id"] in allowed}
    return ready if set(ready) == allowed else {}


def media_path(asset):
    root = os.environ.get("BSV_ACADEMY_MEDIA_ROOT", "")
    if not root or not Path(root).is_absolute():
        return None
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
        return None
    path = root / (asset.asset_id + ".bin")
    try:
        if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size != asset.size:
            return None
        with path.open("rb") as data:
            return path if hashlib.file_digest(data, "sha256").hexdigest() == asset.digest else None
    except OSError:
        return None


def assets_for(db, course_id, version):
    return list(db.scalars(select(Media).where(Media.course_id == course_id, Media.version == version)))


def resources_available(db, course_id, version):
    return all(media_path(asset) is not None for asset in assets_for(db, course_id, version))


def active_employee(db, person, clock=None):
    return bool(person and person.status == "active" and is_issued(db, person.tr_code, "EMP")
                and active_engagement(db, person.tr_code, LEGAL, clock))


def current_courses(db):
    rows = db.execute(select(Course, CourseVersion).join(CourseVersion).where(
        Course.legal_entity_id == LEGAL, CourseVersion.status == "published",
    ).order_by(Course.course_id, CourseVersion.version.desc()))
    result = {}
    for course, revision in rows:
        result.setdefault(course.course_id, (course, revision))
    return list(result.values())


def passing_attempt(db, tr, course_id, version):
    return db.scalar(select(Attempt).where(Attempt.tr_code == tr, Attempt.course_id == course_id,
                                           Attempt.version == version, Attempt.passed.is_(True))
                     .order_by(Attempt.ordinal.desc()).limit(1))


def practical_for(db, tr, course_id, version):
    return db.scalar(select(Practical).where(Practical.tr_code == tr, Practical.course_id == course_id,
                                             Practical.version == version)
                     .order_by(Practical.reviewed_at.desc(), Practical.review_id.desc()).limit(1))


def training_reason(db, person, store_id, clock=None):
    clock = clock or now()
    if store_id not in available_stores():
        return "STORE_UNAUTHORIZED"
    if not active_employee(db, person, clock):
        return "ENGAGEMENT_INACTIVE"
    tr = person.tr_code
    courses = current_courses(db)
    common = [rev for row, rev in courses if row.store_id is None and row.role == ROLE]
    local = [rev for row, rev in courses if row.store_id == store_id and row.role == ROLE]
    if not common or any(r.status != "published" or not resources_available(db, r.course_id, r.version)
                         or not passing_attempt(db, tr, r.course_id, r.version) for r in common):
        return "COMMON_TRAINING_REQUIRED"
    if not local or any(r.status != "published" or not resources_available(db, r.course_id, r.version)
                        or not passing_attempt(db, tr, r.course_id, r.version) for r in local):
        return "STORE_TRAINING_REQUIRED"
    for rev in local:
        practical = practical_for(db, tr, rev.course_id, rev.version)
        if not practical or practical.decision != "verified":
            return "PRACTICAL_REQUIRED"
        credential = db.scalar(select(Credential).where(Credential.review_id == practical.review_id))
        if not credential or credential.status != "eligible" or aware(credential.expires_at) <= clock:
            return "CREDENTIAL_INACTIVE"
    return "OK"


def subject_for(db, tr):
    links = list(db.scalars(select(AuthLink.auth_subject_id).where(AuthLink.tr_code == tr, AuthLink.revoked_at.is_(None)).limit(2)))
    return links[0] if len(links) == 1 else None


def scoped_pos_action(db, subject, action, store_id, clock=None):
    return bool(subject and has_action(db, subject, action, store_id, LEGAL, clock, academy_pos=True))


def schedule_reason(db, person, store_id, clock=None):
    reason = training_reason(db, person, store_id, clock)
    if reason == "OK":
        subject = subject_for(db, person.tr_code)
        if not all(scoped_pos_action(db, subject, action, store_id, clock)
                   for action in ("pos.order.read", "pos.order.create")):
            return "POS_GRANT_REQUIRED"
    return reason


def shift_for_now(db, tr, store_id, clock):
    return db.scalar(select(Shift).where(
        Shift.tr_code == tr, Shift.store_id == store_id, Shift.legal_entity_id == LEGAL, Shift.role == ROLE,
        Shift.status.in_(("approved", "confirmed")), Shift.start_at <= clock, Shift.end_at > clock,
    ).order_by(Shift.start_at))


def iso(value: datetime):
    return aware(value).isoformat()
