import os,tempfile
from pathlib import Path
import pytest
from cryptography.fernet import Fernet
from services.api.supply.config import load_settings
from services.api.supply.backup import verify_snapshot
from services.api.supply.cache import LocalCache

def test_config_url_swappable(tmp_path,monkeypatch):
    import json
    p=Path(__file__).resolve().parents[2]/'config/modules/supply-sources.example.json'
    data=json.loads(p.read_text('utf-8'))
    data['sources']['A']['primary']='https://newhost.example.org/master'
    q=tmp_path/'sources.json';q.write_text(json.dumps(data))
    monkeypatch.setenv('BSV_SOURCES_CONFIG',str(q))
    assert load_settings().sources['A'].primary=='https://newhost.example.org/master'

def test_cache_ttl(tmp_path):
    c=LocalCache(tmp_path)
    c.save('A:/items',[{'item_id':'X'}])
    assert c.get('A:/items',1)['payload'][0]['item_id']=='X'
    assert c.get('missing',1) is None

def test_backup_key_required(tmp_path,monkeypatch):
    from services.api.supply.backup import _secret_key
    monkeypatch.delenv('BSV_BACKUP_FERNET_KEY',raising=False)
    with pytest.raises(RuntimeError):_secret_key()
