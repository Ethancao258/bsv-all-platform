"""Run against the dedicated PostgreSQL 17 instance migrated by the test launcher."""
from concurrent.futures import ThreadPoolExecutor
import os

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, DBAPIError

from services.api.identity.database import SourceRouter
from domains.workforce.identity.core import approve_registration, register, verify_registration
from domains.workforce.identity.models import Base, IsolatedBase, CodeAllocator, Person, Registration

router = SourceRouter()
with router.a.connect() as conn:
    assert int(conn.exec_driver_sql("SHOW server_version_num").scalar_one()) // 10000 == 17
    actual = set(conn.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'").scalars())
    assert actual == set(Base.metadata.tables) | set(IsolatedBase.metadata.tables) | {"alembic_version"}, actual
    assert len(Base.metadata.tables) == 15


def enroll(index):
    with router.session(write=True) as db:
        application = register(db, f"pg:{index}", "synthetic-test-key", "Same synthetic label",
                               None, "non-production-pepper", "DEMO_LEGAL")
        verify_registration(db, application.id, "pg:verifier", "Synthetic identity review")
        return application.id


def issue(request_id):
    with router.session(write=True) as db:
        return approve_registration(db, request_id, "pg:approver", "Independent synthetic approval").tr_code


with ThreadPoolExecutor(max_workers=20) as pool:
    requests = list(pool.map(enroll, range(120)))
    codes = list(pool.map(issue, requests))
    repeat = list(pool.map(issue, [requests[0]] * 16))
assert len(set(codes)) == 120 and set(repeat) == {codes[0]}

with router.session() as db:
    assert db.scalar(select(func.count()).select_from(Person)) == 120
    assert db.get(CodeAllocator, 1).next_index == 120

request_id = enroll(121)
try:
    with router.session(write=True) as db:
        rolled = approve_registration(db, request_id, "pg:approver", "Intentional test rollback").tr_code
        raise RuntimeError("abort")
except RuntimeError as exc:
    assert str(exc) == "abort"
with router.session() as db:
    assert db.get(Person, rolled) is None and db.get(CodeAllocator, 1).next_index == 120
    assert db.get(Registration, request_id).status == "verified"
assert issue(request_id) == rolled
try:
    with router.session(write=True) as db:
        db.add(Person(tr_code=rolled, display_label="Duplicate key"))
except IntegrityError:
    pass
else:
    raise AssertionError("duplicate TR accepted")

for sql in (
        "DELETE FROM bsv_identity_people WHERE tr_code=:id",
        "UPDATE bsv_identity_people SET tr_code='TRZ9999' WHERE tr_code=:id",
        "DELETE FROM bsv_identity_stage_issuances WHERE tr_code=:id",
        "DELETE FROM bsv_identity_audit_events WHERE target_tr=:id"):
    try:
        with router.session(write=True) as db:
            db.execute(text(sql), {"id": rolled})
    except DBAPIError:
        continue
    raise AssertionError("historical mutation was accepted")

from datetime import timedelta
from domains.workforce.identity import core
from domains.workforce.identity.models import now, AuthSession
from domains.identity_access.identity.security import create_session, validate_session

subject = "pg:121"
legal = "DEMO_LEGAL"
start = now() - timedelta(minutes=5)
with router.session(write=True) as db:
    assert not core.has_action(db, subject, "pos.order.create", "BSVT", legal)
    engagement = core.make_engagement(db,rolled,legal,"part_time",start,None,"SYNTH-PG","pg:verifier")
    core.approve_engagement(db,engagement.id,"pg:approver","Separate employment approval")
    for code in ("EMP_ONBOARDING","BM_MANAGEMENT","POS_SERVICE"):
        core.attest_qualification(db,rolled,code,"pg:"+code,"SYNTH-PG",start,None,"pg:verifier",legal)
    for code in ("EMP","BM"):
        stage = core.request_stage(db,rolled,code,legal,"pg:verifier","PG stage request")
        assert core.issue_stage(db,rolled,code,stage.id,"pg:approver","Separate stage approval") == code+rolled[2:]
    grant = core.request_grant(db,rolled,legal,"BSVT","pos.order.create","manager",None,start,None,
                               "pg:verifier","Scoped PostgreSQL grant")
    core.approve_grant(db,grant.id,"pg:approver","Separate grant approval")
    assert core.has_action(db, subject, "pos.order.create", "BSVT", legal)
    assert not core.has_action(db, subject, "pos.order.create", "BSVS", legal)
    assert not core.has_action(db, subject, "pos.order.create", "BSVT", "OTHER-LEGAL")
    token, _ = create_session(db,subject)
    engagement_id = engagement.id
with router.session(write=True) as db:
    core.revoke_bm(db,rolled,legal,"pg:approver","Synthetic demotion")
    assert not core.has_action(db,subject,"pos.order.create","BSVT",legal)
    core.end_engagement(db,engagement_id,"pg:approver","Synthetic separation")
with router.session() as db:
    try:
        validate_session(db,token)
    except core.DomainError as exc:
        assert exc.status == 401
    else:
        raise AssertionError("Ended engagement retained a session")
    assert db.get(Person,rolled) is not None
    assert core.is_issued(db,rolled,"EMP") and core.is_issued(db,rolled,"BM")

with router.non_sensitive_reference_connection() as conn:
    assert conn.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
    try:
        conn.exec_driver_sql("UPDATE bsv_identity_code_allocator SET next_index=0")
    except DBAPIError:
        pass
    else:
        raise AssertionError("B accepted a mutation")

from services.api.identity.backup import create_archive, decrypt_to_isolated, make_key
from services.api.identity.config import load_settings
from sqlalchemy import create_engine

settings = load_settings()
make_key(settings.backup_key_file)
archive = create_archive(settings)
target = os.environ["BSV_IDENTITY_PG_RESTORE_URL"]
decrypt_to_isolated(archive, settings, target, dry_run=False)
restored = create_engine(target)
with restored.connect() as conn:
    assert conn.exec_driver_sql("SELECT count(*) FROM bsv_identity_people").scalar_one() == 121
    assert conn.exec_driver_sql("SELECT next_index FROM bsv_identity_code_allocator").scalar_one() == 121
restored.dispose()
print("PASS: PostgreSQL 17, 15 domain tables, 120 concurrent persons, retry/rollback, immutable facts, scoped stages/revocation, read-only B and encrypted isolated restore")
