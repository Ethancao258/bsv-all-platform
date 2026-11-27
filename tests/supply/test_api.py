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


def test_unified_remote_cookie_requires_exact_origin_and_csrf(monkeypatch):
    from dataclasses import replace
    from services.api.supply import main
    from starlette.requests import Request
    from fastapi import HTTPException
    import pytest
    monkeypatch.setattr(main, "settings", replace(main.settings, mode="remote"))
    monkeypatch.setenv("BSV_SUPPLY_WEB_ORIGIN", "https://admin.example.test")
    def req(method, host="admin.example.test", origin="https://admin.example.test", csrf="nonce",
            cookie="bsv_identity_session=synthetic; bsv_csrf=nonce", auth=""):
        return Request({"type":"http","method":method,"scheme":"http","path":"/api/me",
                        "headers":[(k.encode(),v.encode()) for k,v in
                                   {"host":host,"origin":origin,"x-csrf-token":csrf,
                                    "cookie":cookie,"authorization":auth}.items()]})
    assert main.session_header(req("GET")) == "Bearer synthetic"
    assert main.session_header(req("POST")) == "Bearer synthetic"
    for invalid in (req("POST", origin="https://wrong.test"), req("POST", origin=""),
                    req("POST", csrf=""), req("POST", csrf="incorrect", auth="Bearer bypass"),
                    req("GET", host="wrong.test")):
        with pytest.raises(HTTPException) as e:
            main.session_header(invalid)
        assert e.value.status_code == 403
    assert main.session_header(req("GET", cookie="", auth="Bearer service")) == "Bearer service"
    with TestClient(main.app) as c:
        assert 'href="/supply-ui/assets/style.css"' in c.get("/hq/supply").text
        assert c.get("/api/health").json()["web_session"] is True
    monkeypatch.setenv("BSV_SUPPLY_WEB_ORIGIN", "http://admin.example.test")
    with pytest.raises(ValueError):
        main.web_origin()
