import json,uuid
from dataclasses import replace
from pathlib import Path
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from services.api.supply.main import app
from services.api.supply.cache import LocalCache
from services.api.supply.config import load_settings
from services.api.supply.backup import make_snapshot,verify_snapshot

def new_id():return str(uuid.uuid4())

def test_http_create_prepare_dispatch_receive_nine_of_ten():
    with TestClient(app) as c:
        r=c.post('/api/shipments',json={'request_id':new_id(),'source_store_id':'DEMO-WH','dest_store_id':'BSVS',
                                         'lines':[{'item_id':'DEMO-P001','packages':10}]})
        assert r.status_code==200, r.text
        sid=r.json()['id']
        assert c.post(f'/api/shipments/{sid}/prepare',json={'request_id':new_id(),'expected_version':1}).json()['version']==2
        detail=c.get(f'/api/shipments/{sid}').json()['data']
        codes=[p['code'] for p in detail['packages']]
        r=c.post(f'/api/shipments/{sid}/dispatch',json={'request_id':new_id(),'expected_version':2,'scanned_codes':codes})
        assert r.status_code==200, r.text
        assert r.json()['state']=='DISPATCHED'
        r=c.post(f'/api/shipments/{sid}/receive',headers={'X-Demo-Actor':'DEMO-E02'},json={
            'request_id':new_id(),'expected_version':3,'scanned_codes':codes[:9],'condition':'ACCEPTED'})
        assert r.status_code==200 and r.json()['pending_in_transit']==1
        detail=c.get(f'/api/shipments/{sid}',headers={'X-Demo-Actor':'DEMO-E02'}).json()['data']
        assert detail['received_count']==9 and detail['state']=='PARTIAL_RECEIVED'
        # The receiving employee sees the appropriate in-transit line in their authorized view.
        v=c.get('/api/inventory?store_id=BSVS',headers={'X-Demo-Actor':'DEMO-E02'}).json()['data']
        assert any(x['location']=='BSVS' and x['item_id']=='DEMO-P001' and x['qty']>=9 for x in v)
        assert any(x['location']=='IN_TRANSIT:'+sid and x['item_id']=='DEMO-P001' and x['qty']==1 for x in v)
        assert c.post(f'/api/shipments/{sid}/receive',headers={'X-Demo-Actor':'DEMO-E02'},json={
            'request_id':new_id(),'expected_version':3,'scanned_codes':codes[9:],'condition':'ACCEPTED'}).status_code==409

def test_real_v9_reference_remains_unapproved_and_admin_only():
    with TestClient(app) as c:
        assert c.get('/api/v9-reference',headers={'X-Demo-Actor':'DEMO-E02'}).status_code==403
        ref=c.get('/api/v9-reference').json()
        assert ref['reference_only'] is True
        assert any(x['id']=='P000015' for x in ref['p'])
        assert all(item['item_id'].startswith('DEMO-') for item in c.get('/api/items').json()['data'])

def test_idempotent_inspection_and_count(tmp_path):
    from services.api.supply.demo import DemoCentral
    c=DemoCentral(tmp_path/'demo.sqlite3');me=c.actor('DEMO-E01')
    ins=dict(request_id=new_id(),store_id='BSVS',results={k:'OK' for k in
        ['expiry','temperature','hygiene','equipment','pricing','previous_actions']})
    first=c.inspect(ins,me)
    assert c.inspect(ins,me)==first
    count=dict(request_id=new_id(),store_id='BSVS',item_id='DEMO-P001',full_packages=2,opened_count=1,opened_percent=50)
    obs={'method':'FIVE_BUCKET','estimated_packages':'2.5','exact':False}
    a=c.record_count(count,me,obs)
    assert c.record_count(count,me,obs)==a
    assert len(c.counts(me))==1

class FakeGateway:
    def read(self,key,path,**kwargs):return {'data':{'code':key,'path':path},'meta':{'source':'PRIMARY'}}

def test_real_encrypted_api_snapshot_roundtrip(tmp_path,monkeypatch):
    original=load_settings();settings=replace(original,mode='remote',backup_dir=tmp_path)
    monkeypatch.setenv('BSV_BACKUP_FERNET_KEY',Fernet.generate_key().decode())
    result=make_snapshot(settings,FakeGateway())
    assert result['datasets']>=2
    v=verify_snapshot(Path(result['file']))
    assert v['sha256']==result['sha256'] and len(v['datasets'])==result['datasets']
    # File bytes contain no plaintext JSON field of a dataset.
    assert b'"datasets"' not in Path(result['file']).read_bytes()
