"""BSV ALL identity API and responsive web. Scope checks always run server-side."""
import hmac
import os
from pathlib import Path
from datetime import datetime
from typing import Literal
from fastapi import FastAPI, Request, Query
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from .config import load_settings
from domains.workforce.identity.core import SUPPLY_ROLE_ACTIONS
from .database import SourceRouter
from domains.workforce.identity.models import (now, CodeAllocator, Person, Registration, StageIssuance, AuthLink,
                     AuthSession, Engagement, Qualification, StageRequest, Grant,
                     ManagementAppointment, AuditEvent, LegacyAlias, AuthRecoveryRequest, IsolatedUser, PrivacyRequest)
from domains.workforce.identity.core import (DomainError, CAPACITY, stage_code, register, verify_registration,
                   approve_registration, person_for_subject, is_issued,
                   active_engagement, active_bm, active_qualification, has_action, require,
                   make_engagement, approve_engagement, end_engagement, attest_qualification,
                   request_stage, issue_stage, revoke_bm, request_grant, approve_grant,
                   revoke_grant, suspend_person, restore_person, redact_person,
                   legacy_preview, log, request_account_rebind, approve_account_rebind,
                   request_redaction, approve_redaction, require_exclusive_legal_scope)
from domains.identity_access.identity.security import (Throttle, create_session, validate_session, verify_csrf,
                       create_isolated_user, login_isolated, validate_external_token)

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps/staff-center/identity"
HQ = REPO / "apps/hq-console/identity"
SESSION_COOKIE = "bsv_identity_session"
settings = load_settings()
router = SourceRouter(settings)
throttle = Throttle()
app = FastAPI(title="BSV ALL | TR permanent identity service", version="2.0.2",
              docs_url="/api/docs" if settings.env != "production" else None,
              openapi_url="/openapi.json" if settings.env != "production" else None,
              redoc_url=None)
@app.get("/hq-assets/hq.js", include_in_schema=False)
def hq_script():
    return FileResponse(HQ / "hq.js", media_type="text/javascript")

app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")
if settings.env == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[settings.allowed_host])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(StrictModel):
    username: str
    password: str


class NoticeRegistration(StrictModel):
    legal_entity_id: str = Field(min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=80)
    display_label: str = Field(min_length=1, max_length=80)
    proof_hint: str | None = Field(default=None, max_length=80,
                                   description="Only HMAC digest saved; not a government ID")
    consent_version: str = "2026-11-18"


class Decision(StrictModel):
    reason: str = Field(min_length=8, max_length=500)
    legal_entity_id: str = Field(min_length=2, max_length=80)
    separate_person_confirmed: bool = False


class EngagementInput(StrictModel):
    tr_code: str
    legal_entity_id: str = Field(min_length=2, max_length=80)
    type: Literal["employee", "part_time", "contractor", "partner"]
    effective_from: datetime
    effective_to: datetime | None = None
    evidence_ref: str = Field(min_length=6, max_length=160)


class QualificationInput(StrictModel):
    tr_code: str
    legal_entity_id: str = Field(min_length=2, max_length=80)
    qualification_code: str
    learning_credential_id: str
    source_evidence_ref: str
    effective_from: datetime
    effective_to: datetime | None = None


class StageInput(StrictModel):
    legal_entity_id: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=8, max_length=500)


class StageIssueInput(StageInput):
    request_id: str


class GrantInput(StrictModel):
    tr_code: str
    legal_entity_id: str = Field(min_length=2, max_length=80)
    store_id: str | None = None
    role: Literal["staff", "manager", "hq"]
    action: str
    required_qualification: str | None = None
    valid_from: datetime
    valid_to: datetime | None = None
    reason: str = Field(min_length=8, max_length=500)


class AuthorizeInput(StrictModel):
    auth_subject_id: str
    legal_entity_id: str
    store_id: str | None = None
    action: str


class LegacyRow(StrictModel):
    source_system: str
    legacy_value: str
    tr_code: str


class LegacyPreview(StrictModel):
    legal_entity_id: str
    rows: list[LegacyRow] = Field(max_length=500)


class RedactInput(StrictModel):
    tr_code: str
    legal_entity_id: str = Field(min_length=2,max_length=80)
    reason: str = Field(min_length=8,max_length=500)
    evidence_ref: str = Field(min_length=8,max_length=160)


class RecoveryInput(StrictModel):
    tr_code: str
    legal_entity_id: str = Field(min_length=2, max_length=80)
    new_auth_subject_id: str | None = None
    external_identity_token: str | None = None
    evidence_ref: str = Field(min_length=8, max_length=160)


class LegacyCommit(LegacyPreview):
    reason: str = Field(min_length=8, max_length=500)
    evidence_ref: str = Field(min_length=6, max_length=160)


@app.exception_handler(DomainError)
def domain_error(request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(SQLAlchemyError)
def db_error(request: Request, exc: SQLAlchemyError):
    # No internals or personal values in API responses. Logging in deployed environment must redact DB params.
    return JSONResponse(status_code=503, content={"error": {"code": "DB_UNAVAILABLE", "message": "Authoritative source A unavailable; denied"}})


@app.middleware("http")
async def secure_headers(request: Request, call_next):
    # Block cross-site state-changing browser requests, including login CSRF.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin:
            own_origin = f"{request.url.scheme}://{request.url.netloc}"
            if origin != own_origin and origin not in settings.allowed_origins:
                return JSONResponse(status_code=403, content={"error":{"code":"BAD_ORIGIN","message":"Origin rejected"}})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    if settings.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def current_session(request, db, csrf=False):
    sess = validate_session(db, request.cookies.get(SESSION_COOKIE, ""))
    if csrf:
        verify_csrf(sess, request.headers.get("X-CSRF-Token", ""))
    return sess


def grant_guard(request, db, action, legal_entity_id, store_id=None):
    sess = current_session(request, db, csrf=request.method not in {"GET", "HEAD"})
    require(db, sess.subject, action, legal_entity_id, store_id)
    return sess.subject


def response_session(subject, db, request):
    token, csrf = create_session(db, subject)
    out = JSONResponse({"authenticated": True, "subject_provider": subject.split(":")[0]})
    out.set_cookie(SESSION_COOKIE, token, httponly=True, secure=settings.cookie_secure,
                   samesite="lax", max_age=8*3600, path="/")
    out.set_cookie("bsv_csrf", csrf, httponly=False, secure=settings.cookie_secure,
                   samesite="lax", max_age=8*3600, path="/")
    return out


@app.get("/")
def root():
    return FileResponse(WEB / "index.html")


@app.get("/staff")
def staff():
    return FileResponse(WEB / "staff.html")


@app.get("/hq")
def headquarters():
    return FileResponse(HQ / "hq.html")


@app.get("/health/live")
def live():
    return {"status": "alive", "version": app.version}


@app.get("/health/ready")
def ready():
    try:
        with router.session() as db:
            allocator = db.get(CodeAllocator, 1)
            if not allocator:
                raise RuntimeError("Allocator not initialized")
            return {"status": "ready", "database": "A", "mode": settings.env}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "A"})


@app.post("/api/v1/auth/isolated/signup", status_code=201)
def isolated_signup(body: Credentials, request: Request):
    if settings.auth_provider != "isolated" or settings.env != "isolated":
        raise DomainError("Test signup disabled", 404, "DISABLED")
    throttle.check("signup:" + (request.client.host if request.client else "unknown"), 15, 60)
    with router.session(write=True) as db:
        user = create_isolated_user(db, body.username, body.password)
        out = response_session(user.subject, db, request)
        out.status_code = 201
        return out


@app.post("/api/v1/auth/isolated/login")
def isolated_login(body: Credentials, request: Request):
    if settings.auth_provider != "isolated" or settings.env == "production":
        raise DomainError("Isolated login disabled", 404, "DISABLED")
    throttle.check("login:" + (request.client.host if request.client else "unknown"), 15, 60)
    with router.session(write=True) as db:
        subject = login_isolated(db, body.username, body.password)
        return response_session(subject, db, request)


@app.post("/api/v1/auth/cloudbase/token-session")
def cloudbase_session(body: dict, request: Request):
    if settings.auth_provider != "cloudbase_jwks":
        raise DomainError("CloudBase adapter not configured", 404, "DISABLED")
    token = body.get("id_token", "")
    if not isinstance(token, str) or len(token) > 8192:
        raise DomainError("Invalid external token", 401, "INVALID_EXTERNAL_TOKEN")
    subject = validate_external_token(token, settings)
    with router.session(write=True) as db:
        # Unlinked authenticated subject may apply for TR; cannot gain business authorization.
        return response_session(subject, db, request)


@app.get("/api/v1/auth/session")
def session_status(request: Request):
    with router.session() as db:
        sess = current_session(request, db)
        person = person_for_subject(db, sess.subject)
        return {"authenticated": True, "linked": bool(person), "tr_code": person.tr_code if person else None,
                "app_env": settings.env}


@app.post("/api/v1/auth/logout")
def logout(request: Request):
    with router.session(write=True) as db:
        sess = current_session(request, db, csrf=True)
        sess.revoked_at = now()
        out = JSONResponse({"signed_out": True})
        out.delete_cookie(SESSION_COOKIE, path="/")
        out.delete_cookie("bsv_csrf", path="/")
        return out


@app.get("/api/v1/identity/public-config")
def public_config():
    return {"registration_entities": settings.registration_entities, "privacy_notice_version": "2026-11-18",
            "environment": settings.env}


@app.post("/api/v1/identity/registrations", status_code=202)
def submit_registration(body: NoticeRegistration, request: Request):
    throttle.check("register:" + (request.client.host if request.client else "unknown"), 25, 60)
    with router.session(write=True) as db:
        sess = current_session(request, db, csrf=True)
        if body.legal_entity_id not in settings.registration_entities:
            raise DomainError("Unsupported registration entity", 422, "ENTITY_NOT_AVAILABLE")
        row = register(db, sess.subject, body.idempotency_key, body.display_label,
                       body.proof_hint, settings.privacy_pepper, body.legal_entity_id,
                       body.consent_version)
        return {"registration_id": row.id, "status": row.status,
                "tr_code": row.approved_tr_code if row.status == "approved" else None}


@app.post("/api/v1/identity/registrations/{request_id}/verify")
def verify_register(request_id: str, body: Decision, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "people.verify", body.legal_entity_id)
        req = db.get(Registration,request_id)
        if not req or req.requested_legal_entity_id != body.legal_entity_id:
            raise DomainError("Registration not in legal entity scope", 404, "NOT_FOUND")
        obj = verify_registration(db, request_id, actor, body.reason, body.separate_person_confirmed)
        return {"registration_id": obj.id, "status": obj.status}


@app.post("/api/v1/identity/registrations/{request_id}/approve")
def approve_register(request_id: str, body: Decision, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "people.approve", body.legal_entity_id)
        req = db.get(Registration,request_id)
        if not req or req.requested_legal_entity_id != body.legal_entity_id:
            raise DomainError("Registration not in legal entity scope", 404, "NOT_FOUND")
        person = approve_registration(db, request_id, actor, body.reason)
        return {"tr_code": person.tr_code, "stage": "TR", "status": "approved"}


@app.get("/api/v1/identity/me")
def me(request: Request):
    with router.session() as db:
        sess = current_session(request, db)
        person = person_for_subject(db, sess.subject)
        if not person:
            req = db.scalar(select(Registration).where(Registration.subject == sess.subject)
                            .order_by(Registration.created_at.desc()))
            return {"tr_code": None, "registration_status": req.status if req else "not_started",
                    "emp_code": None, "bm_code": None, "active": False,
                    "engagements": [], "grants": [], "qualifications": []}
        tr = person.tr_code
        engagements = list(db.scalars(select(Engagement).where(Engagement.tr_code == tr)))
        active_legal = sorted({e.legal_entity_id for e in engagements if active_engagement(db, tr, e.legal_entity_id)})
        active_grants = [g for g in db.scalars(select(Grant).where(Grant.tr_code == tr, Grant.status == "active"))
                         if has_action(db, sess.subject, g.action, g.store_id, g.legal_entity_id)]
        credentials = [q for q in db.scalars(select(Qualification).where(Qualification.tr_code == tr))
                       if active_qualification(db, tr, q.qualification_code)]
        return {"tr_code": tr, "display_label": person.display_label, "person_status": person.status,
                "emp_code": stage_code(tr, "EMP") if is_issued(db, tr, "EMP") else None,
                "bm_code": stage_code(tr, "BM") if is_issued(db, tr, "BM") else None,
                "bm_active_entities": [e for e in active_legal if active_bm(db, tr, e)],
                "active": person.status == "active", "active_legal_entities": active_legal,
                "engagements": [{"id": x.id, "legal_entity_id": x.legal_entity_id,
                                 "type": x.type, "status": x.status} for x in engagements],
                "grants": [{"store_id": g.store_id, "legal_entity_id": g.legal_entity_id,
                            "role": g.role, "action": g.action} for g in active_grants],
                "qualifications": [{"code": q.qualification_code, "credential_id": q.learning_credential_id}
                                   for q in credentials],
                "public_learning_url": "/staff#learning"}


@app.get("/api/v1/identity/admin/people")
def search_people(request: Request, legal_entity_id: str, q: str = Query(default="", max_length=80)):
    with router.session() as db:
        actor = grant_guard(request, db, "hq.people.read", legal_entity_id)
        query = select(Person).order_by(Person.created_at.desc()).limit(100)
        if q.strip():
            term = q.strip()
            query = select(Person).where((Person.tr_code == term) | (Person.display_label.contains(term)))\
                                  .order_by(Person.created_at.desc()).limit(50)
        results = list(db.scalars(query))
        # Scope: only people engaged with the requested legal entity, except pending request queue.
        scoped = [p for p in results if db.scalar(select(Engagement.id).where(
            Engagement.tr_code == p.tr_code, Engagement.legal_entity_id == legal_entity_id))]
        return {"people": [{"tr_code": p.tr_code, "display_label": p.display_label,
                            "status": p.status} for p in scoped]}


@app.get("/api/v1/identity/admin/queue")
def admin_queue(request: Request, legal_entity_id: str):
    with router.session() as db:
        grant_guard(request, db, "hq.people.read", legal_entity_id)
        regs = list(db.scalars(select(Registration).where(
            Registration.requested_legal_entity_id == legal_entity_id,
            Registration.status.in_(["pending", "needs_review", "verified"])).order_by(
            Registration.created_at.asc()).limit(100)))
        stages = list(db.scalars(select(StageRequest).where(
            StageRequest.legal_entity_id == legal_entity_id,
            StageRequest.status == "pending").limit(100)))
        grants = list(db.scalars(select(Grant).where(
            Grant.legal_entity_id == legal_entity_id, Grant.status == "pending").limit(100)))
        eng = list(db.scalars(select(Engagement).where(
            Engagement.legal_entity_id == legal_entity_id, Engagement.status == "pending").limit(100)))
        return {"registrations": [{"id": r.id, "display_label": r.display_label,
                                  "status": r.status, "suspected_duplicate": r.status == "needs_review"} for r in regs],
                "stages": [{"id": s.id, "tr_code": s.tr_code, "stage": s.stage,
                            "legal_entity_id": s.legal_entity_id} for s in stages],
                "grants": [{"id": g.id, "tr_code": g.tr_code, "action": g.action,
                            "store_id": g.store_id} for g in grants],
                "engagements": [{"id": e.id, "tr_code": e.tr_code, "type": e.type} for e in eng]}


@app.get("/api/v1/identity/allocator")
def allocator_status(request: Request, legal_entity_id: str):
    with router.session() as db:
        grant_guard(request, db, "audit.read", legal_entity_id)
        a = db.get(CodeAllocator, 1)
        remaining = CAPACITY - a.next_index
        return {"allocated": a.next_index, "capacity": CAPACITY, "remaining": remaining,
                "warning": remaining <= settings.allocator_warning_remaining}


@app.post("/api/v1/identity/engagements", status_code=201)
def create_engagement(body: EngagementInput, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "engagement.manage", body.legal_entity_id)
        row = make_engagement(db, body.tr_code, body.legal_entity_id, body.type,
                              body.effective_from, body.effective_to, body.evidence_ref, actor)
        return {"id": row.id, "status": row.status}


@app.post("/api/v1/identity/engagements/{engagement_id}/approve")
def approve_eng(engagement_id: str, body: Decision, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "engagement.manage", body.legal_entity_id)
        obj = db.get(Engagement, engagement_id)
        if not obj or obj.legal_entity_id != body.legal_entity_id:
            raise DomainError("Engagement not found in scope", 404, "NOT_FOUND")
        return {"id": approve_engagement(db, engagement_id, actor, body.reason).id, "status": "active"}


@app.post("/api/v1/identity/engagements/{engagement_id}/end")
def end_eng(engagement_id: str, body: Decision, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "engagement.manage", body.legal_entity_id)
        obj = db.get(Engagement, engagement_id)
        if not obj or obj.legal_entity_id != body.legal_entity_id:
            raise DomainError("Engagement not found in scope", 404, "NOT_FOUND")
        end_engagement(db, engagement_id, actor, body.reason)
        return {"id": engagement_id, "status": "ended"}


@app.post("/api/v1/identity/qualifications", status_code=201)
def add_qualification(body: QualificationInput, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "qualification.attest", body.legal_entity_id)
        if (person_for_subject(db, actor) or Person(tr_code="")).tr_code == body.tr_code:
            raise DomainError("Cannot attest own qualification", 403, "SEPARATION_OF_DUTIES")
        row = attest_qualification(db, body.tr_code, body.qualification_code,
                                   body.learning_credential_id, body.source_evidence_ref,
                                   body.effective_from, body.effective_to, actor,
                                   body.legal_entity_id)
        return {"id": row.id, "qualification_code": row.qualification_code}


@app.post("/api/v1/identity/{tr_code}/emp/requests", status_code=201)
def emp_request(tr_code: str, body: StageInput, request: Request):
    return _request_stage(tr_code, "EMP", body, request)


@app.post("/api/v1/identity/{tr_code}/bm/requests", status_code=201)
def bm_request(tr_code: str, body: StageInput, request: Request):
    return _request_stage(tr_code, "BM", body, request)


def _request_stage(tr, stage, body, request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "stage.request", body.legal_entity_id)
        row = request_stage(db, tr, stage, body.legal_entity_id, actor, body.reason)
        return {"id": row.id, "status": row.status, "stage": row.stage}


@app.post("/api/v1/identity/{tr_code}/emp/issue")
def emp_issue(tr_code: str, body: StageIssueInput, request: Request):
    return _issue_stage(tr_code, "EMP", body, request)


@app.post("/api/v1/identity/{tr_code}/bm/issue")
def bm_issue(tr_code: str, body: StageIssueInput, request: Request):
    return _issue_stage(tr_code, "BM", body, request)


def _issue_stage(tr, stage, body, request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "stage.issue", body.legal_entity_id)
        req = db.get(StageRequest, body.request_id)
        if not req or req.legal_entity_id != body.legal_entity_id:
            raise DomainError("Stage request not found in scope", 404, "NOT_FOUND")
        code = issue_stage(db, tr, stage, body.request_id, actor, body.reason)
        return {"code": code, "tr_code": tr, "stage": stage, "issued": True}


@app.post("/api/v1/identity/{tr_code}/bm/revoke")
def bm_revoke(tr_code: str, body: StageInput, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "stage.revoke", body.legal_entity_id)
        revoke_bm(db, tr_code, body.legal_entity_id, actor, body.reason)
        return {"code": stage_code(tr_code, "BM"), "active": False}


@app.post("/api/v1/identity/grants", status_code=201)
def create_grant(body: GrantInput, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "grant.request", body.legal_entity_id)
        row = request_grant(db, body.tr_code, body.legal_entity_id, body.store_id,
                            body.action, body.role, body.required_qualification,
                            body.valid_from, body.valid_to, actor, body.reason)
        return {"grant_id": row.id, "status": row.status}


@app.post("/api/v1/identity/grants/{grant_id}/approve")
def grant_approve(grant_id: str, body: Decision, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "grant.approve", body.legal_entity_id)
        g = db.get(Grant, grant_id)
        if not g or g.legal_entity_id != body.legal_entity_id:
            raise DomainError("Grant not found in scope", 404, "NOT_FOUND")
        # The isolated V4 path accepts a verified, current store-specific Academy
        # qualification in place of the legacy generic POS_SERVICE requirement.
        academy_pos = False
        if (settings.env == "isolated" and g.store_id and g.legal_entity_id == "DEMO_LEGAL"
                and g.action in {"pos.order.read", "pos.order.create"}
                and not active_qualification(db, g.tr_code, "POS_SERVICE")):
            from .academy_policy import training_reason
            from sqlalchemy import inspect
            if inspect(db.connection()).has_table("bsv_learning_courses"):
                academy_pos = training_reason(db, db.get(Person, g.tr_code), g.store_id) == "OK"
        approve_grant(db, grant_id, actor, body.reason, academy_pos=academy_pos)
        return {"grant_id": grant_id, "status": "active"}


@app.post("/api/v1/identity/grants/{grant_id}/revoke")
def grant_revoke(grant_id: str, body: Decision, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "grant.revoke", body.legal_entity_id)
        g = db.get(Grant, grant_id)
        if not g or g.legal_entity_id != body.legal_entity_id:
            raise DomainError("Grant not found in scope", 404, "NOT_FOUND")
        revoke_grant(db, grant_id, actor, body.reason)
        return {"grant_id": grant_id, "status": "revoked"}


@app.post("/api/v1/identity/{tr_code}/suspend")
def person_suspend(tr_code: str, body: Decision, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "people.suspend", body.legal_entity_id)
        require_exclusive_legal_scope(db, tr_code, body.legal_entity_id)
        suspend_person(db, tr_code, actor, body.reason)
        return {"tr_code": tr_code, "status": "suspended"}


@app.post("/api/v1/identity/{tr_code}/restore")
def person_restore(tr_code: str, body: Decision, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "people.suspend", body.legal_entity_id)
        require_exclusive_legal_scope(db, tr_code, body.legal_entity_id)
        restore_person(db, tr_code, actor, body.reason)
        return {"tr_code": tr_code, "status": "active", "requires_grant_reapproval": True}


@app.post("/api/v1/identity/redaction/requests", status_code=201)
def redact_request(body: RedactInput, request: Request):
    with router.session(write=True) as db:
        actor=grant_guard(request, db, "people.redact", body.legal_entity_id)
        obj=request_redaction(db,body.tr_code,body.legal_entity_id,body.evidence_ref,actor,body.reason)
        return {"request_id":obj.id,"status":"pending"}


@app.post("/api/v1/identity/redaction/{request_id}/approve")
def redact_approve(request_id: str, body: Decision, request: Request):
    with router.session(write=True) as db:
        actor=grant_guard(request,db,"people.redact",body.legal_entity_id)
        obj=db.get(PrivacyRequest,request_id)
        if not obj or obj.legal_entity_id != body.legal_entity_id:
            raise DomainError("Privacy review not found in scope",404,"NOT_FOUND")
        approved=approve_redaction(db,request_id,actor,body.reason)
        return {"tr_code":approved.tr_code,"status":"tombstone"}


@app.get("/api/v1/identity/{tr_code}/history")
def history(tr_code: str, request: Request, legal_entity_id: str | None = None):
    with router.session() as db:
        sess = current_session(request, db)
        own = person_for_subject(db, sess.subject)
        if not own or own.tr_code != tr_code:
            if not legal_entity_id:
                raise DomainError("Scope required", 403, "FORBIDDEN")
            require(db, sess.subject, "audit.read", legal_entity_id)
            # Cross-entity IDOR: target must have an engagement with that legal entity.
            if not db.scalar(select(Engagement.id).where(Engagement.tr_code == tr_code,
                                                       Engagement.legal_entity_id == legal_entity_id)):
                raise DomainError("No history in scope", 404, "NOT_FOUND")
        history_query = select(AuditEvent).where(AuditEvent.target_tr == tr_code)
        if not own or own.tr_code != tr_code:
            history_query = history_query.where(AuditEvent.legal_entity_id == legal_entity_id)
        events = list(db.scalars(history_query.order_by(AuditEvent.occurred_at.desc()).limit(100)))
        return {"tr_code": tr_code, "events": [{"event_type": x.event_type,
                "occurred_at": x.occurred_at.isoformat(), "effective_at": x.effective_at.isoformat() if x.effective_at else None,
                "details": x.details} for x in events]}


@app.post("/api/v1/identity/auth-recovery/requests", status_code=201)
def create_recovery(body: RecoveryInput, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "people.verify", body.legal_entity_id)
        if settings.auth_provider == "isolated":
            new_subject = body.new_auth_subject_id or ""
            if not db.get(IsolatedUser, new_subject):
                raise DomainError("New subject not verified by isolated login provider", 422, "SUBJECT_NOT_VERIFIED")
        else:
            if not body.external_identity_token:
                raise DomainError("Verified new external identity token required", 422, "SUBJECT_NOT_VERIFIED")
            new_subject = validate_external_token(body.external_identity_token, settings)
        row = request_account_rebind(db, body.tr_code, body.legal_entity_id,
                                     new_subject, body.evidence_ref, actor)
        return {"request_id":row.id,"status":row.status,"tr_code":row.tr_code}


@app.post("/api/v1/identity/auth-recovery/{recovery_id}/approve")
def approve_recovery(recovery_id: str, body: Decision, request: Request):
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "people.approve", body.legal_entity_id)
        row=db.get(AuthRecoveryRequest,recovery_id)
        if not row or row.legal_entity_id != body.legal_entity_id:
            raise DomainError("Recovery not found in scope",404,"NOT_FOUND")
        result=approve_account_rebind(db, recovery_id, actor, body.reason)
        return {"tr_code":result.tr_code,"status":result.status,"old_sessions_revoked":True}


def require_integration_service(request, service):
    token = request.headers.get("X-BSV-Service-Token", "")
    conf = settings.service_tokens.get(service, {})
    if not token or not conf.get("token") or not hmac.compare_digest(token, conf["token"]):
        raise DomainError("Service authentication required", 401, "SERVICE_UNAUTHENTICATED")
    return conf


def bearer_session(request, db):
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return validate_session(db, token if scheme.lower() == "bearer" else "")


class PosSessionCheck(StrictModel):
    legal_entity_id: str
    store_id: str
    legacy_staff_id: str
    action: Literal["pos.order.read", "pos.order.create"]


class HqLayoutSessionCheck(StrictModel):
    action: Literal["hq.layout.read", "hq.layout.edit", "hq.layout.publish", "hq.store.register"]
    legal_entity_id: str = Field(min_length=2, max_length=80)
    store_id: str | None = Field(default=None, min_length=3, max_length=32)


@app.post("/api/v1/identity/pos-session")
def pos_session(body: PosSessionCheck, request: Request):
    conf = require_integration_service(request, "pos")
    if (body.action not in conf.get("actions", []) or body.legal_entity_id not in conf.get("legal_entities", [])
            or body.store_id not in conf.get("stores", [])):
        raise DomainError("Service scope denied", 403, "SERVICE_SCOPE_DENIED")
    with router.session() as db:
        session = bearer_session(request, db)
        person = person_for_subject(db, session.subject)
        alias = db.scalar(select(LegacyAlias).where(LegacyAlias.source_system == "bsv1_pos",
                          LegacyAlias.legacy_value == body.legacy_staff_id,
                          LegacyAlias.legal_entity_id == body.legal_entity_id))
        allowed = bool(person and alias and alias.tr_code == person.tr_code and has_action(
            db, session.subject, body.action, body.store_id, body.legal_entity_id))
        return {"allowed":allowed,"decision_source":"A","cache_ttl_seconds":0}


@app.post("/api/v1/identity/hq-layout-session")
def hq_layout_session(body: HqLayoutSessionCheck, request: Request):
    conf = require_integration_service(request, "layout-admin")
    if (body.action not in conf.get("actions", [])
            or body.legal_entity_id not in conf.get("legal_entities", [])
            or (body.store_id is not None and body.store_id not in conf.get("stores", []))
            or (body.action == "hq.store.register" and body.store_id is None)):
        raise DomainError("Service scope denied", 403, "SERVICE_SCOPE_DENIED")
    with router.session() as db:
        session = bearer_session(request, db)
        if not session:
            raise DomainError("Authentication required", 401, "AUTH_REQUIRED")
        person = person_for_subject(db, session.subject)
        if not person or not person.status == "active" or not is_issued(db, person.tr_code, "EMP"):
            return {"allowed": False, "decision_source": "A", "cache_ttl_seconds": 0,
                    "action": body.action, "legal_entity_id": body.legal_entity_id,
                    "store_id": body.store_id}
        allowed = has_action(db, session.subject, body.action, body.store_id, body.legal_entity_id)
        return {"allowed": allowed, "decision_source": "A", "cache_ttl_seconds": 0,
                "action": body.action, "legal_entity_id": body.legal_entity_id,
                "store_id": body.store_id, **({"actor_tr_code": person.tr_code} if allowed else {})}


@app.get("/api/v1/auth/me")
def supply_identity(request: Request):
    conf = require_integration_service(request, "supply")
    legal = conf.get("legal_entity_id")
    if settings.env == "production":
        raise DomainError("Organization connector requires production acceptance", 503, "ORG_CONNECTOR_LOCKED")
    departments = conf.get("department_by_tr", {})
    with router.session() as db:
        session = bearer_session(request, db)
        person = person_for_subject(db, session.subject)
        department = departments.get(person.tr_code) if person else None
        if (person and not department and settings.env == "isolated"
                and legal == "DEMO_LEGAL" and conf.get("isolated_test_department") == "SYNTH-STAGE"):
            department = "SYNTH-STAGE"
        if not legal or not department:
            raise DomainError("Organization reference unavailable", 403, "FORBIDDEN")
        role_stores = {
            role: [store for store in conf.get("stores", [])
                   if has_action(db, session.subject, action, store, legal)]
            for role, action in SUPPLY_ROLE_ACTIONS.items() if action in conf.get("actions", [])
        }
        role_stores = {role: stores for role, stores in role_stores.items() if stores}
        if not role_stores:
            raise DomainError("No active supply authorization", 403, "FORBIDDEN")
        return {"employee_id":stage_code(person.tr_code,"EMP"), "department_id":department,
                "legal_entity_id":legal, "stores":sorted({store for stores in role_stores.values() for store in stores}),
                "roles":sorted(role_stores), "role_stores":role_stores}


@app.post("/api/v1/identity/authorize")
def authorize(body: AuthorizeInput, request: Request):
    sid = request.headers.get("X-BSV-Service-ID", "")
    token = request.headers.get("X-BSV-Service-Token", "")
    conf = settings.service_tokens.get(sid)
    if not conf or not token or not hmac.compare_digest(token, conf.get("token", "")):
        raise DomainError("Service authentication required", 401, "SERVICE_UNAUTHENTICATED")
    if body.action not in conf.get("actions", []) or (conf.get("legal_entities") and
        body.legal_entity_id not in conf["legal_entities"]) or (conf.get("stores") and
        body.store_id not in conf["stores"]):
        raise DomainError("Service scope denied", 403, "SERVICE_SCOPE_DENIED")
    with router.session() as db:
        allowed = has_action(db, body.auth_subject_id, body.action,
                             body.store_id, body.legal_entity_id)
        return {"allowed": allowed, "decision_source": "A", "cache_ttl_seconds": 0}


@app.post("/api/v1/identity/legacy-import/dry-run")
def legacy_dry_run(body: LegacyPreview, request: Request):
    with router.session() as db:
        grant_guard(request, db, "legacy.preview", body.legal_entity_id)
        return legacy_preview(db, [row.model_dump() for row in body.rows], body.legal_entity_id)


@app.post("/api/v1/identity/legacy-import/commit")
def legacy_commit(body: LegacyCommit, request: Request):
    # Strictly isolated-only until existing POS/operator references are mapped and G0/G1 migration signed off.
    if settings.env != "isolated" or settings.auth_provider != "isolated":
        raise DomainError("Legacy commit disabled until approved CloudBase G0/G1 mapping", 403, "MIGRATION_LOCKED")
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "legacy.commit", body.legal_entity_id)
        preview = legacy_preview(db, [row.model_dump() for row in body.rows], body.legal_entity_id)
        if preview["blocked"]:
            raise DomainError("Resolve all mapping conflicts first", 409, "MIGRATION_PRECHECK_FAILED")
        inserted = {}
        records = preview["records"]
        insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
        # Acquire overlapping keys in a consistent order. A concurrent writer can
        # win after the preview, so compare the actual row on every insert conflict.
        for row in sorted(records, key=lambda item: (item["source_system"], item["legacy_value"])):
            key = {"legal_entity_id": body.legal_entity_id, "source_system": row["source_system"],
                   "legacy_value": row["legacy_value"]}
            alias_id = None
            if not row["issues"]:
                statement = insert(LegacyAlias).values(
                    **key, tr_code=row["tr_code"], approved_by=actor, evidence_ref=body.evidence_ref,
                ).on_conflict_do_nothing(index_elements=list(key)).returning(LegacyAlias.id)
                alias_id = db.scalar(statement)
            if alias_id is None:
                existing = db.scalar(select(LegacyAlias.tr_code).filter_by(**key).with_for_update())
                if existing != row["tr_code"]:
                    raise DomainError("Resolve all mapping conflicts first", 409, "MIGRATION_PRECHECK_FAILED")
                row["issues"] = ["ALREADY_MAPPED"]
                continue
            row["status"] = "committed"
            inserted[row["source_system"], row["legacy_value"]] = alias_id
            log(db, "legacy.alias.committed", row["tr_code"], actor, body.reason,
                source_system=row["source_system"], legal_entity_id=body.legal_entity_id)
        created_ids = [inserted[row["source_system"], row["legacy_value"]] for row in records if not row["issues"]]
        return {"write_count": len(created_ids), "status": "committed_isolated_only",
                "already_mapped_count": len(records) - len(created_ids),
                "created_alias_ids": created_ids, "records": records}


class LegacyRollback(StrictModel):
    legal_entity_id: str
    alias_ids: list[str] = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=8, max_length=500)


@app.post("/api/v1/identity/legacy-import/rollback")
def legacy_rollback(body: LegacyRollback, request: Request):
    if settings.env != "isolated":
        raise DomainError("Legacy rollback only in isolated environment",403,"MIGRATION_LOCKED")
    with router.session(write=True) as db:
        actor = grant_guard(request, db, "legacy.commit", body.legal_entity_id)
        ids = set(body.alias_ids)
        rows = list(db.scalars(select(LegacyAlias).where(
            LegacyAlias.legal_entity_id == body.legal_entity_id,
            LegacyAlias.id.in_(ids)).with_for_update()))
        if len(rows) != len(ids):
            raise DomainError("Alias batch incomplete or outside scope",409,"MIGRATION_PRECHECK_FAILED")
        for alias in rows:
            log(db, "legacy.alias.rolled_back", alias.tr_code, actor, body.reason,
                alias_id=alias.id, source_system=alias.source_system, legal_entity_id=body.legal_entity_id)
            db.delete(alias)
        return {"removed":len(rows),"identities_changed":False}


# Route registration after the existing identity guards are defined.
from .academy_api import academy_router  # noqa: E402

app.include_router(academy_router)
