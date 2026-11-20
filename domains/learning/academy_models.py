"""Additive Academy, scheduling and terminal facts for the isolated authority.

The existing person registry remains the sole owner of natural person IDs.
"""
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from domains.workforce.identity.models import Person, now, uid


class AcademyBase(DeclarativeBase):
    """The isolated V4 revision stays separate from V3 metadata."""


class Course(AcademyBase):
    __tablename__ = "bsv_learning_courses"
    course_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    legal_entity_id: Mapped[str] = mapped_column(String(80))
    store_id: Mapped[str | None] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(24))
    __table_args__ = (Index("learning_course_scope", "legal_entity_id", "store_id", "role"),)


class CourseVersion(AcademyBase):
    __tablename__ = "bsv_learning_course_versions"
    course_id: Mapped[str] = mapped_column(ForeignKey(Course.course_id, ondelete="RESTRICT"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(140))
    status: Mapped[str] = mapped_column(String(12), default="draft")
    rights_ref: Mapped[str] = mapped_column(String(160))
    questions: Mapped[list] = mapped_column(JSON)
    passing_score: Mapped[int] = mapped_column(Integer)
    practical_requirements: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(ForeignKey(Person.tr_code, ondelete="RESTRICT"))
    publisher: Mapped[str | None] = mapped_column(ForeignKey(Person.tr_code, ondelete="RESTRICT"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('draft','published','retired')", name="learning_course_version_status"),
        CheckConstraint("version > 0 AND passing_score BETWEEN 1 AND 100", name="learning_course_version_numbers"),
    )


def version_fk():
    return ForeignKeyConstraint(["course_id", "version"], [CourseVersion.course_id, CourseVersion.version], ondelete="RESTRICT")


class Enrollment(AcademyBase):
    __tablename__ = "bsv_learning_enrollments"
    tr_code: Mapped[str] = mapped_column(ForeignKey(Person.tr_code, ondelete="RESTRICT"), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (version_fk(),)


def enrollment_fk():
    return ForeignKeyConstraint(["tr_code", "course_id", "version"], [Enrollment.tr_code, Enrollment.course_id, Enrollment.version], ondelete="RESTRICT")


class Attempt(AcademyBase):
    __tablename__ = "bsv_learning_attempts"
    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tr_code: Mapped[str] = mapped_column(String(7))
    course_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    score: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    graded_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    request_id: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        enrollment_fk(),
        UniqueConstraint("tr_code", "course_id", "version", "ordinal", name="learning_attempt_number"),
        UniqueConstraint("tr_code", "course_id", "version", "request_id", name="learning_attempt_request"),
    )


class Practical(AcademyBase):
    __tablename__ = "bsv_learning_practical_reviews"
    review_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tr_code: Mapped[str] = mapped_column(String(7))
    course_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    reviewer: Mapped[str] = mapped_column(ForeignKey(Person.tr_code, ondelete="RESTRICT"))
    decision: Mapped[str] = mapped_column(String(12))
    evidence_ref: Mapped[str] = mapped_column(String(160))
    reason: Mapped[str] = mapped_column(String(500))
    attempt_id: Mapped[str] = mapped_column(ForeignKey(Attempt.attempt_id, ondelete="RESTRICT"))
    reviewed_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        enrollment_fk(), CheckConstraint("tr_code <> reviewer", name="learning_practical_independent"),
        CheckConstraint("decision IN ('verified','rejected')", name="learning_practical_decision"),
        UniqueConstraint("tr_code", "course_id", "version", "evidence_ref", name="learning_practical_evidence_unique"),
    )


class Credential(AcademyBase):
    __tablename__ = "bsv_learning_credentials"
    credential_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tr_code: Mapped[str] = mapped_column(String(7))
    course_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    review_id: Mapped[str] = mapped_column(ForeignKey(Practical.review_id, ondelete="RESTRICT"), unique=True)
    status: Mapped[str] = mapped_column(String(12), default="eligible")
    issued_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        enrollment_fk(),
        CheckConstraint("status IN ('eligible','revoked','suspended')", name="learning_credential_status"),
        Index("learning_credential_scope", "tr_code", "course_id", "version"),
    )


class Media(AcademyBase):
    __tablename__ = "bsv_learning_assets"
    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(120))
    mime: Mapped[str] = mapped_column(String(40))
    rights_ref: Mapped[str] = mapped_column(String(160))
    digest: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    scanned_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (version_fk(), UniqueConstraint("course_id", "version", "digest", name="learning_asset_unique"),)


class Shift(AcademyBase):
    __tablename__ = "bsv_workforce_shift_assignments"
    shift_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    tr_code: Mapped[str] = mapped_column(ForeignKey(Person.tr_code, ondelete="RESTRICT"))
    legal_entity_id: Mapped[str] = mapped_column(String(80))
    store_id: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(24))
    start_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    creator: Mapped[str] = mapped_column(ForeignKey(Person.tr_code, ondelete="RESTRICT"))
    approver: Mapped[str | None] = mapped_column(ForeignKey(Person.tr_code, ondelete="RESTRICT"))
    replaces_shift_id: Mapped[str | None] = mapped_column(ForeignKey("bsv_workforce_shift_assignments.shift_id", ondelete="RESTRICT"))
    confirmed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','confirmed','cancelled','replaced')", name="workforce_shift_status"),
        CheckConstraint("start_at < end_at", name="workforce_shift_interval"),
        CheckConstraint("approver IS NULL OR (approver <> tr_code AND approver <> creator)", name="workforce_shift_approval"),
        Index("workforce_shift_person_time", "tr_code", "start_at", "end_at"),
        Index("workforce_shift_replacement", "replaces_shift_id", "status"),
    )


class Device(AcademyBase):
    __tablename__ = "bsv_identity_store_devices"
    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    legal_entity_id: Mapped[str] = mapped_column(String(80))
    store_id: Mapped[str] = mapped_column(String(80))
    token_digest: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(12), default="registered")
    registered_by: Mapped[str] = mapped_column(ForeignKey(Person.tr_code, ondelete="RESTRICT"))
    registered_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    revoked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("state IN ('registered','revoked')", name="identity_device_state"),)
