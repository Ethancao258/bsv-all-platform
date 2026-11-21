"""Transactional identity workflows. No endpoint derives permission from prefix alone."""
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError
from .models import (
    now, Person, CodeAllocator, StageIssuance, AuthLink, AuthSession,
    Registration, Engagement, Qualification, StageRequest, ManagementAppointment,
    Grant, AuditEvent, LegacyAlias, AuthRecoveryRequest, PrivacyRequest
)

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # 24 characters, no I/O
CAPACITY = len(ALPHABET) * 9999
TR_RE = re.compile(r"^TR[ABCDEFGHJKLMNPQRSTUVWXYZ][0-9]{4}$")
STAGES = {"TR": "TR", "EMP": "EMP", "BM": "BM"}
MANAGEMENT_ACTIONS = frozenset({
    "hq.people.read", "people.verify", "people.approve", "engagement.manage",
    "hq.layout.read", "hq.layout.edit", "hq.layout.publish", "hq.store.register",
    "qualification.attest", "stage.request", "stage.issue", "stage.revoke",
    "grant.request", "grant.approve", "grant.revoke", "audit.read",
    "legacy.preview", "legacy.commit", "people.suspend", "people.redact",
})
ACTION_QUALIFICATIONS = {
    "pos.order.create": "POS_SERVICE", "pos.order.read": "POS_SERVICE",
    "supply.batch.read": "SUPPLY_SAFETY", "supply.batch.write": "SUPPLY_SAFETY",
}
SUPPLY_ROLE_ACTIONS = {
    "dispatch": "supply.dispatch", "receive": "supply.receive",
    "inspect": "quality.self_check", "inspect_independent": "quality.independent.submit",
    "review_independent": "quality.independent.review",
}
ACTION_QUALIFICATIONS.update({
    "supply.dispatch": "SUPPLY_SAFETY", "supply.receive": "SUPPLY_SAFETY",
    "quality.independent.submit": "QUALITY_INSPECTOR",
    "quality.independent.review": "QUALITY_REVIEWER",
})
STORE_ACTION_PREFIXES = ("pos.", "store.", "quality.", "supply.")
ALLOWED_ACTIONS = MANAGEMENT_ACTIONS | frozenset(SUPPLY_ROLE_ACTIONS.values()) | frozenset({
    "pos.order.create", "pos.order.read", "supply.batch.read", "supply.batch.write",
    "store.shift.read", "store.shift.write", "learning.qualified.read",
    "learning.course.read", "quality.check.write", "marketing.task.write",
})


class DomainError(Exception):
    def __init__(self, message, status=409, code="CONFLICT"):
        self.message, self.status, self.code = message, status, code
        super().__init__(message)


def aware(ts):
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def active_window(start, end, clock=None):
    clock = clock or now()
    return aware(start) <= clock and (end is None or clock < aware(end))


def encode_index(index):
    if not 0 <= index < CAPACITY:
        raise DomainError("TR code capacity exhausted", 503, "CODE_POOL_EXHAUSTED")
    return f"TR{ALPHABET[index // 9999]}{(index % 9999)+1:04d}"


def stage_code(tr, stage):
    if not TR_RE.fullmatch(tr) or tr[-4:] == "0000":
        raise DomainError("Invalid canonical TR code", 422, "INVALID_CODE")
    if stage not in STAGES:
        raise DomainError("Unknown stage", 422, "INVALID_STAGE")
    return stage + tr[2:]


def log(db, event, target, actor, reason, **details):
    # Deliberately restrict details to non-PII identifiers (never names, proof, contact, tokens).
    legal = details.pop("legal_entity_id", None)
    db.add(AuditEvent(event_type=event, legal_entity_id=legal,
                      target_tr=target, actor_subject=actor,
                      reason=reason[:500], details=details))


def get_person(db, tr):
    if not TR_RE.fullmatch(tr) or tr.endswith("0000"):
        raise DomainError("Invalid code", 422, "INVALID_CODE")
    obj = db.get(Person, tr)
    if not obj:
        raise DomainError("Person not found", 404, "NOT_FOUND")
    return obj


def person_for_subject(db, subject):
    link = db.scalar(select(AuthLink).where(AuthLink.auth_subject_id == subject, AuthLink.revoked_at.is_(None)))
    return db.get(Person, link.tr_code) if link else None


def require_exclusive_legal_scope(db, tr, legal_entity_id):
    """Prevent a company-local admin from modifying global person/auth state of other companies.

    Multi-entity person-wide recovery, privacy deletion and suspension require a
    future group-level approval workflow; fail closed rather than invent approval.
    """
    entities=set(db.scalars(select(Engagement.legal_entity_id).where(
        Engagement.tr_code == tr)))
    entities.update(db.scalars(select(Registration.requested_legal_entity_id).where(
        Registration.approved_tr_code == tr)))
    if legal_entity_id not in entities:
        raise DomainError("No documented legal entity scope for person", 404, "NOT_FOUND")
    if len(entities)>1:
        raise DomainError("Cross-entity person-wide change requires central governance review", 409,
                          "CROSS_ENTITY_GLOBAL_ACTION_LOCKED")


def is_issued(db, tr, stage):
    return db.scalar(select(StageIssuance.id).where(StageIssuance.tr_code == tr, StageIssuance.stage == stage)) is not None


def active_engagement(db, tr, legal_entity_id, clock=None):
    clock = clock or now()
    return any(active_window(x.effective_from, x.effective_to, clock) for x in db.scalars(
        select(Engagement).where(Engagement.tr_code == tr, Engagement.legal_entity_id == legal_entity_id,
                                 Engagement.status == "active")
    ))


def active_qualification(db, tr, qualification_code, clock=None):
    clock = clock or now()
    return any(active_window(x.effective_from, x.effective_to, clock) for x in db.scalars(
        select(Qualification).where(Qualification.tr_code == tr,
                                    Qualification.qualification_code == qualification_code,
                                    Qualification.status == "active")
    ))


def active_bm(db, tr, legal_entity_id, clock=None):
    clock = clock or now()
    if not is_issued(db, tr, "BM"):
        return False
    return any(active_window(x.valid_from, x.valid_to, clock) for x in db.scalars(
        select(ManagementAppointment).where(ManagementAppointment.tr_code == tr,
                                           ManagementAppointment.legal_entity_id == legal_entity_id,
                                           ManagementAppointment.status == "active")
    ))


def has_action(db, subject, action, store_id=None, legal_entity_id=None, clock=None, *, academy_pos=False):
    """Always authoritative A-read; fail closed if DB is down. No role encoded in token."""
    clock = clock or now()
    if action not in ALLOWED_ACTIONS or not legal_entity_id:
        return False
    person = person_for_subject(db, subject)
    if not person or person.status != "active" or not is_issued(db, person.tr_code, "EMP"):
        return False
    if not active_engagement(db, person.tr_code, legal_entity_id, clock):
        return False
    for grant in db.scalars(select(Grant).where(
        Grant.tr_code == person.tr_code, Grant.legal_entity_id == legal_entity_id,
        Grant.action == action, Grant.status == "active"
    )):
        if not active_window(grant.valid_from, grant.valid_to, clock):
            continue
        if grant.store_id is not None and grant.store_id != store_id:
            continue
        if store_id and grant.store_id is None and grant.role != "hq":
            continue
        if not store_id and grant.store_id is not None:
            continue
        mandatory = ACTION_QUALIFICATIONS.get(action)
        # The V4 caller independently proves current store evidence. V3 still uses POS_SERVICE.
        covered = academy_pos and action in {"pos.order.read", "pos.order.create"} and mandatory == "POS_SERVICE"
        if mandatory and not covered and not active_qualification(db, person.tr_code, mandatory, clock):
            continue
        if (grant.required_qualification and not (covered and grant.required_qualification == mandatory)
                and not active_qualification(db, person.tr_code,
                                             grant.required_qualification, clock)):
            continue
        if grant.role in {"manager", "hq"} or action in MANAGEMENT_ACTIONS:
            if not active_bm(db, person.tr_code, legal_entity_id, clock):
                continue
            if not active_qualification(db, person.tr_code, "BM_MANAGEMENT", clock):
                continue
        return True
    return False


def require(db, actor, action, legal_entity_id, store_id=None):
    if not has_action(db, actor, action, store_id, legal_entity_id):
        raise DomainError("Not authorized for this action/scope", 403, "FORBIDDEN")


def _normalize_hint(value):
    return " ".join(value.strip().casefold().split())


def register(db, subject, idempotency_key, display_label, proof_hint, privacy_pepper,
             legal_entity_id, consent_version="2026-11-18"):
    if not 2 <= len(legal_entity_id) <= 80:
        raise DomainError("Registration legal entity required", 422, "LEGAL_ENTITY_REQUIRED")
    if not 8 <= len(idempotency_key) <= 80:
        raise DomainError("Idempotency key must be 8-80 chars", 422, "BAD_IDEMPOTENCY")
    if not 1 <= len(display_label.strip()) <= 80:
        raise DomainError("Display label required", 422, "BAD_LABEL")
    if consent_version != "2026-11-18":
        raise DomainError("Current privacy notice consent required", 422, "CONSENT_REQUIRED")
    data = {"name": display_label.strip(), "hint": _normalize_hint(proof_hint or ""),
            "consent": consent_version, "legal_entity_id": legal_entity_id}
    digest = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if db.bind.dialect.name == "postgresql":
        # Per-verified-subject transaction lock serializes retries and simultaneous
        # distinct idempotency keys. Never read MAX() and increment.
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                   {"lock_key": "bsv-registration:" + subject})
    previous = db.scalar(select(Registration).where(Registration.subject == subject,
                                                     Registration.idempotency_key == idempotency_key))
    if previous:
        if previous.request_digest != digest:
            raise DomainError("Idempotency key reused for different payload", 409, "IDEMPOTENCY_CONFLICT")
        return previous
    if db.scalar(select(AuthLink.id).where(AuthLink.auth_subject_id == subject)):
        raise DomainError("Account previously linked; use account recovery rather than a new TR", 409, "HISTORICAL_SUBJECT_LINK")
    # One in-flight request per subject: a unique idempotency key alone is not a new identity.
    unfinished = db.scalar(select(Registration).where(Registration.subject == subject,
                        Registration.status.in_(["pending", "needs_review", "verified"])))
    if unfinished:
        raise DomainError("An active application already exists", 409, "ACTIVE_APPLICATION")
    proof = hmac.new(privacy_pepper.encode(), data["hint"].encode(), hashlib.sha256).hexdigest() if data["hint"] else None
    suspected = bool(proof and db.scalar(select(Registration.id).where(
        Registration.proof_digest == proof, Registration.subject != subject,
        Registration.status.in_(["pending", "needs_review", "verified", "approved"])).limit(1)))
    obj = Registration(subject=subject, requested_legal_entity_id=legal_entity_id,
                       idempotency_key=idempotency_key, request_digest=digest,
                       display_label=data["name"], proof_digest=proof, consent_version=consent_version,
                       status="needs_review" if suspected else "pending",
                       expires_at=now() + timedelta(days=30))
    db.add(obj)
    db.flush()
    log(db, "registration.submitted", None, subject, "Consent and registration submitted",
        request_id=obj.id, legal_entity_id=legal_entity_id)
    return obj


def verify_registration(db, request_id, actor, reason, separate_person_confirmed=False):
    obj = db.scalar(select(Registration).where(Registration.id == request_id).with_for_update())
    if not obj:
        raise DomainError("Application not found", 404, "NOT_FOUND")
    if obj.status not in {"pending", "needs_review"} or aware(obj.expires_at) < now():
        raise DomainError("Application not reviewable", 409, "INVALID_TRANSITION")
    if obj.subject == actor:
        raise DomainError("Cannot verify own registration", 403, "SEPARATION_OF_DUTIES")
    if obj.status == "needs_review" and not separate_person_confirmed:
        raise DomainError("Suspected duplicate requires documented separate-person decision", 409, "DUPLICATE_REVIEW")
    if len(reason.strip()) < 8:
        raise DomainError("Reason/evidence required (at least 8 chars)", 422, "REASON_REQUIRED")
    obj.status = "verified"
    obj.verified_by = actor
    obj.verification_reason = reason.strip()
    obj.separate_person_confirmed = separate_person_confirmed
    log(db, "registration.verified", None, actor, reason, request_id=obj.id,
        legal_entity_id=obj.requested_legal_entity_id, separate=separate_person_confirmed)
    return obj


def approve_registration(db, request_id, actor, reason):
    obj = db.scalar(select(Registration).where(Registration.id == request_id).with_for_update())
    if not obj:
        raise DomainError("Application not found", 404, "NOT_FOUND")
    if obj.status == "approved":
        return db.get(Person, obj.approved_tr_code)
    if obj.status != "verified" or aware(obj.expires_at) <= now():
        raise DomainError("Application must be verified and unexpired", 409, "INVALID_TRANSITION")
    if obj.subject == actor or obj.verified_by == actor:
        raise DomainError("Independent verifier/approver required", 403, "SEPARATION_OF_DUTIES")
    if person_for_subject(db, obj.subject):
        raise DomainError("Existing TR for authentication subject", 409, "ALREADY_REGISTERED")
    allocator = db.scalar(select(CodeAllocator).where(CodeAllocator.id == 1).with_for_update())
    if allocator is None:
        # seeded only in isolated migration/bootstrap; no auto repair in production.
        raise DomainError("Code allocator missing: manual repair required", 503, "ALLOCATOR_MISSING")
    # Revalidate duplicate proof at issue time; parallel approvals cannot accidentally merge people.
    if obj.proof_digest and not obj.separate_person_confirmed and db.scalar(
        select(Registration.id).where(Registration.proof_digest == obj.proof_digest,
                                      Registration.id != obj.id, Registration.status == "approved")):
        raise DomainError("Identical proof signal requires manual separate-person confirmation", 409, "DUPLICATE_REVIEW")
    tr = encode_index(allocator.next_index)
    allocator.next_index += 1
    person = Person(tr_code=tr, display_label=obj.display_label)
    db.add(person)
    db.flush()
    db.add(StageIssuance(tr_code=tr, stage="TR", issued_by=actor,
                         approval_ref=obj.id, reason=reason))
    db.add(AuthLink(auth_subject_id=obj.subject, tr_code=tr, provider="verified_auth_subject"))
    obj.status, obj.approved_tr_code, obj.approved_by = "approved", tr, actor
    log(db, "identity.tr.issued", tr, actor, reason, request_id=obj.id,
        legal_entity_id=obj.requested_legal_entity_id, allocator_next=allocator.next_index)
    db.flush()
    return person


def make_engagement(db, tr, legal_entity_id, kind, effective_from, effective_to, evidence_ref, actor):
    get_person(db, tr)
    if kind not in {"employee", "part_time", "contractor", "partner"}:
        raise DomainError("Invalid engagement type", 422, "INVALID_TYPE")
    if effective_to and aware(effective_to) <= aware(effective_from):
        raise DomainError("End must follow start", 422, "INVALID_DATES")
    if len(evidence_ref.strip()) < 6:
        raise DomainError("Evidence reference required", 422, "EVIDENCE_REQUIRED")
    obj = Engagement(tr_code=tr, legal_entity_id=legal_entity_id, type=kind,
                     effective_from=effective_from, effective_to=effective_to,
                     evidence_ref=evidence_ref, created_by=actor)
    db.add(obj); db.flush()
    log(db, "engagement.submitted", tr, actor, "Employment/cooperation relationship requested",
        engagement_id=obj.id, legal_entity_id=legal_entity_id)
    return obj


def approve_engagement(db, engagement_id, actor, reason):
    obj = db.scalar(select(Engagement).where(Engagement.id == engagement_id).with_for_update())
    if not obj or obj.status != "pending":
        raise DomainError("No pending engagement", 409, "INVALID_TRANSITION")
    if obj.created_by == actor or (person_for_subject(db, actor) or Person(tr_code="")).tr_code == obj.tr_code:
        raise DomainError("Independent approver required", 403, "SEPARATION_OF_DUTIES")
    obj.status, obj.approved_by = "active", actor
    log(db, "engagement.approved", obj.tr_code, actor, reason,
        engagement_id=obj.id, legal_entity_id=obj.legal_entity_id)
    return obj


def end_engagement(db, engagement_id, actor, reason):
    obj = db.get(Engagement, engagement_id)
    if not obj or obj.status != "active":
        raise DomainError("Engagement not active", 409, "INVALID_TRANSITION")
    obj.status, obj.effective_to = "ended", now()
    # End an individual contractual relationship. Another approved active relationship
    # with the same legal entity must not be destroyed by ending this one.
    still_active = active_engagement(db, obj.tr_code, obj.legal_entity_id)
    if not still_active:
        for g in db.scalars(select(Grant).where(Grant.tr_code == obj.tr_code,
                                                Grant.legal_entity_id == obj.legal_entity_id,
                                                Grant.status == "active")):
            g.status, g.revoked_at, g.revoked_by = "revoked", now(), actor
        for bm in db.scalars(select(ManagementAppointment).where(
            ManagementAppointment.tr_code == obj.tr_code,
            ManagementAppointment.legal_entity_id == obj.legal_entity_id,
            ManagementAppointment.status == "active")):
            bm.status, bm.valid_to, bm.revoked_at, bm.revoked_by = "revoked", now(), now(), actor
        # Force reauthentication when the last engagement under this entity ends.
        # Other entity access should be revalidated through A after new login.
        for link in db.scalars(select(AuthLink).where(AuthLink.tr_code == obj.tr_code,
                                                       AuthLink.revoked_at.is_(None))):
            for sess in db.scalars(select(AuthSession).where(AuthSession.subject == link.auth_subject_id,
                                                            AuthSession.revoked_at.is_(None))):
                sess.revoked_at = now()
    log(db, "engagement.ended", obj.tr_code, actor, reason, engagement_id=obj.id,
        legal_entity_id=obj.legal_entity_id,
        another_active_relation=still_active)
    return obj


def attest_qualification(db, tr, code, credential_id, evidence_ref, effective_from, effective_to, actor, legal_entity_id=None):
    get_person(db, tr)
    if code not in {"EMP_ONBOARDING", "BM_MANAGEMENT", "POS_SERVICE", "SUPPLY_SAFETY", "QUALITY_INSPECTOR", "QUALITY_REVIEWER"}:
        raise DomainError("Qualification not in reviewed vocabulary", 422, "INVALID_QUALIFICATION")
    if not credential_id or len(evidence_ref) < 6:
        raise DomainError("Externally referenced learning evidence required", 422, "EVIDENCE_REQUIRED")
    if effective_to and aware(effective_to) <= aware(effective_from):
        raise DomainError("Invalid qualification validity window", 422, "INVALID_DATES")
    obj = Qualification(tr_code=tr, qualification_code=code,
                        learning_credential_id=credential_id, source_evidence_ref=evidence_ref,
                        effective_from=effective_from, effective_to=effective_to,
                        verified_by=actor)
    db.add(obj); db.flush()
    log(db, "qualification.attested", tr, actor, "External learning credential verified",
        qualification=code, credential_ref=credential_id, legal_entity_id=legal_entity_id)
    return obj


def request_stage(db, tr, stage, legal_entity_id, actor, reason):
    get_person(db, tr)
    if stage not in {"EMP", "BM"}:
        raise DomainError("Invalid stage request", 422, "INVALID_STAGE")
    if (person_for_subject(db, actor) or Person(tr_code="")).tr_code == tr:
        raise DomainError("Cannot request own higher stage", 403, "SEPARATION_OF_DUTIES")
    if stage == "EMP" and is_issued(db, tr, "EMP"):
        raise DomainError("EMP permanently issued; use re-engagement grants", 409, "STAGE_ALREADY_ISSUED")
    if stage == "BM" and not is_issued(db, tr, "EMP"):
        raise DomainError("EMP must be issued before BM", 409, "EMP_REQUIRED")
    obj = StageRequest(tr_code=tr, stage=stage, legal_entity_id=legal_entity_id,
                       requested_by=actor, reason=reason)
    db.add(obj); db.flush()
    log(db, "stage.requested", tr, actor, reason, stage=stage,
        stage_request_id=obj.id, legal_entity_id=legal_entity_id)
    return obj


def issue_stage(db, tr, stage, request_id, actor, reason):
    # Serialize issuance and appointment checks for the same person across requests.
    db.scalar(select(Person).where(Person.tr_code == tr).with_for_update())
    obj = db.scalar(select(StageRequest).where(StageRequest.id == request_id).with_for_update())
    if not obj or obj.stage != stage or obj.tr_code != tr or obj.status != "pending":
        raise DomainError("Valid pending stage request required", 409, "INVALID_TRANSITION")
    actor_person = person_for_subject(db, actor)
    if obj.requested_by == actor or (actor_person and actor_person.tr_code == tr):
        raise DomainError("Independent approval required", 403, "SEPARATION_OF_DUTIES")
    if not active_engagement(db, tr, obj.legal_entity_id):
        raise DomainError("Approved active engagement required", 409, "ENGAGEMENT_REQUIRED")
    required = "EMP_ONBOARDING" if stage == "EMP" else "BM_MANAGEMENT"
    if not active_qualification(db, tr, required):
        raise DomainError("Verified active qualification required", 409, "QUALIFICATION_REQUIRED")
    if stage == "BM" and not is_issued(db, tr, "EMP"):
        raise DomainError("EMP issuance required", 409, "EMP_REQUIRED")
    if stage == "EMP" and is_issued(db, tr, "EMP"):
        raise DomainError("EMP already issued permanently", 409, "STAGE_ALREADY_ISSUED")
    if not is_issued(db, tr, stage):
        db.add(StageIssuance(tr_code=tr, stage=stage, issued_by=actor,
                             approval_ref=request_id, reason=reason))
        db.flush()
    if stage == "BM":
        if active_bm(db, tr, obj.legal_entity_id):
            raise DomainError("Active BM appointment already exists for legal entity", 409, "ALREADY_APPOINTED")
        db.add(ManagementAppointment(tr_code=tr, legal_entity_id=obj.legal_entity_id,
                                      stage_request_id=obj.id, issued_by=actor))
    obj.status, obj.decided_by, obj.decided_at = "approved", actor, now()
    log(db, "stage.issued", tr, actor, reason, stage=stage, stage_request_id=obj.id,
        permanent_code=stage_code(tr, stage), legal_entity_id=obj.legal_entity_id)
    db.flush()
    return stage_code(tr, stage)


def revoke_bm(db, tr, legal_entity_id, actor, reason):
    if (person_for_subject(db, actor) or Person(tr_code="")).tr_code == tr:
        raise DomainError("Cannot revoke own appointment via this endpoint", 403, "SEPARATION_OF_DUTIES")
    rows = list(db.scalars(select(ManagementAppointment).where(
        ManagementAppointment.tr_code == tr,
        ManagementAppointment.legal_entity_id == legal_entity_id,
        ManagementAppointment.status == "active")))
    if not rows:
        raise DomainError("No active BM appointment", 409, "NOT_ACTIVE")
    for row in rows:
        row.status, row.valid_to, row.revoked_at, row.revoked_by = "revoked", now(), now(), actor
    for g in db.scalars(select(Grant).where(Grant.tr_code == tr,
                                            Grant.legal_entity_id == legal_entity_id,
                                            Grant.status == "active", Grant.role.in_(["manager", "hq"]))):
        g.status, g.revoked_at, g.revoked_by = "revoked", now(), actor
    log(db, "bm.revoked", tr, actor, reason, legal_entity_id=legal_entity_id)


def request_grant(db, tr, legal_entity_id, store_id, action, role, qualification, start, end, actor, reason):
    get_person(db, tr)
    if action not in ALLOWED_ACTIONS or role not in {"staff", "manager", "hq"}:
        raise DomainError("Unsupported action/role", 422, "INVALID_PERMISSION")
    if action in MANAGEMENT_ACTIONS and role != "hq":
        raise DomainError("HQ privileged action requires HQ role", 422, "INVALID_PERMISSION")
    if action.startswith(STORE_ACTION_PREFIXES) and not store_id:
        raise DomainError("Store operation needs a store scope", 422, "STORE_REQUIRED")
    mandatory = ACTION_QUALIFICATIONS.get(action)
    if mandatory:
        if qualification and qualification != mandatory:
            raise DomainError("Mandatory action qualification cannot be weakened", 422, "QUALIFICATION_MISMATCH")
        qualification = mandatory
    if role == "hq" and store_id:
        raise DomainError("HQ privileges cannot silently include store operations; use scoped manager role", 422, "SCOPE_ERROR")
    if end and aware(end) <= aware(start):
        raise DomainError("Invalid grant window", 422, "INVALID_DATES")
    if (person_for_subject(db, actor) or Person(tr_code="")).tr_code == tr:
        raise DomainError("Cannot grant own permissions", 403, "SEPARATION_OF_DUTIES")
    obj = Grant(tr_code=tr, legal_entity_id=legal_entity_id, store_id=store_id,
                action=action, role=role, required_qualification=qualification,
                valid_from=start, valid_to=end, requested_by=actor, reason=reason)
    db.add(obj); db.flush()
    log(db, "grant.requested", tr, actor, reason, grant_id=obj.id, action=action,
        store=store_id, legal_entity_id=legal_entity_id)
    return obj


def approve_grant(db, grant_id, actor, reason, *, academy_pos=False):
    obj = db.scalar(select(Grant).where(Grant.id == grant_id).with_for_update())
    if not obj or obj.status != "pending":
        raise DomainError("No pending grant", 409, "INVALID_TRANSITION")
    actor_person = person_for_subject(db, actor)
    if obj.requested_by == actor or (actor_person and actor_person.tr_code == obj.tr_code):
        raise DomainError("Approver and requester/beneficiary must differ", 403, "SEPARATION_OF_DUTIES")
    if not is_issued(db, obj.tr_code, "EMP") or not active_engagement(db, obj.tr_code, obj.legal_entity_id):
        raise DomainError("Active EMP relationship required", 409, "ENGAGEMENT_REQUIRED")
    if obj.role in {"manager", "hq"} and not active_bm(db, obj.tr_code, obj.legal_entity_id):
        raise DomainError("Active BM appointment required", 409, "BM_REQUIRED")
    covered = (academy_pos and obj.action in {"pos.order.read", "pos.order.create"}
               and obj.required_qualification == "POS_SERVICE")
    if obj.required_qualification and not covered and not active_qualification(db, obj.tr_code, obj.required_qualification):
        raise DomainError("Required qualification missing", 409, "QUALIFICATION_REQUIRED")
    if obj.role in {"manager", "hq"} and not active_qualification(db, obj.tr_code, "BM_MANAGEMENT"):
        raise DomainError("Management qualification expired or missing", 409, "QUALIFICATION_REQUIRED")
    obj.status, obj.approved_by, obj.approved_at = "active", actor, now()
    log(db, "grant.approved", obj.tr_code, actor, reason, grant_id=obj.id,
        action=obj.action, legal_entity_id=obj.legal_entity_id)
    return obj


def revoke_grant(db, grant_id, actor, reason):
    obj = db.get(Grant, grant_id)
    if not obj or obj.status != "active":
        raise DomainError("No active grant", 409, "INVALID_TRANSITION")
    obj.status, obj.revoked_by, obj.revoked_at = "revoked", actor, now()
    log(db, "grant.revoked", obj.tr_code, actor, reason, grant_id=obj.id,
        action=obj.action, legal_entity_id=obj.legal_entity_id)
    return obj


def suspend_person(db, tr, actor, reason):
    obj = get_person(db, tr)
    if obj.status != "active":
        raise DomainError("Person not active", 409, "INVALID_TRANSITION")
    if (person_for_subject(db, actor) or Person(tr_code="")).tr_code == tr:
        raise DomainError("Cannot suspend self", 403, "SEPARATION_OF_DUTIES")
    obj.status, obj.version = "suspended", obj.version + 1
    for grant in db.scalars(select(Grant).where(Grant.tr_code == tr, Grant.status == "active")):
        grant.status, grant.revoked_at, grant.revoked_by = "revoked", now(), actor
    for bm in db.scalars(select(ManagementAppointment).where(
        ManagementAppointment.tr_code == tr, ManagementAppointment.status == "active")):
        bm.status, bm.valid_to, bm.revoked_at, bm.revoked_by = "revoked", now(), now(), actor
    for link in db.scalars(select(AuthLink).where(AuthLink.tr_code == tr)):
        for sess in db.scalars(select(AuthSession).where(AuthSession.subject == link.auth_subject_id)):
            sess.revoked_at = now()
    log(db, "person.suspended", tr, actor, reason)
    return obj


def restore_person(db, tr, actor, reason):
    obj = get_person(db, tr)
    if obj.status != "suspended":
        raise DomainError("Person not suspended", 409, "INVALID_TRANSITION")
    obj.status, obj.version = "active", obj.version + 1
    # prior grants and engagements not revived: explicit new review after suspension.
    for g in db.scalars(select(Grant).where(Grant.tr_code == tr, Grant.status == "active")):
        g.status, g.revoked_at, g.revoked_by = "revoked", now(), actor
    log(db, "person.restored.require_reapproval", tr, actor, reason)
    return obj


def redact_person(db, tr, actor, reason):
    obj = get_person(db, tr)
    if obj.status == "tombstone":
        raise DomainError("Person already tombstoned", 409, "ALREADY_REDACTED")
    if (person_for_subject(db, actor) or Person(tr_code="")).tr_code == tr:
        raise DomainError("Cannot independently approve own redaction", 403, "SEPARATION_OF_DUTIES")
    obj.status, obj.display_label, obj.version = "tombstone", None, obj.version + 1
    for link in db.scalars(select(AuthLink).where(AuthLink.tr_code == tr)):
        link.revoked_at = now()
        for sess in db.scalars(select(AuthSession).where(AuthSession.subject == link.auth_subject_id)):
            sess.revoked_at = now()
    for reg in db.scalars(select(Registration).where(Registration.approved_tr_code == tr)):
        reg.display_label, reg.proof_digest, reg.request_digest = "[redacted]", None, "0"*64
    for g in db.scalars(select(Grant).where(Grant.tr_code == tr, Grant.status == "active")):
        g.status, g.revoked_at, g.revoked_by = "revoked", now(), actor
    log(db, "person.tombstoned", tr, actor, reason)
    return obj


def legacy_preview(db, rows, legal_entity_id):
    """Only preflight; no new identity or alias is written."""
    results = []
    seen = {}
    for row in rows:
        source = str(row.get("source_system", "")).strip()
        raw = str(row.get("legacy_value", "")).strip()
        tr = str(row.get("tr_code", "")).upper().strip()
        issues = []
        if not source or not raw or not TR_RE.fullmatch(tr) or tr.endswith("0000"):
            issues.append("INVALID_MAPPING_FIELDS")
        k = (source, raw)
        if k in seen:
            issues.append("SAME_LEGACY_DIFFERENT_TR" if seen[k] != tr else "DUPLICATE_MAPPING_ROW")
        if k not in seen:
            seen[k] = tr
        old = db.scalar(select(LegacyAlias).where(LegacyAlias.legal_entity_id == legal_entity_id,
                                                   LegacyAlias.source_system == source,
                                                   LegacyAlias.legacy_value == raw))
        if not issues and not old:
            engagement = db.scalar(select(Engagement.id).where(Engagement.tr_code == tr,
                                  Engagement.legal_entity_id == legal_entity_id).limit(1))
            registration = db.scalar(select(Registration.id).where(Registration.approved_tr_code == tr,
                                    Registration.requested_legal_entity_id == legal_entity_id).limit(1))
            if not engagement and not registration:
                issues.append("TR_NOT_IN_LEGAL_SCOPE")
        if old and old.tr_code != tr:
            issues.append("EXISTING_ALIAS_CONFLICT")
        if old and old.tr_code == tr:
            issues.append("ALREADY_MAPPED")
        results.append({"source_system": source, "legacy_value": raw, "tr_code": tr,
                        "status": "blocked" if any(x != "ALREADY_MAPPED" for x in issues) else "reviewed",
                        "issues": issues})
    return {"dry_run": True, "write_count": 0, "records": results,
            "blocked": sum(x["status"] == "blocked" for x in results)}


def request_account_rebind(db, tr, legal_entity_id, new_subject, evidence_ref, actor):
    """Two-person account recovery; the new subject must be externally verified first."""
    get_person(db, tr)
    require_exclusive_legal_scope(db, tr, legal_entity_id)
    if len(evidence_ref.strip()) < 8 or not new_subject.startswith(("isolated:", "cloudbase:")):
        raise DomainError("Verified subject and recovery evidence required", 422, "EVIDENCE_REQUIRED")
    if db.scalar(select(AuthLink.id).where(AuthLink.auth_subject_id == new_subject)):
        raise DomainError("New authentication subject already bound", 409, "SUBJECT_BOUND")
    if not db.scalar(select(Engagement.id).where(Engagement.tr_code == tr,
                                                Engagement.legal_entity_id == legal_entity_id)):
        raise DomainError("Recovery must be reviewed by a legal entity with existing record", 403, "FORBIDDEN")
    old_active=db.scalar(select(AuthLink.auth_subject_id).where(
        AuthLink.tr_code == tr, AuthLink.revoked_at.is_(None)))
    if not old_active:
        raise DomainError("No active account binding to recover", 409, "NO_ACTIVE_BINDING")
    obj = AuthRecoveryRequest(tr_code=tr, legal_entity_id=legal_entity_id,
                              new_auth_subject_id=new_subject, previous_auth_subject_id=old_active,
                              evidence_ref=evidence_ref,
                              requested_by=actor)
    db.add(obj); db.flush()
    log(db, "auth.recovery.requested", tr, actor, "Verified subject recovery initiated",
        recovery_id=obj.id, legal_entity_id=legal_entity_id)
    return obj


def approve_account_rebind(db, request_id, actor, reason):
    obj = db.scalar(select(AuthRecoveryRequest).where(AuthRecoveryRequest.id == request_id).with_for_update())
    if not obj or obj.status != "pending":
        raise DomainError("Account recovery request not pending", 409, "INVALID_TRANSITION")
    if obj.requested_by == actor or (person_for_subject(db, actor) or Person(tr_code="")).tr_code == obj.tr_code:
        raise DomainError("Independent account recovery approval required", 403, "SEPARATION_OF_DUTIES")
    if db.scalar(select(AuthLink.id).where(AuthLink.auth_subject_id == obj.new_auth_subject_id)):
        raise DomainError("Subject already bound before recovery approval", 409, "SUBJECT_BOUND")
    existing=list(db.scalars(select(AuthLink).where(AuthLink.tr_code == obj.tr_code,
                                                    AuthLink.revoked_at.is_(None))))
    if not existing or obj.previous_auth_subject_id not in [link.auth_subject_id for link in existing]:
        raise DomainError("Binding changed since review; re-verify subject", 409, "STALE_RECOVERY")
    for link in existing:
        link.revoked_at=now()
        for sess in db.scalars(select(AuthSession).where(AuthSession.subject == link.auth_subject_id,
                                                        AuthSession.revoked_at.is_(None))):
            sess.revoked_at=now()
    db.add(AuthLink(auth_subject_id=obj.new_auth_subject_id,tr_code=obj.tr_code,
                    provider="recovered_verified_subject"))
    obj.status, obj.approved_by, obj.approved_at="approved",actor,now()
    log(db, "auth.recovery.approved", obj.tr_code, actor, reason, recovery_id=obj.id,
        old_links_revoked=len(existing), legal_entity_id=obj.legal_entity_id)
    db.flush()
    return obj


def request_redaction(db, tr, legal_entity_id, evidence_ref, actor, reason):
    get_person(db, tr)
    require_exclusive_legal_scope(db, tr, legal_entity_id)
    if len(evidence_ref.strip()) < 8:
        raise DomainError("Privacy redaction requires formal evidence reference", 422, "EVIDENCE_REQUIRED")
    if (person_for_subject(db, actor) or Person(tr_code="")).tr_code == tr:
        raise DomainError("Privacy redaction must be independently requested", 403, "SEPARATION_OF_DUTIES")
    if not db.scalar(select(Engagement.id).where(Engagement.tr_code == tr,
                                                Engagement.legal_entity_id == legal_entity_id)):
        raise DomainError("Person outside legal entity's documented scope", 404, "NOT_FOUND")
    obj=PrivacyRequest(tr_code=tr,legal_entity_id=legal_entity_id,requested_by=actor,
                       evidence_ref=evidence_ref,reason=reason)
    db.add(obj); db.flush()
    log(db, "person.redact.requested", tr, actor, "Formal privacy review requested",
        request_id=obj.id, legal_entity_id=legal_entity_id)
    return obj


def approve_redaction(db, request_id, actor, reason):
    obj=db.get(PrivacyRequest, request_id)
    if not obj or obj.status != "pending":
        raise DomainError("No pending privacy request", 409, "INVALID_TRANSITION")
    if obj.requested_by == actor or (person_for_subject(db, actor) or Person(tr_code="")).tr_code == obj.tr_code:
        raise DomainError("Second independent privacy approver required", 403, "SEPARATION_OF_DUTIES")
    redact_person(db, obj.tr_code, actor, reason)
    obj.status,obj.decided_by,obj.decided_at="approved",actor,now()
    log(db,"person.redact.approved",obj.tr_code,actor,reason,
        request_id=obj.id, legal_entity_id=obj.legal_entity_id)
    return obj
