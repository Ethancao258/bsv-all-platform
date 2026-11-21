"""Customer consent and POS-scoped access, independent of UI fixture state."""
import base64, hashlib, hmac, importlib, json, os, time
from pathlib import Path

os.environ['BSV_GROWTH_ENV'] = 'isolated'
os.environ['BSV_GROWTH_DB_URL'] = 'sqlite:///file:pref_suite?mode=memory&cache=shared&uri=true'
os.environ['BSV_GROWTH_SIGNING_KEY'] = 'ISOLATED-ONLY-SIGNING-KEY-TEST-1234567890'
os.environ['BSV_GROWTH_POS_CONTEXT_KEY'] = 'ISOLATED-ONLY-POS-CONTEXT-KEY-1234567890'
os.environ['BSV_GROWTH_SIGNATURE_KEY'] = 'dPN4xVuZL1lXzkdB5BrD60WIz3WZBcPBGhSuTCmTX-A='
os.environ['BSV_GROWTH_ALLOWED_ORIGINS'] = 'http://testserver'

from fastapi.testclient import TestClient
from services.api.customer_growth.app import app, Base, engine
# Earlier tests may import the module before this suite configures its independent POS key.
importlib.import_module("services.api.customer_growth.app").POS_CONTEXT_KEY = os.environ["BSV_GROWTH_POS_CONTEXT_KEY"]


def post(client, path, payload):
    return client.post('/api/v1/growth' + path, json=payload,
                       headers={'X-Growth-CSRF':client.cookies.get('bsv_growth_csrf',
                                              client.cookies.get('bsv_dev_csrf', ''))})


def context(customer_id, *, store_id='BSVS', visit_id='VISIT-0001', exp_offset=90):
    obj={'customer_id': customer_id, 'store_id': store_id, 'visit_id':visit_id,
         'iat':int(time.time()), 'exp':int(time.time())+exp_offset}
    body=base64.urlsafe_b64encode(json.dumps(obj,separators=(',',':')).encode()).decode().rstrip('=')
    mac=hmac.new(os.environ['BSV_GROWTH_POS_CONTEXT_KEY'].encode(),body.encode(),hashlib.sha256).hexdigest()
    return body+'.'+mac


def setup_customer_and_staff():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    guest,staff,other=TestClient(app),TestClient(app),TestClient(app)
    assert post(guest,'/dev/guest-login',{'subject':'taste-user','store_id':'BSVS'}).status_code==200
    res=post(guest,'/public/register',{'privacy_accepted':True,'display_name':'客人'});assert res.status_code==200
    assert post(staff,'/dev/staff-login',{'tr':'TRA0001','role':'staff','name':'现场员工','store_id':'BSVS'}).status_code==200
    return guest,staff,other,res.json()['customer_id']


def test_customer_opt_in_and_pos_scope():
    guest,staff,other,cid=setup_customer_and_staff()
    token=context(cid)
    route='/api/v1/growth/staff/guest-context?context='+token
    assert staff.get(route).json()['tags']==[]
    assert other.get(route).status_code==401
    assert staff.get('/api/v1/growth/staff/guest-context?context=foo').status_code==403
    assert staff.get('/api/v1/growth/staff/guest-context?context='+context(cid,store_id='BSVT')).status_code==403
    assert staff.get('/api/v1/growth/staff/guest-context?context='+context(cid,exp_offset=-30)).status_code==403
    invalid=post(guest,'/public/taste',{'tags':['果香酸爽','不存在的标签'],'share_for_service':True})
    assert invalid.status_code==422
    assert post(guest,'/public/taste',{'tags':['果香酸爽','清爽轻盈'],'share_for_service':False}).status_code==200
    assert guest.get('/api/v1/growth/public/me').json()['taste']['tags']==['果香酸爽','清爽轻盈']
    assert staff.get(route).json()['tags']==[]
    assert post(guest,'/public/taste',{'tags':['果香酸爽'],'share_for_service':True}).status_code==200
    visible=staff.get(route).json();assert visible['tags']==['果香酸爽']
    assert 'phone' not in visible and 'order' not in visible and 'display_name' not in visible
    assert post(guest,'/public/taste',{'tags':['果香酸爽'],'share_for_service':False}).status_code==200
    assert staff.get(route).json()['tags']==[]


def test_no_internal_language_in_public_pages():
    for path in ('/member/','/member/privacy','/staff/growth/'):
        html=TestClient(app).get(path).text
        assert '测试' not in html and '演练' not in html and 'demo' not in html.lower()
        assert 'DEMO' not in html and 'localhost' not in html
    for path in ('/member/app.js','/staff/growth/app.js','/staff/growth/pos-entry.js'):
        assert TestClient(app).get(path).status_code==200
