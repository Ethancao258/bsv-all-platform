"""Isolated V4 routes, reusing the existing identity sessions, grants and audit."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
from typing import Annotated, Literal
from uuid import UUID, NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from pydantic import Field, model_validator
from sqlalchemy import select

from domains.learning.academy_models import Attempt, Course, CourseVersion, Credential, Device, Enrollment, Practical, Shift
from domains.workforce.identity.core import DomainError, aware, has_action, log, person_for_subject
from domains.workforce.identity.models import LegacyAlias, Person, now
from . import api as identity
from .academy_policy import (
    BUSY_REASON, LEGAL, ROLE, active_employee, assets_for, available_stores, current_courses,
    iso, passing_attempt, practical_for, resources_available, schedule_reason, scoped_pos_action, shift_for_now,
    subject_for, training_reason,
)

academy_router = APIRouter(prefix="/api/v1/academy", tags=["Vincent Academy"])
Slug = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")]
Role = Literal["bartender"]
TextRef = Annotated[str, Field(min_length=3, max_length=160)]
OPEN_SHIFTS = ("pending", "approved", "confirmed")
MAX_ATTEMPTS = 5
QUALIFICATION_DAYS = 90


class Empty(identity.StrictModel):
    pass


class Question(identity.StrictModel):
    prompt: str = Field(min_length=1, max_length=300)
    options: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(min_length=2, max_length=6)
    correct_index: int = Field(ge=0, le=5, strict=True)

    @model_validator(mode="after")
    def reviewed_options(self):
        if self.correct_index >= len(self.options) or len(set(self.options)) != len(self.options):
            raise ValueError("Answer must identify one distinct, available option")
        return self


class Draft(identity.StrictModel):
    course_id: Slug
    version: int = Field(ge=1, le=10000, strict=True)
    title: str = Field(min_length=1, max_length=140)
    store_id: str | None = None
    role: Role
    passing_score: int = Field(ge=1, le=100, strict=True)
    questions: list[Question] = Field(min_length=1, max_length=30)
    rights_ref: TextRef
    practical_requirements: str = Field(default="", max_length=3500)


class Exam(identity.StrictModel):
    answers: list[Annotated[int, Field(ge=0, le=5, strict=True)]] = Field(min_length=1, max_length=30)
    request_id: UUID | None = None


class Review(identity.StrictModel):
    tr_code: str = Field(pattern=r"^TR[A-Z][0-9]{4}$")
    decision: Literal["verified", "rejected"]
    evidence_ref: TextRef
    reason: str = Field(min_length=3, max_length=500)


class Schedule(identity.StrictModel):
    tr_code: str = Field(pattern=r"^TR[A-Z][0-9]{4}$")
    store_id: str
    role: Role
    start: datetime
    end: datetime
    timezone: Literal["Asia/Shanghai"]
    request_id: UUID
    replaces_shift_id: UUID | None = None

    @model_validator(mode="after")
    def duration(self):
        if any(ts.tzinfo is None or ts.utcoffset() is None for ts in (self.start, self.end)):
            raise ValueError("Shift times must include an offset")
        if not timedelta(0) < self.end - self.start <= timedelta(hours=24):
            raise ValueError("Shift must have positive duration within twenty-four hours")
        return self


class Terminal(identity.StrictModel):
    device_id: Slug
    store_id: str


class TerminalCheck(Terminal):
    action: Literal["pos.order.read", "pos.order.create"]
    device_token: str = Field(min_length=32, max_length=120)


def error(code, status=403, text=None):
    raise DomainError(text or BUSY_REASON.get(code, "此操作未获准。"), status, code)


def isolated():
    if identity.settings.env != "isolated" or identity.settings.auth_provider != "isolated":
        error("ACADEMY_ISOLATED_ONLY", 404, "学院隔离演练演示未启用。")


def actor(db, request):
    isolated()
    session = identity.current_session(request, db, csrf=request.method not in {"GET", "HEAD"})
    person = person_for_subject(db, session.subject)
    return session.subject, person


def manager(db, request, action, store=None):
    subject, person = actor(db, request)
    if not person or not has_action(db, subject, action, store, LEGAL):
        error("FORBIDDEN", 403, "当前账号没有这项学院或门店管理权限。")
    return subject, person


def training_access(db, subject, person, store):
    return active_employee(db, person) and (store is None or (
        store in available_stores() and has_action(db, subject, "learning.course.read", store, LEGAL)
    ))


def course_and_version(db, course_id, version, *, lock=False):
    # The family lock serializes revision changes, publication and upload.
    course = db.scalar(select(Course).where(Course.course_id == course_id).with_for_update()) if lock else db.get(Course, course_id)
    target = db.get(CourseVersion, (course_id, version))
    if not course or course.legal_entity_id != LEGAL or not target:
        error("COURSE_NOT_FOUND", 404, "未找到这项课程。")
    return course, target


def course_for_learner(db, request, course_id, version):
    subject, person = actor(db, request)
    family, row = course_and_version(db, course_id, version, lock=True)
    if row.status != "published" or not training_access(db, subject, person, family.store_id):
        error("COURSE_ACCESS_DENIED", 403, "当前账号不能学习这项课程。请联系负责人。")
    if not resources_available(db, course_id, version):
        error("MEDIA_UNAVAILABLE", 503, "暂无法确认课件，请联系培训负责人。")
    return subject, person, family, row


def audited(db, action, person, subject, detail="", **facts):
    log(db, "academy." + action, person.tr_code if person else None, subject,
        detail or "Isolated Academy operation", legal_entity_id=LEGAL, **facts)


def public_course(db, family, row, person=None, *, admin=False):
    course = row.course_id
    version = row.version
    questions = row.questions if admin else [{k: q[k] for k in ("prompt", "options")} for q in row.questions]
    result = {"course_id": course, "version": version, "title": row.title, "store_id": family.store_id,
              "role": family.role, "status": row.status, "questions": questions, "passing_score": row.passing_score,
              "practical_requirements": row.practical_requirements, "media_available": resources_available(db, course, version),
              "media": [{"asset_id": m.asset_id, "filename": m.filename, "mime": m.mime,
                         "url": "/api/v1/academy/media/" + m.asset_id} for m in assets_for(db, course, version)]}
    if admin:
        result["rights_ref"] = row.rights_ref
        result["author_tr"] = row.author
    if person:
        enrollment = db.get(Enrollment, (person.tr_code, course, version))
        latest = db.scalar(select(Attempt).where(Attempt.tr_code == person.tr_code, Attempt.course_id == course,
                                                Attempt.version == version).order_by(Attempt.ordinal.desc()).limit(1))
        review = practical_for(db, person.tr_code, course, version)
        result.update(completed=bool(enrollment and enrollment.completed_at),
                      progress=("completed" if enrollment.completed_at else "in_progress") if enrollment else "not_started",
                      latest_attempt={"passed": latest.passed, "score": latest.score, "attempt_count": latest.ordinal}
                      if latest else None,
                      practical_status=review.decision if review else "not_started",
                      practical_reason=review.reason if review else None)
    return result


def public_shift(db, row):
    effective = row.status
    if row.status in OPEN_SHIFTS and aware(row.end_at) > now():
        if schedule_reason(db, db.get(Person, row.tr_code), row.store_id) != "OK":
            effective = "NEEDS_REASSIGNMENT"
    local = ZoneInfo(row.timezone)
    return {"shift_id": row.shift_id, "tr_code": row.tr_code, "store_id": row.store_id, "role": row.role,
            "start": iso(row.start_at), "end": iso(row.end_at),
            "local_start": aware(row.start_at).astimezone(local).isoformat(),
            "local_end": aware(row.end_at).astimezone(local).isoformat(), "timezone": row.timezone,
            "status": effective, "version": row.version, "replaces_shift_id": row.replaces_shift_id}


def public_device(row):
    return {"device_id": row.device_id, "store_id": row.store_id, "state": row.state,
            "registered_at": iso(row.registered_at)}


def academy_scope(db, subject):
    return {"training": has_action(db, subject, "qualification.attest", legal_entity_id=LEGAL),
            "publication": has_action(db, subject, "stage.issue", legal_entity_id=LEGAL),
            "devices": has_action(db, subject, "grant.approve", legal_entity_id=LEGAL),
            "scheduling_stores": [st for st in available_stores()
                                  if has_action(db, subject, "store.shift.write", st, LEGAL)]}


@academy_router.get("/work")
def work(request: Request):
    from .academy_media import media_ready
    isolated()
    with identity.router.session() as db:
        subject, person = actor(db, request)
        scopes = academy_scope(db, subject)
        courses = [public_course(db, family, row, person) for family, row in current_courses(db)
                   if training_access(db, subject, person, family.store_id)]
        shifts = [] if not person else [
            public_shift(db, row) for row in db.scalars(select(Shift).where(Shift.tr_code == person.tr_code)
                .order_by(Shift.start_at.desc()).limit(100))]
        stores = []
        clock = now()
        for store, name in available_stores().items():
            training = training_reason(db, person, store, clock)
            role_reason = schedule_reason(db, person, store, clock) if training == "OK" else training
            shift = shift_for_now(db, person.tr_code, store, clock) if role_reason == "OK" else None
            reason = role_reason
            if reason == "OK":
                reason = "SHIFT_INACTIVE" if shift is None else "SHIFT_UNCONFIRMED" if shift.status != "confirmed" else "OK"
            device_available = db.scalar(select(Device.device_id).where(
                Device.store_id == store, Device.legal_entity_id == LEGAL, Device.state == "registered",
            ).limit(1)) is not None
            if reason == "OK" and not device_available:
                reason = "DEVICE_UNVERIFIED"
            stores.append({"store_id": store, "name": name, "role": ROLE, "device_available": device_available,
                           "qualification": "eligible" if training == "OK" else "not_eligible",
                           "can_schedule": role_reason == "OK", "can_pos": reason == "OK",
                           "reason": reason, "next_step": BUSY_REASON[reason]})
        return {"courses": courses, "shifts": shifts, "stores": stores, "management": scopes,
                "can_manage": any(scopes.values()), "media_ready": media_ready(), "mode": "isolated"}


@academy_router.get("/admin")
def admin(request: Request):
    from .academy_media import media_ready
    isolated()
    with identity.router.session() as db:
        subject, _ = actor(db, request)
        scopes = academy_scope(db, subject)
        if not any(scopes.values()):
            error("FORBIDDEN")
        view_courses = scopes["training"] or scopes["publication"]
        courses = [public_course(db, family, row, admin=True)
                   for family, row in db.execute(select(Course, CourseVersion).join(CourseVersion)
                      .where(Course.legal_entity_id == LEGAL).order_by(Course.course_id, CourseVersion.version.desc()).limit(150))
                   ] if view_courses else []
        shifts = [public_shift(db, row) for row in db.scalars(select(Shift)
                  .where(Shift.store_id.in_(scopes["scheduling_stores"]), Shift.legal_entity_id == LEGAL)
                  .order_by(Shift.start_at.desc()).limit(100))]
        devices = [public_device(row) for row in db.scalars(select(Device).where(Device.legal_entity_id == LEGAL)
                   .order_by(Device.device_id).limit(100))] if scopes["devices"] else []
        return {"courses": courses, "shifts": shifts, "devices": devices, "media_ready": media_ready(),
                "management": scopes, "stores": list(available_stores())}


@academy_router.post("/courses", status_code=201)
def draft(body: Draft, request: Request):
    isolated()
    with identity.router.session(write=True) as db:
        subject, person = manager(db, request, "qualification.attest")
        if body.store_id is not None and body.store_id not in available_stores():
            error("STORE_UNAUTHORIZED")
        if body.store_id is not None and not body.practical_requirements.strip():
            error("PRACTICAL_PLAN_REQUIRED", 422, "请填写门店实操核验要求。")
        # An allocator lock is unnecessary here: the existing author person lock
        # serializes their duplicate requests and database uniqueness checks all authors.
        db.scalar(select(Person).where(Person.tr_code == person.tr_code).with_for_update())
        family = db.scalar(select(Course).where(Course.course_id == body.course_id).with_for_update())
        previous = db.get(CourseVersion, (body.course_id, body.version))
        values = dict(title=body.title, passing_score=body.passing_score, rights_ref=body.rights_ref,
                      questions=[q.model_dump() for q in body.questions],
                      practical_requirements=body.practical_requirements)
        if family and (family.legal_entity_id, family.store_id, family.role) != (LEGAL, body.store_id, body.role):
            error("COURSE_SCOPE_IMMUTABLE", 409, "请使用另一个经审核的课程编号。")
        if previous:
            if previous.author == person.tr_code and all(getattr(previous, key) == value for key, value in values.items()):
                return public_course(db, family, previous, admin=True)
            error("COURSE_VERSION_EXISTS", 409, "这版课程已存在。")
        last_version = db.scalar(select(CourseVersion.version).where(CourseVersion.course_id == body.course_id)
                                 .order_by(CourseVersion.version.desc()).limit(1)) or 0
        if body.version != last_version + 1:
            error("COURSE_VERSION_SEQUENCE", 409, "请使用课程的下一版本。")
        if family is None:
            family = Course(course_id=body.course_id, legal_entity_id=LEGAL, store_id=body.store_id, role=body.role)
            db.add(family)
            db.flush()
        row = CourseVersion(course_id=body.course_id, version=body.version, **values, author=person.tr_code)
        db.add(row)
        audited(db, "course.drafted", person, subject, course_id=body.course_id, version=body.version, store_id=body.store_id)
        db.flush()
        return public_course(db, family, row, admin=True)


@academy_router.post("/courses/{course_id}/{version}/publish")
def publish(course_id: Slug, version: int, body: Empty, request: Request):
    isolated()
    with identity.router.session(write=True) as db:
        subject, person = manager(db, request, "stage.issue")
        family, row = course_and_version(db, course_id, version, lock=True)
        if row.author == person.tr_code:
            error("SEPARATION_OF_DUTIES", 403, "请由另一位有权同事审批课程。")
        if row.status == "published" and row.publisher == person.tr_code:
            return public_course(db, family, row, admin=True)
        newer = db.scalar(select(CourseVersion.version).where(CourseVersion.course_id == course_id,
                     CourseVersion.version > version, CourseVersion.status != "draft").limit(1))
        if row.status != "draft" or newer:
            error("INVALID_TRANSITION", 409, "不能发布历史版本或已退出的课程。")
        if not resources_available(db, course_id, version):
            error("MEDIA_UNAVAILABLE", 503, "无法核验课件，暂未发布。")
        for previous in db.scalars(select(CourseVersion).where(CourseVersion.course_id == course_id,
                                                              CourseVersion.status == "published")):
            previous.status = "retired"
        row.status, row.publisher, row.published_at = "published", person.tr_code, now()
        audited(db, "course.published", person, subject, course_id=course_id, version=version, store_id=family.store_id)
        return public_course(db, family, row, admin=True)


@academy_router.post("/courses/{course_id}/{version}/retire")
def retire(course_id: Slug, version: int, body: Empty, request: Request):
    isolated()
    with identity.router.session(write=True) as db:
        subject, person = manager(db, request, "stage.issue")
        family, row = course_and_version(db, course_id, version, lock=True)
        if row.author == person.tr_code:
            error("SEPARATION_OF_DUTIES")
        if row.status == "retired":
            return public_course(db, family, row, admin=True)
        if row.status != "published":
            error("INVALID_TRANSITION", 409)
        row.status = "retired"
        audited(db, "course.retired", person, subject, course_id=course_id, version=version, store_id=family.store_id)
        return public_course(db, family, row, admin=True)


@academy_router.post("/courses/{course_id}/{version}/enroll")
def enroll(course_id: Slug, version: int, body: Empty, request: Request):
    isolated()
    with identity.router.session(write=True) as db:
        subject, person, family, row = course_for_learner(db, request, course_id, version)
        if db.get(Enrollment, (person.tr_code, course_id, version)) is None:
            db.add(Enrollment(tr_code=person.tr_code, course_id=course_id, version=version))
            audited(db, "enrolled", person, subject, course_id=course_id, version=version)
            db.flush()
        return public_course(db, family, row, person)


def enrollment_for(db, tr, course_id, version):
    enrolled = db.get(Enrollment, (tr, course_id, version), with_for_update=True)
    if not enrolled:
        error("ENROLLMENT_REQUIRED", 403, "请先开始学习这项课程。")
    return enrolled


@academy_router.post("/courses/{course_id}/{version}/complete")
def complete(course_id: Slug, version: int, body: Empty, request: Request):
    isolated()
    with identity.router.session(write=True) as db:
        subject, person, family, row = course_for_learner(db, request, course_id, version)
        enrolled = enrollment_for(db, person.tr_code, course_id, version)
        if enrolled.completed_at is None:
            enrolled.completed_at = now()
            audited(db, "materials.completed", person, subject, course_id=course_id, version=version)
        return public_course(db, family, row, person)


def score_response(row):
    return {"attempt_id": row.attempt_id, "score": row.score, "passed": row.passed, "attempt_count": row.ordinal}


@academy_router.post("/courses/{course_id}/{version}/exam")
def exam(course_id: Slug, version: int, body: Exam, request: Request):
    isolated()
    with identity.router.session(write=True) as db:
        subject, person, family, row = course_for_learner(db, request, course_id, version)
        enrolled = enrollment_for(db, person.tr_code, course_id, version)
        if not enrolled.completed_at:
            error("TRAINING_INCOMPLETE", 403, "请先完成课件学习，再参加测验。")
        if len(row.questions) != len(body.answers) or any(answer >= len(q["options"])
                for q, answer in zip(row.questions, body.answers)):
            error("ANSWER_COUNT_INVALID", 422, "请检查每道题是否均选择一个有效答案。")
        digest = hashlib.sha256(json.dumps(body.answers).encode()).hexdigest()
        request_id = str(body.request_id or uuid5(NAMESPACE_URL, f"{person.tr_code}:{course_id}:{version}:{digest}"))
        query = select(Attempt).where(Attempt.tr_code == person.tr_code, Attempt.course_id == course_id, Attempt.version == version)
        existing = db.scalar(query.where(Attempt.request_id == request_id))
        if existing:
            if existing.request_digest != digest:
                error("REQUEST_REUSED", 409, "提交编号已用于另一份答案。")
            return score_response(existing)
        passed = passing_attempt(db, person.tr_code, course_id, version)
        if passed:
            return score_response(passed)
        last = db.scalar(query.order_by(Attempt.ordinal.desc()).limit(1))
        ordinal = last.ordinal + 1 if last else 1
        if ordinal > MAX_ATTEMPTS:
            error("ATTEMPT_LIMIT", 403, "尝试次数已达上限，请联系培训负责人。")
        score = (sum(q["correct_index"] == answer for q, answer in zip(row.questions, body.answers)) * 100) // len(row.questions)
        attempt = Attempt(tr_code=person.tr_code, course_id=course_id, version=version, ordinal=ordinal,
                          score=score, passed=score >= row.passing_score, request_id=request_id, request_digest=digest)
        db.add(attempt)
        audited(db, "theory.graded", person, subject, course_id=course_id, version=version, ordinal=ordinal,
                request_id=request_id, score=score)
        db.flush()
        return score_response(attempt)


@academy_router.post("/courses/{course_id}/{version}/practical")
def practical(course_id: Slug, version: int, body: Review, request: Request):
    isolated()
    with identity.router.session(write=True) as db:
        subject, reviewer = manager(db, request, "qualification.attest")
        family, course = course_and_version(db, course_id, version, lock=True)
        if family.store_id not in available_stores() or course.status != "published":
            error("PRACTICAL_NOT_AVAILABLE", 409, "仅当前门店课程可以核验实操。")
        if reviewer.tr_code == body.tr_code:
            error("SEPARATION_OF_DUTIES", 403, "培训人员不能核验自己的实操。")
        person = db.get(Person, body.tr_code)
        if not training_access(db, subject_for(db, body.tr_code), person, family.store_id):
            error("TRAINING_SCOPE_DENIED", 403, "未确认该员工可参加本店课程。")
        enrollment_for(db, body.tr_code, course_id, version)
        attempt = passing_attempt(db, body.tr_code, course_id, version)
        if not attempt:
            error("EXAM_REQUIRED", 403, "请先通过理论考核，再核验实操。")
        if not resources_available(db, course_id, version):
            error("MEDIA_UNAVAILABLE", 503, "无法核验课程材料，暂不能签发资格。")
        existing = db.scalar(select(Practical).where(Practical.tr_code == body.tr_code, Practical.course_id == course_id,
                            Practical.version == version, Practical.evidence_ref == body.evidence_ref))
        if existing:
            if existing.reviewer != reviewer.tr_code or existing.decision != body.decision or existing.reason != body.reason:
                error("EVIDENCE_REUSED", 409, "该证据已用于另一项核验。")
            credential = db.scalar(select(Credential).where(Credential.review_id == existing.review_id))
            return {"status": existing.decision, "review_id": existing.review_id,
                    "credential_id": credential.credential_id if credential else None}
        previous = practical_for(db, body.tr_code, course_id, version)
        if previous:
            old = db.scalar(select(Credential).where(Credential.review_id == previous.review_id))
            if old and old.status == "eligible":
                old.status = "revoked"
        review = Practical(tr_code=body.tr_code, course_id=course_id, version=version, reviewer=reviewer.tr_code,
                           decision=body.decision, evidence_ref=body.evidence_ref, reason=body.reason, attempt_id=attempt.attempt_id)
        db.add(review)
        db.flush()
        credential = None
        if body.decision == "verified":
            credential = Credential(tr_code=body.tr_code, course_id=course_id, version=version,
                                    expires_at=now() + timedelta(days=QUALIFICATION_DAYS), review_id=review.review_id)
            db.add(credential)
            db.flush()
        audited(db, "practical.reviewed", person, subject, body.reason, course_id=course_id, version=version,
                store_id=family.store_id, review_id=review.review_id, decision=body.decision,
                credential_id=credential.credential_id if credential else None)
        return {"status": body.decision, "review_id": review.review_id,
                "credential_id": credential.credential_id if credential else None,
                "expires_at": iso(credential.expires_at) if credential else None}


@academy_router.post("/credentials/{credential_id}/revoke")
@academy_router.post("/credentials/{credential_id}/suspend")
def change_credential(credential_id: UUID, body: Empty, request: Request):
    isolated()
    state = "suspended" if request.url.path.endswith("/suspend") else "revoked"
    with identity.router.session(write=True) as db:
        subject, reviewer = manager(db, request, "qualification.attest")
        credential = db.get(Credential, str(credential_id), with_for_update=True)
        family = db.get(Course, credential.course_id) if credential else None
        if not family or family.legal_entity_id != LEGAL:
            error("CREDENTIAL_NOT_FOUND", 404)
        if reviewer.tr_code == credential.tr_code:
            error("SEPARATION_OF_DUTIES")
        if credential.status != state and credential.status == "eligible":
            credential.status = state
            audited(db, "credential." + state, db.get(Person, credential.tr_code), subject, credential_id=str(credential_id))
        return {"credential_id": str(credential_id), "status": credential.status}


@academy_router.get("/eligible")
def eligible(request: Request, store_id: str, role: Role):
    isolated()
    with identity.router.session() as db:
        if store_id not in available_stores():
            error("STORE_UNAUTHORIZED")
        manager(db, request, "store.shift.write", store_id)
        could = list(db.scalars(select(Person).where(Person.status == "active").order_by(Person.tr_code).limit(1000)))
        return {"people": [{"tr_code": person.tr_code} for person in could if schedule_reason(db, person, store_id) == "OK"]}


def lock_person(db, tr):
    return db.scalar(select(Person).where(Person.tr_code == tr).with_for_update())


def check_overlap(db, person, start, end, *, except_id=None):
    # All scheduling writes for a person take their authoritative row lock.
    existing = select(Shift.shift_id).where(Shift.tr_code == person.tr_code, Shift.start_at < end, Shift.end_at > start,
                                           Shift.status.in_(OPEN_SHIFTS))
    if except_id:
        existing = existing.where(Shift.shift_id != except_id)
    if db.scalar(existing.limit(1)):
        error("SHIFT_OVERLAP", 409, "这个时段已安排其他班次。请调整时间。")


def ensure_eligible(db, person, store, clock=None):
    reason = schedule_reason(db, person, store, clock)
    if reason != "OK":
        error(reason)


@academy_router.post("/shifts", status_code=201)
def schedule(body: Schedule, request: Request):
    isolated()
    with identity.router.session(write=True) as db:
        if body.store_id not in available_stores():
            error("STORE_UNAUTHORIZED")
        subject, creator = manager(db, request, "store.shift.write", body.store_id)
        if creator.tr_code == body.tr_code:
            error("SEPARATION_OF_DUTIES", 403, "请由另一位负责人为你创建班次。")
        person = lock_person(db, body.tr_code)
        if not person:
            error("PERSON_NOT_FOUND", 404)
        digest = hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        existing = db.scalar(select(Shift).where(Shift.request_id == str(body.request_id)))
        if existing:
            if existing.request_digest != digest or existing.creator != creator.tr_code:
                error("REQUEST_REUSED", 409, "此提交编号已用于另一个班次。")
            return public_shift(db, existing)
        ensure_eligible(db, person, body.store_id)
        if body.end <= now():
            error("SHIFT_TIME_ELAPSED", 409, "不能为已结束时段安排班次。")
        start = body.start.astimezone(timezone.utc)
        end = body.end.astimezone(timezone.utc)
        check_overlap(db, person, start, end)
        if body.replaces_shift_id:
            replaces = db.get(Shift, str(body.replaces_shift_id), with_for_update=True)
            if (not replaces or replaces.status not in {"approved", "confirmed"} or replaces.tr_code == body.tr_code
                    or replaces.store_id != body.store_id or replaces.legal_entity_id != LEGAL or replaces.role != body.role
                    or aware(replaces.start_at) != start or aware(replaces.end_at) != end
                    or db.scalar(select(Shift.shift_id).where(Shift.replaces_shift_id == str(body.replaces_shift_id),
                                                              Shift.status.in_(OPEN_SHIFTS)).limit(1))):
                error("REPLACEMENT_CONFLICT", 409, "替班必须对应同店同岗同时间且仍有效的班次。")
        row = Shift(tr_code=body.tr_code, legal_entity_id=LEGAL, store_id=body.store_id, role=body.role,
                    start_at=start, end_at=end, timezone=body.timezone, creator=creator.tr_code,
                    request_id=str(body.request_id), request_digest=digest,
                    replaces_shift_id=str(body.replaces_shift_id) if body.replaces_shift_id else None)
        db.add(row)
        db.flush()
        audited(db, "shift.requested", person, subject, shift_id=row.shift_id, request_id=row.request_id, store_id=row.store_id)
        return public_shift(db, row)


@academy_router.post("/shifts/{shift_id}/{operation}")
def shift_decision(shift_id: UUID, operation: Literal["approve", "confirm", "cancel"], body: Empty, request: Request):
    isolated()
    with identity.router.session(write=True) as db:
        actor_id, operator = actor(db, request)
        row = db.get(Shift, str(shift_id))
        if not row or row.legal_entity_id != LEGAL or row.store_id not in available_stores():
            error("SHIFT_NOT_FOUND", 404)
        person = lock_person(db, row.tr_code)
        db.refresh(row, with_for_update=True)
        if not operator:
            error("FORBIDDEN")
        if operation == "confirm":
            if operator.tr_code != row.tr_code:
                error("FORBIDDEN", 403, "只能确认分配给自己的班次。")
            ensure_eligible(db, person, row.store_id)
            acceptable = {"approved", "confirmed"}
            target = "confirmed"
        else:
            if not has_action(db, actor_id, "store.shift.write", row.store_id, LEGAL):
                error("FORBIDDEN")
            if operation == "approve":
                if operator.tr_code in {row.creator, row.tr_code}:
                    error("SEPARATION_OF_DUTIES", 403, "请由另一位具备门店权限的负责人审批。")
                ensure_eligible(db, person, row.store_id)
                acceptable = {"pending", "approved", "confirmed"}
                target = "approved"
            else:
                acceptable = set(OPEN_SHIFTS) | {"cancelled"}
                target = "cancelled"
        if row.status not in acceptable:
            error("INVALID_TRANSITION", 409, "该班次目前不能执行这项操作。")
        if row.status == target or (operation == "approve" and row.status == "confirmed"):
            return public_shift(db, row)
        if operation != "cancel":
            if aware(row.end_at) <= now():
                error("SHIFT_TIME_ELAPSED", 409, "班次已结束。")
            check_overlap(db, person, row.start_at, row.end_at, except_id=row.shift_id)
        if operation == "confirm" and row.replaces_shift_id:
            replaces = db.get(Shift, row.replaces_shift_id, with_for_update=True)
            if not replaces or replaces.status not in {"approved", "confirmed"}:
                error("REPLACEMENT_CONFLICT", 409, "原班次已变更，请联系负责人重新安排。")
            replaces.status, replaces.version = "replaced", replaces.version + 1
        if operation == "approve":
            row.approver = operator.tr_code
        if operation == "confirm":
            row.confirmed_at = now()
        row.status, row.version = target, row.version + 1
        audited(db, "shift." + target, person, actor_id, shift_id=row.shift_id, store_id=row.store_id)
        return public_shift(db, row)



def device_admin(db, request):
    subject, person = manager(db, request, "grant.approve")
    session = identity.current_session(request, db, csrf=True)
    if now() - aware(session.issued_at) > timedelta(minutes=15):
        error("REAUTH_REQUIRED", 401, "请重新登录管理员账号，再管理门店终端。")
    return subject, person


@academy_router.post("/devices", status_code=201)
def register_device(body: Terminal, request: Request):
    isolated()
    with identity.router.session(write=True) as db:
        subject, person = device_admin(db, request)
        if body.store_id not in available_stores():
            error("STORE_UNAUTHORIZED")
        if db.get(Device, body.device_id):
            error("DEVICE_ID_USED", 409, "设备编号已用过。已遗失或停用的设备须用新编号登记。")
        token = secrets.token_urlsafe(40)
        row = Device(device_id=body.device_id, legal_entity_id=LEGAL, store_id=body.store_id,
                     token_digest=hashlib.sha256(token.encode()).hexdigest(), registered_by=person.tr_code)
        db.add(row)
        audited(db, "device.registered", person, subject, device_id=body.device_id, store_id=body.store_id)
        db.flush()
        return {**public_device(row), "device_token": token}


@academy_router.post("/devices/{device_id}/revoke")
def revoke_device(device_id: Slug, body: Empty, request: Request):
    isolated()
    with identity.router.session(write=True) as db:
        subject, person = device_admin(db, request)
        row = db.get(Device, device_id, with_for_update=True)
        if not row or row.legal_entity_id != LEGAL:
            error("DEVICE_NOT_FOUND", 404)
        if row.state != "revoked":
            row.state, row.revoked_at = "revoked", now()
            audited(db, "device.revoked", person, subject, device_id=device_id, store_id=row.store_id)
        return public_device(row)


@academy_router.post("/pos-authorize")
def pos_authorize(body: TerminalCheck, request: Request):
    isolated()
    conf = identity.require_integration_service(request, "pos")

    def denied(reason):
        return {"allowed": False, "decision_source": "A", "reason": reason,
                "message": BUSY_REASON[reason], "store_id": body.store_id, "device_id": body.device_id}

    with identity.router.session() as db:
        session = identity.bearer_session(request, db)
        if (body.action not in conf.get("actions", []) or LEGAL not in conf.get("legal_entities", [])
                or body.store_id not in available_stores() or body.store_id not in conf.get("academy_stores", available_stores())):
            return denied("STORE_UNAUTHORIZED")
        device = db.get(Device, body.device_id)
        if (not device or device.legal_entity_id != LEGAL or device.store_id != body.store_id
                or device.state != "registered"
                or not hmac.compare_digest(device.token_digest, hashlib.sha256(body.device_token.encode()).hexdigest())):
            return denied("DEVICE_UNVERIFIED")
        person = person_for_subject(db, session.subject)
        clock = now()
        reason = training_reason(db, person, body.store_id, clock)
        if reason != "OK":
            return denied(reason)
        if not scoped_pos_action(db, session.subject, body.action, body.store_id, clock):
            return denied("POS_GRANT_REQUIRED")
        shift = shift_for_now(db, person.tr_code, body.store_id, clock)
        if shift is None or shift.status != "confirmed":
            return denied("SHIFT_UNCONFIRMED" if shift else "SHIFT_INACTIVE")
        aliases = list(db.scalars(select(LegacyAlias.legacy_value).where(
            LegacyAlias.legal_entity_id == LEGAL, LegacyAlias.source_system == "bsv1_pos",
            LegacyAlias.tr_code == person.tr_code).limit(2)))
        return {"allowed": True, "decision_source": "A", "reason": "OK", "tr_code": person.tr_code,
                "shift_id": shift.shift_id, "role": shift.role, "store_id": body.store_id, "device_id": body.device_id,
                "legacy_staff_id": aliases[0] if len(aliases) == 1 else None}


# Share the router, request guards and metadata with the private media handler.
from . import academy_media  # noqa: E402, F401
