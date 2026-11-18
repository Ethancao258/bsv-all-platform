"""Normalized domain records. Cross-domain IDs remain external references, not new masters."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String, Integer, DateTime, ForeignKey, Boolean, Text, UniqueConstraint,
    CheckConstraint, Index, JSON
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class IsolatedBase(DeclarativeBase):
    """Disposable test-only auth metadata: NEVER migrate into BSV ALL central master."""
    pass


class Person(Base):
    __tablename__ = "bsv_identity_people"
    tr_code: Mapped[str] = mapped_column(String(7), primary_key=True)
    display_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (CheckConstraint("status IN ('active','suspended','tombstone')", name="people_status_ck"),)


class CodeAllocator(Base):
    __tablename__ = "bsv_identity_code_allocator"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    next_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (CheckConstraint("next_index >= 0 AND next_index <= 239976", name="capacity_ck"),)


class StageIssuance(Base):
    __tablename__ = "bsv_identity_stage_issuances"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tr_code: Mapped[str] = mapped_column(ForeignKey("bsv_identity_people.tr_code", ondelete="RESTRICT"), nullable=False)
    stage: Mapped[str] = mapped_column(String(3), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    issued_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approval_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    __table_args__ = (
        UniqueConstraint("tr_code", "stage", name="one_stage_ever_per_person"),
        CheckConstraint("stage IN ('TR','EMP','BM')", name="stage_allowed_ck"),
    )


class AuthLink(Base):
    __tablename__ = "bsv_identity_auth_links"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    auth_subject_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    tr_code: Mapped[str] = mapped_column(ForeignKey("bsv_identity_people.tr_code", ondelete="RESTRICT"), nullable=False)
    provider: Mapped[str] = mapped_column(String(25), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("idx_authlink_tr", "tr_code"),)


class AuthSession(Base):
    __tablename__ = "bsv_identity_auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IsolatedUser(IsolatedBase):
    __tablename__ = "bsv_identity_isolated_users"
    subject: Mapped[str] = mapped_column(String(128), primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Registration(Base):
    __tablename__ = "bsv_identity_registration_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    subject: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    requested_legal_entity_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    display_label: Mapped[str] = mapped_column(String(80), nullable=False)
    proof_digest: Mapped[str | None] = mapped_column(String(64))
    consent_version: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    verified_by: Mapped[str | None] = mapped_column(String(128))
    verification_reason: Mapped[str | None] = mapped_column(String(500))
    separate_person_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_tr_code: Mapped[str | None] = mapped_column(ForeignKey("bsv_identity_people.tr_code", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("subject", "idempotency_key", name="reg_idempotence_uk"),
        Index("idx_reg_proof", "proof_digest"),
        Index("idx_reg_status", "status"),
    )


class Engagement(Base):
    __tablename__ = "bsv_identity_engagements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tr_code: Mapped[str] = mapped_column(ForeignKey("bsv_identity_people.tr_code", ondelete="RESTRICT"), nullable=False)
    legal_entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    type: Mapped[str] = mapped_column(String(25), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        CheckConstraint("type IN ('employee','part_time','contractor','partner')", name="eng_type_ck"),
        CheckConstraint("status IN ('pending','active','ended','rejected')", name="eng_status_ck"),
        Index("idx_eng_active", "tr_code", "legal_entity_id", "status"),
    )


class Qualification(Base):
    __tablename__ = "bsv_identity_qualification_links"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tr_code: Mapped[str] = mapped_column(ForeignKey("bsv_identity_people.tr_code", ondelete="RESTRICT"), nullable=False)
    qualification_code: Mapped[str] = mapped_column(String(60), nullable=False)
    learning_credential_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    source_evidence_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(14), default="active", nullable=False)
    verified_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("idx_qualification_tr", "tr_code", "qualification_code"),)


class StageRequest(Base):
    __tablename__ = "bsv_identity_stage_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tr_code: Mapped[str] = mapped_column(ForeignKey("bsv_identity_people.tr_code", ondelete="RESTRICT"), nullable=False)
    stage: Mapped[str] = mapped_column(String(3), nullable=False)
    legal_entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(14), default="pending", nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(128))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("stage IN ('EMP','BM')", name="req_stage_ck"),)


class ManagementAppointment(Base):
    __tablename__ = "bsv_identity_bm_appointments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tr_code: Mapped[str] = mapped_column(ForeignKey("bsv_identity_people.tr_code", ondelete="RESTRICT"), nullable=False)
    legal_entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    stage_request_id: Mapped[str] = mapped_column(ForeignKey("bsv_identity_stage_requests.id"), nullable=False, unique=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(14), default="active", nullable=False)
    issued_by: Mapped[str] = mapped_column(String(128), nullable=False)
    revoked_by: Mapped[str | None] = mapped_column(String(128))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Grant(Base):
    __tablename__ = "bsv_identity_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tr_code: Mapped[str] = mapped_column(ForeignKey("bsv_identity_people.tr_code", ondelete="RESTRICT"), nullable=False)
    legal_entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    store_id: Mapped[str | None] = mapped_column(String(80))  # organization-domain FK resolved via API
    role: Mapped[str] = mapped_column(String(25), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    required_qualification: Mapped[str | None] = mapped_column(String(60))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(14), default="pending", nullable=False)
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(String(128))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    __table_args__ = (
        CheckConstraint("role IN ('staff','manager','hq')", name="grant_role_ck"),
        CheckConstraint("status IN ('pending','active','rejected','revoked')", name="grant_status_ck"),
        Index("idx_grant_scope", "tr_code", "legal_entity_id", "store_id", "action", "status"),
    )


class LegacyAlias(Base):
    __tablename__ = "bsv_identity_legacy_aliases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    legal_entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    legacy_value: Mapped[str] = mapped_column(String(200), nullable=False)
    tr_code: Mapped[str] = mapped_column(ForeignKey("bsv_identity_people.tr_code", ondelete="RESTRICT"), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("legal_entity_id", "source_system", "legacy_value", name="legacy_alias_unique"),)


class AuthRecoveryRequest(Base):
    __tablename__ = "bsv_identity_auth_recovery_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tr_code: Mapped[str] = mapped_column(ForeignKey("bsv_identity_people.tr_code", ondelete="RESTRICT"), nullable=False)
    legal_entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    new_auth_subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    previous_auth_subject_id: Mapped[str | None] = mapped_column(String(128))
    evidence_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(15), default="pending", nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("status IN ('pending','approved','rejected')", name="recovery_status_ck"),)


class PrivacyRequest(Base):
    __tablename__ = "bsv_identity_privacy_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tr_code: Mapped[str] = mapped_column(ForeignKey("bsv_identity_people.tr_code", ondelete="RESTRICT"), nullable=False)
    legal_entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(15), default="pending", nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(128))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status IN ('pending','approved','rejected')", name="privacy_req_status_ck"),)


class AuditEvent(Base):
    __tablename__ = "bsv_identity_audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    legal_entity_id: Mapped[str | None] = mapped_column(String(80), index=True)
    target_tr: Mapped[str | None] = mapped_column(String(7), index=True)
    actor_subject: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Append-only blocked by application: production DB user must have no UPDATE/DELETE on this table.
    __table_args__ = (Index("idx_audit_time", "occurred_at"),)


# PostgreSQL hardening: DB-level irreversible stage and event history, immutable TR.
# Install in isolated staging via SQLAlchemy metadata events; official CloudBase G0/G1
# must reconcile these names/roles before any formal migration.
from sqlalchemy import event, DDL

event.listen(Base.metadata, "before_create", DDL("""
CREATE OR REPLACE FUNCTION bsv_identity_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'BSV historical record is immutable: %%', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql
""").execute_if(dialect="postgresql"))

event.listen(Base.metadata, "before_create", DDL("""
CREATE OR REPLACE FUNCTION bsv_identity_reject_tr_change() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'TR permanent identity cannot be deleted';
    END IF;
    IF NEW.tr_code IS DISTINCT FROM OLD.tr_code THEN
        RAISE EXCEPTION 'TR permanent identity cannot change';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
""").execute_if(dialect="postgresql"))

for _table in (StageIssuance.__table__, AuditEvent.__table__):
    event.listen(_table, "after_create", DDL(
        f"CREATE TRIGGER bsv_identity_block_update_delete BEFORE UPDATE OR DELETE ON {_table.name} "
        "FOR EACH ROW EXECUTE FUNCTION bsv_identity_reject_mutation()"
    ).execute_if(dialect="postgresql"))

event.listen(Person.__table__, "after_create", DDL("""
CREATE TRIGGER bsv_identity_tr_permanent BEFORE UPDATE OR DELETE ON bsv_identity_people
FOR EACH ROW EXECUTE FUNCTION bsv_identity_reject_tr_change()
""").execute_if(dialect="postgresql"))

event.listen(Base.metadata, "after_drop", DDL(
    "DROP FUNCTION IF EXISTS bsv_identity_reject_mutation()"
).execute_if(dialect="postgresql"))
event.listen(Base.metadata, "after_drop", DDL(
    "DROP FUNCTION IF EXISTS bsv_identity_reject_tr_change()"
).execute_if(dialect="postgresql"))
