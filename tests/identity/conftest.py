"""100% synthetic local fixtures; never imports real employee data."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

TEST_DIR=Path(tempfile.mkdtemp(prefix="bsv-identity-tests-"))
os.environ["BSV_APP_ENV"]="isolated"
os.environ["BSV_AUTH_PROVIDER"]="isolated"
client_pg_url = (os.environ.get("BSV_DB_PREFLIGHT_STAGE_URL")
                 or os.environ.get("BSV_DB_PREFLIGHT_CLIENT_URL"))
if client_pg_url:
    from sqlalchemy.engine import make_url

    address = make_url(client_pg_url)
    allowed_databases = {"bsv_identity_isolated_clients"}
    if os.environ.get("BSV_DB_PREFLIGHT_STAGE_URL"):
        allowed_databases.add("bsv_identity_isolated_stage")
    if (address.drivername != "postgresql+psycopg" or address.host != "127.0.0.1"
            or address.database not in allowed_databases):
        raise RuntimeError("Use only a named disposable preflight or stage database on loopback")
os.environ["BSV_DB_A_URL"] = client_pg_url or "sqlite+pysqlite:///"+str(TEST_DIR/"identity.db")
os.environ["BSV_DEMO_ADMIN_1_PASSWORD"]="synthetic-admin-password-one-2026"
os.environ["BSV_DEMO_ADMIN_2_PASSWORD"]="synthetic-admin-password-two-2026"
os.environ["BSV_SERVICE_TOKENS_JSON"]='{"pos":{"token":"synthetic-long-service-token-1111111111","actions":["pos.order.create"],"legal_entities":["DEMO_LEGAL"],"stores":["BSVT"]}}'
os.environ["BSV_BACKUP_KEY_FILE"]=str(TEST_DIR/"test.key")
os.environ["BSV_LOCAL_ARCHIVE_DIR"]=str(TEST_DIR/"archives")

from services.api.identity.api import app, router, throttle
from domains.workforce.identity.models import Base, IsolatedBase, CodeAllocator
from services.api.identity.seed_isolated import seed


@pytest.fixture(autouse=True)
def reset_db():
    throttle.attempts.clear()
    stage_url = os.environ.get("BSV_DB_PREFLIGHT_STAGE_URL")
    if stage_url:
        # The stage-only Academy migration adds foreign keys from its tables to
        # identity tables. Reset this explicitly named loopback test database as
        # a unit, then replay the migration before seeding synthetic identities.
        # This branch is unreachable for local SQLite or the clients preflight DB.
        address = __import__("sqlalchemy.engine", fromlist=["make_url"]).make_url(stage_url)
        if address.host != "127.0.0.1" or address.database != "bsv_identity_isolated_stage":
            raise RuntimeError("Refusing schema reset outside the disposable isolated-stage database")
        with router.a.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA public CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA public")
        router.a.dispose()
        root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["BSV_DB_A_URL"] = stage_url
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c",
             str(root / "platform/lighthouse/identity/alembic.ini"),
             "upgrade", "bsv_academy_0002"],
            cwd=root, env=env, check=True,
        )
    else:
        IsolatedBase.metadata.drop_all(router.a)
        Base.metadata.drop_all(router.a)
    Base.metadata.create_all(router.a)
    IsolatedBase.metadata.create_all(router.a)
    with router.session(write=True) as db:
        db.add(CodeAllocator(id=1,next_index=0))
    seed()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:yield c


def login_admin(index):
    client=TestClient(app)
    pw=os.getenv(f"BSV_DEMO_ADMIN_{index}_PASSWORD")
    r=client.post("/api/v1/auth/isolated/login",json={"username":f"reviewer{index}","password":pw})
    assert r.status_code==200, r.text
    return client


def admin_post(client,path,payload):
    return client.post(path,json=payload,headers={"X-CSRF-Token":client.cookies.get("bsv_csrf","")})


def create_person(tag="testperson",hint=None):
    user=TestClient(app)
    r=user.post("/api/v1/auth/isolated/signup",json={"username":tag,"password":"example-only-password-22222"})
    assert r.status_code==201, r.text
    r=admin_post(user,"/api/v1/identity/registrations",{"idempotency_key":tag+"-request-123456",
             "display_label":"SYNTHETIC "+tag,"proof_hint":hint,"legal_entity_id":"DEMO_LEGAL","consent_version":"2026-11-18"})
    assert r.status_code==202,r.text
    rid=r.json()["registration_id"]
    one,two=login_admin(1),login_admin(2)
    r=admin_post(one,f"/api/v1/identity/registrations/{rid}/verify",
                 {"legal_entity_id":"DEMO_LEGAL","reason":"Verified synthetic identity for isolated tests",
                  "separate_person_confirmed":bool(hint)})
    assert r.status_code==200,r.text
    r=admin_post(two,f"/api/v1/identity/registrations/{rid}/approve",
                 {"legal_entity_id":"DEMO_LEGAL","reason":"Approved independent synthetic identity"})
    assert r.status_code==200,r.text
    return user,one,two,r.json()["tr_code"],rid


def onboard(tr,one,two,bm=False):
    from datetime import datetime, timezone, timedelta
    start=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
    r=admin_post(one,"/api/v1/identity/engagements",{"tr_code":tr,"legal_entity_id":"DEMO_LEGAL",
            "type":"part_time","effective_from":start,"evidence_ref":"SYNTHETIC-HR-DOCUMENT"})
    assert r.status_code==201,r.text
    eng=r.json()["id"]
    r=admin_post(two,f"/api/v1/identity/engagements/{eng}/approve",
             {"legal_entity_id":"DEMO_LEGAL","reason":"Independent approval of synthetic relation"})
    assert r.status_code==200,r.text
    for qual in (["EMP_ONBOARDING","BM_MANAGEMENT","POS_SERVICE"] if bm else ["EMP_ONBOARDING"]):
        r=admin_post(one,"/api/v1/identity/qualifications",{"tr_code":tr,"legal_entity_id":"DEMO_LEGAL",
           "qualification_code":qual,"learning_credential_id":"SYNTH-"+qual+tr,
           "source_evidence_ref":"SYNTH-LEARNING-EVIDENCE","effective_from":start})
        assert r.status_code==201,r.text
    for stage in (["emp","bm"] if bm else ["emp"]):
        r=admin_post(one,f"/api/v1/identity/{tr}/{stage}/requests",
                     {"legal_entity_id":"DEMO_LEGAL","reason":"Qualified controlled stage request"})
        assert r.status_code==201,r.text
        r=admin_post(two,f"/api/v1/identity/{tr}/{stage}/issue",
                     {"legal_entity_id":"DEMO_LEGAL","reason":"Independent approved issuance",
                      "request_id":r.json()["id"]})
        assert r.status_code==200,r.text
    return eng


def grant_action(tr,one,two,action,store="BSVT",role="staff",qual=None):
    from datetime import datetime,timezone,timedelta
    start=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    r=admin_post(one,"/api/v1/identity/grants",{"tr_code":tr,"legal_entity_id":"DEMO_LEGAL",
                  "store_id":store,"role":role,"action":action,"required_qualification":qual,
                  "valid_from":start,"reason":"Synthetic least privilege test grant"})
    assert r.status_code==201,r.text
    gid=r.json()["grant_id"]
    r=admin_post(two,f"/api/v1/identity/grants/{gid}/approve",{"legal_entity_id":"DEMO_LEGAL",
                  "reason":"Independent grant approval for tests"})
    assert r.status_code==200,r.text
    return gid
