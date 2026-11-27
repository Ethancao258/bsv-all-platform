"""Independent BSV delivery app, central-ledger-first and configuration-driven."""
from __future__ import annotations
import hashlib, hmac, json, os, re, uuid
from typing import Literal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .config import ROOT, load_settings
from .cache import LocalCache
from .demo import DemoCentral, DEMO_STORES, DEMO_ITEMS, DEMO_ACTORS
from .domain import calc_reorder, validate_count, unique_codes
from .gateway import Gateway, Unreachable
from .shipment_contract import shipment_for_console
from .central_routes import central_router

settings=load_settings()
cache=LocalCache(settings.cache_dir)
gateway=Gateway(settings,cache)
demo=DemoCentral(settings.cache_dir/'DEMO_ONLY_ledger.sqlite3') if settings.mode=='demo' else None
app=FastAPI(title='BSV ALL Supply & Inventory',version='2.0.0',docs_url='/openapi-docs')
app.mount('/assets',StaticFiles(directory=ROOT/'apps/hq-console/supply'),name='assets')


class Lines(BaseModel):
    item_id:str
    packages:int=Field(ge=1,le=100)

class ShipmentCreate(BaseModel):
    request_id:uuid.UUID
    source_store_id:str
    dest_store_id:str
    lines:list[Lines]=Field(min_length=1,max_length=30)

class Action(BaseModel):
    request_id:uuid.UUID
    expected_version:int=Field(ge=1)

class ScanAction(Action):
    scanned_codes:list[str]=Field(min_length=1,max_length=300)

class ReceiveAction(ScanAction):
    condition:str='ACCEPTED'

class Inspection(BaseModel):
    request_id:uuid.UUID
    store_id:str
    subject_department:str=''
    subject_employee:str=''
    results:dict[str,str]
    kind:Literal['self_check','independent']='self_check'

class InspectionReview(BaseModel):
    request_id:uuid.UUID
    decision:Literal['APPROVED','CHANGES_REQUIRED']

class BucketCount(BaseModel):
    request_id:uuid.UUID|None=None
    store_id:str
    item_id:str
    full_packages:int
    opened_count:int=Field(ge=0)
    opened_percent:int|None=None

class Replenishment(BaseModel):
    confirmed_available:str
    usage_before_next:str
    arrivals_before_next:str
    reserved:str
    expiry_before_next:str
    demand_next_cycle:str
    safety_stock:str
    arrivals_next_cycle:str
    pack_size:str
    approved:bool=True
    reliable:bool=True
    max_packs:int|None=None

def demo_actor(request: Request):
    host=request.client.host if request.client else ''
    authority=request.url.hostname
    forwarded=any(k in request.headers for k in ('forwarded','x-forwarded-for','x-forwarded-host'))
    if host not in ('127.0.0.1','::1','localhost','testclient') or authority not in ('127.0.0.1','localhost','::1','testserver') or forwarded:
        raise HTTPException(403,'演示模式只允许本机访问，生产请接公司身份服务')
    name=request.headers.get('X-Demo-Actor','DEMO-E01')
    return demo.actor(name)


def web_origin():
    """Explicit opt-in to the unified HTTPS gateway. Never enable demo access."""
    value = os.environ.get("BSV_SUPPLY_WEB_ORIGIN", "")
    if not value:
        return ""
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or value != f"https://{parsed.netloc}"):
        raise ValueError("BSV_SUPPLY_WEB_ORIGIN must be an exact HTTPS origin")
    return value


def session_header(request: Request):
    if settings.mode == 'internal-stage':
        cookie = request.cookies.get('bsv_identity_session', '')
        if request.method not in {'GET', 'HEAD'}:
            csrf = request.headers.get('X-CSRF-Token', '')
            expected = request.cookies.get('bsv_csrf', '')
            origin = request.headers.get('Origin', '')
            if not csrf or not expected or not hmac.compare_digest(csrf.encode(), expected.encode()) or (
                    origin and origin != f'{request.url.scheme}://{request.url.netloc}'):
                raise HTTPException(403, '内部测试会话 CSRF 校验失败')
        return 'Bearer ' + cookie if cookie else ''
    if settings.mode == "remote" and web_origin():
        cookie = request.cookies.get("bsv_identity_session", "")
        # Bearer-only service consumers retain the existing API contract.
        # Browser requests carrying a session must never bypass CSRF via a header.
        if cookie:
            origin = web_origin()
            if request.headers.get("host", "").lower() != urlsplit(origin).netloc.lower():
                raise HTTPException(403, "统一工作台主机不匹配")
            if request.method not in {"GET", "HEAD"}:
                csrf = request.headers.get("X-CSRF-Token", "")
                expected = request.cookies.get("bsv_csrf", "")
                if (request.headers.get("Origin") != origin or not csrf or not expected
                        or not hmac.compare_digest(csrf.encode(), expected.encode())):
                    raise HTTPException(403, "统一工作台 CSRF 校验失败")
            return "Bearer " + cookie
    return request.headers.get('Authorization', '')


async def actor(request: Request):
    if settings.mode == 'demo':
        return demo_actor(request)
    header = session_header(request)
    if not header.startswith('Bearer ') or not header[7:].strip():raise HTTPException(401,'请使用公司统一身份令牌')
    token=header[7:].strip()
    try:
        res=gateway.read('B','/auth/me',user_token=token,allow_cache=False)
        me=res['data']
    except (Unreachable,KeyError):raise HTTPException(503,'公司身份服务不可用，拒绝新授权操作')
    if (not isinstance(me,dict) or any(not isinstance(me.get(k),str) or not me[k] for k in ('employee_id','department_id'))
            or any(not isinstance(me.get(k),list) or any(not isinstance(v,str) for v in me[k]) for k in ('stores','roles'))):
        raise HTTPException(502,'人事身份响应缺失必要字段')
    request.state.scope = scope_of(me)
    return me

def scope_of(me):
    fields = [me['employee_id'], me['department_id'], sorted(set(me['stores'])), sorted(set(me['roles'])), me.get('legal_entity_id'), me.get('role_stores')]
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()

def token_of(request):
    if settings.mode=='demo':return None
    return session_header(request)[7:]

def permitted(me,role,store=None):
    if role not in me.get('roles',[]):raise HTTPException(403,'缺少操作权限: '+role)
    if store and store not in me.get('stores',[]):raise HTTPException(403,'目标门店无权限')
    scoped = me.get('role_stores')
    if store and scoped is not None and store not in scoped.get(role, ()):
        raise HTTPException(403,'目标门店未授权此操作')

def remote_read(k,path,request,params=None):
    try:return gateway.read(k,path,user_token=token_of(request),params=params,permission_scope=request.state.scope)
    except Unreachable as e:raise HTTPException(503,str(e))

def remote_mutation(k,path,body,request,me,allow_queue=True):
    if settings.mode == 'internal-stage':
        raise HTTPException(503, '中央 D/E 权威服务未接入，未提交且未排队')
    try:return {'state':'COMMITTED','data':gateway.write(k,path,body,user_token=token_of(request))}
    except Unreachable as e:
        if not allow_queue:raise HTTPException(503,str(e))
        try:
            row=cache.enqueue(str(body['request_id']),k,path,'POST',body,me['employee_id'],scope_of(me))
        except ValueError as exc:raise HTTPException(409,str(exc))
        return JSONResponse(status_code=202,content={'state':'QUEUED_NOT_COMMITTED','request_id':body['request_id'],
                             'warning':'中央服务离线，未入正式库存，请勿当作收货成功','queue':row['state']})

central_enabled = settings.mode == 'demo' or (
    settings.mode == 'remote' and os.environ.get('BSV_SUP59_D_V1') == '1'
    and bool(settings.sources['D'].primary) and not settings.sources['D'].read_only
)
app.include_router(central_router(mode=settings.mode, demo=demo, enabled=central_enabled,
                                 gateway=gateway, actor=actor, token_of=token_of))

@app.get('/',response_class=HTMLResponse)
@app.get('/hq/supply',response_class=HTMLResponse)
@app.get('/store/supply',response_class=HTMLResponse)
@app.get('/inspector/supply',response_class=HTMLResponse)
def index():
    page = (ROOT/'apps/hq-console/supply/index.html').read_text('utf-8')
    if settings.mode == 'internal-stage' or (settings.mode == 'remote' and web_origin()):
        return page.replace('"/assets/', '"/supply-ui/assets/')
    return page

@app.get('/api/health')
def health():
    return {"status":"OK","mode":settings.mode,"version":"2.0.0","production_connected":False if settings.mode != 'remote' else 'NOT_VERIFIED',
            "central_candidate":central_enabled, "web_session":bool(settings.mode == "remote" and web_origin()), "source_aliases":{k:{'name':v.name,'configured':bool(v.primary and '.invalid' not in v.primary),
                           'standby_read':bool(v.standby_read)} for k,v in settings.sources.items()}}

@app.get('/api/me')
async def me(current=Depends(actor)):return current

@app.get('/api/items')
async def items(request:Request,current=Depends(actor)):
    if demo:return {"data":DEMO_ITEMS,"meta":{"source":"DEMO_DATA","stale":False}}
    return remote_read('A','/items',request,{'stockable':'true'})

@app.get('/api/stores')
async def stores(request:Request,current=Depends(actor)):
    if demo:return {"data":[x for x in DEMO_STORES if x['store_id'] in current['stores']],"meta":{"source":"DEMO_DATA","stale":False}}
    res=remote_read('C','/stores',request)
    if isinstance(res['data'],list):res['data']=[x for x in res['data'] if x.get('store_id') in current['stores']]
    return res

@app.get('/api/shipments')
async def shipments(request:Request,store_id:str|None=None,current=Depends(actor)):
    if store_id:permitted(current,'receive' if 'receive' in current['roles'] else 'dispatch',store_id)
    if demo:return {"data":demo.list(current,store_id),"meta":{"source":"DEMO_DATA","stale":False}}
    envelope=remote_read('D','/supply/shipments',request,{'store_id':store_id} if store_id else None)
    if not isinstance(envelope['data'],list):raise HTTPException(502,'无效配送单列表')
    return {**envelope,'data':[shipment_for_console(row) for row in envelope['data']]}

@app.get('/api/shipments/{sid}')
async def shipment_detail(sid:str,request:Request,current=Depends(actor)):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',sid):
        raise HTTPException(422,'无效配送单编号')
    if demo:return {"data":demo.view(sid,current),"meta":{"source":"DEMO_DATA","stale":False}}
    envelope=remote_read('D','/supply/shipments/'+sid,request)
    return {**envelope,'data':shipment_for_console(envelope['data'],detail=True)}

@app.get('/api/inventory')
async def inventory(request:Request,store_id:str|None=None,current=Depends(actor)):
    if store_id and store_id not in current['stores']:raise HTTPException(403,'无目标门店库存权限')
    if demo:return {"data":demo.inventory(current,store_id),"meta":{"source":"DEMO_DATA","stale":False}}
    return remote_read('D','/inventory/balances',request,{'store_id':store_id} if store_id else None)

@app.post('/api/shipments')
async def create(body:ShipmentCreate,request:Request,current=Depends(actor)):
    permitted(current,'dispatch',body.source_store_id)
    d=body.model_dump(mode='json')
    if demo:return demo.mutate('create',None,d,current)
    result=remote_mutation('D','/supply/shipments',d,request,current)
    if isinstance(result,dict):result['data']=shipment_for_console(result['data'])
    return result

async def _change(sid,operation,body,request,current):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',sid):
        raise HTTPException(422,'无效配送单编号')
    d=body.model_dump(mode='json')
    if operation in ('dispatch','receive'):
        try:unique_codes(d['scanned_codes'])
        except ValueError as e:raise HTTPException(422,str(e))
    if demo:return demo.mutate(operation,sid,d,current)
    if operation=='dispatch':permitted(current,'dispatch')
    if operation=='receive':permitted(current,'receive')
    if operation=='prepare':permitted(current,'dispatch')
    # The central ledger independently checks source/destination membership and optimistic version.
    result=remote_mutation('D',f'/supply/shipments/{sid}/{operation}',d,request,current)
    if isinstance(result,dict):result['data']=shipment_for_console(result['data'])
    return result

@app.post('/api/shipments/{sid}/prepare')
async def prepare(sid:str,body:Action,request:Request,current=Depends(actor)):
    return await _change(sid,'prepare',body,request,current)
@app.post('/api/shipments/{sid}/dispatch')
async def dispatch(sid:str,body:ScanAction,request:Request,current=Depends(actor)):
    return await _change(sid,'dispatch',body,request,current)
@app.post('/api/shipments/{sid}/receive')
async def receive(sid:str,body:ReceiveAction,request:Request,current=Depends(actor)):
    return await _change(sid,'receive',body,request,current)

@app.post('/api/inspections')
async def inspect(body:Inspection,request:Request,current=Depends(actor)):
    permitted(current,'inspect_independent' if body.kind=='independent' else 'inspect',body.store_id)
    d=body.model_dump(mode='json')
    if demo:return demo.inspect(d,current)
    return remote_mutation('E','/inspections',d,request,current)

@app.post('/api/inspections/{inspection_id}/review')
async def review_inspection(inspection_id:str,body:InspectionReview,request:Request,current=Depends(actor)):
    permitted(current,'review_independent')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',inspection_id):
        raise HTTPException(422,'无效检查编号')
    data=body.model_dump(mode='json')
    if demo:return demo.review_inspection(inspection_id,data,current)
    # E is the authority for exact store access and separation of duties.
    return remote_mutation('E',f'/inspections/{inspection_id}/review',data,request,current,allow_queue=False)

@app.get('/api/inspections')
async def inspections(request:Request,current=Depends(actor)):
    if demo:return {"data":demo.inspections(current),"meta":{"source":"DEMO_DATA","stale":False}}
    return remote_read('E','/inspections',request)

@app.post('/api/stock-count/preview')
async def count_preview(body:BucketCount,current=Depends(actor)):
    if body.store_id not in current['stores']:raise HTTPException(403,'无该网点权限')
    try:return {"item_id":body.item_id,"store_id":body.store_id,"observation":validate_count(body.full_packages,body.opened_percent,body.opened_count),"posted":False}
    except ValueError as e:raise HTTPException(422,str(e))

@app.post('/api/stock-count')
async def record_count(body:BucketCount,request:Request,current=Depends(actor)):
    permitted(current,'inspect',body.store_id)
    try:observation=validate_count(body.full_packages,body.opened_percent,body.opened_count)
    except ValueError as e:raise HTTPException(422,str(e))
    if body.request_id is None:
        raise HTTPException(422,'正式盘点提交必须携带调用端生成的 request_id；预览可以省略')
    d=body.model_dump(mode='json')
    d['observation']=observation
    if demo:return demo.record_count(d,current,observation)
    return remote_mutation('D','/inventory/counts',d,request,current)

@app.get('/api/stock-count')
async def get_counts(request:Request,current=Depends(actor)):
    if demo:return {'data':demo.counts(current),'meta':{'source':'DEMO_DATA'}}
    return remote_read('D','/inventory/counts',request)

@app.get('/api/v9-reference')
async def v9_reference(current=Depends(actor)):
    permitted(current,'admin')
    import json
    # This is a read-only historic source excerpt, never directly authorized for production transfers.
    ref=json.loads((ROOT/'ingestion/sources/supply-v9-id-index.json').read_text(encoding='utf-8'))
    return {'reference_only':True,'source':ref.get('source'),'p':ref.get('p',[]),
            'warning':'历史V9记录不等于审核通过、可生产、可配送的当前物料'}

@app.post('/api/reorder/preview')
async def reorder_preview(body:Replenishment,current=Depends(actor)):
    try:return calc_reorder(**body.model_dump())
    except Exception as e:
        if isinstance(e,(ValueError,ArithmeticError)):raise HTTPException(422,str(e))
        raise

@app.get('/api/pending')
async def pending(current=Depends(actor)):
    if demo:return []
    return cache.pending_for(current['employee_id'],scope_of(current))

@app.post('/api/pending/sync')
async def pending_sync(request:Request,current=Depends(actor)):
    if demo:return {"synced":0,"mode":"demo"}
    results=[]
    for row in cache.queued(current['employee_id'],scope_of(current)):
        try:
            d=json.loads(row['payload'])
            outcome=gateway.write(row['source_key'],row['path'],d,user_token=token_of(request))
            cache.finish(row['request_id'],'COMMITTED',outcome)
            results.append({"request_id":row['request_id'],"state":"COMMITTED"})
        except HTTPException as e:
            cache.finish(row['request_id'],'CONFLICT',{'status':e.status_code,'detail':e.detail})
            results.append({"request_id":row['request_id'],"state":"CONFLICT"})
        except Unreachable:
            results.append({"request_id":row['request_id'],"state":"STILL_QUEUED"});break
    return {"results":results}

@app.post('/api/photo-preview')
async def photo_preview(request:Request,file:UploadFile=File(...),consent_external:bool=Form(False),current=Depends(actor)):
    blob=await file.read(8*1024*1024+1)
    if len(blob)>8*1024*1024:raise HTTPException(413,'照片上限8MB')
    if not blob:raise HTTPException(422,'图片为空')
    from integrations.vision.supply_photo import preview_candidates
    return preview_candidates(blob, settings.sources['F'],
                              allow_external=settings.mode=='remote' and os.environ.get('BSV_SUPPLY_VISION_ENABLED')=='1'
                              and consent_external)
