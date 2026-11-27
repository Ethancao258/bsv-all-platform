"""Unified configurable company API access. No hardcoded database addresses in business code."""
from __future__ import annotations
import hashlib
import httpx
from fastapi import HTTPException
from .config import Settings, auth_header
from .cache import LocalCache

class Unreachable(Exception):pass

class Gateway:
    def __init__(self,settings:Settings,cache:LocalCache):
        self.settings=settings;self.cache=cache
    @staticmethod
    def _url(base,path):
        if not path.startswith('/') or '://' in path or '..' in path:raise ValueError('非法路径')
        return base+path
    def read(self,key,path,*,user_token=None,params=None,allow_cache=True,permission_scope="",primary_only=False):
        src=self.settings.sources[key]
        q=httpx.QueryParams(params or {})
        # Cache must be scoped by the caller's credential fingerprint to prevent cross-employee data leaks.
        # A fresh user token yields a new cache identity; credentials themselves are never persisted.
        principal=hashlib.sha256(user_token.encode()).hexdigest() if user_token else 'SERVICE_ONLY'
        cache_key=key+':'+path+'?'+str(q)+'#principal='+principal+'#scope='+permission_scope
        attempts=[('PRIMARY',src.primary)]
        if not primary_only and src.standby_read and key not in "BFG":attempts.append(('STANDBY_READ',src.standby_read))
        for label,base in attempts:
            if not base:continue
            try:
                with httpx.Client(timeout=self.settings.timeout_seconds,follow_redirects=False,trust_env=False) as client:
                    r=client.get(self._url(base,path),params=params,headers=auth_header(src,user_token))
                if r.status_code in (401,403):raise HTTPException(r.status_code,'上游拒绝授权')
                if 400<=r.status_code<500:raise HTTPException(r.status_code,'上游请求失败: '+str(r.status_code))
                r.raise_for_status()
                payload=r.json()
                if label=='PRIMARY' and key!='B' and allow_cache:self.cache.save(cache_key,payload)
                return {"data":payload,"meta":{"source":label,"stale":label!='PRIMARY'}}
            except HTTPException:raise
            except (httpx.HTTPError,ValueError):continue
        if allow_cache and key!='B':
            record=self.cache.get(cache_key,self.settings.max_snapshot_age_hours)
            if record:return {"data":record['payload'],"meta":{"source":"LOCAL_CACHE","stale":True,"saved_at":record['saved_at']}}
        raise Unreachable(f'{key} 数据源及允许时效内的本地快照均不可用')
    def write(self,key,path,payload,*,user_token,expected_state=None):
        src=self.settings.sources[key]
        if key not in ('D','E') or src.read_only:raise ValueError('只读数据源拒绝写入')
        if not src.primary:raise Unreachable('上游写入地址未配置')
        try:
            with httpx.Client(timeout=self.settings.timeout_seconds,follow_redirects=False,trust_env=False) as client:
                r=client.post(self._url(src.primary,path),json=payload,headers=auth_header(src,user_token))
            if r.status_code>=400 and r.status_code<500:
                try:detail=r.json()
                except ValueError:detail=r.text[:200]
                raise HTTPException(r.status_code,detail)
            r.raise_for_status()
            if r.status_code not in (200,201):
                raise Unreachable('中央业务 API 未确认事务提交')
            outcome = r.json()
            if not isinstance(outcome,dict) or outcome.get('state') in ('QUEUED','QUEUED_NOT_COMMITTED','PENDING'):
                raise Unreachable('中央业务 API 未返回已提交结果')
            if expected_state is not None and outcome.get('state') != expected_state:
                raise Unreachable('中央业务 API 未返回约定状态')
            return outcome
        except HTTPException:raise
        except (httpx.HTTPError,ValueError) as exc:
            raise Unreachable(f'中央业务API不可达: {type(exc).__name__}') from exc
