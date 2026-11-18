import json
import httpx
import pytest
from pathlib import Path
from services.api.supply.cache import LocalCache
from services.api.supply.config import load_settings
from services.api.supply.gateway import Gateway, Unreachable

class FakeClient:
    def __init__(self,responder):self.responder=responder
    def __enter__(self):return self
    def __exit__(self,*args):return None
    def get(self,url,params=None,headers=None):
        return self.responder('GET',url,headers)
    def post(self,url,json=None,headers=None):
        return self.responder('POST',url,headers)

def test_cache_is_identity_isolated(monkeypatch,tmp_path):
    config=load_settings()
    g=Gateway(config,LocalCache(tmp_path))
    urls=[]
    def success(method,url,headers):
        urls.append(url)
        token=headers['Authorization'].split(' ',1)[1]
        return httpx.Response(200,json={'actor':token},request=httpx.Request('GET',url))
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:FakeClient(success))
    g.read('D','/supply/shipments',user_token='TOKEN-EMP-A')
    def outage(*args):raise httpx.ConnectError('down')
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:FakeClient(outage))
    assert g.read('D','/supply/shipments',user_token='TOKEN-EMP-A')['data']['actor']=='TOKEN-EMP-A'
    with pytest.raises(Unreachable):g.read('D','/supply/shipments',user_token='TOKEN-EMP-B')

def test_primary_write_never_redirects_to_standby(monkeypatch,tmp_path):
    from dataclasses import replace
    config=load_settings()
    src=replace(config.sources['D'],standby_read='https://read-only.example.com')
    setting=replace(config,sources={**config.sources,'D':src})
    g=Gateway(setting,LocalCache(tmp_path))
    seen=[]
    def outage(method,url,headers):
        seen.append(url)
        raise httpx.ConnectError('down')
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:FakeClient(outage))
    with pytest.raises(Unreachable):g.write('D','/supply/shipments',{'request_id':'X'},user_token='USER-A')
    assert len(seen)==1 and 'read-only.example.com' not in seen[0]


def test_unconfirmed_primary_response_is_not_a_commit(monkeypatch,tmp_path):
    gateway=Gateway(load_settings(),LocalCache(tmp_path))

    def pending(method,url,headers):
        return httpx.Response(202,json={'state':'QUEUED_NOT_COMMITTED'},request=httpx.Request(method,url))

    monkeypatch.setattr(httpx,'Client',lambda **kw:FakeClient(pending))
    with pytest.raises(Unreachable):
        gateway.write('D','/inventory/counts',{'request_id':'X'},user_token='USER-A')
