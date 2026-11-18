import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi import HTTPException
from services.api.supply.demo import DemoCentral

def rid():return str(uuid.uuid4())
@pytest.fixture
def env(tmp_path):
    c=DemoCentral(tmp_path/'central.sqlite3')
    a=c.actor('DEMO-E01');b=c.actor('DEMO-E02')
    return c,a,b

def build(env,n=10):
    c,a,_=env
    s=c.mutate('create',None,dict(request_id=rid(),source_store_id='DEMO-WH',dest_store_id='BSVS',
                                 lines=[{'item_id':'DEMO-P001','packages':n}]),a)
    c.mutate('prepare',s['id'],dict(request_id=rid(),expected_version=1),a)
    d=c.view(s['id'],a)
    codes=[p['code'] for p in d['packages']]
    return s['id'],codes

def dispatch(env,n=10):
    c,a,_=env;sid,codes=build(env,n)
    d=c.mutate('dispatch',sid,dict(request_id=rid(),expected_version=2,scanned_codes=codes),a)
    assert d['version']==3
    return sid,codes

def test_ten_nine_conservation(env):
    c,a,b=env
    sid,codes=dispatch(env,10)
    before={x['location']:x['qty'] for x in c.inventory(a,'') if x['item_id']=='DEMO-P001'}
    assert before['DEMO-WH']==30
    rec=c.mutate('receive',sid,dict(request_id=rid(),expected_version=3,scanned_codes=codes[:9],condition='ACCEPTED'),b)
    assert rec['state']=='PARTIAL_RECEIVED' and rec['pending_in_transit']==1
    after=c.inventory(a,'')
    assert any(x['location']=='BSVS' and x['qty']==9 for x in after)
    with c._conn() as conn:
        inv={x['location']:x['qty'] for x in conn.execute("SELECT location,qty FROM balances WHERE item_id='DEMO-P001'")}
    assert inv['DEMO-WH']==30 and inv['IN_TRANSIT:'+sid]==1 and inv['BSVS']==9
    assert sum(inv.values())==40

def test_idempotency_and_conflict(env):
    c,a,b=env
    sid,codes=dispatch(env,3)
    rq=rid();body=dict(request_id=rq,expected_version=3,scanned_codes=codes[:2],condition='ACCEPTED')
    first=c.mutate('receive',sid,body,b)
    assert c.mutate('receive',sid,body,b)==first
    with pytest.raises(HTTPException) as e:c.mutate('receive',sid,{**body,'scanned_codes':codes[:1]},b)
    assert e.value.status_code==409
    with pytest.raises(HTTPException):c.mutate('receive',sid,dict(request_id=rid(),expected_version=3,scanned_codes=codes[:1],condition='ACCEPTED'),b)
    with pytest.raises(HTTPException):c.mutate('receive',sid,dict(request_id=rid(),expected_version=4,scanned_codes=codes[:1],condition='ACCEPTED'),b)

def test_two_users_same_package_one_commit(env):
    c,a,b=env
    sid,codes=dispatch(env,1)
    def f(receiver):
        try:return c.mutate('receive',sid,dict(request_id=rid(),expected_version=3,scanned_codes=codes,condition='ACCEPTED'),receiver)
        except HTTPException as e:return e.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(f,(a,b)))
    assert sum(isinstance(x,dict) for x in results)==1
    assert sum(x==409 for x in results)==1
    assert c.view(sid,a)['received_count']==1

def test_inspector_authorization(env):
    c,a,b=env
    with pytest.raises(HTTPException) as e:c.authorize(b,'inspect','BSVM')
    assert e.value.status_code==403

def test_wrong_product_scan(env):
    c,a,b=env
    sid,codes=build(env,2)
    with pytest.raises(HTTPException) as e:c.mutate('dispatch',sid,dict(request_id=rid(),expected_version=2,scanned_codes=[codes[0]]),a)
    assert e.value.status_code==409
    assert c.view(sid,a)['state']=='READY'
