from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select,func
from services.api.identity.api import router
from domains.workforce.identity.core import (CAPACITY,ALPHABET,DomainError,encode_index,stage_code,
                               register,verify_registration,approve_registration,
                               has_action,active_window,legacy_preview)
from domains.workforce.identity.models import (CodeAllocator,Registration,Person,StageIssuance,
                                 AuthLink,Engagement,Grant,Qualification,AuditEvent)


def test_code_space_exact_boundary():
    assert len(ALPHABET)==24
    assert CAPACITY==239976
    assert encode_index(0)=="TRA0001"
    assert encode_index(9998)=="TRA9999"
    assert encode_index(9999)=="TRB0001"
    assert encode_index(CAPACITY-1)=="TRZ9999"
    with pytest.raises(DomainError):encode_index(CAPACITY)
    assert stage_code("TRA0001","EMP")=="EMPA0001"
    assert stage_code("TRA0001","BM")=="BMA0001"
    with pytest.raises(DomainError):stage_code("TRA0000","EMP")


def test_atomic_rollback_and_no_code_reuse_after_approved():
    with pytest.raises(RuntimeError):
        with router.session(write=True) as db:
            a=db.get(CodeAllocator,1)
            a.next_index+=1
            db.add(Person(tr_code="TRA0003",display_label="synthetic"))
            raise RuntimeError("simulated server disconnect before commit")
    with router.session() as db:
        assert db.get(CodeAllocator,1).next_index==2 # two isolated admins
        assert db.get(Person,"TRA0003") is None


def test_100_concurrent_distinct_registration_and_code_allocations():
    n=100
    def submit(i):
        with router.session(write=True) as db:
            x=register(db,f"isolated:parallel-{i}",f"submit-{i:04d}-key","Test User",None,"TEST_PEPPER","DEMO_LEGAL")
            x.status="verified";x.verified_by="isolated:reviewer1";x.verification_reason="Verified synthetic request"
            return x.id
    with ThreadPoolExecutor(max_workers=20) as pool:
        request_ids=list(pool.map(submit,range(n)))
    assert len(set(request_ids))==n
    def issue(rid):
        with router.session(write=True) as db:
            return approve_registration(db,rid,"isolated:reviewer2","Independent approval").tr_code
    with ThreadPoolExecutor(max_workers=20) as pool:
        codes=list(pool.map(issue,request_ids))
    assert len(set(codes))==n
    with router.session() as db:
        assert db.scalar(select(func.count()).select_from(Person))==102
        assert db.get(CodeAllocator,1).next_index==102
        assert db.scalar(select(func.count()).select_from(StageIssuance).where(StageIssuance.stage=="TR"))==102
    assert codes.count("TRA0001")==0


def test_same_idempotency_key_same_tr_and_payload_conflict():
    with router.session(write=True) as db:
        r=register(db,"isolated:tester","repeat-abcdef","Synthetic",None,"pepper","DEMO_LEGAL")
        assert register(db,"isolated:tester","repeat-abcdef","Synthetic",None,"pepper","DEMO_LEGAL").id==r.id
        with pytest.raises(DomainError) as err:
            register(db,"isolated:tester","repeat-abcdef","Other",None,"pepper","DEMO_LEGAL")
        assert err.value.code=="IDEMPOTENCY_CONFLICT"
        r.status="verified";r.verified_by="verifier"
        assert approve_registration(db,r.id,"approver","approved in test").tr_code=="TRA0003"
        assert approve_registration(db,r.id,"approver","retry response").tr_code=="TRA0003"
    with router.session() as db:assert db.get(CodeAllocator,1).next_index==3


def test_same_display_name_is_not_auto_merged_but_same_proof_suspected():
    with router.session(write=True) as db:
        a=register(db,"isolated:usera","alpha-repeat","Same Name","proof-xyz","pepper","DEMO_LEGAL")
        b=register(db,"isolated:userb","bravo-repeat","Same Name","proof-xyz","pepper","DEMO_LEGAL")
        c=register(db,"isolated:userc","charlie-repeat","Same Name","other-proof","pepper","DEMO_LEGAL")
        assert a.status=="pending" and b.status=="needs_review" and c.status=="pending"
        with pytest.raises(DomainError):verify_registration(db,b.id,"reviewer","Evidence reviewed",False)
        verify_registration(db,b.id,"reviewer","Different synthetic natural person confirmed",True)


def test_missing_orphan_qualification_rejected_and_iso_window():
    start=datetime.now(timezone.utc)-timedelta(days=1)
    end=datetime.now(timezone.utc)-timedelta(seconds=1)
    assert not active_window(start,end)
    with pytest.raises(Exception):
        with router.session(write=True) as db:
            db.add(Qualification(tr_code="TRZ9999",qualification_code="EMP_ONBOARDING",
                                 learning_credential_id="orphan",source_evidence_ref="fixture-only",
                                 effective_from=start,verified_by="tester"))
            db.flush()


def test_manual_legacy_preview_never_writes():
    with router.session() as db:
        res=legacy_preview(db,[{"source_system":"POS","legacy_value":"BM001","tr_code":"TRA0001"},
                               {"source_system":"POS","legacy_value":"BM001","tr_code":"TRA0002"},
                               {"source_system":"old","legacy_value":"LongNameEMPId","tr_code":"TRZ9999"}], "DEMO_LEGAL")
        assert res["dry_run"] and res["write_count"]==0
        assert res["blocked"]==2
        assert "SAME_LEGACY_DIFFERENT_TR" in res["records"][1]["issues"]


def test_production_runtime_blocks_isolated_auth(monkeypatch):
    from services.api.identity.config import load_settings
    monkeypatch.setenv("BSV_APP_ENV","production")
    monkeypatch.setenv("BSV_AUTH_PROVIDER","isolated")
    with pytest.raises(RuntimeError,match="Production refuses"):
        load_settings()
