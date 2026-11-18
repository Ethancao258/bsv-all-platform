from fastapi.testclient import TestClient
from services.api.supply.main import app

def test_health_and_ui():
    with TestClient(app) as c:
        assert c.get('/').status_code==200
        assert 'BSV' in c.get('/').text
        h=c.get('/api/health').json();assert h['mode']=='demo'
        assert len(h['source_aliases'])==7
        assert c.get('/api/items').status_code==200
        assert c.get('/api/stores').status_code==200
        assert c.get('/api/me',headers={'X-Demo-Actor':'NONE'}).status_code==401
        assert c.get('/api/stores',headers={'X-Demo-Actor':'DEMO-E02'}).json()['data'][0]['store_id']=='BSVS'

def test_preview_and_inspection():
    with TestClient(app) as c:
        assert c.post('/api/stock-count/preview',json={'store_id':'BSVS','item_id':'DEMO-P001',
                      'full_packages':2,'opened_count':1,'opened_percent':50},headers={'X-Demo-Actor':'DEMO-E02'}).json()['observation']['exact'] is False
        r=c.post('/api/reorder/preview',json={'confirmed_available':'8','usage_before_next':'3',
            'arrivals_before_next':'0','reserved':'0','expiry_before_next':'0',
            'demand_next_cycle':'10','safety_stock':'2','arrivals_next_cycle':'0','pack_size':'1'})
        assert r.json()['packages']==7
        r=c.post('/api/inspections',headers={'X-Demo-Actor':'DEMO-E02'},json={
            'request_id':'22222222-2222-4222-8222-222222222222','store_id':'BSVS',
            'results':{'expiry':'OK','temperature':'OK','hygiene':'ISSUE','equipment':'OK','pricing':'OK','previous_actions':'NOT_CHECKED'}})
        assert r.status_code==200 and r.json()['issues']==['hygiene']

def test_remote_guard_is_example():
    # Remote mode must never connect silently to placeholder domains.
    from services.api.supply.config import load_settings
    import os,pytest
    os.environ['BSV_MODE']='remote'
    try:
        with pytest.raises(ValueError):load_settings()
    finally:os.environ.pop('BSV_MODE',None)
