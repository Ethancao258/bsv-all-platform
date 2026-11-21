import base64, hashlib, hmac, json, os, sys, time
from pathlib import Path
from io import BytesIO

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
os.environ['BSV_GROWTH_ENV']='isolated'
os.environ['BSV_GROWTH_DB_URL']='sqlite:////tmp/bsv-growth-test-suite.sqlite3'
os.environ['BSV_GROWTH_SIGNING_KEY']='ISOLATED-TEST-SIGNING-KEY-100000000000000000000'
os.environ['BSV_GROWTH_PAYMENT_SIGNING_KEY']='ISOLATED-TEST-PAYMENT-KEY-100000000000000000000'

from fastapi.testclient import TestClient
from PIL import Image,ImageDraw
from services.api.customer_growth.app import app, Base, engine


def post(client,path,data,csrf=False):
    headers={}
    if csrf:
        headers['X-Growth-CSRF']=client.cookies.get('bsv_growth_csrf') or client.cookies.get('bsv_dev_csrf')
    return client.post('/api/v1/growth'+path,json=data,headers=headers)


def png():
    im=Image.new('RGBA',(250,80),'white')
    ImageDraw.Draw(im).line((10,20,70,40,180,40),fill='black',width=3)
    buf=BytesIO();im.save(buf,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()


def signed_payment(event):
    payload=json.dumps(event,separators=(',',':')).encode();ts=str(int(time.time()))
    mac=hmac.new(os.environ['BSV_GROWTH_PAYMENT_SIGNING_KEY'].encode(),ts.encode()+b'.'+payload,hashlib.sha256).hexdigest()
    return payload,{'X-Growth-Timestamp':ts,'X-Growth-Signature':mac,'Content-Type':'application/json'}


def test_complete_guest_to_staff_to_commission():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    staff=TestClient(app);guest=TestClient(app);hq=TestClient(app)
    assert post(staff,'/dev/staff-login',{'tr':'TRA0001','role':'staff','name':'演练员工','store_id':'BSVS'}).status_code==200
    assert post(hq,'/dev/staff-login',{'tr':'TRB0001','role':'hq','name':'总部','store_id':'BSVS'}).status_code==200
    assert post(hq,'/hq/commission-policy',{'store_id':'BSVS','version':'DEMO-V1','base_rate_bps':600},csrf=True).status_code==200
    assert post(guest,'/dev/guest-login',{'subject':'customer001','store_id':'BSVS'}).status_code==200
    reg=post(guest,'/public/register',{'privacy_accepted':True,'display_name':'一位客人','marketing_opt_in':False},csrf=True)
    assert reg.status_code==200,reg.text
    cid=reg.json()['customer_id']
    assert reg.json()['referral']=='AVAILABLE_FOR_CLAIM'
    assert post(staff,'/staff/claims?store_id=BSVS',{'ticket_id':'invalid','attested':True,'policy_version':'DEMO-V1'},csrf=True).status_code==409
    signature=post(staff,'/staff/signature?store_id=BSVS',{'full_name':'演练员工','png_data':png()},csrf=True)
    assert signature.status_code==200,signature.text
    assert staff.get('/api/v1/growth/staff/policy?store_id=BSVS').json()['base_rate_bps']==600
    queue=staff.get('/api/v1/growth/staff/queue?store_id=BSVS').json()['tickets']
    assert len(queue)==1
    claim=post(staff,'/staff/claims?store_id=BSVS',{'ticket_id':queue[0]['ticket_id'],'attested':True,'policy_version':'DEMO-V1'},csrf=True)
    assert claim.status_code==200,claim.text
    claimid=claim.json()['claim_id']
    unauthorized=post(staff,'/public/claims/'+claimid+'/confirm',{'confirmed':True},csrf=True)
    assert unauthorized.status_code==401
    confirm=post(guest,'/public/claims/'+claimid+'/confirm',{'confirmed':True},csrf=True)
    assert confirm.status_code==200
    assert confirm.json()['status']=='CONFIRMED'
    pay={'event_id':'EV-001','action':'PAID','order_id':'ORDER-001','customer_id':cid,'store_id':'BSVS','amount_minor':30000}
    payload,headers=signed_payment(pay)
    response=guest.post('/api/v1/growth/internal/payment-event',content=payload,headers=headers)
    assert response.status_code==200,response.text
    assert response.json()['commission_status']=='PROVISIONAL_NOT_PAYABLE'
    assert response.json()['provisional_commission_minor']==1800
    assert guest.post('/api/v1/growth/internal/payment-event',content=payload,headers=headers).json()['duplicate'] is True
    refund={**pay,'event_id':'EV-002','action':'REFUNDED','amount_minor':10000}
    payload2,headers2=signed_payment(refund)
    response=guest.post('/api/v1/growth/internal/payment-event',content=payload2,headers=headers2)
    assert response.status_code==200,response.text
    assert response.json()['provisional_commission_minor']==1200
    badsig=guest.post('/api/v1/growth/internal/payment-event',content=payload,headers={'X-Growth-Timestamp':'1','X-Growth-Signature':'x'})
    assert badsig.status_code==401
    assert guest.get('/api/v1/growth/public/me').json()['membership_status']=='ACTIVE'


def test_online_invite_beats_onsite_claim():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    staff=TestClient(app);guest=TestClient(app)
    post(staff,'/dev/staff-login',{'tr':'TRA0001','role':'staff','name':'演练员工','store_id':'BSVS'})
    invite=post(staff,'/staff/invite?store_id=BSVS',{},csrf=True).json()['invite']
    post(guest,'/dev/guest-login',{'subject':'customer002','store_id':'BSVS','invite':invite})
    reg=post(guest,'/public/register',{'privacy_accepted':True},csrf=True)
    assert reg.status_code==200,reg.text
    assert reg.json()['referral']=='PREBOUND'
    assert staff.get('/api/v1/growth/staff/queue?store_id=BSVS').json()['tickets']==[]
    assert post(guest,'/public/register',{'privacy_accepted':True},csrf=True).json()['already_registered'] is True


def test_single_use_benefit_reservation_and_privacy():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    guest=TestClient(app)
    post(guest,'/dev/guest-login',{'subject':'benefit-member','store_id':'BSVS'})
    reg=post(guest,'/public/register',{'privacy_accepted':True,'marketing_opt_in':True},csrf=True)
    cid=reg.json()['customer_id']
    payment={'event_id':'EV-B1','action':'PAID','order_id':'ORDER-B1','customer_id':cid,'store_id':'BSVS','amount_minor':10000}
    body,headers=signed_payment(payment)
    assert guest.post('/api/v1/growth/internal/payment-event',content=body,headers=headers).status_code==200
    rights=guest.get('/api/v1/growth/public/me').json()['benefits']
    assert {x['kind'] for x in rights}=={'COMPANION_GIFT','RETURN_DISCOUNT'}
    reservation={'customer_id':cid,'store_id':'BSVS','order_id':'ORDER-B2','kind':'RETURN_DISCOUNT'}
    body,headers=signed_payment(reservation)
    hold=guest.post('/api/v1/growth/internal/benefits/reserve',content=body,headers=headers)
    assert hold.status_code==200,hold.text
    # A second order cannot obtain the same benefit while first hold is active.
    other={**reservation,'order_id':'ORDER-B3'}
    body2,headers2=signed_payment(other)
    assert guest.post('/api/v1/growth/internal/benefits/reserve',content=body2,headers=headers2).status_code==409
    second={**payment,'event_id':'EV-B2','order_id':'ORDER-B2'}
    body,headers=signed_payment(second)
    assert guest.post('/api/v1/growth/internal/payment-event',content=body,headers=headers).status_code==200
    kinds={x['kind'] for x in guest.get('/api/v1/growth/public/me').json()['benefits']}
    assert kinds=={'COMPANION_GIFT'}
    assert guest.post('/api/v1/growth/internal/benefits/reserve',content=body2,headers=headers2).status_code==409
    optout=post(guest,'/public/marketing-preference',{'marketing_opt_in':False},csrf=True)
    assert optout.status_code==200
    assert guest.get('/api/v1/growth/public/me').json()['marketing_opt_in'] is False
    delete=post(guest,'/public/delete-request',{},csrf=True)
    assert delete.status_code==200
    repeated=post(guest,'/public/delete-request',{},csrf=True)
    assert delete.json()['request_id']==repeated.json()['request_id']


def test_store_isolation_and_signature_versions():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    staff=TestClient(app)
    post(staff,'/dev/staff-login',{'tr':'TRA0001','role':'staff','name':'演练员工','store_id':'BSVS'})
    assert staff.get('/api/v1/growth/staff/queue?store_id=BSVM').status_code==403
    assert staff.get('/api/v1/growth/staff/invite-qr?store_id=BSVS').headers['content-type']=='image/png'
    a=post(staff,'/staff/signature?store_id=BSVS',{'full_name':'演练员工','png_data':png()},csrf=True)
    b=post(staff,'/staff/signature?store_id=BSVS',{'full_name':'演练员工','png_data':png()},csrf=True)
    assert a.status_code==200 and a.json()['signature_version']==1
    assert b.status_code==200 and b.json()['signature_version']==2
    assert post(staff,'/hq/commission-policy',{'store_id':'BSVS','version':'NOT-HQ','base_rate_bps':999},csrf=True).status_code==403
    assert staff.get('/member/').status_code==200
    assert staff.get('/staff/growth/').status_code==200
    assert staff.get('/member/app.js').status_code==200
    assert staff.get('/staff/growth/styles.css').status_code==200
    assert staff.get('/member/traversal').status_code==404


def test_hq_correction_requires_second_approver_and_preserves_finance():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    guest=TestClient(app);hq1=TestClient(app);hq2=TestClient(app)
    post(guest,'/dev/guest-login',{'subject':'error-attribution','store_id':'BSVS'})
    invite_actor=TestClient(app)
    post(invite_actor,'/dev/staff-login',{'tr':'TRA0001','role':'staff','name':'演练员工','store_id':'BSVS'})
    token=post(invite_actor,'/staff/invite?store_id=BSVS',{},csrf=True).json()['invite']
    post(guest,'/dev/guest-login',{'subject':'error-attribution','store_id':'BSVS','invite':token})
    customer=post(guest,'/public/register',{'privacy_accepted':True},csrf=True).json()['customer_id']
    post(hq1,'/dev/staff-login',{'tr':'TRC0001','role':'hq','name':'HQ-1','store_id':'BSVS'})
    post(hq2,'/dev/staff-login',{'tr':'TRD0001','role':'hq','name':'HQ-2','store_id':'BSVS'})
    proposal=post(hq1,'/hq/attribution-corrections',{'customer_id':customer,'proposed_actor_tr':'TRB0001',
        'reason':'线上邀请有错误证据，客户提供新的验证记录','evidence_ref':'audit-probe-001'},csrf=True)
    assert proposal.status_code==200,proposal.text
    cid=proposal.json()['correction_id']
    assert post(hq1,'/hq/attribution-corrections/'+cid+'/approve',{},csrf=True).status_code==403
    approved=post(hq2,'/hq/attribution-corrections/'+cid+'/approve',{},csrf=True)
    assert approved.status_code==200 and approved.json()['status']=='APPROVED'
    assert post(hq2,'/hq/attribution-corrections/'+cid+'/approve',{},csrf=True).status_code==404
