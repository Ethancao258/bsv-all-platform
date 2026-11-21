"""BSV customer-growth vertical slice. Isolated demo only until G0/G1 and real identity/payment wiring.

API contract: /api/v1/growth. Never infer a paid order from POS's simulated checkout.
"""
from __future__ import annotations
import base64, hashlib, hmac, json, os, re, secrets, time, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import BytesIO
from urllib.parse import quote, urlencode, urlparse

import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text, Index, text,
                        UniqueConstraint, create_engine, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

ROOT = Path(__file__).resolve().parents[3]
ENV = os.getenv('BSV_GROWTH_ENV', 'disabled')
ISOLATED = ENV == 'isolated'
DATABASE_URL = os.getenv('BSV_GROWTH_DB_URL', 'sqlite:///:memory:' if ISOLATED else '')
SECRET = os.getenv('BSV_GROWTH_SIGNING_KEY', '')
SIGNATURE_KEY = os.getenv('BSV_GROWTH_SIGNATURE_KEY', '')
STORES = tuple(x.strip() for x in os.getenv('BSV_GROWTH_STORE_IDS', 'BSVM,BSVS,BSVT' if ISOLATED else '').split(',') if x.strip())
LEGAL_ENTITY = os.getenv('BSV_GROWTH_LEGAL_ENTITY_ID', 'DEMO_LEGAL' if ISOLATED else '')
IDENTITY_ME_URL = os.getenv('BSV_GROWTH_IDENTITY_ME_URL', '')
WECHAT_APPID = os.getenv('BSV_WECHAT_APPID', '')
WECHAT_SECRET = os.getenv('BSV_WECHAT_SECRET', '')
WECHAT_REDIRECT = os.getenv('BSV_WECHAT_REDIRECT', '')
PAYMENT_SIGNING_KEY = os.getenv('BSV_GROWTH_PAYMENT_SIGNING_KEY', '')
MEMBER_POLICY_VERSION = os.getenv('BSV_GROWTH_MEMBER_POLICY_VERSION', 'ISOLATED-MEMBER-V1' if ISOLATED else '')
ALLOWED_ORIGINS = tuple(x.rstrip('/') for x in os.getenv('BSV_GROWTH_ALLOWED_ORIGINS', '').split(',') if x)
BASE_PATH = '/api/v1/growth'

if ENV not in {'isolated', 'production', 'disabled'}:
    raise RuntimeError('Unsupported BSV_GROWTH_ENV')
if ENV == 'production' and (not DATABASE_URL or len(SECRET) < 32 or not STORES or not LEGAL_ENTITY or not IDENTITY_ME_URL or not ALLOWED_ORIGINS):
    raise RuntimeError('Production missing required database, identity, signing, origin or store settings')
if not SECRET:
    SECRET = 'ISOLATED-ONLY-NOT-FOR-PRODUCTION-secret-43'
if not SIGNATURE_KEY:
    SIGNATURE_KEY = Fernet.generate_key().decode() if ISOLATED else ''
if ENV == 'production' and not MEMBER_POLICY_VERSION:
    raise RuntimeError('Production requires an approved membership policy version')
if ENV == 'production' and not SIGNATURE_KEY:
    raise RuntimeError('Production requires an encryption key for signature templates')


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid.uuid4())


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def signed(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':'), ensure_ascii=True).encode()).decode().rstrip('=')
    mac = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return body + '.' + mac


def unsign(token: str) -> dict:
    try:
        body, mac = token.split('.', 1)
        expected = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError('mac')
        obj = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
        if obj.get('exp', 0) < time.time():
            raise ValueError('expired')
        return obj
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(400, '邀请码已失效，请重新获取') from exc


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = 'bsv_growth_customer_candidate'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    display_name: Mapped[str] = mapped_column(String(32), default='会员')
    consent_version: Mapped[str] = mapped_column(String(30), default='2026-11-21')
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    source_store_id: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    first_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    membership_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    membership_policy_version: Mapped[str | None] = mapped_column(String(40))


class CustomerIdentity(Base):
    __tablename__ = 'bsv_growth_customer_identity_candidate'
    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    provider_subject_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey('bsv_growth_customer_candidate.id'))


class BrowserSession(Base):
    __tablename__ = 'bsv_growth_browser_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_hash: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(20))
    csrf_hash: Mapped[str] = mapped_column(String(64))
    store_id: Mapped[str] = mapped_column(String(40))
    invite: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthState(Base):
    __tablename__ = 'bsv_growth_oauth_state'
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(40))
    invite: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ClaimTicket(Base):
    __tablename__ = 'bsv_marketing_claim_ticket'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(String(36), unique=True)
    store_id: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default='OPEN')


class Claim(Base):
    __tablename__ = 'bsv_marketing_claim_candidate'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    ticket_id: Mapped[str] = mapped_column(String(36), index=True)
    customer_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_tr: Mapped[str] = mapped_column(String(12))
    policy_version: Mapped[str] = mapped_column(String(40))
    signature_version: Mapped[int] = mapped_column(Integer)
    attestation: Mapped[bool] = mapped_column(Boolean)
    evidence_note: Mapped[str | None] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(20), default='PENDING_CUSTOMER')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index('uq_bsv_pending_customer_claim', 'customer_id',unique=True,
                            sqlite_where=text("status IN ('PENDING_CUSTOMER','CONFIRMED')"),
                            postgresql_where=text("status IN ('PENDING_CUSTOMER','CONFIRMED')")),)


class Attribution(Base):
    __tablename__ = 'bsv_marketing_attribution_candidate'
    customer_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_tr: Mapped[str] = mapped_column(String(12))
    source: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default='PENDING_PAYMENT')
    original_supervisor_chain_json: Mapped[str] = mapped_column(Text, default='[]')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SignatureTemplate(Base):
    __tablename__ = 'bsv_workforce_signature_template_candidate'
    actor_tr: Mapped[str] = mapped_column(String(12), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(50))
    ciphertext: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MembershipCycle(Base):
    __tablename__='bsv_customer_membership_cycle_candidate'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(String(36), index=True)
    activated_by_order_id: Mapped[str] = mapped_column(String(80), unique=True)
    policy_version: Mapped[str] = mapped_column(String(40))
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Benefit(Base):
    __tablename__='bsv_customer_benefit_candidate'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(String(36), index=True)
    cycle_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20),default='AVAILABLE')
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    redeemed_by_order_id: Mapped[str | None] = mapped_column(String(80))
    __table_args__=(UniqueConstraint('cycle_id','kind'),)


class BenefitReservation(Base):
    __tablename__='bsv_customer_benefit_reservation_candidate'
    benefit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(80), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(18), default='HELD')


class PaymentFact(Base):
    __tablename__ = 'bsv_growth_verified_payment_projection'
    order_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(36))
    store_id: Mapped[str] = mapped_column(String(40))
    paid_minor: Mapped[int] = mapped_column(Integer)
    refunded_minor: Mapped[int] = mapped_column(Integer, default=0)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProcessedEvent(Base):
    __tablename__ = 'bsv_growth_processed_event'
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Policy(Base):
    __tablename__ = 'bsv_marketing_commission_policy_candidate'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    store_id: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[str] = mapped_column(String(40))
    base_rate_bps: Mapped[int] = mapped_column(Integer)
    full_days: Mapped[int] = mapped_column(Integer, default=365)
    reduced_days: Mapped[int] = mapped_column(Integer, default=183)
    reduced_coeff_bps: Mapped[int] = mapped_column(Integer, default=3000)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('store_id','version'),)


class Commission(Base):
    __tablename__ = 'bsv_operating_finance_commission_candidate'
    order_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    actor_tr: Mapped[str] = mapped_column(String(12))
    policy_version: Mapped[str] = mapped_column(String(40))
    rate_bps: Mapped[int] = mapped_column(Integer)
    coeff_bps: Mapped[int] = mapped_column(Integer)
    accrued_minor: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default='PROVISIONAL_NOT_PAYABLE')


class CommissionLedger(Base):
    __tablename__='bsv_operating_finance_commission_ledger_candidate'
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(80),index=True)
    actor_tr: Mapped[str] = mapped_column(String(12))
    delta_minor: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24),default='PROVISIONAL_NOT_PAYABLE')
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)


class PrivacyRequest(Base):
    __tablename__='bsv_growth_privacy_request'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(String(36),index=True)
    type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(24),default='PENDING_REVIEW')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)


class Audit(Base):
    __tablename__ = 'bsv_growth_audit_event'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(80))
    metadata_json: Mapped[str] = mapped_column(Text, default='{}')
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


engine = create_engine(DATABASE_URL or 'sqlite:///:memory:', connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite:') else {}, pool_pre_ping=True)
DB = sessionmaker(bind=engine, expire_on_commit=False)
if ISOLATED:
    Base.metadata.create_all(engine)  # ONLY isolated; never create production tables implicitly.

app = FastAPI(title='BSV Customer Growth | isolated vertical slice', docs_url='/growth/docs' if ISOLATED else None)


def db_session():
    return DB()


def utc(v: datetime) -> datetime:
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)


def require_store(store_id: str) -> None:
    if store_id not in STORES:
        raise HTTPException(422, '门店未在授权列表中')


def latest_signature(db:Session, tr:str):
    return db.scalar(select(SignatureTemplate).where(SignatureTemplate.actor_tr==tr)
                     .order_by(SignatureTemplate.version.desc()).limit(1))


def require_enabled():
    if ENV == 'disabled':
        raise HTTPException(503, '会员系统未启用')


def mutation_origin(request: Request) -> None:
    if ISOLATED:
        return
    origin = request.headers.get('origin')
    if not origin or origin.rstrip('/') not in ALLOWED_ORIGINS:
        raise HTTPException(403, '非法请求来源')


def require_guest(request: Request, db: Session, write=False) -> BrowserSession:
    token = request.cookies.get('bsv_growth_sid', '')
    sess = db.get(BrowserSession, digest(token)) if token else None
    if not sess or utc(sess.expires_at) < now():
        raise HTTPException(401, '请先完成微信或手机号身份验证')
    if write:
        mutation_origin(request)
        header = request.headers.get('x-growth-csrf', '')
        cookie = request.cookies.get('bsv_growth_csrf', '')
        if not header or not cookie or not hmac.compare_digest(header, cookie) or not hmac.compare_digest(digest(header), sess.csrf_hash):
            raise HTTPException(403, '请刷新页面后重试')
    return sess


def set_guest(response: Response, db: Session, provider: str, subject: str, store_id: str, invite: str | None):
    token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(24)
    db.add(BrowserSession(token_hash=digest(token), csrf_hash=digest(csrf), provider=provider,
                          subject_hash=digest(provider + ':' + subject), store_id=store_id,
                          invite=invite, expires_at=now() + timedelta(days=7)))
    for name, value, secure, http_only in (
        ('bsv_growth_sid',token,not ISOLATED,True),
        ('bsv_growth_csrf',csrf,not ISOLATED,False),
    ):
        response.set_cookie(name, value, max_age=7*86400, httponly=http_only, secure=secure, samesite='lax', path='/')


def staff_auth(request: Request, store_id: str | None = None, *, write=False, hq=False) -> tuple[str,str]:
    if write:
        mutation_origin(request)
    if ISOLATED:
        raw = request.cookies.get('bsv_dev_staff','')
        payload = unsign(raw) if raw else {}
        if payload.get('role') not in ('staff','hq'):
            raise HTTPException(401, '请先登录员工中心')
        if write:
            csrf = request.cookies.get('bsv_dev_csrf','')
            if not csrf or request.headers.get('x-growth-csrf','') != csrf:
                raise HTTPException(403, '员工操作确认已过期')
        if hq and payload.get('role') != 'hq':
            raise HTTPException(403, '仅总部可审批')
        if store_id and store_id not in payload.get('stores', []):
            raise HTTPException(403, '当前门店未授权')
        return payload['tr'],payload.get('name',payload['tr'])
    if not IDENTITY_ME_URL:
        raise HTTPException(503, '人员身份服务未接通')
    try:
        with httpx.Client(timeout=5) as client:
            response = client.get(IDENTITY_ME_URL, headers={'Cookie':request.headers.get('cookie','')})
        response.raise_for_status()
        me = response.json()
    except Exception as exc:
        raise HTTPException(503,'人员权限暂时无法验证') from exc
    if not me.get('tr_code') or not me.get('emp_code') or not me.get('active') or LEGAL_ENTITY not in me.get('active_legal_entities',[]):
        raise HTTPException(403, '人员资格不符合要求')
    action = 'hq.people.read' if hq else 'marketing.task.write'
    if not any(g.get('action') == action and g.get('legal_entity_id') == LEGAL_ENTITY
               and (hq or g.get('store_id') == store_id) for g in me.get('grants',[])):
        raise HTTPException(403, '缺少对应岗位授权')
    if write:
        csrf = request.cookies.get('bsv_csrf','')
        if not csrf or request.headers.get('x-csrf-token','') != csrf:
            raise HTTPException(403, '身份系统CSRF验证失败')
    return me['tr_code'], me.get('display_label') or me['tr_code']


class DemoLogin(BaseModel):
    tr: str = 'TRA0001'
    role: str = 'staff'
    name: str = '演练员工'
    store_id: str = 'BSVS'


@app.post(BASE_PATH + '/dev/staff-login')
def demo_staff_login(data: DemoLogin, request: Request, response: Response):
    if not ISOLATED or request.client.host not in ('127.0.0.1','::1','testclient','localhost') or request.url.hostname not in ('127.0.0.1','localhost','testserver'):
        raise HTTPException(404, 'Not available')
    require_store(data.store_id)
    if not re.fullmatch(r'TR[A-Z][0-9]{4}',data.tr) or data.role not in ('staff','hq'):
        raise HTTPException(422,'演练人员信息无效')
    token=signed({'tr':data.tr,'role':data.role,'name':data.name[:40], 'stores':[data.store_id], 'exp':time.time()+3600})
    response.set_cookie('bsv_dev_staff', token, httponly=True, samesite='lax', path='/')
    csrf=secrets.token_urlsafe(24)
    response.set_cookie('bsv_dev_csrf',csrf,httponly=False,samesite='lax',path='/')
    return {'ok':True,'actor_tr':data.tr,'mode':'ISOLATED_ONLY'}


class DemoGuest(BaseModel):
    subject: str = Field(min_length=3,max_length=70)
    store_id: str = 'BSVS'
    invite: str | None = None


@app.post(BASE_PATH + '/dev/guest-login')
def demo_guest_login(data: DemoGuest, request: Request, response: Response):
    if not ISOLATED or request.client.host not in ('127.0.0.1','::1','testclient','localhost') or request.url.hostname not in ('127.0.0.1','localhost','testserver'):
        raise HTTPException(404,'Not available')
    require_store(data.store_id)
    with db_session() as db:
        set_guest(response,db,'isolated',data.subject,data.store_id,data.invite)
        db.commit()
    return {'ok':True,'mode':'ISOLATED_ONLY'}


@app.get(BASE_PATH + '/public/config')
def public_config():
    return {'enabled':ENV!='disabled','stores':STORES,'wechat_enabled':bool(WECHAT_APPID and WECHAT_SECRET and WECHAT_REDIRECT),
            'sms_enabled':False,'privacy_version':'2026-11-21','mode':ENV}


@app.get(BASE_PATH + '/auth/wechat/start')
def wechat_start(store_id: str, invite: str | None = None):
    require_enabled(); require_store(store_id)
    if not (WECHAT_APPID and WECHAT_SECRET and WECHAT_REDIRECT):
        raise HTTPException(503, '微信授权待配置')
    if invite:
        obj=unsign(invite)
        if obj.get('kind')!='invitation':
            raise HTTPException(400,'邀请链接无效')
    nonce=secrets.token_urlsafe(25)
    with db_session() as db:
        db.add(OAuthState(state_hash=digest(nonce),store_id=store_id,invite=invite,expires_at=now()+timedelta(minutes=10)))
        db.commit()
    url='https://open.weixin.qq.com/connect/oauth2/authorize?' + urlencode({
        'appid':WECHAT_APPID,'redirect_uri':WECHAT_REDIRECT,'response_type':'code',
        'scope':'snsapi_base','state':nonce})+'#wechat_redirect'
    result=RedirectResponse(url,status_code=302)
    result.set_cookie('bsv_wx_oauth_state',nonce,max_age=600,httponly=True,secure=not ISOLATED,samesite='lax',path='/')
    return result


@app.get(BASE_PATH + '/auth/wechat/callback')
def wechat_callback(code: str, state: str, request:Request):
    require_enabled()
    if not hmac.compare_digest(state,request.cookies.get('bsv_wx_oauth_state','')):
        raise HTTPException(403,'微信授权未从本设备开始')
    with db_session() as db:
        st=db.get(OAuthState,digest(state))
        if not st or utc(st.expires_at)<now():
            raise HTTPException(400,'授权状态过期')
        store,invite=st.store_id,st.invite
        db.delete(st); db.commit()  # consume state before exchanging code (one use)
    try:
        r=httpx.get('https://api.weixin.qq.com/sns/oauth2/access_token',params={
            'appid':WECHAT_APPID,'secret':WECHAT_SECRET,'code':code,'grant_type':'authorization_code'},timeout=8)
        r.raise_for_status(); payload=r.json()
        subject=payload.get('openid','')
        if not re.fullmatch(r'[A-Za-z0-9_\-]{8,128}',subject):
            raise ValueError('invalid provider identity')
    except (httpx.HTTPError,ValueError) as exc:
        raise HTTPException(503,'微信验证未完成') from exc
    res=RedirectResponse('/member/',status_code=303)
    res.delete_cookie('bsv_wx_oauth_state',path='/')
    with db_session() as db:
        set_guest(res,db,'wechat',subject,store,invite)
        db.commit()
    return res


class Register(BaseModel):
    display_name: str = Field(default='会员', min_length=1,max_length=32)
    privacy_accepted: bool
    marketing_opt_in: bool = False


def customer_for_session(db: Session, sess: BrowserSession):
    link=db.get(CustomerIdentity,(sess.provider,sess.subject_hash))
    return db.get(Customer,link.customer_id) if link else None


@app.post(BASE_PATH + '/public/register')
def register(body: Register, request: Request):
    require_enabled()
    with db_session() as db:
        sess=require_guest(request,db,True)
        if not body.privacy_accepted:
            raise HTTPException(422,'请确认已阅读会员隐私告知')
        old=customer_for_session(db,sess)
        if old:
            return {'customer_id':old.id,'already_registered':True,'status':'ACTIVE' if old.first_paid_at else 'PENDING_FIRST_PAID'}
        customer=Customer(display_name=body.display_name.strip(),consent_version='2026-11-21',
                          marketing_opt_in=body.marketing_opt_in,source_store_id=sess.store_id)
        db.add(customer);db.flush()
        db.add(CustomerIdentity(provider=sess.provider,provider_subject_hash=sess.subject_hash,customer_id=customer.id))
        assigned=False
        if sess.invite:
            obj=unsign(sess.invite)
            if obj.get('kind')!='invitation' or obj.get('store') not in STORES or not re.fullmatch(r'TR[A-Z][0-9]{4}',obj.get('tr','')):
                raise HTTPException(422,'邀请关系异常，请重新扫码')
            db.add(Attribution(customer_id=customer.id,actor_tr=obj['tr'],source='INVITE',status='PENDING_PAYMENT'))
            assigned=True
        if not assigned:
            db.add(ClaimTicket(customer_id=customer.id,store_id=sess.store_id,expires_at=now()+timedelta(hours=24)))
        db.add(Audit(actor='customer:'+customer.id,action='CUSTOMER_REGISTER',target=customer.id,
                     metadata_json=json.dumps({'store_id':sess.store_id,'source':'invite' if assigned else 'store_card'})))
        db.commit()
        return {'customer_id':customer.id,'already_registered':False,'status':'PENDING_FIRST_PAID',
                'referral':'PREBOUND' if assigned else 'AVAILABLE_FOR_CLAIM'}


@app.get(BASE_PATH + '/public/me')
def guest_me(request: Request):
    with db_session() as db:
        sess=require_guest(request,db)
        person=customer_for_session(db,sess)
        if not person:
            return {'registered':False,'source_store_id':sess.store_id}
        attr=db.get(Attribution,person.id)
        ticket=db.scalar(select(ClaimTicket).where(ClaimTicket.customer_id==person.id))
        return {'registered':True,'customer_id':person.id,'display_name':person.display_name,
                'source_store_id':person.source_store_id,
                'membership_status':'ACTIVE' if person.first_paid_at else 'PENDING_FIRST_PAID',
                'membership_expires_at':person.membership_expires_at.isoformat() if person.membership_expires_at else None,
                'benefits':[{'id':b.id,'kind':b.kind,'status':b.status,'expires_at':b.expires_at.isoformat()}
                            for b in db.scalars(select(Benefit).where(Benefit.customer_id==person.id))
                            if b.status=='AVAILABLE' and utc(b.expires_at)>now()],
                'marketing_opt_in':person.marketing_opt_in,
                'referral_status':attr.status if attr else 'NONE',
                'ticket_id':ticket.id if ticket and ticket.status=='OPEN' else None}


@app.get(BASE_PATH + '/staff/me')
def staff_me(request: Request, store_id: str):
    require_store(store_id)
    tr,name=staff_auth(request,store_id)
    with db_session() as db:
        sig=latest_signature(db,tr)
        return {'actor_tr':tr,'name':name,'store_id':store_id,
                'signature_version':sig.version if sig else None,
                'policy_version':'GROWTH-CLAIM-V1'}


@app.post(BASE_PATH + '/staff/invite')
def staff_invite(request: Request, store_id: str):
    require_store(store_id)
    tr,_=staff_auth(request,store_id,write=True)
    return {'invite':signed({'kind':'invitation','tr':tr,'store':store_id,
                             'exp':time.time()+14*86400}),'store_id':store_id,'valid_days':14}


@app.get(BASE_PATH + '/staff/queue')
def staff_queue(request: Request, store_id: str):
    require_store(store_id)
    staff_auth(request,store_id)
    with db_session() as db:
        tickets=list(db.scalars(select(ClaimTicket).where(ClaimTicket.store_id==store_id,
                           ClaimTicket.status=='OPEN').order_by(ClaimTicket.created_at.desc()).limit(30)))
        return {'tickets':[{'ticket_id':t.id,'short_id':t.id[:6].upper(),
                            'created_at':t.created_at.isoformat()}
                           for t in tickets if utc(t.expires_at)>now()]}


class SignatureUpload(BaseModel):
    full_name: str = Field(min_length=2,max_length=50)
    png_data: str = Field(max_length=220000)


@app.post(BASE_PATH + '/staff/signature')
def enroll_signature(body: SignatureUpload, request: Request, store_id: str):
    require_store(store_id)
    tr,name=staff_auth(request,store_id,write=True)
    if name.strip() != body.full_name.strip():
        raise HTTPException(422,'请与身份系统中的姓名保持一致')
    try:
        prefix='data:image/png;base64,'
        if not body.png_data.startswith(prefix):
            raise ValueError('not PNG')
        data=base64.b64decode(body.png_data[len(prefix):],validate=True)
        if not (100 <= len(data) <= 130000 and data[:8]==b'\x89PNG\r\n\x1a\n'):
            raise ValueError('bad png')
        from PIL import Image
        pic=Image.open(BytesIO(data));pic.verify()
        pic=Image.open(BytesIO(data)).convert('RGBA')
        if not (180 <= pic.width <= 1500 and 60 <= pic.height <= 650):
            raise ValueError('invalid size')
        # Transparent-canvas and white-background strokes both count, blank signatures do not.
        pixels=list(pic.get_flattened_data())
        strokes=sum(1 for r,g,b,a in pixels[::max(1,len(pixels)//10000)]
                    if a>90 and max(r,g,b)<170)
        if strokes<12:
            raise ValueError('blank signature')
        if ENV=='production':
            raise HTTPException(503,'人员法定姓名核验接口尚未完成，暂停正式签名母版采集')
        cipher=Fernet(SIGNATURE_KEY.encode()).encrypt(data).decode()
    except (ValueError,TypeError) as exc:
        raise HTTPException(422,'签名图片无效') from exc
    with db_session() as db:
        current=latest_signature(db,tr)
        version=current.version+1 if current else 1
        db.add(SignatureTemplate(actor_tr=tr,version=version,full_name=name,ciphertext=cipher,
                                 content_sha256=hashlib.sha256(data).hexdigest()))
        db.add(Audit(actor=tr,action='SIGNATURE_TEMPLATE_UPDATED',target=tr,
                     metadata_json=json.dumps({'version':version})))
        db.commit()
        return {'ok':True,'signature_version':version,'notice':'签名母版不等于正式合同签署'}


class ClaimRequest(BaseModel):
    ticket_id: str
    policy_version: str = 'GROWTH-CLAIM-V1'
    attested: bool
    evidence_note: str = Field(default='',max_length=180)


@app.post(BASE_PATH + '/staff/claims')
def claim(body: ClaimRequest, request: Request, store_id: str):
    require_store(store_id)
    tr,_=staff_auth(request,store_id,write=True)
    if not body.attested or body.policy_version!='GROWTH-CLAIM-V1':
        raise HTTPException(422,'须明确确认本次认领规则')
    with db_session() as db:
        sig=latest_signature(db,tr)
        if not sig:
            raise HTTPException(409,'请先在员工中心录入本人规范签名')
        t=db.get(ClaimTicket,body.ticket_id)
        if not t or t.store_id!=store_id or t.status!='OPEN' or utc(t.expires_at)<now():
            raise HTTPException(409,'客户不在有效待认领队列中')
        if db.get(Attribution,t.customer_id):
            raise HTTPException(409,'客户已有有效开发线索')
        if db.scalar(select(Claim).where(Claim.customer_id==t.customer_id,
                                      Claim.status.in_(['PENDING_CUSTOMER','CONFIRMED']))):
            raise HTTPException(409,'当前客户已有待处理认领')
        c=Claim(ticket_id=t.id,customer_id=t.customer_id,actor_tr=tr,
                signature_version=sig.version,attestation=True,
                policy_version=body.policy_version,evidence_note=body.evidence_note.strip())
        db.add(c);db.add(Audit(actor=tr,action='CLAIM_SUBMITTED',target=t.customer_id))
        db.commit()
        return {'claim_id':c.id,'status':'PENDING_CUSTOMER'}


class ConfirmClaim(BaseModel):
    confirmed: bool


@app.post(BASE_PATH + '/public/claims/{claim_id}/confirm')
def confirm_claim(claim_id: str, body: ConfirmClaim,request: Request):
    with db_session() as db:
        sess=require_guest(request,db,True)
        customer=customer_for_session(db,sess)
        claim=db.get(Claim,claim_id)
        if not customer or not claim or claim.customer_id!=customer.id or claim.status!='PENDING_CUSTOMER':
            raise HTTPException(404,'认领申请不存在')
        if not body.confirmed:
            claim.status='REJECTED'
        elif db.get(Attribution,customer.id):
            claim.status='CONFLICT'
        else:
            claim.status='CONFIRMED'
            db.add(Attribution(customer_id=customer.id,actor_tr=claim.actor_tr,source='ONSITE',
                               status='CONFIRMED' if customer.first_paid_at else 'PENDING_PAYMENT',
                               confirmed_at=now() if customer.first_paid_at else None))
            ticket=db.get(ClaimTicket,claim.ticket_id)
            if ticket:ticket.status='CLAIMED'
        db.add(Audit(actor='customer:'+customer.id,action='CUSTOMER_CLAIM_RESPONSE',target=claim.id,
                     metadata_json=json.dumps({'confirmed':body.confirmed})))
        db.commit()
        return {'status':claim.status}


@app.get(BASE_PATH + '/public/claim-requests')
def customer_claim_requests(request: Request):
    with db_session() as db:
        sess=require_guest(request,db);person=customer_for_session(db,sess)
        if not person:return {'requests':[]}
        claims=list(db.scalars(select(Claim).where(Claim.customer_id==person.id,Claim.status=='PENDING_CUSTOMER')))
        return {'requests':[{'claim_id':c.id,'employee_hint':c.actor_tr[-4:],
                             'status':c.status} for c in claims]}


class PaymentEvent(BaseModel):
    event_id: str = Field(min_length=3,max_length=100)
    action: str = Field(pattern=r'^(PAID|REFUNDED)$')
    order_id: str = Field(min_length=3,max_length=80)
    customer_id: str = Field(min_length=3,max_length=40)
    store_id: str
    amount_minor: int = Field(gt=0,le=100000000)
    policy_version: str | None = None


def verify_finance_request(request: Request, raw: bytes):
    if not PAYMENT_SIGNING_KEY or len(PAYMENT_SIGNING_KEY)<32:
        raise HTTPException(503,'真实支付系统未接入，禁止计佣')
    try:
        ts=int(request.headers.get('x-growth-timestamp','0'))
    except ValueError:
        raise HTTPException(401,'支付签名无效')
    if abs(time.time()-ts)>300:
        raise HTTPException(401,'支付事件已过期')
    supplied=request.headers.get('x-growth-signature','')
    expected=hmac.new(PAYMENT_SIGNING_KEY.encode(),str(ts).encode()+b'.'+raw,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied,expected):
        raise HTTPException(401,'支付事件签名无效')


def commission_for(db: Session, payment: PaymentFact):
    c=db.get(Customer,payment.customer_id)
    a=db.get(Attribution,payment.customer_id)
    if not c or not c.first_paid_at or not a or a.status!='CONFIRMED':
        return None
    policy=db.scalar(select(Policy).where(Policy.store_id==payment.store_id,Policy.effective_at<=payment.paid_at)
                     .order_by(Policy.effective_at.desc()).limit(1))
    if not policy:
        return None
    age=(utc(payment.paid_at)-utc(c.first_paid_at)).days
    coeff=10000 if age<policy.full_days else (policy.reduced_coeff_bps if age<policy.full_days+policy.reduced_days else 0)
    net=max(0,payment.paid_minor-payment.refunded_minor)
    accrued=(net*policy.base_rate_bps*coeff+50000000)//100000000
    obj=db.get(Commission,payment.order_id)
    if not obj:
        obj=Commission(order_id=payment.order_id,actor_tr=a.actor_tr,policy_version=policy.version,
                       rate_bps=policy.base_rate_bps,coeff_bps=coeff,accrued_minor=accrued)
        db.add(obj)
    else:
        # Preserve the original order's rule on refunds; never reprice historic order with current policy.
        obj.accrued_minor=(net*obj.rate_bps*obj.coeff_bps+50000000)//100000000
    return obj


@app.post(BASE_PATH + '/internal/payment-event')
async def payment_event(request: Request):
    # Machine-to-machine call: validated by HMAC; browser Origin is deliberately not used.
    raw=await request.body()
    verify_finance_request(request,raw)
    try:body=PaymentEvent.model_validate_json(raw)
    except Exception as exc:raise HTTPException(422,'支付事件结构无效') from exc
    require_store(body.store_id)
    with db_session() as db:
        previously=db.get(ProcessedEvent,body.event_id)
        if previously:
            if previously.payload_sha256!=hashlib.sha256(raw).hexdigest():
                raise HTTPException(409,'事件ID内容冲突')
            return {'accepted':True,'duplicate':True}
        c=db.get(Customer,body.customer_id)
        if not c:raise HTTPException(404,'客户身份未绑定')
        pay=db.get(PaymentFact,body.order_id)
        if body.action=='PAID':
            if pay:raise HTTPException(409,'订单支付事实已存在')
            pay=PaymentFact(order_id=body.order_id,customer_id=c.id,store_id=body.store_id,
                            paid_minor=body.amount_minor,paid_at=now())
            db.add(pay)
            reservation=db.scalar(select(BenefitReservation).where(BenefitReservation.order_id==body.order_id))
            if reservation and reservation.status=='HELD':
                benefit=db.get(Benefit,reservation.benefit_id)
                if utc(reservation.expires_at)>=now() and benefit and benefit.customer_id==c.id and benefit.status=='HELD':
                    benefit.status='REDEEMED';benefit.redeemed_by_order_id=body.order_id
                    reservation.status='COMMITTED'
                else:
                    raise HTTPException(409,'该订单的权益预占已失效，不能确认优惠核销')
            if c.first_paid_at is None:
                c.first_paid_at=pay.paid_at
                attr=db.get(Attribution,c.id)
                if attr and attr.status=='PENDING_PAYMENT':attr.status='CONFIRMED';attr.confirmed_at=now()
            if c.membership_expires_at is None or utc(c.membership_expires_at)<now():
                expiry=now()+timedelta(days=365)
                cycle=MembershipCycle(customer_id=c.id, activated_by_order_id=body.order_id,
                                      policy_version=MEMBER_POLICY_VERSION,expires_at=expiry)
                db.add(cycle); db.flush()
                c.membership_expires_at=expiry
                c.membership_policy_version=MEMBER_POLICY_VERSION
                if ISOLATED and c.first_paid_at==pay.paid_at:
                    for kind in ('RETURN_DISCOUNT','COMPANION_GIFT'):
                        db.add(Benefit(customer_id=c.id,cycle_id=cycle.id,kind=kind,expires_at=expiry))
        else:
            if not pay or pay.customer_id!=c.id or pay.store_id!=body.store_id or pay.refunded_minor+body.amount_minor>pay.paid_minor:
                raise HTTPException(409,'退款无法与有效支付匹配')
            pay.refunded_minor+=body.amount_minor
        db.flush()
        before=db.get(Commission,body.order_id)
        previous_minor=before.accrued_minor if before else 0
        commission=commission_for(db,pay)
        if commission:
            delta=commission.accrued_minor-previous_minor
            db.add(CommissionLedger(event_id=body.event_id,order_id=body.order_id,
                                    actor_tr=commission.actor_tr,delta_minor=delta))
        db.add(ProcessedEvent(event_id=body.event_id,payload_sha256=hashlib.sha256(raw).hexdigest()))
        db.add(Audit(actor='trusted-payment-bridge',action=body.action,target=body.order_id,
                     metadata_json=json.dumps({'store_id':body.store_id,'amount_minor':body.amount_minor})))
        db.commit()
        return {'accepted':True,'duplicate':False,'commission_status':commission.status if commission else 'NOT_ELIGIBLE_OR_POLICY_MISSING',
                'provisional_commission_minor':commission.accrued_minor if commission else 0}


class ReserveBenefit(BaseModel):
    customer_id: str = Field(min_length=3,max_length=40)
    store_id: str
    order_id: str = Field(min_length=3,max_length=80)
    kind: str = Field(pattern=r'^(RETURN_DISCOUNT|COMPANION_GIFT)$')


@app.post(BASE_PATH + '/internal/benefits/reserve')
async def reserve_benefit(request: Request):
    # Trusted POS/pricing service only; this is a hold before payment, not a paper-card redemption.
    raw=await request.body();verify_finance_request(request,raw)
    try:body=ReserveBenefit.model_validate_json(raw)
    except Exception as exc:raise HTTPException(422,'权益请求格式不正确') from exc
    require_store(body.store_id)
    with db_session() as db:
        customer=db.get(Customer,body.customer_id)
        if not customer or not customer.first_paid_at or not customer.membership_expires_at or utc(customer.membership_expires_at)<=now():
            raise HTTPException(409,'会员无有效可核销权益')
        if db.get(PaymentFact,body.order_id):
            raise HTTPException(409,'不能给已经付款的订单事后预占优惠')
        existing=db.scalar(select(BenefitReservation).where(BenefitReservation.order_id==body.order_id))
        if existing:
            if existing.status=='HELD' and utc(existing.expires_at)>now():
                b=db.get(Benefit,existing.benefit_id)
                if b and b.customer_id==body.customer_id and b.kind==body.kind:
                    return {'reserved':True,'benefit_id':b.id,'expires_at':existing.expires_at.isoformat()}
            raise HTTPException(409,'订单已有不同的权益预占')
        candidates=list(db.scalars(select(Benefit).where(Benefit.customer_id==body.customer_id,
                                Benefit.kind==body.kind).with_for_update()))
        for candidate in candidates:
            prior=db.get(BenefitReservation,candidate.id)
            if candidate.status=='HELD' and prior and prior.status=='HELD' and utc(prior.expires_at)<=now():
                candidate.status='AVAILABLE'
        benefit=next((x for x in candidates if x.status=='AVAILABLE' and utc(x.expires_at)>now()),None)
        if not benefit:raise HTTPException(409,'当前没有剩余有效权益')
        prior=db.get(BenefitReservation,benefit.id)
        if prior and prior.status=='HELD' and utc(prior.expires_at)>now():
            raise HTTPException(409,'权益正在另一笔订单使用')
        if prior and prior.status=='HELD':
            # Expired hold: retain previous state in audit and atomically replace the one active slot.
            db.add(Audit(actor='trusted-checkout',action='EXPIRED_BENEFIT_HOLD_RELEASED',target=benefit.id,
                         metadata_json=json.dumps({'prior_order_id':prior.order_id})))
            db.delete(prior);db.flush()
        benefit.status='HELD'
        reservation=BenefitReservation(benefit_id=benefit.id,order_id=body.order_id,
                                        expires_at=now()+timedelta(minutes=10))
        db.add(reservation);db.commit()
        return {'reserved':True,'benefit_id':benefit.id,'expires_at':reservation.expires_at.isoformat()}


class PolicyInput(BaseModel):
    store_id: str
    version: str = Field(min_length=3,max_length=40)
    base_rate_bps: int = Field(ge=0,le=3000)
    full_days: int = Field(default=365,ge=1,le=730)
    reduced_days: int = Field(default=183,ge=0,le=730)
    reduced_coeff_bps: int = Field(default=3000,ge=0,le=10000)


@app.post(BASE_PATH + '/hq/commission-policy')
def create_policy(data: PolicyInput,request: Request):
    require_store(data.store_id)
    actor,_=staff_auth(request,None,write=True,hq=True)
    with db_session() as db:
        if db.scalar(select(Policy).where(Policy.store_id==data.store_id,Policy.version==data.version)):
            raise HTTPException(409,'该政策版本已存在')
        db.add(Policy(store_id=data.store_id,version=data.version,base_rate_bps=data.base_rate_bps,
                      full_days=data.full_days,reduced_days=data.reduced_days,
                      reduced_coeff_bps=data.reduced_coeff_bps,effective_at=now()))
        db.add(Audit(actor=actor,action='POLICY_CREATED',target=data.store_id,
                     metadata_json=json.dumps({'version':data.version})))
        db.commit()
        return {'ok':True,'version':data.version}


@app.get(BASE_PATH + '/staff/invite-qr')
def staff_invite_qr(request:Request,store_id:str):
    require_store(store_id)
    tr,_=staff_auth(request,store_id)
    import qrcode
    public_base=os.getenv('BSV_GROWTH_PUBLIC_BASE_URL','http://127.0.0.1:8767' if ISOLATED else '')
    if not public_base.startswith(('https://','http://127.0.0.1:')):
        raise HTTPException(503,'公网域名尚未通过配置核验')
    link=public_base.rstrip('/')+'/member/?'+urlencode({'store_id':store_id,'invite':signed({
        'kind':'invitation','tr':tr,'store':store_id,'exp':time.time()+14*86400})})
    buf=BytesIO();qrcode.make(link).save(buf,format='PNG');buf.seek(0)
    return StreamingResponse(buf,media_type='image/png',headers={'Cache-Control':'no-store'})


class MarketingPreference(BaseModel):
    marketing_opt_in: bool


@app.post(BASE_PATH + '/public/marketing-preference')
def marketing_preference(data:MarketingPreference,request:Request):
    with db_session() as db:
        sess=require_guest(request,db,True);customer=customer_for_session(db,sess)
        if not customer:raise HTTPException(404,'会员不存在')
        customer.marketing_opt_in=data.marketing_opt_in
        db.add(Audit(actor='customer:'+customer.id,action='MARKETING_CONSENT_CHANGED',target=customer.id,
                     metadata_json=json.dumps({'enabled':data.marketing_opt_in})))
        db.commit();return {'ok':True,'marketing_opt_in':data.marketing_opt_in}


@app.post(BASE_PATH + '/public/delete-request')
def delete_request(request:Request):
    with db_session() as db:
        sess=require_guest(request,db,True);customer=customer_for_session(db,sess)
        if not customer:raise HTTPException(404,'会员不存在')
        old=db.scalar(select(PrivacyRequest).where(PrivacyRequest.customer_id==customer.id,
                         PrivacyRequest.type=='ERASURE',PrivacyRequest.status=='PENDING_REVIEW'))
        if old:return {'ok':True,'status':old.status,'request_id':old.id}
        row=PrivacyRequest(customer_id=customer.id,type='ERASURE')
        customer.marketing_opt_in=False
        db.add(row);db.add(Audit(actor='customer:'+customer.id,action='ERASURE_REQUESTED',target=customer.id))
        db.commit();return {'ok':True,'status':row.status,'request_id':row.id}


@app.get('/member/')
def member_page():
    return FileResponse(ROOT/'apps/guest-web/member/index.html',media_type='text/html',headers={'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})


@app.get('/staff/growth/')
def staff_page():
    return FileResponse(ROOT/'apps/staff-center/growth/index.html',media_type='text/html',headers={'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})


@app.get('/member/privacy')
def member_privacy():
    return FileResponse(ROOT/'apps/guest-web/member/privacy.html',media_type='text/html',headers={'Cache-Control':'no-store'})


@app.get('/member/{asset_name}')
def member_asset(asset_name:str):
    if asset_name not in ('styles.css','app.js'):
        raise HTTPException(404,'Not found')
    return FileResponse(ROOT/'apps/guest-web/member'/asset_name,media_type='text/css' if asset_name.endswith('.css') else 'application/javascript',headers={'Cache-Control':'no-store'})


@app.get('/staff/growth/{asset_name}')
def staff_asset(asset_name:str):
    if asset_name not in ('styles.css','app.js'):
        raise HTTPException(404,'Not found')
    return FileResponse(ROOT/'apps/staff-center/growth'/asset_name,media_type='text/css' if asset_name.endswith('.css') else 'application/javascript',headers={'Cache-Control':'no-store'})


@app.get('/growth/health')
def health():
    return {'status':'ready' if ISOLATED else ('pending-integration' if ENV=='production' else 'disabled'),
            'mode':ENV,'payments_connected':bool(PAYMENT_SIGNING_KEY),'customer_schema_verified':False}
