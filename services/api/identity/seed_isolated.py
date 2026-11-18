"""Explicit, isolated-only synthetic dual administrators for end-to-end workflows.

NEVER use synthetic fixture identities on CloudBase or a production system.
"""
import argparse
import os
from datetime import timedelta
from sqlalchemy import select
from domains.workforce.identity.models import (Person, StageIssuance, AuthLink, IsolatedUser, Engagement,
                     ManagementAppointment, StageRequest, Qualification, Grant,
                     CodeAllocator, now, AuditEvent)
from domains.workforce.identity.core import encode_index, MANAGEMENT_ACTIONS, stage_code
from .config import load_settings
from .database import SourceRouter
from .cli import isolated_guard
from domains.identity_access.identity.security import create_isolated_user


def seed():
    s=load_settings()
    if s.env != "isolated" or s.auth_provider != "isolated":
        raise RuntimeError("Synthetic administrator bootstrap only allowed in isolated test")
    isolated_guard(s)
    url = s.db_a_url.lower()
    if "prod" in url or "cloudbase" in url:
        raise RuntimeError("Refusing to seed possible live database")
    secrets=[]
    for i in (1,2):
        u=os.getenv(f"BSV_DEMO_ADMIN_{i}_USERNAME",f"reviewer{i}")
        p=os.getenv(f"BSV_DEMO_ADMIN_{i}_PASSWORD","")
        if len(p)<14:raise RuntimeError(f"Set BSV_DEMO_ADMIN_{i}_PASSWORD with >=14 chars")
        secrets.append((u,p))
    legal=os.getenv("BSV_DEMO_LEGAL_ENTITY", "DEMO_LEGAL")
    d=SourceRouter(s)
    with d.session(write=True) as db:
        allocation=db.get(CodeAllocator,1)
        if not allocation:raise RuntimeError("Initialize schema first")
        for username,password in secrets:
            found=db.scalar(select(IsolatedUser).where(IsolatedUser.username==username))
            if found:
                print("EXISTING_DEMO_ADMIN",username)
                continue
            usr=create_isolated_user(db,username,password)
            tr=encode_index(allocation.next_index);allocation.next_index+=1
            db.add(Person(tr_code=tr,display_label="ISOLATED TEST OPERATOR "+username))
            db.flush()
            db.add(AuthLink(auth_subject_id=usr.subject,tr_code=tr,provider="isolated-fixture"))
            for stage in ("TR","EMP","BM"):
                db.add(StageIssuance(tr_code=tr,stage=stage,issued_by="system:isolated_seed",
                                     approval_ref="isolated-fixture",reason="Isolated test bootstrap only"))
            eng=Engagement(tr_code=tr,legal_entity_id=legal,type="employee",
                           effective_from=now()-timedelta(days=1),evidence_ref="SYNTHETIC-ENGAGEMENT",
                           status="active",created_by="system:isolated_seed",approved_by="system:isolated_seed")
            db.add(eng)
            q=Qualification(tr_code=tr,qualification_code="BM_MANAGEMENT",
                            learning_credential_id="SYNTHETIC-BM-"+tr,
                            source_evidence_ref="SYNTHETIC-LEARNING",effective_from=now()-timedelta(days=1),
                            verified_by="system:isolated_seed")
            db.add(q)
            stage_req=StageRequest(tr_code=tr,stage="BM",legal_entity_id=legal,
                                   requested_by="system:isolated_seed",reason="Synthetic fixture",
                                   status="approved",decided_by="system:isolated_seed",decided_at=now())
            db.add(stage_req);db.flush()
            db.add(ManagementAppointment(tr_code=tr,legal_entity_id=legal,stage_request_id=stage_req.id,
                                         valid_from=now()-timedelta(days=1),issued_by="system:isolated_seed"))
            for action in sorted(MANAGEMENT_ACTIONS):
                db.add(Grant(tr_code=tr,legal_entity_id=legal,role="hq",action=action,
                             valid_from=now()-timedelta(days=1),status="active",
                             requested_by="system:isolated_seed",approved_by="system:isolated_seed",
                             approved_at=now(),reason="Isolated test fixture ONLY"))
            db.add(AuditEvent(event_type="bootstrap.synthetic",target_tr=tr,
                              actor_subject="system:isolated_seed",reason="SYNTHETIC, non-production"))
            print("CREATED_SYNTHETIC_ADMIN",username,tr)


if __name__ == "__main__":
    p=argparse.ArgumentParser();p.add_argument("--i-understand-isolated",action="store_true")
    if not p.parse_args().i_understand_isolated:
        raise SystemExit("Explicit --i-understand-isolated required")
    seed()
