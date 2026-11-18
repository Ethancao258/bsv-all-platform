"""Encrypted, integrity-checked DATA API snapshot. Not a full PostgreSQL physical backup."""
from __future__ import annotations
import hashlib,json,os,secrets,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
from cryptography.fernet import Fernet
from .config import Settings
from .gateway import Gateway

def _secret_key():
    secret=os.environ.get('BSV_BACKUP_FERNET_KEY','')
    if not secret:raise RuntimeError('必须从安全环境变量提供 BSV_BACKUP_FERNET_KEY；不能明文备份')
    return Fernet(secret.encode())

def make_snapshot(settings:Settings,gateway:Gateway,backup_path:Path|None=None):
    cipher=_secret_key()
    if settings.mode=='demo':raise RuntimeError('演示模式只需要演示数据；真实备份仅在 remote 运行')
    dataset={}; meta={}
    for key,source in settings.sources.items():
        for path in source.backup_paths:
            data=gateway.read(key,path,allow_cache=False)
            if data['meta']['source']!='PRIMARY':
                raise RuntimeError(f'{key}{path} 并非主数据源，拒绝生成带有最新标记的快照')
            dataset[key+':'+path]=data['data']
            meta[key+':'+path]={'source':'PRIMARY','url_alias':key}
    if not dataset:raise RuntimeError('备份配置中没有允许的快照路径')
    blob=json.dumps({'format':'BSV_API_SNAPSHOT_V2','created_at':datetime.now(timezone.utc).isoformat(),
                     'datasets':dataset,'provenance':meta},ensure_ascii=False,sort_keys=True).encode('utf-8')
    sha=hashlib.sha256(blob).hexdigest()
    wrapper=json.dumps({'sha256':sha,'payload':blob.decode('utf-8')},ensure_ascii=False).encode('utf-8')
    encrypted=cipher.encrypt(wrapper)
    output=backup_path or settings.backup_dir
    output.mkdir(parents=True,exist_ok=True)
    target=output/('api_snapshot_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+secrets.token_hex(3)+'.fernet')
    fd,temp=tempfile.mkstemp(prefix='.snapshot-',suffix='.tmp',dir=output)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'wb') as fp:fp.write(encrypted);fp.flush();os.fsync(fp.fileno())
        Path(temp).replace(target)
    finally:
        if Path(temp).exists():Path(temp).unlink()
    return {'file':str(target),'sha256':sha,'datasets':len(dataset),'bytes':len(encrypted)}

def verify_snapshot(path:Path):
    cipher=_secret_key()
    obj=json.loads(cipher.decrypt(path.read_bytes()))
    content=obj['payload'].encode('utf-8')
    if hashlib.sha256(content).hexdigest()!=obj['sha256']:raise ValueError('备份校验和失败')
    payload=json.loads(content)
    if payload.get('format')!='BSV_API_SNAPSHOT_V2':raise ValueError('错误的备份类型')
    return {'sha256':obj['sha256'],'created_at':payload['created_at'],'datasets':sorted(payload['datasets'])}
