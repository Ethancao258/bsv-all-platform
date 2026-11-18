"""Second-pass adversarial findings: scope, rebind, lifetime, mandatory skills, fail-closed."""
from datetime import datetime,timezone,timedelta
from contextlib import contextmanager
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from sqlalchemy.exc import OperationalError
from .conftest import create_person,onboard,grant_action,admin_post,login_admin
from services.api.identity.api import app,router
from domains.workforce.identity.models import (Person,AuthLink,Grant,Engagement,ManagementAppointment,
                                 StageIssuance,Registration,CodeAllocator,Qualification)
from domains.workforce.identity.core import (DomainError,has_action,active_qualification,stage_code,
                               request_grant,active_engagement,register)


def test_required_pos_qualification_cannot_be_removed_or_swapped():
    user,one,two,tr,_=create_person('qhard1')
    onboard(tr,one,two,bm=False)
    from datetime import datetime,timezone
    start=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    base={"tr_code":tr,"legal_entity_id":"DEMO_LEGAL","store_id":"BSVT","role":"staff",
          "action":"pos.order.create","valid_from":start,"reason":"Test mandatory POS qualification"}
    bad=admin_post(one,'/api/v1/identity/grants',{**base,'required_qualification':'EMP_ONBOARDING'})
    assert bad.status_code==422 and bad.json()['error']['code']=='QUALIFICATION_MISMATCH'
    pending=admin_post(one,'/api/v1/identity/grants',base)
    assert pending.status_code==201,pending.text
    gid=pending.json()['grant_id']
    approve=admin_post(two,f'/api/v1/identity/grants/{gid}/approve',
                       {'legal_entity_id':'DEMO_LEGAL','reason':'Review without POS qualification'})
    assert approve.status_code==409 and approve.json()['error']['code']=='QUALIFICATION_REQUIRED'
    with router.session() as db:assert db.get(Grant,gid).required_qualification=='POS_SERVICE'


def test_no_global_pos_grant_for_hq_or_staff():
    user,one,two,tr,_=create_person('scope2')
    onboard(tr,one,two,bm=True)
    start=datetime.now(timezone.utc)-timedelta(minutes=1)
    for role in ('staff','hq'):
        bad=admin_post(one,'/api/v1/identity/grants',{
            'tr_code':tr,'legal_entity_id':'DEMO_LEGAL','store_id':None,
            'role':role,'action':'pos.order.create','valid_from':start.isoformat(),
            'reason':'Try broadening store permissions'})
        assert bad.status_code==422


def test_two_parallel_engagements_do_not_wrongly_remove_rights():
    user,one,two,tr,_=create_person('parallel3')
    first=onboard(tr,one,two,bm=True)
    second=admin_post(one,'/api/v1/identity/engagements',{
        'tr_code':tr,'legal_entity_id':'DEMO_LEGAL','type':'contractor',
        'effective_from':(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat(),
        'evidence_ref':'SYNTHETIC-PARALLEL-RECORD'}).json()['id']
    approved=admin_post(two,f'/api/v1/identity/engagements/{second}/approve',
                       {'legal_entity_id':'DEMO_LEGAL','reason':'Second verified legal engagement'})
    assert approved.status_code==200
    gid=grant_action(tr,one,two,'pos.order.create',role='staff',qual='POS_SERVICE')
    assert admin_post(one,f'/api/v1/identity/engagements/{first}/end',
            {'legal_entity_id':'DEMO_LEGAL','reason':'First relationship finished'}).status_code==200
    with router.session() as db:
        assert db.get(Grant,gid).status=='active'
        assert active_engagement(db,tr,'DEMO_LEGAL')
    assert user.get('/api/v1/identity/me').status_code==200
    assert admin_post(one,f'/api/v1/identity/engagements/{second}/end',
            {'legal_entity_id':'DEMO_LEGAL','reason':'Last relationship finished'}).status_code==200
    with router.session() as db:
        assert db.get(Grant,gid).status=='revoked'
        assert not active_engagement(db,tr,'DEMO_LEGAL')
    assert user.get('/api/v1/identity/me').status_code==401


def test_bm_management_qualification_expiry_removes_hq_rights():
    admin=login_admin(1)
    with router.session(write=True) as db:
        from domains.workforce.identity.models import Qualification
        q=db.scalar(select(Qualification).where(Qualification.tr_code=='TRA0001',
                                                 Qualification.qualification_code=='BM_MANAGEMENT'))
        q.effective_to=datetime.now(timezone.utc)-timedelta(minutes=1)
    assert admin.get('/api/v1/identity/admin/queue?legal_entity_id=DEMO_LEGAL').status_code==403
    with router.session() as db:
        assert not active_qualification(db,'TRA0001','BM_MANAGEMENT')


def test_cross_legal_entity_registration_queue_cannot_leak():
    one=login_admin(1)
    newcomer=TestClient(app)
    newcomer.post('/api/v1/auth/isolated/signup',json={'username':'enrollment4','password':'example-only-password-22222'})
    body={'idempotency_key':'app-unique-30303','display_label':'Synthetic outsider',
          'proof_hint':None,'legal_entity_id':'COMPANY_OTHER','consent_version':'2026-11-18'}
    rejected=admin_post(newcomer,'/api/v1/identity/registrations',body)
    assert rejected.status_code==422
    assert rejected.json()['error']['code']=='ENTITY_NOT_AVAILABLE'
    accepted=admin_post(newcomer,'/api/v1/identity/registrations',{**body,'legal_entity_id':'DEMO_LEGAL'})
    assert accepted.status_code==202
    q=one.get('/api/v1/identity/admin/queue?legal_entity_id=DEMO_LEGAL')
    assert any(r['id']==accepted.json()['registration_id'] for r in q.json()['registrations'])
    assert one.get('/api/v1/identity/admin/queue?legal_entity_id=COMPANY_OTHER').status_code==403


def test_two_person_recovery_rebind_preserves_one_tr_and_revokes_old_login():
    user,one,two,tr,_=create_person('recovery5')
    onboard(tr,one,two)
    replacement=TestClient(app)
    r=replacement.post('/api/v1/auth/isolated/signup',json={
        'username':'replacement5','password':'replacement-account-password-5555'})
    assert r.status_code==201
    from domains.workforce.identity.models import IsolatedUser
    with router.session() as db:
        sub=db.scalar(select(IsolatedUser.subject).where(IsolatedUser.username=='replacement5'))
        old_sub=db.scalar(select(AuthLink.auth_subject_id).where(AuthLink.tr_code==tr,AuthLink.revoked_at.is_(None)))
    r=admin_post(one,'/api/v1/identity/auth-recovery/requests',{
        'tr_code':tr,'legal_entity_id':'DEMO_LEGAL','new_auth_subject_id':sub,
        'evidence_ref':'SYNTHETIC-RECOVERY-PROOF'})
    assert r.status_code==201,r.text
    rid=r.json()['request_id']
    denied=admin_post(one,f'/api/v1/identity/auth-recovery/{rid}/approve',
        {'legal_entity_id':'DEMO_LEGAL','reason':'Requester cannot approve recovery'})
    assert denied.status_code==403
    approved=admin_post(two,f'/api/v1/identity/auth-recovery/{rid}/approve',
        {'legal_entity_id':'DEMO_LEGAL','reason':'Independent evidence review complete'})
    assert approved.status_code==200,approved.text
    assert user.get('/api/v1/identity/me').status_code==401
    assert replacement.get('/api/v1/identity/me').json()['tr_code']==tr
    with router.session() as db:
        assert db.get(CodeAllocator,1).next_index==3
        assert db.scalar(select(func.count()).select_from(Person))==3
        assert db.scalar(select(AuthLink.revoked_at).where(AuthLink.auth_subject_id==old_sub)) is not None
    r=user.post('/api/v1/auth/isolated/login',json={'username':'recovery5','password':'example-only-password-22222'})
    assert r.status_code==200
    new_app=admin_post(user,'/api/v1/identity/registrations',{
        'legal_entity_id':'DEMO_LEGAL','idempotency_key':'try-new-identity-00001',
        'display_label':'Attempt duplicate','consent_version':'2026-11-18'})
    assert new_app.status_code==409 and new_app.json()['error']['code']=='HISTORICAL_SUBJECT_LINK'


def test_recovery_rejects_unverified_or_already_bound_subjects():
    user,one,two,tr,_=create_person('rebind6')
    onboard(tr,one,two)
    r=admin_post(one,'/api/v1/identity/auth-recovery/requests',{
        'tr_code':tr,'legal_entity_id':'DEMO_LEGAL','new_auth_subject_id':'isolated:not-verified',
        'evidence_ref':'SYNTHETIC-RECOVERY'})
    assert r.status_code==422
    with router.session() as db:
        existing=db.scalar(select(AuthLink.auth_subject_id).where(AuthLink.tr_code=='TRA0001'))
    r=admin_post(one,'/api/v1/identity/auth-recovery/requests',{
        'tr_code':tr,'legal_entity_id':'DEMO_LEGAL','new_auth_subject_id':existing,
        'evidence_ref':'SYNTHETIC-RECOVERY'})
    assert r.status_code==409


def test_two_person_privacy_redaction_tombstone_not_reassign():
    user,one,two,tr,_=create_person('privacy7')
    onboard(tr,one,two)
    original=tr
    r=admin_post(one,'/api/v1/identity/redaction/requests',{
       'tr_code':tr,'legal_entity_id':'DEMO_LEGAL',
       'evidence_ref':'SYNTHETIC-PRIVACY-BASIS','reason':'Test privacy request with rights review'})
    assert r.status_code==201,r.text
    rid=r.json()['request_id']
    denied=admin_post(one,f'/api/v1/identity/redaction/{rid}/approve',
        {'legal_entity_id':'DEMO_LEGAL','reason':'Unsafe self approval should fail'})
    assert denied.status_code==403
    r=admin_post(two,f'/api/v1/identity/redaction/{rid}/approve',
        {'legal_entity_id':'DEMO_LEGAL','reason':'Independent legal retention and scope review'})
    assert r.status_code==200,r.text
    assert user.get('/api/v1/identity/me').status_code==401
    with router.session() as db:
        person=db.get(Person,tr)
        assert person.status=='tombstone' and person.display_label is None
        assert db.get(CodeAllocator,1).next_index==3
        assert db.scalar(select(func.count()).select_from(StageIssuance).where(StageIssuance.tr_code==tr,StageIssuance.stage=='TR'))==1


def test_authorization_fails_closed_if_source_A_unavailable(monkeypatch):
    user,one,two,tr,_=create_person('dbfail8')
    onboard(tr,one,two)
    from domains.workforce.identity.models import AuthLink
    with router.session() as db:
        subject=db.scalar(select(AuthLink.auth_subject_id).where(AuthLink.tr_code==tr))
    @contextmanager
    def broken(*args,**kwargs):
        raise OperationalError('SELECT 1',{},Exception('simulated database A outage'))
        yield
    monkeypatch.setattr(router,'session',broken)
    token={'X-BSV-Service-ID':'pos','X-BSV-Service-Token':'synthetic-long-service-token-1111111111'}
    payload={'auth_subject_id':subject,'store_id':'BSVT','legal_entity_id':'DEMO_LEGAL','action':'pos.order.create'}
    result=user.post('/api/v1/identity/authorize',json=payload,headers=token)
    assert result.status_code==503 and result.json()['error']['code']=='DB_UNAVAILABLE'
    assert user.get('/health/live').status_code==200
    assert user.get('/health/ready').status_code==503


def test_cross_origin_login_request_blocked():
    c=TestClient(app)
    r=c.post('/api/v1/auth/isolated/login',json={'username':'reviewer1','password':'synthetic-admin-password-one-2026'},
         headers={'Origin':'https://malicious.example'})
    assert r.status_code==403 and r.json()['error']['code']=='BAD_ORIGIN'


def test_user_cannot_bypass_auth_with_guessable_stage_codes():
    c=TestClient(app)
    for code in ('TRA0001','EMPA0001','BMA0001'):
        assert c.get('/api/v1/identity/me',headers={'X-Employee-Code':code}).status_code==401
    assert c.get('/api/v1/identity/TRA0001/history').status_code==401


def test_hq_history_cannot_read_other_entity_audit_events():
    from domains.workforce.identity.models import AuditEvent
    user,one,two,tr,_=create_person('audit9')
    onboard(tr,one,two)
    with router.session(write=True) as db:
        db.add(AuditEvent(event_type='other.entity.contract',target_tr=tr,
                legal_entity_id='OTHER_COMPANY',actor_subject='test-other-company',
                reason='Synthetic external legal entity event',details={"other_entity":True}))
    hq=one.get(f'/api/v1/identity/{tr}/history?legal_entity_id=DEMO_LEGAL')
    assert hq.status_code==200
    assert 'other.entity.contract' not in [x['event_type'] for x in hq.json()['events']]
    owner=user.get(f'/api/v1/identity/{tr}/history')
    assert owner.status_code==200
    assert 'other.entity.contract' in [x['event_type'] for x in owner.json()['events']]


def test_legacy_identical_old_code_can_exist_in_separate_legal_entities():
    from domains.workforce.identity.models import LegacyAlias
    from domains.workforce.identity.core import legacy_preview
    with router.session(write=True) as db:
        db.add(LegacyAlias(legal_entity_id='DEMO_LEGAL',source_system='POS',
                           legacy_value='BM001',tr_code='TRA0001',
                           approved_by='test',evidence_ref='synthetic-source'))
        db.add(LegacyAlias(legal_entity_id='OTHER_COMPANY',source_system='POS',
                           legacy_value='BM001',tr_code='TRA0002',
                           approved_by='test',evidence_ref='synthetic-source'))
    with router.session() as db:
        one=legacy_preview(db,[{'source_system':'POS','legacy_value':'BM001','tr_code':'TRA0001'}],
                           'DEMO_LEGAL')
        two=legacy_preview(db,[{'source_system':'POS','legacy_value':'BM001','tr_code':'TRA0002'}],
                           'OTHER_COMPANY')
        assert 'ALREADY_MAPPED' in one['records'][0]['issues']
        assert 'ALREADY_MAPPED' in two['records'][0]['issues']
        assert one['blocked']==0 and two['blocked']==0


def test_expiry_and_capacity_exhaustion_fail_without_reuse():
    from domains.workforce.identity.models import Registration
    from domains.workforce.identity.core import approve_registration, CAPACITY
    with router.session(write=True) as db:
        a=db.get(CodeAllocator,1)
        a.next_index=CAPACITY
        req=Registration(subject='isolated:capacity',requested_legal_entity_id='DEMO_LEGAL',
          idempotency_key='last-unique-request',request_digest='a'*64,
          display_label='Synthetic cap',consent_version='2026-11-18',
          status='verified',verified_by='synthetic-reviewer',
          expires_at=datetime.now(timezone.utc)+timedelta(days=1))
        db.add(req);db.flush();rid=req.id
    with pytest.raises(DomainError) as err:
        with router.session(write=True) as db:
            approve_registration(db,rid,'synthetic-approver','No capacity left')
    assert err.value.code=='CODE_POOL_EXHAUSTED'
    with router.session() as db:
        assert db.get(CodeAllocator,1).next_index==CAPACITY
        assert db.scalar(select(func.count()).select_from(Person))==2


def test_adversarial_same_idempotency_key_parallel_returns_exact_one_application():
    from domains.workforce.identity.core import register
    from concurrent.futures import ThreadPoolExecutor
    def one(_):
        with router.session(write=True) as db:
            return register(db,'isolated:single-verified-subject','constant-idempotence-0001',
                            'Synthetic repeated',None,'synthetic-pepper','DEMO_LEGAL').id
    with ThreadPoolExecutor(max_workers=16) as pool:
        ids=list(pool.map(one,range(100)))
    assert len(set(ids))==1
    with router.session() as db:
        assert db.scalar(select(func.count()).select_from(Registration).where(
            Registration.subject=='isolated:single-verified-subject'))==1
        assert db.get(CodeAllocator,1).next_index==2


def test_double_migration_safety_required_auth_config(monkeypatch):
    from services.api.identity.config import load_settings
    monkeypatch.setenv('BSV_APP_ENV','production')
    monkeypatch.setenv('BSV_AUTH_PROVIDER','cloudbase_jwks')
    monkeypatch.setenv('BSV_DB_A_URL','sqlite+pysqlite:///./runtime/test.db')
    with pytest.raises(RuntimeError,match='requires PostgreSQL'):
        load_settings()


def test_immutable_postgres_ddl_hooks_registered():
    from sqlalchemy import create_mock_engine
    from domains.workforce.identity.models import Base
    sql=[]
    engine=create_mock_engine('postgresql://', lambda stmt,*a,**kw:sql.append(str(stmt)))
    Base.metadata.create_all(engine)
    text='\n'.join(sql)
    assert 'CREATE TRIGGER bsv_identity_tr_permanent' in text
    assert 'bsv_identity_block_update_delete' in text
    assert 'CREATE OR REPLACE FUNCTION bsv_identity_reject_mutation' in text
    assert 'bsv_identity_audit_events' in text


def test_hq_of_one_legal_cannot_globally_suspend_another_entity_person():
    user,one,two,tr,_=create_person('crossentity-global1')
    # The applicant has identity history at DEMO_LEGAL only. The requested legal
    # scope is authoritative and cannot be changed using a guessed TR code.
    response=admin_post(one,f'/api/v1/identity/{tr}/suspend',
        {'legal_entity_id':'OTHER_COMPANY','reason':'Unauthorized company-wide suspension'})
    assert response.status_code==403
    # Once the person is genuinely employed in TWO entities, a local admin
    # cannot mutate global identity across both entities.
    with router.session(write=True) as db:
        db.add(Engagement(tr_code=tr,legal_entity_id='OTHER_COMPANY',type='contractor',
            effective_from=datetime.now(timezone.utc)-timedelta(days=2),
            evidence_ref='SYNTHETIC-OTHER-CONTRACT',status='active',
            created_by='OTHER-ADMIN',approved_by='OTHER-HR'))
    response=admin_post(one,f'/api/v1/identity/{tr}/suspend',
        {'legal_entity_id':'DEMO_LEGAL','reason':'Local admin trying global suspension'})
    assert response.status_code==409
    assert response.json()['error']['code']=='CROSS_ENTITY_GLOBAL_ACTION_LOCKED'
    with router.session() as db:assert db.get(Person,tr).status=='active'


def test_cross_legal_global_recovery_and_redaction_blocked():
    user,one,two,tr,_=create_person('crossglobal2')
    onboard(tr,one,two)
    with router.session(write=True) as db:
        db.add(Engagement(tr_code=tr,legal_entity_id='OTHER_COMPANY',type='contractor',
            effective_from=datetime.now(timezone.utc)-timedelta(days=2),
            evidence_ref='SYNTHETIC-SECOND-CORP',status='active',
            created_by='OTHER-ADMIN',approved_by='OTHER-HR'))
    response=admin_post(one,'/api/v1/identity/redaction/requests',
        {'tr_code':tr,'legal_entity_id':'DEMO_LEGAL',
         'reason':'Attempt at legal-wide irreversible data redaction',
         'evidence_ref':'SYNTHETIC-LEGAL-REQUEST'})
    assert response.status_code==409 and response.json()['error']['code']=='CROSS_ENTITY_GLOBAL_ACTION_LOCKED'
    replacement=TestClient(app)
    replacement.post('/api/v1/auth/isolated/signup',json={
        'username':'crossglobalreplacement','password':'SYNTHETIC-ACCOUNT-RECOVERY-0000'})
    from domains.workforce.identity.models import IsolatedUser
    with router.session() as db:
        sub=db.scalar(select(IsolatedUser.subject).where(IsolatedUser.username=='crossglobalreplacement'))
    response=admin_post(one,'/api/v1/identity/auth-recovery/requests',
        {'tr_code':tr,'legal_entity_id':'DEMO_LEGAL','new_auth_subject_id':sub,
         'evidence_ref':'SYNTHETIC-MULTI-ENTITY-RECOVERY'})
    assert response.status_code==409 and response.json()['error']['code']=='CROSS_ENTITY_GLOBAL_ACTION_LOCKED'
    assert user.get('/api/v1/identity/me').json()['tr_code']==tr
