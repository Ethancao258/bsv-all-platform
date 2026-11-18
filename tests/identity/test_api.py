from datetime import datetime,timedelta,timezone
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from services.api.identity.api import app,router
from domains.workforce.identity.models import Grant,StageIssuance,AuthLink,LegacyAlias,Engagement
from .conftest import login_admin,admin_post,create_person,onboard,grant_action


def test_browser_pages_and_live_ready(client):
    for path in ("/","/staff","/hq","/assets/style.css","/assets/staff.js","/hq-assets/hq.js","/api/v1/openapi.json"):
        resp=client.get(path)
        if path.endswith('/openapi.json'):
            assert resp.status_code==404 # OpenAPI lives at /openapi.json; checked below
        else:assert resp.status_code==200,(path,resp.text[:100])
    assert client.get('/openapi.json').status_code==200
    assert client.get('/health/live').json()['status']=='alive'
    assert client.get('/health/ready').json()['database']=='A'
    assert 'width=device-width' in client.get('/staff').text


def test_no_login_no_admin_no_csrf(client):
    assert client.get('/api/v1/identity/me').status_code==401
    assert client.get('/api/v1/identity/admin/queue?legal_entity_id=DEMO_LEGAL').status_code==401
    admin=login_admin(1)
    resp=admin.post('/api/v1/identity/grants',json={})
    assert resp.status_code in (403,422) # Validation may precede CSRF, not authorization.
    bad=admin.post('/api/v1/identity/registrations',json={
        'idempotency_key':'no-csrf-key','legal_entity_id':'DEMO_LEGAL','display_label':'Fake','consent_version':'2026-11-18'})
    assert bad.status_code==403
    assert admin.get('/api/v1/identity/TRA9999/history').status_code==403


def test_complete_tr_emp_bm_and_cross_store_permission():
    user,one,two,tr,rid=create_person('apprentice1')
    assert tr=='TRA0003'
    me=user.get('/api/v1/identity/me').json()
    assert me['tr_code']==tr and me['emp_code'] is None and me['grants']==[]
    assert user.get('/api/v1/identity/TRA0001/history').status_code==403
    eng=onboard(tr,one,two,bm=True)
    me=user.get('/api/v1/identity/me').json()
    assert me['emp_code']=='EMPA0003' and me['bm_code']=='BMA0003'
    assert me['bm_active_entities']==['DEMO_LEGAL']
    gid=grant_action(tr,one,two,'pos.order.create',role='staff',qual='POS_SERVICE')
    assert user.get('/api/v1/identity/me').json()['grants'][0]['store_id']=='BSVT'
    token={'X-BSV-Service-ID':'pos','X-BSV-Service-Token':'synthetic-long-service-token-1111111111'}
    subject=one.get('/api/v1/auth/session').json() # not user subject, check in database
    with router.session() as db:
        actual=db.scalar(select(AuthLink.auth_subject_id).where(AuthLink.tr_code==tr))
    payload={'auth_subject_id':actual,'store_id':'BSVT','legal_entity_id':'DEMO_LEGAL','action':'pos.order.create'}
    assert user.post('/api/v1/identity/authorize',json=payload).status_code==401
    assert user.post('/api/v1/identity/authorize',json=payload,headers=token).json()['allowed']
    assert user.post('/api/v1/identity/authorize',json={**payload,'store_id':'BSVS'},headers=token).status_code==403
    assert user.post('/api/v1/identity/authorize',json={**payload,'legal_entity_id':'OTHER'},headers=token).status_code==403
    assert user.post('/api/v1/identity/authorize',json={**payload,'auth_subject_id':'unknown'},headers=token).json()['allowed'] is False
    r=admin_post(one,f'/api/v1/identity/grants/{gid}/revoke',{'legal_entity_id':'DEMO_LEGAL','reason':'Test immediate revocation'})
    assert r.status_code==200,r.text
    assert user.post('/api/v1/identity/authorize',json=payload,headers=token).json()['allowed'] is False
    assert user.get('/api/v1/identity/me').json()['bm_code']=='BMA0003'
    assert admin_post(one,f'/api/v1/identity/{tr}/bm/revoke',{'legal_entity_id':'DEMO_LEGAL','reason':'Test manager demotion'}).status_code==200
    assert user.get('/api/v1/identity/me').json()['bm_active_entities']==[]
    assert user.get('/api/v1/identity/me').json()['emp_code']=='EMPA0003'
    assert user.get(f'/api/v1/identity/{tr}/history').status_code==200


def test_emp_requires_approved_engagement_and_verified_qualification():
    user,one,two,tr,_=create_person('testlearner')
    r=admin_post(one,f'/api/v1/identity/{tr}/emp/requests',{'legal_entity_id':'DEMO_LEGAL','reason':'New employee review request'})
    assert r.status_code==201,r.text
    rid=r.json()['id']
    bad=admin_post(two,f'/api/v1/identity/{tr}/emp/issue',{'legal_entity_id':'DEMO_LEGAL','reason':'Candidate not yet engaged','request_id':rid})
    assert bad.status_code==409 and bad.json()['error']['code']=='ENGAGEMENT_REQUIRED'
    with router.session() as db:
        assert db.scalar(select(func.count()).select_from(StageIssuance).where(StageIssuance.tr_code==tr,StageIssuance.stage=='EMP'))==0


def test_self_bm_escalation_and_same_approver_forbidden():
    user,one,two,tr,_=create_person('newworker3')
    onboard(tr,one,two,bm=True)
    r=admin_post(user,f'/api/v1/identity/{tr}/bm/requests',{'legal_entity_id':'DEMO_LEGAL','reason':'I want to self appoint'})
    assert r.status_code==403
    r=admin_post(one,f'/api/v1/identity/{tr}/bm/requests',{'legal_entity_id':'DEMO_LEGAL','reason':'New additional BM request'})
    assert r.status_code==201
    rid=r.json()['id']
    r=admin_post(one,f'/api/v1/identity/{tr}/bm/issue',{'legal_entity_id':'DEMO_LEGAL','request_id':rid,'reason':'Self approve own management request'})
    assert r.status_code==403
    r=admin_post(two,f'/api/v1/identity/{tr}/bm/issue',{'legal_entity_id':'DEMO_LEGAL','request_id':rid,'reason':'Duplicate active management appointment'})
    assert r.status_code==409


def test_reemployment_reuses_stages_and_readonly_learning_after_end():
    user,one,two,tr,_=create_person('returnee4')
    eng=onboard(tr,one,two,bm=False)
    r=admin_post(one,f'/api/v1/identity/engagements/{eng}/end',{'legal_entity_id':'DEMO_LEGAL','reason':'End temporary contract for test'})
    assert r.status_code==200
    assert user.get('/api/v1/identity/me').status_code==401 # forced logout
    reauth=user.post('/api/v1/auth/isolated/login',json={'username':'returnee4','password':'example-only-password-22222'})
    assert reauth.status_code==200
    me=user.get('/api/v1/identity/me').json()
    assert me['tr_code']==tr and me['emp_code']=='EMPA0003' and me['active_legal_entities']==[]
    assert 'learning' in me['public_learning_url']
    assert user.get('/staff').status_code==200
    assert admin_post(one,f'/api/v1/identity/{tr}/emp/requests',{'legal_entity_id':'DEMO_LEGAL','reason':'Duplicate EMP after rehire'}).status_code==409


def test_legacy_dry_run_isolation_and_history():
    user,one,two,tr,_=create_person('legacy5')
    onboard(tr,one,two)
    payload={'legal_entity_id':'DEMO_LEGAL','rows':[{'source_system':'POS','legacy_value':'BM001','tr_code':tr}]}
    r=admin_post(one,'/api/v1/identity/legacy-import/dry-run',payload)
    assert r.status_code==200,r.text
    assert r.json()['write_count']==0
    with router.session() as db:assert db.scalar(select(func.count()).select_from(LegacyAlias))==0
    r=admin_post(one,'/api/v1/identity/legacy-import/commit',{**payload,'reason':'Manual alias review and signoff','evidence_ref':'SYNTHETIC-LEGACY-SOURCE'})
    assert r.status_code==200,r.text
    assert r.json()['write_count']==1
    r=admin_post(one,'/api/v1/identity/legacy-import/dry-run',payload)
    assert 'ALREADY_MAPPED' in r.json()['records'][0]['issues']


def test_failed_duplicate_alias_precheck_no_write():
    user,one,two,tr,_=create_person('legacy6')
    rows=[{'source_system':'POS','legacy_value':'EMP_OLDNAME','tr_code':tr},
          {'source_system':'POS','legacy_value':'EMP_OLDNAME','tr_code':'TRA0001'}]
    r=admin_post(one,'/api/v1/identity/legacy-import/dry-run',{'legal_entity_id':'DEMO_LEGAL','rows':rows})
    assert r.status_code==200 and r.json()['blocked']>=1
    r=admin_post(one,'/api/v1/identity/legacy-import/commit',{'legal_entity_id':'DEMO_LEGAL','rows':rows,
              'reason':'Unsafe mapping should fail precheck','evidence_ref':'SYNTHETIC-LEGACY'})
    assert r.status_code==409
    with router.session() as db: assert db.scalar(select(func.count()).select_from(LegacyAlias))==0


def test_non_owner_history_and_other_corporation_records_not_visible():
    user,one,two,tr,_=create_person('isolation7')
    onboard(tr,one,two)
    unauth=TestClient(app)
    assert unauth.get(f'/api/v1/identity/{tr}/history').status_code==401
    second=TestClient(app)
    second.post('/api/v1/auth/isolated/signup',json={'username':'otheruser7','password':'example-only-password-22222'})
    assert second.get(f'/api/v1/identity/{tr}/history').status_code==403
    assert second.get('/api/v1/identity/admin/people?legal_entity_id=DEMO_LEGAL').status_code==403
    assert one.get('/api/v1/identity/admin/people?legal_entity_id=OTHER').status_code==403


def test_no_worker_grant_from_fake_emp_bm_code():
    user,one,two,tr,_=create_person('fakeperm8')
    r=user.get('/api/v1/identity/me').json()
    assert r['emp_code'] is None
    with router.session() as db:
        subject=db.scalar(select(AuthLink.auth_subject_id).where(AuthLink.tr_code==tr))
    payload={'auth_subject_id':subject,'store_id':'BSVT','legal_entity_id':'DEMO_LEGAL','action':'pos.order.create'}
    token={'X-BSV-Service-ID':'pos','X-BSV-Service-Token':'synthetic-long-service-token-1111111111'}
    assert user.post('/api/v1/identity/authorize',json=payload,headers=token).json()['allowed'] is False
