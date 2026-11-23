"""BSV ONE canonical BSV1 isolated staging foundation: shared POS/HQ/recipe guide; no real payment.

Python 3.10+, standard library only; localhost-only. Existing V1 SQLite data is migrated
additively and is never deleted. Staging disables built-in demo users; all settlement is UNVERIFIED and not evidence of payment.
"""
from __future__ import annotations
import hashlib, hmac, json, os, re, secrets, sqlite3, time, uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

ROOT = Path(__file__).resolve().parent
APPS = ROOT.parents[2] / "apps"
# 所有模块统一由 bsv_database_config.py 决定数据库路径与文件名。
from bsv_database_config import get_database_path
from bsv_catalog_config import get_excel_path,SHOW_LOCAL_TRAINING_ITEMS
from bsv_v9_import import sync_v9, catalog_for_store as v9_catalog_for_store,price_is_current as v9_price_is_current
from bsv_catalog_contract import semantic_attributes, registry_version
from bsv_catalog_repository import (SQLiteCatalogReadRepository, PostgresCatalogReadRepository,
                                    postgres_catalog_enabled)
import bsv_collab as collab
from bsv_ledger import checkout_report, checkout_csv_bytes
import bsv_layouts
import bsv_one
import bsv_device_pos as device_pos
import bsv_growth_pos as growth_pos
DB_PATH = get_database_path(ROOT)
# Cloud preview is exclusively behind a local-loopback reverse proxy with HTTPS + access gate.
MODE = os.environ.get('BSV_MODE', 'local').strip().lower()
if MODE not in ('local','staging'):
    raise RuntimeError('该版本尚未支持正式营业模式，仅允许 local 或 staging')
HOST = '127.0.0.1'  # NEVER expose Python HTTP server directly to the Internet.
PORT = int(os.environ.get('BSV_PORT', '8767'))
APP_VERSION = '3.1.0-canonical-handoff-preview'
SCHEMA_VERSION = 28


def device_required():
    return os.environ.get("BSV_POS_DEVICE_REQUIRED") == "1"


def growth_integration():
    return (MODE == "staging" and device_required()
            and os.environ.get("BSV_POS_INTERNAL_STAGE") == "1"
            and os.environ.get("BSV_POS_IDENTITY_REQUIRED") == "1"
            and os.environ.get("BSV_POS_GROWTH_INTEGRATION") == "1")


def g1_synthetic_store_activation():
    """Allow the three canonical layouts only in an explicit isolated test stack."""
    if (MODE != "staging" or os.environ.get("BSV_APP_ENV") != "isolated"
            or os.environ.get("BSV_POS_INTERNAL_STAGE") != "1"
            or os.environ.get("BSV_POS_G1_TEST_STORES") != "BSVM,BSVS,BSVT"):
        return False
    try:
        registered = {store["store_id"] for store in bsv_layouts.registry()}
    except (KeyError, TypeError, ValueError, bsv_layouts.LayoutError):
        return False
    return {"BSVM", "BSVS", "BSVT"} <= registered


def application_version():
    return "4.1-isolated-device" if device_required() else APP_VERSION


def identity_client():
    # POS is also started directly by the legacy standalone launcher.
    import sys
    repo = str(ROOT.parents[2])
    if repo not in sys.path:
        sys.path.append(repo)
    from integrations.auth import identity_client as client
    return client

SESSION_SECONDS = 8 * 3600
DEFAULT_WARN_SECONDS = 8 * 60    # DEMO PARAMETER, not empirically validated
DEFAULT_LATE_SECONDS = 15 * 60   # DEMO PARAMETER, not empirically validated
DEFAULT_CRITICAL_SECONDS = 20 * 60 # DEMO PARAMETER, not empirically validated
BATHROOM_WARNING_SECONDS = 15 * 60
BATHROOM_CRITICAL_SECONDS = 15 * 60
SEAT_WARNING_SECONDS = 3 * 60
SEAT_LATE_SECONDS = 5 * 60
SEAT_CRITICAL_SECONDS = 8 * 60
BATHROOM_INTERVAL_SECONDS = 2 * 3600

# 所有门店元数据及地图结构均从 store_layouts/ 加载，不在程序里内置门店常量。
BEIJING_TZ = timezone(timedelta(hours=8),name='Asia/Shanghai')

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def timestamp(): return int(time.time())
def uid(): return uuid.uuid4().hex

def pin_hash(pin, salt):
    return hashlib.pbkdf2_hmac('sha256',pin.encode(),salt,220000).hex()

def connect():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(str(DB_PATH),timeout=15,isolation_level=None)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=10000')
    db.execute('PRAGMA journal_mode=WAL')
    return db

@contextmanager
def db_read():
    db=connect()
    try: yield db
    finally: db.close()

@contextmanager
def tx():
    db=connect()
    try:
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except BaseException:
        db.rollback();raise
    finally:db.close()

def add_col(db,table,column,spec):
    if column not in {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}:
        db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {spec}')

def init_db():
    # 先完整校验所有门店文件，任何一处配置无效时不改数据库。
    configs=bsv_layouts.all_configs()
    previous_db_version = 0
    if DB_PATH.exists():
        src=sqlite3.connect(str(DB_PATH))
        try:
            version=src.execute('PRAGMA user_version').fetchone()[0]
            previous_db_version=version
            # BSV ONE formal build must never silently inherit V2.x test ID schema.
            tables={r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if {'stores','seats','visits'} & tables:
                if 'bsv_platform_identity' not in tables:
                    raise RuntimeError('禁止将V2.x测试数据库原地升级到统一正式底座；请使用独立全新SQLite路径。保留旧库供归档核查。')
                ident=src.execute("SELECT profile FROM bsv_platform_identity WHERE profile='BSV_ONE_CANONICAL_V1'").fetchone()
                if not ident:
                    raise RuntimeError('数据库身份标记不一致，拒绝启动并停止迁移。')
                if 'seats' in tables:
                    bad=src.execute("SELECT id,store_id FROM seats WHERE id NOT LIKE store_id || '-%' OR id NOT LIKE store_id || '-SEAT-%' LIMIT 1").fetchone()
                    if bad:raise RuntimeError('检测到非规范座位ID；禁止使用历史测试库：'+str(bad[0]))
                    bad=src.execute("SELECT id FROM seats WHERE id NOT GLOB store_id || '-SEAT-[0-9][0-9][0-9][0-9]' LIMIT 1").fetchone()
                    if bad:raise RuntimeError('发现旧座位编码，拒绝启动：'+str(bad[0]))
                if 'table_groups' in tables:
                    bad=src.execute("SELECT id,store_id FROM table_groups WHERE id NOT GLOB store_id || '-GROUP-[0-9][0-9][0-9][0-9]' LIMIT 1").fetchone()
                    if bad:raise RuntimeError('检测到非规范合分桌组ID；禁止使用历史测试库：'+str(bad[0]))
            if version>SCHEMA_VERSION:raise RuntimeError('数据库版本比当前程序更新，禁止降级打开')
            has_data=src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stores'").fetchone()
            has_map_table=src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='store_layout_data'").fetchone()
            old_hashes=dict(src.execute('SELECT store_id,content_sha FROM store_layout_data').fetchall()) if has_map_table else {}
            has_ownership=src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bsv_layout_ownership'").fetchone()
            protected={x[0] for x in src.execute("SELECT store_id FROM bsv_layout_ownership WHERE origin='HQ_PUBLISHED'")} if has_ownership else set()
            map_updates=[cfg['store_id'] for _,cfg,digest,_ in configs if cfg and cfg['store_id'] not in protected and old_hashes.get(cfg['store_id'])!=digest]
            # Additive HQ audit alias migration must be backed up before init.
            # Runtime draft handling is never allowed to change SQLite schema.
            needs_hq_audit_migration = bool(has_data and 'bsv_hq_actor_aliases' not in tables)
            # 同一版本仅更改某店JSON/SVG，也必须先做原子一致性备份。
            if has_data and (version<SCHEMA_VERSION or map_updates or needs_hq_audit_migration):
                stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                reason=('升级V28备份' if version<SCHEMA_VERSION
                        else '总部地图审计表迁移前备份' if needs_hq_audit_migration
                        else '门店地图更新前备份')
                backup=DB_PATH.parent/(DB_PATH.stem+'_'+reason+'_'+stamp+'.sqlite3')
                with sqlite3.connect(str(backup)) as dest:src.backup(dest)
        finally:src.close()
    # executescript commits on sqlite3; run schema creation before the seeded transaction.
    with db_read() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS stores (
          id TEXT PRIMARY KEY,name TEXT NOT NULL,design_max_guests INTEGER NOT NULL,
          orientation TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS table_groups (
          id TEXT PRIMARY KEY,store_id TEXT NOT NULL REFERENCES stores(id),
          primary_seat TEXT NOT NULL,secondary_seat TEXT NOT NULL,
          mode TEXT NOT NULL CHECK(mode IN ('SPLIT','MERGED')));
        CREATE TABLE IF NOT EXISTS seats (
          id TEXT PRIMARY KEY,store_id TEXT NOT NULL REFERENCES stores(id),label TEXT NOT NULL,
          seat_type TEXT NOT NULL,x REAL NOT NULL,y REAL NOT NULL,display_order INTEGER NOT NULL,
          group_id TEXT REFERENCES table_groups(id),is_secondary INTEGER NOT NULL DEFAULT 0,
          UNIQUE(store_id,label));
        CREATE TABLE IF NOT EXISTS staff (
          id TEXT PRIMARY KEY,staff_code TEXT UNIQUE NOT NULL,pin_salt TEXT NOT NULL,
          pin_digest TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('STAFF','MANAGER')),
          enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS sessions (
          token_digest TEXT PRIMARY KEY,staff_id TEXT NOT NULL REFERENCES staff(id),
          csrf TEXT NOT NULL,expires_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS bsv_products (
          id TEXT PRIMARY KEY,name TEXT NOT NULL,price_cents INTEGER NOT NULL CHECK(price_cents>=0),
          demo_only INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS visits (
          id TEXT PRIMARY KEY,store_id TEXT NOT NULL REFERENCES stores(id),seat_id TEXT NOT NULL REFERENCES seats(id),
          guests INTEGER NOT NULL DEFAULT 1,status TEXT NOT NULL CHECK(status IN ('OPEN','CANCELLED','TEST_CLOSED')),
          created_by TEXT NOT NULL REFERENCES staff(id),created_at TEXT NOT NULL,closed_at TEXT,
          version INTEGER NOT NULL DEFAULT 1);
        CREATE UNIQUE INDEX IF NOT EXISTS one_open_visit_per_seat ON visits(seat_id) WHERE status='OPEN';
        CREATE TABLE IF NOT EXISTS visit_member_links (
          visit_id TEXT NOT NULL REFERENCES visits(id),person_slot INTEGER NOT NULL CHECK(person_slot>=1),
          member_reference TEXT NOT NULL,PRIMARY KEY(visit_id,person_slot));
        CREATE TABLE IF NOT EXISTS orders (
          id TEXT PRIMARY KEY,visit_id TEXT NOT NULL UNIQUE REFERENCES visits(id),
          status TEXT NOT NULL CHECK(status IN ('OPEN','CANCELLED','TEST_CLOSED')),
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS order_lines (
          id TEXT PRIMARY KEY,order_id TEXT NOT NULL REFERENCES orders(id),
          product_id TEXT NOT NULL REFERENCES bsv_products(id),product_name_snapshot TEXT NOT NULL,
          price_cents INTEGER NOT NULL,quantity INTEGER NOT NULL CHECK(quantity>=1));
        CREATE TABLE IF NOT EXISTS audit_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,store_id TEXT NOT NULL,
          staff_id TEXT REFERENCES staff(id),action TEXT NOT NULL,target_id TEXT,
          detail_json TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS staff_store_access (
          staff_id TEXT NOT NULL REFERENCES staff(id),store_id TEXT NOT NULL REFERENCES stores(id),
          PRIMARY KEY(staff_id,store_id));
        CREATE TABLE IF NOT EXISTS seat_cleaning (
          seat_id TEXT PRIMARY KEY REFERENCES seats(id),store_id TEXT NOT NULL REFERENCES stores(id),
          state TEXT NOT NULL CHECK(state IN ('CLEAN','DIRTY')) DEFAULT 'CLEAN',
          dirty_at TEXT,cleaned_at TEXT,cleaned_by TEXT REFERENCES staff(id));
        CREATE TABLE IF NOT EXISTS bathrooms (
          id TEXT PRIMARY KEY,store_id TEXT NOT NULL REFERENCES stores(id),
          label TEXT NOT NULL,last_clean_at TEXT,last_clean_by TEXT REFERENCES staff(id),
          interval_seconds INTEGER NOT NULL DEFAULT 7200);
        CREATE TABLE IF NOT EXISTS bathroom_checks (
          id TEXT PRIMARY KEY,bathroom_id TEXT NOT NULL REFERENCES bathrooms(id),
          store_id TEXT NOT NULL REFERENCES stores(id),staff_id TEXT NOT NULL REFERENCES staff(id),
          checklist_json TEXT NOT NULL,checked_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS visit_seat_events (
          id TEXT PRIMARY KEY,visit_id TEXT NOT NULL REFERENCES visits(id),
          from_seat_id TEXT,to_seat_id TEXT NOT NULL REFERENCES seats(id),
          staff_id TEXT NOT NULL REFERENCES staff(id),created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS demo_checkouts (
          id TEXT PRIMARY KEY,visit_id TEXT NOT NULL REFERENCES visits(id),store_id TEXT NOT NULL REFERENCES stores(id),
          amount_cents INTEGER NOT NULL CHECK(amount_cents>=0),
          status TEXT NOT NULL CHECK(status='TEST_SETTLED'),
          created_at TEXT NOT NULL,created_by TEXT NOT NULL REFERENCES staff(id));
        CREATE TABLE IF NOT EXISTS visit_closures (
          visit_id TEXT PRIMARY KEY REFERENCES visits(id),store_id TEXT NOT NULL REFERENCES stores(id),
          closed_by TEXT NOT NULL REFERENCES staff(id),print_preference TEXT NOT NULL
          CHECK(print_preference IN ('NONE','PAPER')),closed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS store_documents (
          id TEXT PRIMARY KEY,store_id TEXT NOT NULL REFERENCES stores(id),
          title TEXT NOT NULL,filename TEXT,kind TEXT NOT NULL,available INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS order_drafts (
          id TEXT PRIMARY KEY,visit_id TEXT NOT NULL REFERENCES visits(id),
          product_id TEXT NOT NULL REFERENCES bsv_products(id),
          quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity>0),
          created_by TEXT NOT NULL REFERENCES staff(id),created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_draft_visit ON order_drafts(visit_id);
        CREATE TABLE IF NOT EXISTS members (
          id TEXT PRIMARY KEY,surname TEXT NOT NULL,phone TEXT NOT NULL UNIQUE,
          last4 TEXT NOT NULL,tier TEXT NOT NULL CHECK(tier='SILVER'),
          active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_members_last4 ON members(last4,active);
        CREATE TABLE IF NOT EXISTS alert_escalations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,store_id TEXT NOT NULL,
          category TEXT NOT NULL,entity_id TEXT NOT NULL,cycle_key TEXT NOT NULL,
          occurred_at TEXT NOT NULL,detail_json TEXT NOT NULL,
          UNIQUE(category,entity_id,cycle_key));
        CREATE TABLE IF NOT EXISTS command_dedup (
          action_id TEXT PRIMARY KEY,store_id TEXT NOT NULL,
          response_json TEXT NOT NULL,created_at TEXT NOT NULL);
        ''')
        add_col(db,'order_drafts','price_cents_snapshot','INTEGER')
        add_col(db,'order_drafts','source_revision_snapshot','TEXT')
        add_col(db,'seats','seat_capacity','INTEGER')
        add_col(db,'seats','layout_enabled','INTEGER NOT NULL DEFAULT 1')
        add_col(db,'visits','seat_label_snapshot','TEXT')
        # 旧账单在地图重绘之前保存当时展示的座位号。
        db.execute('''UPDATE visits SET seat_label_snapshot=(SELECT label FROM seats WHERE id=visits.seat_id) WHERE seat_label_snapshot IS NULL''')
        add_col(db,'stores','district','TEXT')
        add_col(db,'stores','business_type','TEXT')
        add_col(db,'stores','layout_ready','INTEGER NOT NULL DEFAULT 0')
        add_col(db,'sessions','store_id','TEXT REFERENCES stores(id)')
        add_col(db,'order_lines','created_at','TEXT')
        add_col(db,'order_lines','served_at','TEXT')
        add_col(db,'order_lines','status',"TEXT NOT NULL DEFAULT 'PENDING'")
        add_col(db,'order_lines','checkout_id','TEXT REFERENCES demo_checkouts(id)')
        add_col(db,'order_lines','added_by','TEXT REFERENCES staff(id)')
        add_col(db,'order_lines','list_price_cents','INTEGER')
        add_col(db,'order_lines','discount_cents','INTEGER NOT NULL DEFAULT 0')
        add_col(db,'order_lines','member_tier_snapshot','TEXT')
        add_col(db,'visit_member_links','member_id','TEXT REFERENCES members(id)')
        add_col(db,'bsv_products','discount_eligible','INTEGER NOT NULL DEFAULT 1')
        add_col(db,'bathrooms','monitor_started_at','TEXT')
        db.execute('CREATE INDEX IF NOT EXISTS ix_audit_store_date ON audit_events(store_id,created_at)')
        db.execute('CREATE INDEX IF NOT EXISTS ix_visits_close_date ON visits(store_id,closed_at)')
        db.execute('CREATE INDEX IF NOT EXISTS ix_checkouts_store_time ON demo_checkouts(store_id,created_at)')
        db.execute('CREATE INDEX IF NOT EXISTS ix_order_lines_checkout ON order_lines(checkout_id)')
        db.execute('UPDATE bathrooms SET monitor_started_at=? WHERE monitor_started_at IS NULL',(now(),))
        db.execute('CREATE INDEX IF NOT EXISTS ix_lines_queue ON order_lines(status,created_at)')
        db.execute('CREATE INDEX IF NOT EXISTS ix_visits_store ON visits(store_id,status)')
    with db_read() as db:
        collab.schema(db)
        bsv_one.schema(db)
        if device_required():
            device_pos.schema(db)
        if growth_integration():
            growth_pos.install_pos_projection(db)
    with tx() as db:
        # 仅新建的规范数据库可在本程序内迭代；拒绝迁移旧V2.x测试库。
        bsv_layouts.apply_data(db, configs, force=previous_db_version<SCHEMA_VERSION,
                               activate=g1_synthetic_store_activation())
        # 门店原图与手册也从独立门店档案注册，不再在代码中逐店罗列。
        for entry in bsv_layouts.registry():
            code=entry['store_id']
            for doc in entry.get('documents',[]):
                filename=doc.get('filename')
                if filename and (not filename.startswith('assets/'+code+'_') or '/' in filename[7:]):
                    raise bsv_layouts.LayoutError('门店文件路径未通过权限校验：'+code)
                db.execute('''INSERT OR IGNORE INTO store_documents(id,store_id,title,filename,kind,available)
                    VALUES(?,?,?,?,?,?)''',(doc['id'],code,doc['title'],filename,doc['kind'],int(bool(filename))))
            db.execute('INSERT OR IGNORE INTO store_documents(id,store_id,title,filename,kind,available) VALUES(?,?,?,?,?,?)',
                       (code+'-MANUAL',code,'门店工作手册（PDF）',None,'MANUAL',0))
        # Clean foundation never automatically creates demonstration staff identities.
        # New staging administrators must be provisioned explicitly via manage_stage_user.sh.
        # No synthetic catalog SKUs or historical demo identity seeded in the clean foundation.
        # Non-destructive migration of old V1 records; never alter settled/previous states.
        db.execute('''UPDATE order_lines SET created_at=(SELECT o.created_at FROM orders o WHERE o.id=order_lines.order_id)
                      WHERE created_at IS NULL''')
        # Legacy sessions are invalidated because they were never associated with a store.
        db.execute('DELETE FROM sessions WHERE store_id IS NULL')
    with db_read() as db:
        db.execute('PRAGMA user_version=28')
        qc = db.execute('PRAGMA quick_check').fetchone()[0]
        if qc != 'ok':
            raise RuntimeError('数据库完整性校验失败，已停止启动：'+str(qc))
    # HQ history is additive; it never edits existing POS orders.
    with tx() as db:
        bsv_one.seed_revisions(db)
    # V9只是源文件；生产订单/价格快照和事务仍存储在SQLite。任一源文件损坏则阻止本地启动.
    if postgres_catalog_enabled():
        print('BSV ALL catalog read source: PostgreSQL 17 (isolated opt-in); SQLite V9 import is paused.')
    else:
        from bsv_v9_import import sync_v9
        report=sync_v9(DB_PATH,get_excel_path(ROOT))
        print('BSV ALL V9同步：', {k:v for k,v in report.items() if k in ('C','P','M','K','R','Q','T','eligible_quotes','unchanged')})
    with tx() as db:
        # AJ统一售价为唯一有效价格源，不再读取旧版门店临时价格。
        # Legacy pending records are represented without modifying source history.
        for x in db.execute('''SELECT l.id AS line_id,v.store_id,v.id AS visit_id,l.status,l.created_at
              FROM order_lines l JOIN orders o ON o.id=l.order_id JOIN visits v ON v.id=o.visit_id
              WHERE l.status='PENDING' AND v.status='OPEN' '''):
            db.execute('''INSERT OR IGNORE INTO production_tasks(line_id,store_id,visit_id,state,assigned_at)
                VALUES(?,?,?,'PENDING',?)''',(x['line_id'],x['store_id'],x['visit_id'],x['created_at'] or now()))

def price_is_current(db,product,store_id):
    return v9_price_is_current(db,product,store_id)

def catalog_for_store(db,store_id):
    """已审核可售商品镜像；资料库查询由独立只读接口提供。"""
    items=v9_catalog_for_store(db,store_id)
    for item in items:
        item['initials']=collab.initials(item['name'])
    return items

def catalog_source(db):
    row=db.execute('SELECT source_sha,imported_at,summary_json FROM bsv_v9_sync WHERE one=1').fetchone()
    if not row:return {'status':'NOT_IMPORTED','sha256':None,'imported_at':None,'counts':{}}
    try:summary=json.loads(row['summary_json'])
    except (TypeError,ValueError):summary={}
    return {'status':'SYNCED','sha256':row['source_sha'],'imported_at':row['imported_at'],
            'counts':{k:summary.get(k,0) for k in ('C','P','M','K','R','Q','T','extras')}}


class UserError(Exception):
    def __init__(self,message,status=400,code=None):
        super().__init__(message)
        self.message=message
        self.status=status
        self.code=code

def required(d,key,maxlen=80):
    v=d.get(key)
    if not isinstance(v,str) or not v.strip() or len(v)>maxlen:raise UserError('无效字段：'+key)
    return v

def store_info(db,store_id):
    s=db.execute('SELECT * FROM stores WHERE id=?',(store_id,)).fetchone()
    if not s:raise UserError('门店不存在',404)
    return dict(s)

def health_snapshot():
    try:
        excel_path = get_excel_path(ROOT)
        excel_error = None
    except Exception as e:
        excel_path = ROOT/'resources'/'BSV_ALL_V9.xlsx'
        excel_error = str(e)
    asset_files = [APPS/'store-console/bsv1/assets'/'BSV_徽记.png', APPS/'store-console/bsv1/assets'/'BSV_完整徽标.png']
    for s in bsv_layouts.registry():
        if s.get('layout_file'):
            asset_files.append(bsv_layouts.MAP_DIR/'art'/(s['store_id']+'.svg'))
    result = {
        'service':'BSV1-multi-store','version':application_version(),'mode':MODE,'payments':False,
        'server_time': now(),
        'db_path': str(DB_PATH), 'db_exists': DB_PATH.exists(),
        'excel_path': str(excel_path), 'excel_exists': Path(excel_path).exists() and not excel_error,
        'assets_ok': all(x.exists() for x in asset_files), 'status':'正常', 'checks':[]
    }
    qc='ok'; catalog=None
    try:
        with db_read() as db:
            qc = db.execute('PRAGMA quick_check').fetchone()[0]
            row = db.execute('SELECT source_path,source_sha,imported_at,summary_json FROM bsv_v9_sync WHERE one=1').fetchone()
            if row:
                catalog = dict(row)
                try:
                    catalog['summary'] = json.loads(catalog.pop('summary_json'))
                except Exception:
                    catalog['summary'] = None
    except Exception as e:
        qc = 'error: '+str(e)
    result['db_quick_check'] = qc
    result['catalog_sync'] = catalog
    result['payment_verified'] = False
    result['business_mode_ready'] = False
    result['notice'] = '仅本地联调。收款机构尚未连接；结账金额只代表系统登记。'
    counts=((catalog or {}).get('summary') or {})
    quote_count = counts.get('c_aj_priced', 0)
    result['approved_quote_count'] = quote_count  # 旧界面兼容字段，含义已变为AJ有效标价款数
    result['price_policy'] = counts.get('price_policy')
    result['c_aj_missing_count'] = len(counts.get('c_aj_missing') or [])
    try:
        current_hash = hashlib.sha256(Path(excel_path).read_bytes()).hexdigest()
    except Exception:
        current_hash = None
    source_current = bool(catalog and current_hash and catalog.get('source_sha') == current_hash)
    result['catalog_source_current'] = source_current
    checks = [
        {'id':'service','label':'本地服务','ok':True,'detail':'程序已响应自检接口'},
        {'id':'db','label':'SQLite数据库','ok':result['db_exists'] and qc=='ok','detail':str(DB_PATH)},
        {'id':'excel','label':'V9 Excel 源文件','ok':result['excel_exists'],'detail':excel_error or str(excel_path)},
        {'id':'assets','label':'门店图纸与Logo资源','ok':result['assets_ok'],'detail':'已检查关键图片资源是否存在'},
        {'id':'catalog','label':'V9同步状态','ok':source_current,'detail':('已同步到当前Excel' if source_current else '源文件与已同步数据不一致；请重新同步')},
    ]
    if not all(c['ok'] for c in checks):
        result['status']='异常'
    elif qc != 'ok' or not catalog or result['c_aj_missing_count']>0:
        result['status']='警告'
    result['checks']=checks
    result['warnings']=(['未连接真实支付，不能核验到账'] + (['C表AJ列尚有%d款缺少售价，请补齐后同步'%result['c_aj_missing_count']] if result['c_aj_missing_count'] else []))
    if MODE != 'local':
        # /api/health is intentionally public, so do not disclose server filesystem paths.
        result['db_path']='[hidden]';result['excel_path']='[hidden]'
        for check in result['checks']:
            if check['id'] in ('db','excel'):check['detail']='路径仅供本地运维查看'
        if result['catalog_sync']:result['catalog_sync']['source_path']='[hidden]'
    return result

def record(db,staff,action,target,detail=None):
    detail = dict(detail or {})
    if staff.get("authority"):
        detail["authority"] = staff["authority"]
        if staff.get("request_id"):
            detail["request_id"] = staff["request_id"]
    db.execute('INSERT INTO audit_events(store_id,staff_id,action,target_id,detail_json,created_at) VALUES (?,?,?,?,?,?)',
               (staff['session_store_id'],staff['id'],action,target,json.dumps(detail,ensure_ascii=False),now()))

def visible(db,store_id,seat_id):
    r=db.execute('''SELECT s.id,s.is_secondary,g.mode FROM seats s
          LEFT JOIN table_groups g ON g.id=s.group_id WHERE s.id=? AND s.store_id=?''',
          (seat_id,store_id)).fetchone()
    return bool(r) and not (r['is_secondary'] and r['mode']=='MERGED')

def seat_clean(db,store_id,seat_id):
    x=db.execute('SELECT state FROM seat_cleaning WHERE seat_id=? AND store_id=?',(seat_id,store_id)).fetchone()
    return x and x['state']=='CLEAN'

def live_visit(db,store_id,vid):
    v=db.execute("SELECT * FROM visits WHERE id=? AND store_id=? AND status='OPEN'",(vid,store_id)).fetchone()
    if not v:raise UserError('桌次已结束或不属于当前登录门店，请刷新',409)
    return v

def visit_all(db,store_id,vid):
    v=db.execute('SELECT * FROM visits WHERE id=? AND store_id=?',(vid,store_id)).fetchone()
    if not v:raise UserError('此门店没有该桌次',404)
    return v

def order_for(db,vid):
    return db.execute('SELECT * FROM orders WHERE visit_id=?',(vid,)).fetchone()

def get_lines(db,order_id):
    return [dict(r) for r in db.execute('''SELECT l.*,st.staff_code AS created_by_code
      FROM order_lines l LEFT JOIN staff st ON st.id=l.added_by
      WHERE l.order_id=? ORDER BY l.created_at,l.rowid''',(order_id,))]

def mask_phone(phone):
    return phone[:3]+'****'+phone[-4:]

def bsv_day_filter(value, end=False):
    if not value:return None
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise UserError('日期格式必须为YYYY-MM-DD')
    # China uses UTC+08:00 with no contemporary daylight-saving time. Avoid
    # ZoneInfo('Asia/Shanghai') here: Windows Python 3.12 often has no tzdata package.
    try:d=datetime.strptime(value,'%Y-%m-%d').replace(tzinfo=BEIJING_TZ)
    except ValueError:raise UserError('日期无效')
    if end:d+=timedelta(days=1)
    return d.astimezone(timezone.utc).isoformat(timespec='seconds')

def report_escalations(store_id):
    # Atomic, unique incident-once registration; tests can trigger by backdating timestamps.
    with tx() as db:
        t=datetime.now(timezone.utc)
        candidates=[]
        for r in db.execute('''SELECT l.id,l.created_at,v.seat_id FROM order_lines l
             JOIN orders o ON o.id=l.order_id JOIN visits v ON v.id=o.visit_id
             WHERE v.store_id=? AND v.status='OPEN' AND l.status='PENDING' ''',(store_id,)):
            seconds=(t-datetime.fromisoformat(r['created_at'])).total_seconds()
            if seconds>=DEFAULT_CRITICAL_SECONDS:
                candidates.append(('SERVICE',r['id'],r['created_at'],{'seat_id':r['seat_id'],'overdue_seconds':int(seconds-DEFAULT_LATE_SECONDS)}))
        for r in db.execute('SELECT * FROM bathrooms WHERE store_id=?',(store_id,)):
            stamp=r['last_clean_at'] or r['monitor_started_at']
            if stamp and (t-datetime.fromisoformat(stamp)).total_seconds() >= r['interval_seconds']+BATHROOM_CRITICAL_SECONDS:
                candidates.append(('BATHROOM',r['id'],stamp,{'label':r['label'],'overdue_seconds':int((t-datetime.fromisoformat(stamp)).total_seconds()-r['interval_seconds'])}))
        for r in db.execute("SELECT * FROM seat_cleaning WHERE store_id=? AND state='DIRTY'",(store_id,)):
            if r['dirty_at'] and (t-datetime.fromisoformat(r['dirty_at'])).total_seconds()>=SEAT_CRITICAL_SECONDS:
                candidates.append(('SEAT',r['seat_id'],r['dirty_at'],{'seat_id':r['seat_id'],'overdue_seconds':int((t-datetime.fromisoformat(r['dirty_at'])).total_seconds()-SEAT_LATE_SECONDS)}))
        for kind,eid,cycle,info in candidates:
            cur=db.execute('''INSERT OR IGNORE INTO alert_escalations(store_id,category,entity_id,cycle_key,occurred_at,detail_json)
                 VALUES (?,?,?,?,?,?)''',(store_id,kind,eid,cycle,now(),json.dumps(info,ensure_ascii=False)))
            if cur.rowcount:
                db.execute('''INSERT INTO audit_events(store_id,staff_id,action,target_id,detail_json,created_at)
                   VALUES (?,NULL,'CRITICAL_OVERDUE',?,?,?)''',(store_id,eid,json.dumps({'category':kind,**info},ensure_ascii=False),now()))

def state(db,staff):
    store=store_info(db,staff['session_store_id'])
    store_id=store['id']
    seats=[dict(r) for r in db.execute('''SELECT s.*,sc.state AS cleaning_state,sc.dirty_at AS dirty_at,
        CASE WHEN s.layout_enabled=0 OR (s.is_secondary=1 AND g.mode='MERGED') THEN 0 ELSE 1 END AS enabled,
        g.mode AS group_mode FROM seats s
        LEFT JOIN table_groups g ON g.id=s.group_id
        LEFT JOIN seat_cleaning sc ON sc.seat_id=s.id
        WHERE s.store_id=? AND s.layout_enabled=1 ORDER BY s.display_order''',(store_id,))]
    visits=[]
    for raw in db.execute("SELECT * FROM visits WHERE store_id=? AND status='OPEN' ORDER BY created_at",(store_id,)):
        v=dict(raw)
        o=order_for(db,v['id']);v['order_id']=o['id'];v['lines']=get_lines(db,o['id'])
        v['member_reference']=db.execute('''SELECT member_reference FROM visit_member_links
                    WHERE visit_id=? AND person_slot=1''',(v['id'],)).fetchone()
        v['member_reference']=v['member_reference'][0] if v['member_reference'] else ''
        v['canonical_customer_linked']=False
        if growth_integration():
            linked=db.execute("""SELECT canonical_customer_id FROM visit_member_links
                                 WHERE visit_id=? AND person_slot=1""",(v['id'],)).fetchone()
            v['canonical_customer_linked']=bool(linked and linked['canonical_customer_id'])
        v['drafts']=[dict(x) for x in db.execute('''SELECT d.*,p.name AS product_name,
           COALESCE(d.price_cents_snapshot,p.price_cents) AS price_cents,p.discount_eligible,
           p.sale_enabled,p.catalog_sha,p.store_id AS product_store_id
           FROM order_drafts d JOIN bsv_products p ON p.id=d.product_id WHERE d.visit_id=?
           ORDER BY d.created_at,d.rowid''',(v['id'],))]
        v['draft_total_cents']=sum(x['quantity']*x['price_cents'] for x in v['drafts'])
        v['member'] = None
        member=db.execute('''SELECT m.id,m.surname,m.phone,m.tier FROM visit_member_links l
          JOIN members m ON m.id=l.member_id WHERE l.visit_id=? AND l.person_slot=1 AND m.active=1''',(v['id'],)).fetchone()
        if member:
            v['member']={'id':member['id'],'surname':member['surname'],'masked_phone':mask_phone(member['phone']),
                         'tier':member['tier'],'discount_percent':10}
        v['total_cents']=sum(x['quantity']*x['price_cents'] for x in v['lines'] if x['status']!='CANCELLED')
        v['unsettled_cents']=sum(x['quantity']*x['price_cents'] for x in v['lines'] if x['checkout_id'] is None and x['status']!='CANCELLED')
        v['checkouts']=[dict(x) for x in db.execute('SELECT * FROM demo_checkouts WHERE visit_id=? ORDER BY created_at',(v['id'],))]
        visits.append(v)
    groups=[dict(x) for x in db.execute('SELECT * FROM table_groups WHERE store_id=?',(store_id,))]
    bathrooms=[dict(x) for x in db.execute('SELECT * FROM bathrooms WHERE store_id=?',(store_id,))]
    docs=[dict(x) for x in db.execute('SELECT id,title,kind,available FROM store_documents WHERE store_id=?',(store_id,))]
    for doc in docs:doc['file_url']='/api/document?doc_id='+doc['id'] if doc['available'] else None
    audit=[]
    for r in db.execute('''SELECT e.id,e.action,e.target_id,e.detail_json,e.created_at,s.staff_code
          FROM audit_events e LEFT JOIN staff s ON e.staff_id=s.id
          WHERE e.store_id=? ORDER BY e.id DESC LIMIT 45''',(store_id,)):
        x=dict(r);x['detail']=json.loads(x.pop('detail_json'));audit.append(x)
    escalations=[dict(x) for x in db.execute('''SELECT id,category,entity_id,cycle_key,occurred_at,detail_json
          FROM alert_escalations WHERE store_id=? ORDER BY id DESC LIMIT 30''',(store_id,))]
    for e in escalations:e['detail']=json.loads(e.pop('detail_json'))
    active_staff=collab.live_staff(db,store_id)
    locked=[dict(x) for x in db.execute('''SELECT l.seat_id,l.staff_id,s.staff_code,l.expires_at FROM seat_edit_locks l
        JOIN staff s ON s.id=l.staff_id WHERE l.store_id=? AND l.expires_at>?''',(store_id,timestamp()))]
    tasks=collab.tasks_for_store(db,store_id)
    return {'online_staff_count':len(active_staff),'online_staff':[{'id':x,'code':db.execute('SELECT staff_code FROM staff WHERE id=?',(x,)).fetchone()[0]} for x in active_staff],
       'seat_edit_locks':locked,'production_tasks':tasks,'alert_escalations':escalations,'severity_thresholds':{'service_warn':DEFAULT_WARN_SECONDS,
       'service_late':DEFAULT_LATE_SECONDS,'service_critical':DEFAULT_CRITICAL_SECONDS,
       'bathroom_warn_before':BATHROOM_WARNING_SECONDS,'bathroom_critical_after':BATHROOM_CRITICAL_SECONDS,
       'seat_warning':SEAT_WARNING_SECONDS,'seat_late':SEAT_LATE_SECONDS,'seat_critical':SEAT_CRITICAL_SECONDS},
       'staff':{'id':staff['id'],'code':staff['staff_code'],'role':staff['role'],'can_manage_hq':bsv_one.is_hq(db,staff),
                **({"shift": staff["authority"]} if staff.get("authority") else {})},
       'store':store,'seats':seats,'visits':visits,'groups':groups,'bathrooms':bathrooms,
       'documents':docs,'layout':bsv_layouts.runtime_layout(db,store_id),
       'products':[dict(x) for x in db.execute('''SELECT * FROM bsv_products WHERE
           (demo_only=0 AND sale_enabled=1 AND (store_id IS NULL OR store_id=?)) OR (demo_only=1 AND ?=1)
           ORDER BY demo_only,id''',(store_id,int(MODE=='local' and SHOW_LOCAL_TRAINING_ITEMS)))
           if x['demo_only']==1 or price_is_current(db,x,store_id)],
       'catalog_items':catalog_for_store(db,store_id),
       'catalog_sync':(lambda r: {'source_sha':r['source_sha'],'imported_at':r['imported_at'],
            'summary':json.loads(r['summary_json'])} if r else None)(db.execute('SELECT * FROM bsv_v9_sync WHERE one=1').fetchone()),
       'audit':audit,'csrf':staff.get('csrf'),'server_time_ms':timestamp()*1000,
       'service_warn_seconds':DEFAULT_WARN_SECONDS,'service_late_seconds':DEFAULT_LATE_SECONDS,
       'payments_enabled':False,'prototype':True,'mode':MODE,'version':application_version()}

def receipt(db,staff,vid):
    store_id=staff['session_store_id']
    v=dict(visit_all(db,store_id,vid));o=order_for(db,vid)
    v['lines']=get_lines(db,o['id'])
    for line in v['lines']:
        maker=db.execute('''SELECT f.finished_at,s.staff_code AS maker_code FROM production_finishes f
           JOIN staff s ON s.id=f.maker_staff_id WHERE f.line_id=? AND f.store_id=?''',
           (line['id'],store_id)).fetchone()
        line['maker_code']=maker['maker_code'] if maker else None
        line['finished_at']=maker['finished_at'] if maker else None
        delivered=db.execute('''SELECT s.staff_code FROM production_deliveries d JOIN staff s ON s.id=d.deliverer_staff_id
            WHERE d.line_id=? AND d.store_id=?''',(line['id'],store_id)).fetchone()
        line['delivered_by']=delivered['staff_code'] if delivered else None
    v['checkouts']=[dict(x) for x in db.execute('SELECT * FROM demo_checkouts WHERE visit_id=? ORDER BY created_at',(vid,))]
    closure=db.execute('SELECT * FROM visit_closures WHERE visit_id=? AND store_id=?',(vid,store_id)).fetchone()
    v['closure']=dict(closure) if closure else None
    v['seat_history']=[dict(x) for x in db.execute('''SELECT e.*,a.label AS from_label,b.label AS to_label
          FROM visit_seat_events e LEFT JOIN seats a ON a.id=e.from_seat_id
          JOIN seats b ON b.id=e.to_seat_id WHERE e.visit_id=? ORDER BY e.created_at''',(vid,))]
    v['member_references']=[dict(x) for x in db.execute('SELECT person_slot,member_reference FROM visit_member_links WHERE visit_id=?',(vid,))]
    return {'store':store_info(db,store_id),'visit':v,
            'demo_only':True,'payment_verified':False,'currency':'CNY'}

MUTATING={
 '/api/seats/open','/api/orders/add-item','/api/orders/remove-item',
 '/api/orders/serve-item','/api/visits/set-member','/api/visits/set-guests',
 '/api/visits/transfer','/api/visits/cancel','/api/visits/depart-demo',
 '/api/checkouts/settle-demo','/api/groups/set-mode','/api/housekeeping/clean-seat',
 '/api/housekeeping/clean-bathroom','/api/drafts/add','/api/drafts/remove',
 '/api/orders/submit','/api/members/assign',
 '/api/production/claim','/api/production/serve','/api/production/reassign','/api/seats/claim-edit',
 '/api/seats/release-edit'}

ACCEPTANCE_ORDER_PATHS = {"/api/seats/open", "/api/drafts/add", "/api/drafts/remove", "/api/orders/submit"}
ACCEPTANCE_CANCEL_PATH = "/api/visits/cancel"


def acceptance_run_for(path, data, staff):
    if "acceptance_run" not in data:
        return None
    # Preserve the original single-store host acceptance principal. Expanding the
    # synthetic acceptance matrix requires a separately explicit test-only store
    # list; this switch is never present in the deployed H configuration.
    legacy_acceptance = (staff["id"] == "SYNTH-STAGE-POS-01"
                         or staff.get("authority", {}).get("tr_code") == "TRA0001")
    requested_stores = os.environ.get("BSV_POS_G1_TEST_STORES", "")
    try:
        g1_stores = [value.strip() for value in requested_stores.split(",")]
        g1_acceptance = (bool(requested_stores) and all(g1_stores)
                         and len(g1_stores) == len(set(g1_stores))
                         and set(g1_stores) <= {"BSVM", "BSVS", "BSVT"}
                         and staff["session_store_id"] in g1_stores
                         and bool(re.fullmatch(r"TR[ABCDEFGHJKLMNPQRSTUVWXYZ][0-9]{4}",
                                               staff.get("authority", {}).get("tr_code", ""))))
    except (AttributeError, TypeError):
        g1_acceptance = False
    if (MODE != "staging" or os.environ.get("BSV_POS_INTERNAL_STAGE") != "1"
            or os.environ.get("BSV_POS_IDENTITY_REQUIRED") != "1"
            or (not legacy_acceptance and not g1_acceptance)
            or path not in ACCEPTANCE_ORDER_PATHS | {ACCEPTANCE_CANCEL_PATH}):
        raise UserError("仅隔离验收账号可标记本次测试订单", 403)
    value = data["acceptance_run"]
    try:
        if not isinstance(value, str) or str(uuid.UUID(value, version=4)) != value:
            raise ValueError
    except ValueError:
        raise UserError("本次验收编号无效", 400)
    return value


def acceptance_marker(db, store_id, visit_id):
    return db.execute(
        "SELECT staff_id,detail_json FROM audit_events WHERE store_id=? AND target_id=? "
        "AND action='ACCEPTANCE_OPEN_VISIT'", (store_id, visit_id),
    ).fetchone()


def handle_action(path,data,staff):
    store_id=staff['session_store_id'];sid=staff['id']
    run_id = acceptance_run_for(path, data, staff)
    internal_stage = os.environ.get("BSV_POS_INTERNAL_STAGE") == "1"
    with tx() as db:
        if staff.get("authority") and not db.execute(
            """SELECT 1 FROM sessions s JOIN bsv_pos_device_sessions d ON s.token_digest=d.session_digest
               WHERE s.token_digest=? AND s.expires_at>? AND s.staff_id=? AND s.store_id=?""",
            (staff["local_session_digest"],timestamp(),sid,store_id),
        ).fetchone():
            raise UserError("本机已锁定或已切换员工。请重新核验。", 401, "AUTH_REQUIRED")
        store=store_info(db,store_id)
        visit_id = data.get("visit_id")
        marker = acceptance_marker(db, store_id, visit_id) if internal_stage and isinstance(visit_id, str) else None
        if marker is not None:
            if marker["staff_id"] != sid or json.loads(marker["detail_json"])["acceptance_run"] != run_id:
                raise UserError("这张测试桌属于另一批验收", 403)
        elif run_id and path != "/api/seats/open":
            raise UserError("仅可操作本次验收新开的测试桌", 403)

        # V4 commands are replayable only with the same authorized actor and exact payload.
        authority = staff.get("authority")
        aid = data.get("_action_id") if authority or (path in MUTATING and not run_id) else None
        if authority or aid is not None:
            if not isinstance(aid,str) or not re.fullmatch('[A-Za-z0-9-]{8,90}',aid):
                raise UserError('请刷新页面后重试，操作编号无效', 400, "ACTION_ID_REQUIRED")
        if authority:
            staff["request_id"] = aid
            expected = device_pos.fingerprint(path, data, authority)
            previous = db.execute("SELECT fingerprint,response_json FROM bsv_pos_device_commands WHERE action_id=?",
                                  (aid,)).fetchone()
            if previous:
                if not hmac.compare_digest(previous["fingerprint"], expected):
                    raise UserError("这项操作编号已用于其他请求。请先核对记录。", 409, "ACTION_ID_CONFLICT")
                return json.loads(previous["response_json"])
        elif aid:
            old=db.execute('SELECT response_json,store_id FROM command_dedup WHERE action_id=?',(aid,)).fetchone()
            if old:
                if old['store_id']!=store_id:raise UserError('操作令牌门店不匹配',403)
                return json.loads(old['response_json'])

        def done(result):
            if authority:
                result = {**result, "request_id": aid}
                db.execute("""INSERT INTO bsv_pos_device_commands
                              (action_id,fingerprint,scope_digest,response_json,created_at) VALUES (?,?,?,?,?)""",
                           (aid,expected,device_pos.scope_digest(authority),json.dumps(result),now()))
            elif aid:
                db.execute('INSERT INTO command_dedup VALUES (?,?,?,?)',(aid,store_id,json.dumps(result),now()))
            return result
        if path=='/api/presence/heartbeat':
            seat=data.get('seat_id')
            if seat and not db.execute('SELECT 1 FROM seats WHERE id=? AND store_id=?',(seat,store_id)).fetchone():seat=None
            collab.heartbeat(db,sid,store_id,seat)
            collab.rebalance(db,store_id)
            return done({'ok':True,'online_staff_count':len(collab.live_staff(db,store_id))})
        if path=='/api/seats/claim-edit':
            seat=required(data,'seat_id')
            if not visible(db,store_id,seat):raise UserError('座位不属于本店或不可使用',409)
            result=collab.claim_seat(db,seat,store_id,sid)
            collab.heartbeat(db,sid,store_id,seat)
            if result['ok']:record(db,staff,'CLAIM_SEAT_EDIT',seat,{'seconds':collab.LOCK_SECONDS})
            return done(result)
        if path=='/api/seats/release-edit':
            seat=required(data,'seat_id')
            db.execute('DELETE FROM seat_edit_locks WHERE seat_id=? AND staff_id=? AND store_id=?',(seat,sid,store_id))
            return done({'ok':True})
        if path=='/api/production/claim':
            lid=required(data,'line_id')
            t=db.execute('SELECT * FROM production_tasks WHERE line_id=? AND store_id=?',(lid,store_id)).fetchone()
            if not t:raise UserError('任务不存在或不属于本店',404)
            collab.heartbeat(db,sid,store_id)
            collab.rebalance(db,store_id)
            t=db.execute('SELECT * FROM production_tasks WHERE line_id=?',(lid,)).fetchone()
            if t['state']=='CLAIMED' and t['claimed_by']==sid:
                db.execute('UPDATE production_tasks SET claim_until=? WHERE line_id=?',(timestamp()+collab.CLAIM_SECONDS,lid))
                return done({'ok':True,'claimed':True})
            if t['state']!='PENDING':raise UserError('任务已由其他调酒师接单或已完成',409)
            if t['assigned_staff_id'] and t['assigned_staff_id']!=sid:
                raise UserError('该任务已分配给其他调酒师，请在本人任务里选择',409)
            db.execute('''UPDATE production_tasks SET state='CLAIMED',claimed_by=?,assigned_staff_id=?,
                claim_until=?,claimed_at=? WHERE line_id=?''',(sid,sid,timestamp()+collab.CLAIM_SECONDS,now(),lid))
            record(db,staff,'CLAIM_PRODUCTION',lid,{'assigned_to':sid})
            return done({'ok':True,'claimed':True})
        if path=='/api/production/finished':
            lid=required(data,'line_id')
            t=db.execute('SELECT * FROM production_tasks WHERE line_id=? AND store_id=?',(lid,store_id)).fetchone()
            if not t or t['state']!='CLAIMED' or t['claimed_by']!=sid:
                raise UserError('只有领取制作任务的调酒师本人可以确认制作完成',409)
            existing=db.execute('SELECT * FROM production_finishes WHERE line_id=?',(lid,)).fetchone()
            if existing:raise UserError('此商品已确认制作完成，请安排送达，不能重复登记',409)
            visit=live_visit(db,store_id,t['visit_id']);o=order_for(db,t['visit_id'])
            line=db.execute('SELECT * FROM order_lines WHERE id=? AND order_id=?',(lid,o['id'])).fetchone()
            if not line or line['status']!='PENDING':raise UserError('该商品已取消或已送达，不能再次制作',409)
            stamp=now()
            db.execute('INSERT INTO production_finishes(line_id,store_id,visit_id,maker_staff_id,finished_at) VALUES(?,?,?,?,?)',
                (lid,store_id,t['visit_id'],sid,stamp))
            record(db,staff,'FINISHED_PRODUCTION',t['visit_id'],{'line_id':lid,'product':line['product_name_snapshot'],'seat':visit['seat_id'],'finished_at':stamp})
            return done({'ok':True,'product':line['product_name_snapshot'],'seat_id':visit['seat_id'],'maker_code':staff['staff_code'],'finished_at':stamp})
        if path=='/api/production/serve':
            lid=required(data,'line_id')
            t=db.execute('SELECT * FROM production_tasks WHERE line_id=? AND store_id=?',(lid,store_id)).fetchone()
            if not t or t['state']!='CLAIMED':
                raise UserError('出品任务不存在或已关闭',409)
            finished=db.execute('SELECT f.*,s.staff_code AS maker_code FROM production_finishes f JOIN staff s ON s.id=f.maker_staff_id WHERE f.line_id=? AND f.store_id=?',(lid,store_id)).fetchone()
            if not finished:raise UserError('尚未确认制作完成，请先由负责调酒师标记制作完成',409)
            if data.get('confirmed_delivered') is not True:raise UserError('请先确认已将正确产品送给正确座位的客人',409)
            visit=live_visit(db,store_id,t['visit_id']);o=order_for(db,t['visit_id'])
            line=db.execute('SELECT * FROM order_lines WHERE id=? AND order_id=?',(lid,o['id'])).fetchone()
            if not line or line['status']!='PENDING':raise UserError('该商品已送达或已撤销，不能重复确认',409)
            stamp=now();db.execute("UPDATE order_lines SET status='SERVED',served_at=? WHERE id=?",(stamp,lid))
            db.execute('INSERT INTO production_deliveries(line_id,store_id,visit_id,deliverer_staff_id,delivered_at) VALUES(?,?,?,?,?)',
                       (lid,store_id,t['visit_id'],sid,stamp))
            db.execute("UPDATE production_tasks SET state='SERVED',claim_until=NULL WHERE line_id=?",(lid,))
            record(db,staff,'SERVED',t['visit_id'],{'line':lid,'product':line['product_name_snapshot'],'seat':visit['seat_id'],'maker_code':finished['maker_code'],'delivered_by':staff['staff_code'],'at':stamp})
            return done({'ok':True,'product':line['product_name_snapshot'],'seat_id':visit['seat_id'],'maker_code':finished['maker_code'],'delivered_by':staff['staff_code'],'served_at':stamp})
        if path=='/api/production/reassign':
            if staff['role']!='MANAGER':raise UserError('只有本店管理员可以重新分配已领取任务',403)
            lid=required(data,'line_id')
            if data.get('confirm_checked') is not True:raise UserError('请先确认原调酒师未在制作或上桌，防止重复出品',409)
            t=db.execute('SELECT * FROM production_tasks WHERE line_id=? AND store_id=?',(lid,store_id)).fetchone()
            if not t or t['state']!='CLAIMED':raise UserError('该任务不是待重新分配的已领取任务',409)
            if db.execute('SELECT 1 FROM production_finishes WHERE line_id=?',(lid,)).fetchone():raise UserError('商品已制作完成，不能重新分配；请送达或走异常撤销流程',409)
            db.execute('''UPDATE production_tasks SET state='PENDING',claimed_by=NULL,claim_until=NULL,
                     assigned_staff_id=NULL,claimed_at=NULL WHERE line_id=?''',(lid,))
            collab.rebalance(db,store_id)
            record(db,staff,'MANUAL_REASSIGN_PRODUCTION',t['visit_id'],{'line_id':lid,'prior_staff':t['claimed_by'],'reason':'manager-confirmed'})
            return done({'ok':True,'line_id':lid})
        if path=='/api/seats/open':
            if not store['layout_ready']:raise UserError('本店尚未导入平面图，禁止误用其他门店座位',409)
            seat=required(data,'seat_id')
            lock=db.execute('SELECT staff_id,expires_at FROM seat_edit_locks WHERE seat_id=?',(seat,)).fetchone()
            if lock and lock['expires_at']>timestamp() and lock['staff_id']!=sid:raise UserError('其他员工正在处理该桌，请勿重复下单',409)
            if not visible(db,store_id,seat):raise UserError('此座位不属于本店或当前不可单独使用',409)
            if run_id:
                prior = db.execute(
                    "SELECT v.id,v.seat_id,v.status FROM audit_events a JOIN visits v ON v.id=a.target_id "
                    "WHERE a.store_id=? AND a.staff_id=? AND a.action='ACCEPTANCE_OPEN_VISIT' "
                    "AND json_extract(a.detail_json,'$.acceptance_run')=?",
                    (store_id, sid, run_id),
                ).fetchone()
                if prior:
                    if prior["seat_id"] != seat or prior["status"] != "OPEN":
                        raise UserError("本次验收编号已用于另一张桌或已归档", 409)
                    return done({"visit_id": prior["id"], "new": False})
            found=db.execute("SELECT id FROM visits WHERE seat_id=? AND store_id=? AND status='OPEN'",(seat,store_id)).fetchone()
            if found:
                if run_id or (internal_stage and acceptance_marker(db, store_id, found["id"])):
                    raise UserError("该桌已被使用，请选择另一张空桌", 409)
                record(db,staff,'OPEN_EXISTING',found['id'],{'seat':seat})
                return done({'visit_id':found['id'],'new':False})
            if not seat_clean(db,store_id,seat):raise UserError('此座位尚未清桌，请先完成清桌确认',409)
            seat_limit=db.execute('SELECT seat_capacity FROM seats WHERE id=?',(seat,)).fetchone()['seat_capacity']
            if seat_limit is not None and seat_limit<1:raise UserError('座位人数配置无效，请检查门店图纸',409)
            maximum=store['design_max_guests'];count=db.execute("SELECT COALESCE(SUM(guests),0) FROM visits WHERE store_id=? AND status='OPEN'",(store_id,)).fetchone()[0]
            if maximum and count>=maximum:raise UserError('已达到图纸标注的设计人数上限；请核实现场情况',409)
            vid=uid();oid=uid();now_=now()
            db.execute("INSERT INTO visits(id,store_id,seat_id,guests,status,created_by,created_at,seat_label_snapshot) VALUES (?,?,?,1,'OPEN',?,?,(SELECT label FROM seats WHERE id=?))",(vid,store_id,seat,sid,now_,seat))
            db.execute('INSERT INTO orders VALUES (?,?,?,?)',(oid,vid,'OPEN',now_))
            db.execute('INSERT INTO visit_seat_events VALUES (?,?,?,?,?,?)',(uid(),vid,None,seat,sid,now_))
            record(db,staff,'OPEN_VISIT',vid,{'seat':seat})
            if run_id:
                record(db, staff, "ACCEPTANCE_OPEN_VISIT", vid, {"acceptance_run": run_id})
            return done({'visit_id':vid,'new':True})
        if path=='/api/drafts/add':
            vid=required(data,'visit_id');pid=required(data,'product_id')
            live_visit(db,store_id,vid)
            try:collab.assert_editable(db,vid,store_id,sid)
            except ValueError as e:raise UserError(str(e),409)
            product=db.execute('SELECT * FROM bsv_products WHERE id=?',(pid,)).fetchone()
            if not product:raise UserError('商品不存在',404)
            if product['demo_only']==1:
                if MODE!='local' or not SHOW_LOCAL_TRAINING_ITEMS:raise UserError('本模式禁止演练商品',403)
            elif not price_is_current(db,product,store_id):
                raise UserError('该商品没有本店已核准售价，不能下单',409)
            draft_id=uid()
            db.execute('''INSERT INTO order_drafts(id,visit_id,product_id,quantity,created_by,created_at,price_cents_snapshot,source_revision_snapshot)
               VALUES(?,?,?,1,?,?,?,?)''',(draft_id,vid,pid,sid,now(),product['price_cents'],product['catalog_sha']))
            record(db,staff,'ADD_DRAFT',vid,{'draft_id':draft_id,'product':pid})
            return done({'ok':True,'draft_id':draft_id,'persisted':True})
        if path=='/api/drafts/remove':
            vid=required(data,'visit_id');did=required(data,'draft_id')
            live_visit(db,store_id,vid)
            try:collab.assert_editable(db,vid,store_id,sid)
            except ValueError as e:raise UserError(str(e),409)
            r=db.execute('SELECT * FROM order_drafts WHERE id=? AND visit_id=?',(did,vid)).fetchone()
            if not r:raise UserError('待下单商品不存在或已经提交',409)
            db.execute('DELETE FROM order_drafts WHERE id=?',(did,))
            record(db,staff,'REMOVE_DRAFT',vid,{'draft_id':did})
            return done({'ok':True})
        if path=='/api/orders/submit':
            vid=required(data,'visit_id');pay_now=data.get('pay_now')
            if type(pay_now)!=bool:raise UserError('请选择下单或下单并结账')
            if pay_now and (device_required() or os.environ.get('BSV_POS_INTERNAL_STAGE') == '1'):
                raise UserError('内部集成测试只允许提交未付款测试订单',403)
            live_visit(db,store_id,vid);o=order_for(db,vid)
            try:collab.assert_editable(db,vid,store_id,sid)
            except ValueError as e:raise UserError(str(e),409)
            drafts=list(db.execute('''SELECT d.*,p.name,p.price_cents,p.discount_eligible,p.demo_only,
                     p.sale_enabled,p.store_id AS product_store_id,p.catalog_sha FROM order_drafts d
                JOIN bsv_products p ON p.id=d.product_id WHERE d.visit_id=? ORDER BY d.created_at,d.rowid''',(vid,)))
            if not drafts:raise UserError('本桌没有待下单商品',409)
            for d in drafts:
                if d['demo_only']==1 and MODE!='local':raise UserError('演练商品不能用于正式营业',403)
                if d['demo_only']==0:
                    check=db.execute('SELECT * FROM bsv_products WHERE id=?',(d['product_id'],)).fetchone()
                    if not price_is_current(db,check,store_id):
                        raise UserError('商品已停售或价格授权失效，请移除该待下单商品',409)
                if d['price_cents_snapshot'] is not None and d['price_cents_snapshot']!=d['price_cents']:
                    raise UserError('商品价格已改变，请先撤销该待下单商品并重新选择',409)
                if d['demo_only']==0 and d['source_revision_snapshot']!=d['catalog_sha']:
                    raise UserError('商品资料已更新，请重新确认并选择商品',409)
            m=db.execute('''SELECT m.* FROM visit_member_links l JOIN members m ON m.id=l.member_id
              WHERE l.visit_id=? AND l.person_slot=1 AND m.active=1''',(vid,)).fetchone()
            total=0;discount_total=0;at=now();inserted_line_ids=[]
            for d in drafts:
                list_cents=d['price_cents'];discount= (list_cents*10+50)//100 if m and m['tier']=='SILVER' and d['discount_eligible'] else 0
                actual=list_cents-discount
                total+=actual*d['quantity'];discount_total+=discount*d['quantity']
                new_line_id=uid();inserted_line_ids.append(new_line_id)
                db.execute('''INSERT INTO order_lines(id,order_id,product_id,product_name_snapshot,
                  price_cents,quantity,created_at,status,added_by,list_price_cents,discount_cents,member_tier_snapshot)
                  VALUES (?,?,?,?,?,?,?,'PENDING',?,?,?,?)''',
                  (new_line_id,o['id'],d['product_id'],d['name'],actual,d['quantity'],at,sid,list_cents,discount,m['tier'] if discount else None))
            collab.add_tasks(db,inserted_line_ids,store_id,vid)
            db.execute('DELETE FROM order_drafts WHERE visit_id=?',(vid,))
            checkout_id=None
            if pay_now:
                checkout_id=uid()
                db.execute("INSERT INTO demo_checkouts VALUES (?,?,?,?,'TEST_SETTLED',?,?)",(checkout_id,vid,store_id,total,at,sid))
                # Only this newly submitted batch is marked as TEST_SETTLED; any earlier unpaid lines remain unpaid.
                db.executemany('UPDATE order_lines SET checkout_id=? WHERE id=?',[(checkout_id,lid) for lid in inserted_line_ids])
            record(db,staff,'SUBMIT_ORDER_TEST' if not pay_now else 'SUBMIT_AND_TEST_CHECKOUT',vid,
                   {'lines':len(drafts),'amount_cents':total,'discount_cents':discount_total,
                    'pay_now':pay_now,'payment_verified':False,
                    **({"order_id": o["id"]} if staff.get("authority") else {})})
            return done({'ok':True,'amount_cents':total,'discount_cents':discount_total,'pay_now':pay_now,
                         'payment_verified':False,'checkout_id':checkout_id,
                         **({"order_id": o["id"]} if staff.get("authority") else {})})
        if path=='/api/members/assign':
            vid=required(data,'visit_id');live_visit(db,store_id,vid)
            mid=data.get('member_id')
            if mid is not None and (not isinstance(mid,str) or len(mid)>80):raise UserError('会员ID无效')
            if mid:
                m=db.execute('SELECT id,tier FROM members WHERE id=? AND active=1',(mid,)).fetchone()
                if not m:raise UserError('会员不存在或已停用',404)
                db.execute('''INSERT INTO visit_member_links(visit_id,person_slot,member_reference,member_id)
                  VALUES (?,1,?,?) ON CONFLICT(visit_id,person_slot)
                  DO UPDATE SET member_reference=excluded.member_reference,member_id=excluded.member_id''',(vid,mid,mid))
            else:db.execute('DELETE FROM visit_member_links WHERE visit_id=? AND person_slot=1',(vid,))
            record(db,staff,'ASSIGN_MEMBER',vid,{'assigned':bool(mid),'member_id':mid})
            return done({'ok':True,'tier':'SILVER' if mid else None})
        if path=='/api/orders/add-item':
            raise UserError('旧版直接加单接口已停用，请先加入待下单商品，再确认正式下单',410)
        if path=='/api/orders/remove-item':
            vid=required(data,'visit_id');lid=required(data,'line_id');live_visit(db,store_id,vid);o=order_for(db,vid)
            l=db.execute('SELECT * FROM order_lines WHERE id=? AND order_id=?',(lid,o['id'])).fetchone()
            if not l:raise UserError('商品不存在或不属于本桌',404)
            if l['checkout_id'] or l['status']!='PENDING':raise UserError('仅能撤销尚未结算、尚未上桌的商品；其他需走退款流程',409)
            db.execute("UPDATE order_lines SET status='CANCELLED' WHERE id=?",(lid,))
            db.execute("UPDATE production_tasks SET state='CANCELLED' WHERE line_id=?",(lid,))
            record(db,staff,'CANCEL_ITEM',vid,{'line':lid})
            return done({'ok':True})
        if path=='/api/orders/serve-item':
            raise UserError('请从待出品队列领取制作任务，并由本人完成送达确认',410)
        if path=='/api/unused-serve-item':
            vid=required(data,'visit_id');lid=required(data,'line_id');live_visit(db,store_id,vid);o=order_for(db,vid)
            l=db.execute('SELECT * FROM order_lines WHERE id=? AND order_id=?',(lid,o['id'])).fetchone()
            if not l:raise UserError('待上桌商品不存在',404)
            if l['status']!='PENDING':raise UserError('该商品已上桌或已撤销，不能重复确认',409)
            db.execute("UPDATE order_lines SET status='SERVED',served_at=? WHERE id=?",(now(),lid))
            record(db,staff,'SERVED',vid,{'line':lid,'created_at':l['created_at']})
            return done({'ok':True})
        if path=='/api/visits/set-member':
            vid=required(data,'visit_id');live_visit(db,store_id,vid)
            ref=data.get('member_reference','')
            if not isinstance(ref,str) or len(ref)>32 or (ref and not re.fullmatch(r'[A-Za-z0-9_-]+',ref)):
                raise UserError('会员编号格式不正确，请检查输入（最长32位）')
            if ref:
                db.execute('''INSERT INTO visit_member_links(visit_id,person_slot,member_reference)
                  VALUES (?,1,?) ON CONFLICT(visit_id,person_slot) DO UPDATE SET member_reference=excluded.member_reference''',(vid,ref))
            else:db.execute('DELETE FROM visit_member_links WHERE visit_id=? AND person_slot=1',(vid,))
            record(db,staff,'SET_MEMBER_TEST',vid,{'has_ref':bool(ref)})
            return done({'ok':True})
        if path=='/api/visits/set-guests':
            vid=required(data,'visit_id');v=live_visit(db,store_id,vid)
            count=data.get('guests')
            if type(count)!=int or count<1 or count>100:raise UserError('人数必须是1—100的整数')
            seat_limit=db.execute('SELECT seat_capacity FROM seats WHERE id=?',(v['seat_id'],)).fetchone()['seat_capacity']
            if seat_limit is not None and count>seat_limit:
                raise UserError('本桌标记最多容纳'+str(seat_limit)+'人，请选择其他座位或调整安排',409)
            maximum=store['design_max_guests']
            if maximum:
                other=db.execute("SELECT COALESCE(SUM(guests),0) FROM visits WHERE store_id=? AND status='OPEN' AND id<>?",(store_id,vid)).fetchone()[0]
                if other+count>maximum:raise UserError('当前记录人数超出图纸设计人数上限',409)
            db.execute('UPDATE visits SET guests=?,version=version+1 WHERE id=?',(count,vid))
            record(db,staff,'SET_GUESTS',vid,{'from':v['guests'],'to':count})
            return done({'ok':True})
        if path=='/api/visits/transfer':
            vid=required(data,'visit_id');src=required(data,'source_seat_id');dst=required(data,'target_seat_id')
            v=live_visit(db,store_id,vid)
            if v['seat_id']!=src:raise UserError('原座位已变化，请重新确认',409)
            if src==dst:raise UserError('目标座位不能与原座位相同')
            target_lock=db.execute('SELECT staff_id,expires_at FROM seat_edit_locks WHERE seat_id=? AND store_id=?',(dst,store_id)).fetchone()
            if target_lock and target_lock['expires_at']>timestamp() and target_lock['staff_id']!=sid:raise UserError('目标座位正由其他员工操作，请更换目标位置',409)
            if not visible(db,store_id,dst):raise UserError('目标座位不属于当前门店或已合桌',409)
            if not seat_clean(db,store_id,dst):raise UserError('目标座位尚未清洁，不能转入',409)
            dest_capacity=db.execute('SELECT seat_capacity FROM seats WHERE id=?',(dst,)).fetchone()['seat_capacity']
            if dest_capacity is not None and v['guests']>dest_capacity:
                raise UserError('目标座位最多容纳'+str(dest_capacity)+'人，当前桌次人数不匹配',409)
            if db.execute("SELECT id FROM visits WHERE seat_id=? AND status='OPEN'",(dst,)).fetchone():
                raise UserError('目标位置已有客人',409)
            db.execute('DELETE FROM seat_edit_locks WHERE seat_id=? AND store_id=? AND staff_id=?',(src,store_id,sid))
            collab.claim_seat(db,dst,store_id,sid)
            db.execute('UPDATE visits SET seat_id=?,seat_label_snapshot=(SELECT label FROM seats WHERE id=?),version=version+1 WHERE id=?',(dst,dst,vid))
            db.execute("UPDATE seat_cleaning SET state='DIRTY',dirty_at=? WHERE seat_id=? AND store_id=?",(now(),src,store_id))
            db.execute('INSERT INTO visit_seat_events VALUES (?,?,?,?,?,?)',(uid(),vid,src,dst,sid,now()))
            record(db,staff,'TRANSFER',vid,{'from':src,'to':dst,'source_now_dirty':True})
            return done({'ok':True,'visit_id':vid})
        if path=='/api/checkouts/settle-demo':
            vid=required(data,'visit_id');live_visit(db,store_id,vid);o=order_for(db,vid)
            lines=list(db.execute("SELECT id,price_cents,quantity FROM order_lines WHERE order_id=? AND checkout_id IS NULL AND status<>'CANCELLED'",(o['id'],)))
            if not lines:raise UserError('本次没有新增商品需要结算',409)
            total=sum(r['price_cents']*r['quantity'] for r in lines);cid=uid()
            db.execute("INSERT INTO demo_checkouts VALUES (?,?,?,?,'TEST_SETTLED',?,?)",(cid,vid,store_id,total,now(),sid))
            db.executemany('UPDATE order_lines SET checkout_id=? WHERE id=?',[(cid,l['id']) for l in lines])
            record(db,staff,'TEST_SETTLE_ROUND',vid,{'checkout_id':cid,'amount_cents':total,'payment_verified':False})
            return done({'ok':True,'checkout_id':cid,'amount_cents':total,'payment_verified':False})
        if path=='/api/visits/depart-demo':
            vid=required(data,'visit_id');pref=required(data,'print_preference');v=live_visit(db,store_id,vid)
            if pref not in ('NONE','PAPER'):raise UserError('请选择是否需要纸质结账单')
            o=order_for(db,vid)
            if db.execute('SELECT 1 FROM order_drafts WHERE visit_id=?',(vid,)).fetchone():
                raise UserError('本桌还有待下单商品，请先下单或逐项撤销',409)
            pending=db.execute("SELECT COUNT(*) FROM order_lines WHERE order_id=? AND status='PENDING'",(o['id'],)).fetchone()[0]
            if pending:raise UserError('还有未上桌商品，请先确认上桌或撤销后再结束桌次',409)
            unbilled=list(db.execute("SELECT id,price_cents,quantity FROM order_lines WHERE order_id=? AND checkout_id IS NULL AND status='SERVED'",(o['id'],)))
            if unbilled:
                cid=uid();total=sum(l['price_cents']*l['quantity'] for l in unbilled)
                db.execute("INSERT INTO demo_checkouts VALUES (?,?,?,?,'TEST_SETTLED',?,?)",(cid,vid,store_id,total,now(),sid))
                db.executemany('UPDATE order_lines SET checkout_id=? WHERE id=?',[(cid,l['id']) for l in unbilled])
            now_=now()
            db.execute("UPDATE visits SET status='TEST_CLOSED',closed_at=?,version=version+1 WHERE id=?",(now_,vid))
            db.execute("UPDATE orders SET status='TEST_CLOSED' WHERE visit_id=?",(vid,))
            db.execute('INSERT INTO visit_closures VALUES (?,?,?,?,?)',(vid,store_id,sid,pref,now_))
            db.execute("UPDATE seat_cleaning SET state='DIRTY',dirty_at=? WHERE seat_id=? AND store_id=?",(now_,v['seat_id'],store_id))
            db.execute('DELETE FROM seat_edit_locks WHERE seat_id=? AND store_id=?',(v['seat_id'],store_id))
            record(db,staff,'DEPART_DEMO',vid,{'seat':v['seat_id'],'paper':pref,'payment_verified':False})
            return done({'ok':True,'visit_id':vid,'receipt_path':'/api/receipt?visit_id='+vid,'payment_verified':False,'print_preference':pref})
        if path=='/api/visits/cancel':
            vid = required(data, "visit_id")
            if run_id and db.execute(
                    "SELECT 1 FROM visits WHERE id=? AND store_id=? AND status='CANCELLED'",
                    (vid, store_id)).fetchone():
                return done({"ok": True, "archived": True, "visit_id": vid})
            v = live_visit(db, store_id, vid)
            if db.execute('SELECT 1 FROM demo_checkouts WHERE visit_id=?',(vid,)).fetchone():
                raise UserError('存在已记录结算批次，禁止整桌撤单；应走退款/冲正流程（尚未开发）',409)
            o=order_for(db,vid)
            if db.execute("SELECT 1 FROM order_lines WHERE order_id=? AND status='SERVED'",(o['id'],)).fetchone():
                raise UserError('已有商品送达，禁止直接撤单；需先由管理员处理异常',409)
            if run_id and db.execute("SELECT 1 FROM production_finishes WHERE visit_id=?", (vid,)).fetchone():
                raise UserError("这张桌已有制作记录，需人工核对后处理", 409)
            draft_count=db.execute('SELECT COUNT(*) FROM order_drafts WHERE visit_id=?',(vid,)).fetchone()[0]
            db.execute('DELETE FROM order_drafts WHERE visit_id=?',(vid,))
            db.execute("UPDATE visits SET status='CANCELLED',closed_at=? WHERE id=?",(now(),vid))
            db.execute("UPDATE orders SET status='CANCELLED' WHERE visit_id=?",(vid,))
            if not run_id and db.execute('SELECT 1 FROM order_lines WHERE order_id=?',(o['id'],)).fetchone():
                db.execute("UPDATE seat_cleaning SET state='DIRTY',dirty_at=? WHERE seat_id=?",(now(),v['seat_id']))
            db.execute('DELETE FROM seat_edit_locks WHERE seat_id=? AND store_id=?',(v['seat_id'],store_id))
            db.execute('''UPDATE production_tasks SET state='CANCELLED' WHERE visit_id=? AND state IN ('PENDING','CLAIMED')''',(vid,))
            detail = {"seat": v["seat_id"], "removed_draft_count": draft_count}
            if run_id:
                detail["acceptance_run"] = run_id
            record(db, staff, "CANCEL_VISIT", vid, detail)
            return done({"ok": True, "archived": True, "visit_id": vid} if run_id else {"ok": True})
        if path=='/api/housekeeping/clean-seat':
            seat=required(data,'seat_id');confirmation=data.get('confirmed')
            if confirmation is not True:raise UserError('必须确认桌面已清洁并恢复摆设')
            if not visible(db,store_id,seat):raise UserError('座位不存在或不可用',409)
            if db.execute("SELECT 1 FROM visits WHERE seat_id=? AND status='OPEN'",(seat,)).fetchone():
                raise UserError('当前仍有在店客人，不能标为清桌完成',409)
            r=db.execute('SELECT state FROM seat_cleaning WHERE seat_id=? AND store_id=?',(seat,store_id)).fetchone()
            if not r or r['state']!='DIRTY':raise UserError('座位当前无需清桌',409)
            db.execute("UPDATE seat_cleaning SET state='CLEAN',cleaned_at=?,cleaned_by=? WHERE seat_id=?",(now(),sid,seat))
            record(db,staff,'SEAT_CLEAN',seat,{'confirmed':True})
            return done({'ok':True})
        if path=='/api/housekeeping/clean-bathroom':
            bathroom=required(data,'bathroom_id');checks=data.get('checks')
            if not isinstance(checks,dict) or any(checks.get(k) is not True for k in ('paper','toilet','sink','floor_trash')):
                raise UserError('请完成并逐项确认：厕纸、马桶、洗手台、地面/垃圾')
            b=db.execute('SELECT * FROM bathrooms WHERE id=? AND store_id=?',(bathroom,store_id)).fetchone()
            if not b:raise UserError('本店没有该卫生间记录',404)
            stamp=now();db.execute('UPDATE bathrooms SET last_clean_at=?,last_clean_by=? WHERE id=?',(stamp,sid,bathroom))
            db.execute('INSERT INTO bathroom_checks VALUES (?,?,?,?,?,?)',(uid(),bathroom,store_id,sid,json.dumps(checks),stamp))
            record(db,staff,'BATHROOM_CLEAN',bathroom,{'completed_all':True})
            return done({'ok':True,'next_due_seconds':b['interval_seconds']})
        if path=='/api/groups/set-mode':
            if staff['role']!='MANAGER':raise UserError('只有管理员可以修改现场合分桌',403)
            gid=required(data,'group_id');mode=required(data,'mode')
            if mode not in ('SPLIT','MERGED'):raise UserError('模式错误')
            g=db.execute('SELECT * FROM table_groups WHERE id=? AND store_id=?',(gid,store_id)).fetchone()
            if not g:raise UserError('组合桌不存在',404)
            if db.execute("SELECT 1 FROM visits WHERE seat_id IN (?,?) AND status='OPEN'",(g['primary_seat'],g['secondary_seat'])).fetchone():
                raise UserError('先结束对应桌次，再调整合分桌',409)
            if mode=='MERGED' and not seat_clean(db,store_id,g['secondary_seat']):
                raise UserError('副桌尚未清洁，禁止直接合桌',409)
            db.execute('UPDATE table_groups SET mode=? WHERE id=?',(mode,gid))
            record(db,staff,'CHANGE_TABLE_MODE',gid,{'from':g['mode'],'to':mode})
            return done({'ok':True})
        raise UserError('未知操作',404)

RATE_LIMIT={}
class Handler(BaseHTTPRequestHandler):
    server_version='BSV1/2.9.0'
    def log_message(self,fmt,*args):print('%s %s'%(self.address_string(),fmt%args))
    def send_json(self,data,status=200,set_cookie=None,delete_cookie=False, *,
                  new_device=None, forget_device=False, clear_identity=False):
        payload=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        # Only for SSH-tunneled private preview: the network hop is encrypted by SSH,
        # and the browser connects to local 127.0.0.1 over HTTP. Never set this option
        # for public reverse proxy/HTTPS production deployments.
        tunneled = (os.environ.get('BSV_PRIVATE_SSH_TUNNEL','') == '1'
                    and MODE == 'staging' and HOST == '127.0.0.1')
        secure_cookie='; Secure' if MODE=='staging' and not tunneled else ''
        def set_header(name, value, path, expiry, strict=True):
            flags = "; HttpOnly" if strict else ""
            self.send_header("Set-Cookie", f"{name}={value}{flags}; SameSite=Strict; Path={path}; Max-Age={expiry}" + secure_cookie)

        session_cookie = self.pos_cookie_name()
        if set_cookie:
            set_header(session_cookie, set_cookie, "/", device_pos.DEVICE_SESSION_SECONDS if device_required() else SESSION_SECONDS)
        if delete_cookie:
            set_header(session_cookie, "", "/", 0)
        if new_device:
            set_header(device_pos.DEVICE_COOKIE, ".".join(new_device), "/api", device_pos.DEVICE_COOKIE_SECONDS)
        if forget_device:
            set_header(device_pos.DEVICE_COOKIE, "", "/api", 0)
        if clear_identity:
            set_header("bsv_identity_session", "", "/", 0)
            set_header("bsv_csrf", "", "/", 0, strict=False)
        self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    def cookie(self, name):
        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            return ""
        entry = jar.get(name)
        return entry.value if entry and len(entry.value) <= 300 else ""

    def pos_cookie_name(self):
        # Cookies are scoped to the host, not the listener port. Never overwrite V3 or legacy POS sessions.
        return device_pos.SESSION_COOKIE if device_required() else "bsv_session"

    def group_identity(self, staff_id, store_id, action):
        if os.environ.get("BSV_POS_IDENTITY_REQUIRED") != "1":
            return True
        session = self.cookie("bsv_identity_session")
        return bool(session and identity_client().authorize_pos(session, staff_id, store_id, action))

    def require_loopback_origin(self):
        authority = self.headers.get("Host", "")
        origin = self.headers.get("Origin", "")
        # Only the SSH tunnel or loopback origin runs this isolated mode.
        if (not re.fullmatch(r"(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?", authority)
                or origin != "http://" + authority):
            raise UserError("请从内部工作台重新打开点单台。", 403, "BAD_ORIGIN")

    def identity_csrf(self):
        expected = self.cookie("bsv_csrf")
        supplied = self.headers.get("X-CSRF-Token", "")
        return bool(expected and supplied and hmac.compare_digest(expected.encode(), supplied.encode()))

    def local_session(self, session):
        with db_read() as db:
            return db.execute("""SELECT s.*,ss.csrf,ss.store_id AS session_store_id
                FROM sessions ss JOIN staff s ON s.id=ss.staff_id
                JOIN staff_store_access a ON a.staff_id=ss.staff_id AND a.store_id=ss.store_id
                WHERE ss.token_digest=? AND ss.expires_at>? AND ss.store_id IS NOT NULL AND s.enabled=1""",
                (device_pos.digest(session), timestamp())).fetchone()

    def device_error(self, reason):
        code = reason if isinstance(reason, str) and reason in device_pos.FAIL_REASONS else "IDENTITY_UNAVAILABLE"
        message, status = device_pos.FAIL_REASONS[code]
        return UserError(message, status, code)

    def authorize_device_context(self, store_id, device, action):
        session = self.cookie("bsv_identity_session")
        if not session:
            raise self.device_error("AUTH_REQUIRED")
        if not device:
            raise self.device_error("DEVICE_UNVERIFIED")
        authority = identity_client().authorize_device(session, store_id, *device, action)
        if authority.get("allowed") is not True:
            raise self.device_error(authority.get("reason"))
        return authority

    def resolve_auth(self):
        session = self.cookie(self.pos_cookie_name())
        self.auth_error = None
        if not session or len(session) > 150:
            return None
        row = self.local_session(session)
        if not row:
            return None
        staff = dict(row)
        if not device_required():
            if self.group_identity(staff["id"], staff["session_store_id"], "pos.order.read"):
                return staff
            return None
        device = device_pos.parse_device_cookie(self.cookie(device_pos.DEVICE_COOKIE))
        with db_read() as db:
            attached = db.execute("SELECT * FROM bsv_pos_device_sessions WHERE session_digest=?",
                                  (device_pos.digest(session),)).fetchone()
        try:
            if not device_pos.same_binding(attached, self.cookie("bsv_identity_session"), device):
                reason = "AUTH_REQUIRED" if not self.cookie("bsv_identity_session") else "POS_SESSION_CHANGED"
                raise self.device_error(reason)
            authority = self.authorize_device_context(staff["session_store_id"], device, "pos.order.read")
            if not device_pos.same_authority(attached, authority):
                raise self.device_error("POS_SESSION_CHANGED")
        except UserError as error:
            self.auth_error = error
            return None
        staff["authority"] = device_pos.scope_from(authority)
        staff["local_session_digest"] = device_pos.digest(session)
        staff["staff_code"] = authority["tr_code"]
        # Local STAFF/MANAGER flags do not confer any V4 action permissions.
        staff["role"] = "STAFF"
        return staff

    def growth_customer_link(self, data, staff):
        """Bind a guest's explicit one-use proof to this authenticated POS visit."""
        if not growth_integration():
            raise UserError("会员桌次绑定尚未启用", 403, "GROWTH_DISABLED")
        self.require_loopback_origin()
        device = device_pos.parse_device_cookie(self.cookie(device_pos.DEVICE_COOKIE))
        authority = self.authorize_device_context(staff["session_store_id"], device, "pos.order.create")
        if device_pos.scope_from(authority) != staff.get("authority"):
            raise self.device_error("POS_SESSION_CHANGED")
        visit_id = data.get("visit_id")
        if not isinstance(visit_id, str) or not growth_pos.VISIT_RE.fullmatch(visit_id):
            raise UserError("桌次编号无效", 422)
        if set(data) not in ({"visit_id", "proof"}, {"visit_id", "proof", "_action_id"}):
            raise UserError("绑定请求字段不符合要求", 422)
        action_id = data.get("_action_id")
        if action_id is not None and (not isinstance(action_id, str)
                                   or not re.fullmatch(r"[a-zA-Z0-9-]{8,90}", action_id)):
            raise UserError("提交编号不符合规范", 422)
        action_id = action_id or uid()
        try:
            proof = growth_pos.verify_guest_link(
                data["proof"], staff["session_store_id"], os.environ.get("BSV_GROWTH_LINK_KEY", ""))
            nonce_hash = growth_pos.nonce_digest(proof["nonce"])
        except (growth_pos.ProofError, KeyError, TypeError):
            raise UserError("顾客授权码无效、已过期或与本店不符", 403, "GROWTH_PROOF_INVALID")
        customer_id = proof["customer_id"]
        with tx() as db:
            live_visit(db, staff["session_store_id"], visit_id)
            used = db.execute(
                """SELECT visit_id,store_id,customer_id,action_id
                   FROM bsv_growth_pos_consumed_nonces WHERE nonce_hash=?""",
                (nonce_hash,)).fetchone()
            if used:
                if (used["visit_id"] == visit_id and used["store_id"] == staff["session_store_id"]
                        and used["customer_id"] == customer_id and used["action_id"] == action_id):
                    # Identical retry after a lost HTTP response: verify state, not
                    # merely the nonce, and return the original successful outcome.
                    linked_now = db.execute("""SELECT 1 FROM visit_member_links
                                               WHERE visit_id=? AND person_slot=1
                                               AND canonical_customer_id=?""",
                                            (visit_id, customer_id)).fetchone()
                    if linked_now:
                        self.send_json({"ok":True,"linked":True,"visit_id":visit_id,
                                        "duplicate":True,
                                        "notice":"会员关联此前已完成，不产生第二条记录"})
                        return
                raise UserError("授权码已使用，请顾客重新生成", 409, "GROWTH_PROOF_REPLAY")
            linked = db.execute("""SELECT member_id,canonical_customer_id FROM visit_member_links
                                   WHERE visit_id=? AND person_slot=1""", (visit_id,)).fetchone()
            if linked and (linked["member_id"] or
                           (linked["canonical_customer_id"] and linked["canonical_customer_id"] != customer_id)):
                raise UserError("本桌已关联其他会员，请先由总部核对", 409, "CUSTOMER_LINK_CONFLICT")
            db.execute("""INSERT INTO bsv_growth_pos_consumed_nonces
                          (nonce_hash,visit_id,store_id,customer_id,action_id,created_at)
                          VALUES(?,?,?,?,?,?)""",
                       (nonce_hash, visit_id, staff["session_store_id"], customer_id,
                        action_id, now()))
            db.execute("""INSERT INTO visit_member_links
                          (visit_id,person_slot,member_reference,canonical_customer_id)
                          VALUES (?,1,'BSV_ACCOUNT',?)
                          ON CONFLICT(visit_id,person_slot) DO UPDATE SET
                          canonical_customer_id=excluded.canonical_customer_id""",
                       (visit_id, customer_id))
            record(db, staff, "LINK_CANONICAL_CUSTOMER", visit_id,
                   {"source": "GUEST_CONSENT_PROOF", "customer_ref_hash": hashlib.sha256(customer_id.encode()).hexdigest()})
        self.send_json({"ok": True, "linked": True, "visit_id":visit_id,
                        "notice":"已关联会员到本次桌次；优惠与支付尚需独立验证"})

    def growth_visit_context(self):
        if not growth_integration():
            raise UserError("接待授权尚未启用", 403, "GROWTH_DISABLED")
        staff = self.resolve_auth()
        if not staff:
            self.fail_auth("请先登录已授权POS设备")
            return
        visit_id = parse_qs(urlparse(self.path).query).get("visit_id", [""])[0]
        if not growth_pos.VISIT_RE.fullmatch(visit_id):
            raise UserError("桌次编号无效", 422)
        with db_read() as db:
            live_visit(db, staff["session_store_id"], visit_id)
            row = db.execute("""SELECT canonical_customer_id FROM visit_member_links
                                WHERE visit_id=? AND person_slot=1""", (visit_id,)).fetchone()
            if not row or not row["canonical_customer_id"]:
                raise UserError("本桌没有经过本人授权关联的会员", 404, "CUSTOMER_NOT_LINKED")
        try:
            token = growth_pos.make_visit_context(
                row["canonical_customer_id"], staff["session_store_id"], visit_id,
                os.environ.get("BSV_GROWTH_POS_CONTEXT_KEY", ""))
        except growth_pos.ProofError:
            raise UserError("接待签名服务未配置", 503, "GROWTH_UNAVAILABLE")
        self.send_json({"context":token,"store_id":staff["session_store_id"],
                        "expires_in_seconds":90})

    def growth_staff_verify(self, data):
        """Internal-only live POS shift/device proof for the identity.A employee.

        Identity.A alone must not infer a POS shift from an approved grant:
        the academy version verifies attendance, course and the actual device.
        """
        key = os.environ.get("BSV_GROWTH_POS_VERIFY_TOKEN", "")
        actual = self.headers.get("Authorization", "")
        if (not growth_integration() or len(key) < 32
                or not hmac.compare_digest(actual, "Bearer " + key)
                or self.client_address[0] not in ("127.0.0.1", "::1")):
            raise UserError("内部当班核验不可访问", 403, "GROWTH_VERIFY_FORBIDDEN")
        if data:
            raise UserError("当班核验字段不正确", 422)
        staff = self.resolve_auth()  # device + academy + active shift, every request
        if not staff or not staff.get("authority"):
            raise UserError("当前员工设备或班次未获准接待", 403, "POS_SCOPE_DENIED")
        tr = staff["authority"].get("tr_code")
        store = staff["session_store_id"]
        if not tr or not store:
            raise UserError("人员和门店身份不完整", 403, "POS_SCOPE_DENIED")
        self.send_json({"allowed":True,"active_shift":True,
                        "actor_tr":tr,"store_id":store})

    def growth_visit_verify(self, data):
        """Private same-host call; re-authorizes the *actual* browser POS device."""
        key = os.environ.get("BSV_GROWTH_POS_VERIFY_TOKEN", "")
        actual = self.headers.get("Authorization", "")
        if (not growth_integration() or len(key) < 32
                or not hmac.compare_digest(actual, "Bearer " + key)
                or self.client_address[0] not in ("127.0.0.1", "::1")):
            raise UserError("内部接待核验不可访问", 403, "GROWTH_VERIFY_FORBIDDEN")
        if set(data) != {"actor_tr", "store_id", "visit_id", "customer_id"}:
            raise UserError("核验字段不正确", 422)
        tr, store, vid, cid = (data[key] for key in ("actor_tr","store_id","visit_id","customer_id"))
        if (not isinstance(tr,str) or not re.fullmatch(r"TR[A-Z][0-9]{4}",tr)
                or not isinstance(store,str) or not growth_pos.ID_RE.fullmatch(store)
                or not isinstance(vid,str) or not growth_pos.VISIT_RE.fullmatch(vid)
                or not growth_pos._uuid(cid)):
            raise UserError("核验实体无效", 422)
        staff = self.resolve_auth()  # includes uncached identity.A academy device + current shift
        if not staff or staff["session_store_id"] != store or staff.get("authority",{}).get("tr_code") != tr:
            raise UserError("当前员工、设备或班次无权接待", 403, "POS_SCOPE_DENIED")
        with db_read() as db:
            v=db.execute("SELECT 1 FROM visits WHERE id=? AND store_id=? AND status='OPEN'",
                         (vid,store)).fetchone()
            link=db.execute("""SELECT 1 FROM visit_member_links WHERE visit_id=?
                               AND person_slot=1 AND canonical_customer_id=?""",(vid,cid)).fetchone()
        if not v or not link:
            raise UserError("本桌会员关联未通过核验", 403, "POS_LINK_DENIED")
        self.send_json({"allowed":True,"active_shift":True,"customer_linked":True,
                        "store_ownership_verified":True})

    def fail_auth(self, default):
        error = getattr(self, "auth_error", None) or UserError(default, 401)
        self.send_error_json(error)

    def hq_layout_scope(self, db, store_id):
        """Only an explicitly marked isolated fixture may use the legacy map for legal scope."""
        if (MODE != "staging" or os.environ.get("BSV_POS_LAYOUT_SCOPE_MODE") != "isolated-synthetic"
                or os.environ.get("BSV_APP_ENV") != "isolated"):
            return None
        try:
            mappings = json.loads(os.environ.get("BSV_POS_STORE_LEGAL_JSON", "{}"))
        except (ValueError, TypeError):
            return None
        legal = mappings.get(store_id) if isinstance(mappings, dict) else None
        if (not isinstance(legal, str) or not legal
                or not db.execute("SELECT 1 FROM stores WHERE id=?", (store_id,)).fetchone()):
            return None
        return legal

    def hq_layout_read(self, path):
        """Read existing POS map data after an uncached identity.A decision."""
        query = parse_qs(urlparse(self.path).query)
        identity_session = self.cookie("bsv_identity_session")
        if not identity_session:
            self.send_json({"error": "请先登录统一身份账号。", "code": "AUTH_REQUIRED"}, 401)
            return
        requested_store = query.get("store_id", [""])[0]
        if requested_store and not re.fullmatch("[A-Z0-9_-]{3,32}", requested_store):
            self.send_json({"error": "门店代码无效。", "code": "STORE_INVALID"}, 400)
            return
        with db_read() as db:
            if path == "/api/hq/status":
                actor = None
                unavailable = False
                for store in bsv_one.stores(db):
                    legal = self.hq_layout_scope(db, store["id"])
                    if legal is None:
                        continue
                    decision = identity_client().authorize_hq_layout(
                        identity_session, store["id"], "hq.layout.read", legal)
                    if decision.get("allowed") is True:
                        actor = decision["actor_tr_code"]
                        break
                    unavailable |= decision.get("reason") == "IDENTITY_UNAVAILABLE"
                if not actor:
                    status = 503 if unavailable else 403
                    self.send_json({"error": "当前账号无权查看总部地图。", "code": "IDENTITY_UNAVAILABLE" if unavailable else "HQ_LAYOUT_FORBIDDEN"}, status)
                    return
                self.send_json({"ok": True, "hq": True, "actor": actor})
                return
            stores = bsv_one.stores(db)
            if path in {"/api/hq/stores", "/api/hq/modules"}:
                visible = []
                for store in stores:
                    legal = self.hq_layout_scope(db, store["id"])
                    if legal is None:
                        continue
                    allowed = identity_client().authorize_hq_layout(
                        identity_session, store["id"], "hq.layout.read", legal)
                    if allowed.get("allowed") is True:
                        visible.append(store)
                    elif allowed.get("reason") == "IDENTITY_UNAVAILABLE":
                        self.send_json({"error": "身份服务暂不可用。", "code": "IDENTITY_UNAVAILABLE"}, 503)
                        return
                if path == "/api/hq/modules":
                    self.send_json({"modules": bsv_one.modules() if visible else []})
                else:
                    self.send_json({"stores": visible})
                return
            legal = self.hq_layout_scope(db, requested_store)
            if legal is None:
                self.send_json({"error": "门店法人关系尚未核验。", "code": "STORE_SCOPE_UNKNOWN"}, 403)
                return
            decision = identity_client().authorize_hq_layout(
                identity_session, requested_store, "hq.layout.read", legal)
            if decision.get("allowed") is not True:
                status = 503 if decision.get("reason") == "IDENTITY_UNAVAILABLE" else 403
                self.send_json({"error": "当前账号无权查看此门店地图。", "code": decision.get("reason")}, status)
                return
            if not db.execute("SELECT 1 FROM stores WHERE id=?", (requested_store,)).fetchone():
                self.send_json({"error": "门店不存在。", "code": "STORE_NOT_FOUND"}, 404)
                return
            if path == "/api/hq/layout/revision":
                # Read one immutable draft only after the same live identity.A store scope check.
                revision_id = query.get("revision_id", [""])[0]
                if not re.fullmatch(r"REV-[0-9a-f]{32}", revision_id):
                    self.send_json({"error": "草稿编号无效。", "code": "REVISION_INVALID"}, 400)
                    return
                row = db.execute("""SELECT revision_id,status,base_version,payload_json,sha256
                    FROM bsv_layout_revisions WHERE store_id=? AND revision_id=?""",
                    (requested_store, revision_id)).fetchone()
                if not row:
                    self.send_json({"error": "未找到本门店草稿。", "code": "REVISION_NOT_FOUND"}, 404)
                    return
                if row["status"] != "DRAFT":
                    self.send_json({"error": "历史正式版本恢复尚未开放。", "code": "REVISION_NOT_DRAFT"}, 409)
                    return
                try:
                    layout = json.loads(row["payload_json"])
                    valid = (isinstance(layout, dict)
                             and layout.get("store_id") == requested_store
                             and bsv_one.digest(layout) == row["sha256"])
                except (TypeError, ValueError):
                    valid = False
                if not valid:
                    self.send_json({"error": "草稿内容校验失败，禁止读取。", "code": "REVISION_INTEGRITY_ERROR"}, 409)
                    return
                self.send_json({"revision_id":revision_id,"status":row["status"],
                                "base_version":row["base_version"],"layout":layout})
                return
            if path == "/api/hq/layout":
                result = bsv_one.current(db, requested_store)
                result["revisions"] = bsv_one.revisions(db, requested_store)
                self.send_json(result)
                return
            try:
                if path == "/api/hq/image":
                    mime, binary = bsv_one.image_by_id(db, requested_store, query.get("asset_id", [""])[0])
                else:
                    mime, binary = bsv_one.layout_art(db, requested_store)
            except bsv_one.ControlError as error:
                self.send_json({"error": str(error)}, error.status)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            # Match the original HQ map image endpoint's SVG sandbox policy.
            self.send_header("Content-Security-Policy", "sandbox; default-src 'none'; style-src 'unsafe-inline'")
            self.send_header("Content-Length", str(len(binary)))
            self.end_headers()
            self.wfile.write(binary)

    def hq_layout_audit_actor(self, db, decision, store_id, legal_entity_id):
        """Create or resolve a disabled SQLite audit projection for an A-verified TR."""
        if (MODE != "staging" or os.environ.get("BSV_APP_ENV") != "isolated"
                or os.environ.get("BSV_POS_LAYOUT_SCOPE_MODE") != "isolated-synthetic"):
            return None
        tr_code = decision.get("actor_tr_code")
        if (not isinstance(tr_code, str)
                or not re.fullmatch(r"TR[ABCDEFGHJKLMNPQRSTUVWXYZ][0-9]{4}", tr_code)):
            return None
        alias = db.execute("SELECT staff_id FROM bsv_hq_actor_aliases WHERE tr_code=?", (tr_code,)).fetchone()
        if alias:
            staff_id = alias["staff_id"]
            staff = db.execute("SELECT staff_code,role,enabled FROM staff WHERE id=?", (staff_id,)).fetchone()
            if not staff or staff["staff_code"] != tr_code or staff["role"] != "STAFF" or staff["enabled"] != 0:
                return None
        else:
            # Never adopt an unrelated legacy staff row that happens to share the TR string.
            if db.execute("SELECT 1 FROM staff WHERE staff_code=? OR id=?", (tr_code, "HQ-AUDIT-" + tr_code)).fetchone():
                return None
            staff_id = "HQ-AUDIT-" + tr_code
            salt = secrets.token_bytes(16)
            disabled_pin = secrets.token_urlsafe(48)
            db.execute("INSERT INTO staff(id,staff_code,pin_salt,pin_digest,role,enabled) VALUES(?,?,?,?,?,0)",
                       (staff_id, tr_code, salt.hex(), pin_hash(disabled_pin, salt), "STAFF"))
            db.execute("INSERT INTO bsv_hq_actor_aliases(tr_code,staff_id,created_at) VALUES(?,?,?)",
                       (tr_code, staff_id, timestamp()))
        if (db.execute("SELECT 1 FROM staff_store_access WHERE staff_id=? LIMIT 1", (staff_id,)).fetchone()
                or db.execute("SELECT 1 FROM bsv_hq_roles WHERE staff_id=? LIMIT 1", (staff_id,)).fetchone()
                or db.execute("SELECT 1 FROM sessions WHERE staff_id=? LIMIT 1", (staff_id,)).fetchone()):
            return None
        return bsv_one.HQLayoutActor(staff_id, tr_code, decision["action"],
                                     legal_entity_id, store_id, secrets.token_urlsafe(18))

    def hq_layout_page(self, path):
        """Authorize the original HQ editor page and its assets through identity.A."""
        identity_session = self.cookie("bsv_identity_session")
        if not identity_session:
            self.send_json({"error": "请先登录总部统一身份账号。", "code": "AUTH_REQUIRED"}, 401)
            return
        unavailable = False
        with db_read() as db:
            for store in bsv_one.stores(db):
                legal_entity_id = self.hq_layout_scope(db, store["id"])
                if legal_entity_id is None:
                    continue
                decision = identity_client().authorize_hq_layout(
                    identity_session, store["id"], "hq.layout.read", legal_entity_id)
                if decision.get("allowed") is True:
                    break
                unavailable |= decision.get("reason") == "IDENTITY_UNAVAILABLE"
            else:
                status = 503 if unavailable else 403
                code = "IDENTITY_UNAVAILABLE" if unavailable else "HQ_LAYOUT_FORBIDDEN"
                self.send_json({"error": "当前账号没有门店地图查看权限。", "code": code}, status)
                return
        files = {
            "/hq/stores/layout": "hq.html",
            "/hq/stores/layout/assets/app.js": "hq.js",
            "/hq/stores/layout/assets/style.css": "hq.css",
        }
        name = files.get(path)
        if not name:
            self.send_error(404)
            return
        file = APPS / "hq-console" / "bsv1" / name
        if not file.is_file():
            self.send_error(404)
            return
        mime = ("text/html; charset=utf-8" if name.endswith(".html") else
                "text/css; charset=utf-8" if name.endswith(".css") else
                "application/javascript; charset=utf-8")
        content = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def hq_layout_draft(self, data):
        identity_session = self.cookie("bsv_identity_session")
        if not identity_session:
            self.send_json({"error": "请先登录统一身份账号。", "code": "AUTH_REQUIRED"}, 401)
            return
        self.require_loopback_origin()
        csrf = self.headers.get("X-CSRF-Token", "")
        if not self.identity_csrf():
            self.send_json({"error": "身份会话校验失败，请刷新后重试。", "code": "BAD_CSRF"}, 403)
            return
        if set(data) != {"store_id", "layout", "base_version"}:
            self.send_json({"error": "草稿参数无效。", "code": "INVALID_DRAFT"}, 400)
            return
        store_id = data.get("store_id")
        if type(store_id) is not str or not re.fullmatch("[A-Z0-9_-]{3,32}", store_id):
            self.send_json({"error": "门店代码无效。", "code": "STORE_INVALID"}, 400)
            return
        with db_read() as db:
            legal_entity_id = self.hq_layout_scope(db, store_id)
            exists = bool(db.execute("SELECT 1 FROM stores WHERE id=?", (store_id,)).fetchone())
        if not legal_entity_id or not exists:
            self.send_json({"error": "门店法人关系尚未核验。", "code": "STORE_SCOPE_UNKNOWN"}, 403)
            return
        decision = identity_client().authorize_hq_layout(
            identity_session, store_id, "hq.layout.edit", legal_entity_id, csrf)
        if decision.get("allowed") is not True:
            reason = decision.get("reason")
            status = 401 if reason == "AUTH_REQUIRED" else 503 if reason == "IDENTITY_UNAVAILABLE" else 403
            self.send_json({"error": "当前账号无权保存此门店地图草稿。", "code": reason or "HQ_LAYOUT_FORBIDDEN"}, status)
            return
        try:
            with tx() as db:
                # Repeat the local scope check immediately before touching the map database.
                if self.hq_layout_scope(db, store_id) != legal_entity_id:
                    raise bsv_one.ControlError("门店法人关系尚未核验。", 403)
                actor = self.hq_layout_audit_actor(db, decision, store_id, legal_entity_id)
                if actor is None:
                    raise bsv_one.ControlError("总部操作人审计映射未通过。", 403)
                result = bsv_one.draft(db, actor, store_id, data.get("layout"), data.get("base_version"))
            self.send_json(result)
        except bsv_one.ControlError as error:
            self.send_json({"error": str(error)}, error.status)
        except bsv_layouts.LayoutError as error:
            self.send_json({"error": str(error)}, 409)

    def send_error_json(self, error):
        self.send_json({"error": error.message, **({"code": error.code} if error.code else {})}, error.status)

    def device_login(self, data):
        if not device_required():
            raise UserError("终端统一登录尚未开放。", 404, "DEVICE_MODE_DISABLED")
        self.require_loopback_origin()
        if not self.cookie("bsv_identity_session"):
            raise self.device_error("AUTH_REQUIRED")
        if not self.identity_csrf():
            raise UserError("员工会话校验失败。请刷新页面再试。", 403, "BAD_CSRF")
        store_id = required(data, "store_id")
        if data.get("confirmed_store_id") != store_id:
            raise UserError("请确认当前所在门店。", 400, "STORE_CONFIRMATION_REQUIRED")
        if set(data) - {"store_id", "confirmed_store_id", "device_id", "device_token"}:
            raise UserError("终端登录参数无效。", 400, "INVALID_LOGIN")
        registering = "device_id" in data or "device_token" in data
        if registering:
            device = device_pos.credentials(data.get("device_id"), data.get("device_token"))
        else:
            device = device_pos.parse_device_cookie(self.cookie(device_pos.DEVICE_COOKIE))
        if not device:
            raise self.device_error("DEVICE_UNVERIFIED")
        upstream = self.cookie("bsv_identity_session")
        if not device_pos.login_allowed(device[0], upstream):
            raise UserError("终端核验过于频繁。请稍后再试或联系负责人。", 429, "DEVICE_RATE_LIMIT")
        authority = self.authorize_device_context(store_id, device, "pos.order.read")
        if device_pos.scope_from(self.authorize_device_context(store_id, device, "pos.order.create")) != device_pos.scope_from(authority):
            raise self.device_error("POS_SESSION_CHANGED")
        with tx() as db:
            if not db.execute("SELECT 1 FROM stores WHERE id=?", (store_id,)).fetchone():
                raise UserError("门店未在本地点单台登记。请联系负责人。", 403, "STORE_NOT_READY")
            staff = device_pos.bind_actor(db, authority, store_id)
            if not staff:
                raise self.device_error("POS_SESSION_CHANGED")
            token = secrets.token_urlsafe(36)
            token_digest = device_pos.digest(token)
            csrf = secrets.token_urlsafe(24)
            db.execute("DELETE FROM sessions WHERE expires_at<=?", (timestamp(),))
            # A new employee on the same terminal must not inherit the prior local session.
            db.execute("""DELETE FROM sessions WHERE token_digest IN
                          (SELECT session_digest FROM bsv_pos_device_sessions WHERE device_id=?)
                          OR (staff_id=? AND store_id<>?)""", (device[0], staff["id"], store_id))
            prior = self.cookie(self.pos_cookie_name())
            if prior:
                db.execute("DELETE FROM sessions WHERE token_digest=?", (device_pos.digest(prior),))
            db.execute("INSERT INTO sessions(token_digest,staff_id,csrf,expires_at,store_id) VALUES (?,?,?,?,?)",
                       (token_digest, staff["id"], csrf, timestamp()+device_pos.DEVICE_SESSION_SECONDS, store_id))
            scope = device_pos.scope_from(authority)
            device_pos.remember(db, token_digest, upstream, device[1], scope)
            record(db, dict(staff, session_store_id=store_id, authority=scope), "DEVICE_LOGIN", staff["id"])
        self.send_json({"ok": True, "scope": scope}, set_cookie=token, new_device=device if registering else None)

    def device_logout(self, *, forget=False):
        self.require_loopback_origin()
        session = self.cookie(self.pos_cookie_name())
        local = self.local_session(session) if session else None
        supplied = self.headers.get("X-BSV-CSRF", "")
        browser_session = self.cookie("bsv_identity_session")
        anonymous_forget = forget and not session and not browser_session
        if not (anonymous_forget or self.identity_csrf() or (local and supplied
                and hmac.compare_digest(local["csrf"].encode(), supplied.encode()))):
            raise UserError("页面会话校验失败。请刷新后继续。", 403, "BAD_CSRF")
        if session:
            with tx() as db:
                db.execute("DELETE FROM sessions WHERE token_digest=?", (device_pos.digest(session),))
        revoked = not browser_session or identity_client().revoke_browser_session(browser_session, self.cookie("bsv_csrf"))
        response = {"ok": True, "identity_session_revoked": revoked}
        if not revoked:
            response["message"] = "已锁定本机点单，统一会话的远端退出结果尚未确认。"
        self.send_json(response, delete_cookie=True, clear_identity=True, forget_device=forget)

    def read_body(self):
        try:n=int(self.headers.get('Content-Length','0'))
        except ValueError:raise UserError('无效请求长度')
        if n<0 or n>(3000000 if self.path.startswith('/api/hq/image/upload') else 131072 if self.path.startswith('/api/hq/') else 16384):raise UserError('请求内容过大',413)
        if 'application/json' not in self.headers.get('Content-Type',''):raise UserError('仅接受JSON',415)
        try:
            d=json.loads(self.rfile.read(n) or b'{}')
            if type(d)!=dict:raise ValueError()
            return d
        except (ValueError,UnicodeDecodeError):raise UserError('JSON格式错误')
    def do_GET(self):
        path=unquote(urlparse(self.path).path)
        versioned_catalog=None
        versioned_id=None
        if path=="/api/v1/catalog/products":
            path="/api/catalog/search";versioned_catalog="search"
        else:
            match=re.fullmatch(r"/api/v1/catalog/products/([CPMK]\d{6})(/recipe)?",path)
            if match:
                versioned_id=match.group(1)
                versioned_catalog="recipe" if match.group(2) else "item"
                path="/api/production/recipe" if versioned_catalog=="recipe" else "/api/catalog/item"
        if path in {"/hq/stores/layout", "/hq/stores/layout/assets/app.js",
                    "/hq/stores/layout/assets/style.css"}:
            self.hq_layout_page(path)
            return
        if path=='/api/bootstrap':
            with db_read() as db:
                stores=[dict(x) for x in db.execute('SELECT id,name,district,business_type,layout_ready FROM stores ORDER BY district,id')]
            capability = ({"device_required": True,
                           "device_remembered": bool(device_pos.parse_device_cookie(self.cookie(device_pos.DEVICE_COOKIE)))}
                          if device_required() else {})
            self.send_json({'province':'北京市','stores':stores,'prototype':True,'version':application_version(),'mode':MODE,
                            **capability});return
        if path=='/api/health':self.send_json(health_snapshot());return
        if path=='/api/visits/customer-context':
            try:self.growth_visit_context()
            except UserError as e:self.send_error_json(e)
            return
        if device_required() and path.startswith("/api/pos/commands/"):
            request_id = path.removeprefix("/api/pos/commands/")
            if not re.fullmatch(r"[A-Za-z0-9-]{8,90}", request_id):
                self.send_json({"error": "操作编号无效。", "code": "ACTION_ID_REQUIRED"}, 400)
                return
            staff = self.resolve_auth()
            if not staff:
                self.fail_auth("请先重新核验门店。")
                return
            with db_read() as db:
                row = db.execute("""SELECT response_json FROM bsv_pos_device_commands
                                    WHERE action_id=? AND scope_digest=?""",
                                 (request_id, device_pos.scope_digest(staff["authority"]))).fetchone()
            if not row:
                self.send_json({"status": "NOT_CONFIRMED", "request_id": request_id}, 404)
            else:
                self.send_json({"status": "CONFIRMED", "request_id": request_id,
                                "result": json.loads(row["response_json"])})
            return
        if device_required() and (path.startswith("/api/members/") or path == "/api/history"):
            self.send_json({"error":"内部演练不开放会员或结账历史。","code":"POS_ACTION_DISABLED"},403)
            return
        # Headquarters API: authenticated + separately granted HQ role.
        if (device_required() or os.environ.get("BSV_POS_IDENTITY_REQUIRED") == "1") and path.startswith(('/api/hq/','/hq','/api/reports/','/api/audit')):
            read_only_hq = {"/api/hq/status", "/api/hq/stores", "/api/hq/modules",
                            "/api/hq/layout", "/api/hq/layout/revision", "/api/hq/art", "/api/hq/image"}
            if path in read_only_hq and self.command == "GET":
                self.hq_layout_read(path)
                return
            self.send_json({'error':'此读操作尚未接入集团授权'},403)
            return
        if path in ('/api/hq/status','/api/hq/stores','/api/hq/layout','/api/hq/art','/api/hq/image','/api/hq/modules'):
            staff=self.resolve_auth()
            if not staff:self.fail_auth('请先从点单页登录');return
            with db_read() as db:
                if not bsv_one.is_hq(db,staff):self.send_json({'error':'仅总部授权账号可访问'},403);return
                q=parse_qs(urlparse(self.path).query)
                sid=q.get('store_id',[''])[0]
                if path=='/api/hq/status':self.send_json({'ok':True,'hq':True,'actor':staff['staff_code']});return
                if path=='/api/hq/stores':self.send_json({'stores':bsv_one.stores(db)});return
                if path=='/api/hq/modules':self.send_json({'modules':bsv_one.modules()});return
                if not re.fullmatch('[A-Z0-9_-]{3,32}',sid):self.send_json({'error':'门店代码无效'},400);return
                if not db.execute('SELECT 1 FROM stores WHERE id=?',(sid,)).fetchone():
                    self.send_json({'error':'门店不存在'},404);return
                if path=='/api/hq/layout':
                    result=bsv_one.current(db,sid);result['revisions']=bsv_one.revisions(db,sid)
                    self.send_json(result);return
                if path in ('/api/hq/art','/api/hq/image'):
                    try:
                        if path=='/api/hq/image':
                            aid=q.get('asset_id',[''])[0]
                            mime,binary=bsv_one.image_by_id(db,sid,aid)
                        else:mime,binary=bsv_one.layout_art(db,sid)
                    except bsv_one.ControlError as e:self.send_json({'error':str(e)},e.status);return
                    self.send_response(200);self.send_header('Content-Type',mime)
                    self.send_header('Cache-Control','private, no-store');self.send_header('X-Content-Type-Options','nosniff')
                    self.send_header('Content-Security-Policy',"sandbox; default-src 'none'; style-src 'unsafe-inline'")
                    self.send_header('Content-Length',str(len(binary)));self.end_headers();self.wfile.write(binary);return
        if path=='/api/menu-preview':
            staff=self.resolve_auth()
            if not staff:self.fail_auth('请先登录');return
            q=parse_qs(urlparse(self.path).query)
            sid=q.get('store_id',[staff['session_store_id']])[0]
            with db_read() as db:
                allowed=sid==staff['session_store_id'] or bsv_one.is_hq(db,staff)
                if not allowed:self.send_json({'error':'门店未授权'},403);return
                if not db.execute('SELECT 1 FROM stores WHERE id=?',(sid,)).fetchone():
                    self.send_json({'error':'门店不存在'},404);return
                rows=[] if postgres_catalog_enabled() else catalog_for_store(db,sid)
            source = 'postgresql-raw-catalog-not-public' if postgres_catalog_enabled() else 'C_现场成品!AJ'
            self.send_json({'store_id':sid,'source':source,'scope':'private-preview',
              'catalog_publication':'BLOCKED_RAW_NOT_APPROVED' if postgres_catalog_enabled() else 'EXISTING_SQLITE_APPROVALS',
              'products':rows,'priced':sum(bool(r['sale_enabled']) for r in rows if r['domain']=='C'),
              'payments_enabled':False});return
        if path=='/api/document':
            staff=self.resolve_auth()
            if not staff:self.fail_auth('请先登录并确认门店');return
            docid=parse_qs(urlparse(self.path).query).get('doc_id',[''])[0]
            with db_read() as db:
                doc=db.execute('SELECT * FROM store_documents WHERE id=? AND store_id=? AND available=1',
                               (docid,staff['session_store_id'])).fetchone()
                if not doc or not doc['filename']:self.send_json({'error':'本店资料不存在'},404);return
                name=doc['filename']
                if not (name.startswith('assets/'+staff['session_store_id']+'_') and '/' not in name[7:]):
                    self.send_json({'error':'非法文件名'},403);return
                file=ROOT/name
                if not file.is_file():self.send_json({'error':'资料尚未上传'},404);return
            from mimetypes import guess_type
            content=file.read_bytes();self.send_response(200)
            self.send_header('Content-Type',guess_type(file.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length',str(len(content)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Cache-Control','private,no-store, max-age=0')
            self.send_header('Vary','Cookie')
            self.send_header('X-BSV-Store',staff['session_store_id'])
            self.end_headers();self.wfile.write(content);return
        if path=='/api/store-layout-art':
            staff=self.resolve_auth()
            if not staff:self.fail_auth('请先登录并确认门店');return
            requested_store=parse_qs(urlparse(self.path).query).get('store_id',[staff['session_store_id']])[0]
            if requested_store!=staff['session_store_id']:
                self.send_json({'error':'底图门店与登录门店不一致，请刷新页面'},403);return
            with db_read() as db:
                try: mime,content=bsv_one.layout_art(db,staff['session_store_id'])
                except bsv_one.ControlError as e:self.send_json({'error':str(e)},e.status);return
            self.send_response(200)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(content)))
            self.send_header('Content-Security-Policy',"sandbox; default-src 'none'; style-src 'unsafe-inline'")
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Cache-Control','private,no-store')
            self.end_headers();self.wfile.write(content);return
        if path=='/api/reports/checkout-csv':
            staff=self.resolve_auth()
            if not staff:self.fail_auth('请先登录并确认门店');return
            q=parse_qs(urlparse(self.path).query)
            try:
                start=bsv_day_filter(q.get('from',[''])[0]);end=bsv_day_filter(q.get('to',[''])[0],True)
                if start and end and start>=end:raise UserError('结束日期不能早于开始日期')
            except UserError as e:self.send_error_json(e);return
            with db_read() as db:
                payload=checkout_csv_bytes(db,staff['session_store_id'],start,end)
            self.send_response(200)
            self.send_header('Content-Type','text/csv; charset=utf-8')
            self.send_header('Content-Disposition',f'attachment; filename="BSV1_{staff["session_store_id"]}_checkouts.csv"')
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers();self.wfile.write(payload);return
        if path=='/api/production/photo':
            staff=self.resolve_auth()
            if not staff:self.fail_auth('请先登录并确认门店');return
            q=parse_qs(urlparse(self.path).query)
            lid=q.get('line_id',[''])[0];product_id=q.get('product_id',[''])[0];kind=q.get('kind',[''])[0]
            if kind not in ('materials','final'):self.send_json({'error':'图片类型不支持'},400);return
            with db_read() as db:
                if product_id and not lid:
                    if not re.fullmatch(r'C\d{6}',product_id):
                        self.send_json({'error':'无效商品固定ID'},400);return
                else:
                    r=db.execute('''SELECT l.product_id FROM production_tasks t JOIN order_lines l ON l.id=t.line_id
                        WHERE t.line_id=? AND t.store_id=?''',(lid,staff['session_store_id'])).fetchone()
                    if not r:self.send_json({'error':'任务不属于本店'},404);return
                    product_id=r['product_id']
                if postgres_catalog_enabled():
                    try:
                        product=PostgresCatalogReadRepository().get_product(product_id,allow_confidential=True)
                    except Exception as error:
                        if not isinstance(error,(ValueError,RuntimeError,OSError)) and not error.__class__.__module__.startswith('psycopg'):
                            raise
                        self.send_json({'error':'PostgreSQL资料源暂不可用。POS订单和座位数据未受影响。',
                                        'code':'CATALOG_SOURCE_UNAVAILABLE'},503);return
                    if not product:self.send_json({'error':'资料不存在'},404);return
                    field={'materials':'配方图文件名｜首次确认','final':'成品图文件名'}[kind]
                    filepath=collab._media_file(product_id,product.get('source_fields',{}).get(field))
                else:
                    info=collab.recipe(db,staff['session_store_id'],product_id)
                    photo=info.get('photos',{}).get(kind,{})
                    filepath=collab._media_file(product_id,photo.get('filename'))
            if not filepath:self.send_json({'error':'尚未上传此商品的图片文件'},404);return
            from mimetypes import guess_type
            payload=filepath.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type',guess_type(filepath.name)[0] or 'application/octet-stream')
            self.send_header('Cache-Control','private, no-store')
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers();self.wfile.write(payload);return
        if path in ('/api/state','/api/receipt','/api/history','/api/audit','/api/members/search','/api/catalog/item','/api/catalog/search','/api/production/recipe'):
            staff=self.resolve_auth()
            if not staff:self.fail_auth('请先登录并确认门店');return
            if path=='/api/state' and not device_required():report_escalations(staff['session_store_id'])
            q=parse_qs(urlparse(self.path).query)
            if versioned_id:
                q["id"]=[versioned_id]
            with db_read() as db:
                if path=='/api/state':data=state(db,staff)
                elif versioned_catalog and postgres_catalog_enabled():
                    try:
                        repository = PostgresCatalogReadRepository()
                        hq_reader = bsv_one.is_hq(db, staff)
                        if versioned_catalog == 'search':
                            term = q.get('q',[''])[0].strip()
                            domain = q.get('domain',['ALL'])[0]
                            if len(term) > 100 or domain not in {'ALL','C','P','M','K','READY'}:
                                self.send_json({'error':'无效查询条件'},400);return
                            data = repository.search(term, domain, 100)
                        elif versioned_catalog == 'item':
                            data = repository.get_product(versioned_id, allow_confidential=(versioned_id[0] in {'C','P'} or hq_reader))
                            if not data:
                                self.send_json({'error':'资料不存在'},404);return
                            if versioned_id[0] == 'M' and not hq_reader:
                                data['withheld_fields'] = sorted(set(data.get('withheld_fields',[])) | {
                                    key for key in data.get('source_fields',{})
                                    if any(word in key for word in ('采购价','成本','供应商','进货价','单价','金额'))})
                        else:
                            data = repository.recipe(versioned_id, allow_confidential=True)
                            if not data:
                                self.send_json({'error':'制作资料不存在'},404);return
                    except Exception as error:
                        if not isinstance(error, (ValueError, RuntimeError, OSError)) and not error.__class__.__module__.startswith('psycopg'):
                            raise
                        self.send_json({'error':'PostgreSQL资料源暂不可用。POS订单和座位数据未受影响。',
                                        'code':'CATALOG_SOURCE_UNAVAILABLE'},503);return
                elif path=='/api/production/recipe':
                    lid=q.get('line_id',[''])[0]
                    product_id=q.get('id',[''])[0]
                    if product_id and not lid and not re.fullmatch(r'C\d{6}',product_id):
                        self.send_json({'error':'无效商品固定ID'},400);return
                    if not (product_id and not lid):
                        task=db.execute('''SELECT t.*,l.product_id FROM production_tasks t JOIN order_lines l ON l.id=t.line_id
                            WHERE t.line_id=? AND t.store_id=?''',(lid,staff['session_store_id'])).fetchone()
                        if not task:self.send_json({'error':'制作任务不属于本店'},404);return
                        product_id=task['product_id']
                    if postgres_catalog_enabled():
                        try:
                            data=PostgresCatalogReadRepository().recipe(product_id,allow_confidential=True)
                        except Exception as error:
                            if not isinstance(error,(ValueError,RuntimeError,OSError)) and not error.__class__.__module__.startswith('psycopg'):
                                raise
                            self.send_json({'error':'PostgreSQL资料源暂不可用。POS订单和座位数据未受影响.',
                                            'code':'CATALOG_SOURCE_UNAVAILABLE'},503);return
                        if not data:self.send_json({'error':'制作资料不存在'},404);return
                    else:
                        data=collab.recipe(db,staff['session_store_id'],product_id)
                elif path=='/api/catalog/search':
                    term=q.get('q',[''])[0].strip().casefold()
                    domain=q.get('domain',['ALL'])[0]
                    allowed_domains={'ALL','C','P','M','K','READY'}
                    if domain not in allowed_domains or len(term)>100:
                        self.send_json({'error':'无效查询条件'},400);return
                    if not term:
                        self.send_json({'items':[],'source':catalog_source(db)});return
                    page_map={'C':'C_现场成品','P':'P_预调半成品','M':'M_采购纯饮','K':'K_套餐组合'}
                    pages=[page_map[x] for x in page_map if domain in ('ALL',x) or domain=='READY' and x=='C']
                    records=[]
                    for page_name in pages:
                        for record in db.execute('''SELECT fixed_id,display_name,page,fields_json FROM bsv_v9_record
                                WHERE page=? ORDER BY source_row LIMIT 1000''',(page_name,)):
                            fields=json.loads(record['fields_json'])
                            haystack=' '.join([record['fixed_id'],record['display_name'],
                                *(str(v) for k,v in fields.items() if any(w in str(k).casefold()
                                  for w in ('名称','系列','类别','分类','规格','sku')))]).casefold()
                            if term not in haystack:continue
                            fixed_id=record['fixed_id']
                            product=db.execute('SELECT * FROM bsv_products WHERE id=?',(fixed_id,)).fetchone()
                            sellable=bool(product and price_is_current(db,product,staff['session_store_id']))
                            if domain=='READY' and not sellable:continue
                            if record['page']=='M_采购纯饮':
                                withheld=[k for k in fields if any(word in str(k).casefold()
                                    for word in ('采购价','成本','供应商','进货价','单价','价格','金额'))]
                                fields={k:v for k,v in fields.items() if k not in withheld}
                            else:withheld=[]
                            records.append({'id':fixed_id,'name':record['display_name'],'domain':fixed_id[0],
                                'series':str(fields.get('销售系列') or fields.get('类别') or ''),
                                'sale_enabled':sellable,'fields':fields,'withheld_fields':withheld})
                            if len(records)>=100:break
                        if len(records)>=100:break
                    data={'items':records,'source':catalog_source(db)}
                elif path=='/api/catalog/item':
                    fixed_id=q.get('id',[''])[0]
                    if not re.fullmatch(r'[CPMK]\d{6}',fixed_id):
                        self.send_json({'error':'无效资料固定ID'},400);return
                    page={'C':'C_现场成品','P':'P_预调半成品','M':'M_采购纯饮','K':'K_套餐组合'}[fixed_id[0]]
                    if versioned_catalog=='item':
                        record=SQLiteCatalogReadRepository(db).get_product(fixed_id)
                        row=({'display_name':record['name'],'fields_json':json.dumps(record['source_fields'],ensure_ascii=False)}
                             if record else None)
                    else:
                        row=db.execute('''SELECT display_name,fields_json FROM bsv_v9_record WHERE fixed_id=? AND page=?''',
                                       (fixed_id,page)).fetchone()
                    if not row:self.send_json({'error':'资料不存在'},404);return
                    fields=json.loads(row['fields_json'])
                    withheld=[]
                    if page=='M_采购纯饮':
                        withheld=[k for k in fields if any(word in str(k).casefold()
                            for word in ('采购价','成本','供应商','进货价','单价','价格','金额'))]
                        fields={k:v for k,v in fields.items() if k not in withheld}
                    ready=db.execute('SELECT * FROM bsv_products WHERE id=?',(fixed_id,)).fetchone()
                    data={'id':fixed_id,'name':row['display_name'],'fields':fields,
                          'sale_enabled':bool(ready and price_is_current(db,ready,staff['session_store_id'])),
                          'withheld_fields':withheld,'source':catalog_source(db)}
                    if page=='K_套餐组合':
                        data['store_research']=[]
                        for section in ('K_套餐槽位','K_门店NPS'):
                            for extra in db.execute("SELECT section,source_row,fields_json FROM bsv_v9_extra WHERE section=? ORDER BY source_row",(section,)):
                                item=json.loads(extra['fields_json'])
                                if item.get('套餐ID')==fixed_id:
                                    data['store_research'].append({'section':section,'source_row':extra['source_row'],'fields':item})
                    if page=='P_预调半成品':
                        data['production_standard_approved']=(str(fields.get('审核状态') or '') in
                            ('已批准','已核准','审核通过'))
                elif path=='/api/members/search':
                    last4=q.get('last4',[''])[0]
                    if not re.fullmatch(r'\d{4}',last4):
                        self.send_json({'error':'请输入手机号后四位'},400);return
                    matches=db.execute('''SELECT id,surname,phone,tier FROM members WHERE active=1 AND last4=?
                       ORDER BY surname,id LIMIT 20''',(last4,)).fetchall()
                    data={'matches':[{'id':x['id'],'surname':x['surname'],
                        'masked_phone':mask_phone(x['phone']),'tier':x['tier']} for x in matches],
                        'ambiguity':len(matches)>1}
                elif path=='/api/audit':
                    try:start=bsv_day_filter(q.get('from',[''])[0]);end=bsv_day_filter(q.get('to',[''])[0],True)
                    except UserError as e:self.send_error_json(e);return
                    cat=q.get('category',['ALL'])[0]
                    categories={'ALL':None,'ORDERS':['OPEN_VISIT','OPEN_EXISTING','ADD_DRAFT','REMOVE_DRAFT','SUBMIT_ORDER_TEST','SUBMIT_AND_TEST_CHECKOUT','ADD_DEMO_ITEM','CANCEL_ITEM','CANCEL_VISIT','SERVED','CLAIM_PRODUCTION','FINISHED_PRODUCTION','MANUAL_REASSIGN_PRODUCTION'],
                     'PAYMENTS':['TEST_SETTLE_ROUND','SUBMIT_AND_TEST_CHECKOUT','DEPART_DEMO'],
                     'SEATS':['TRANSFER','SEAT_CLEAN','CHANGE_TABLE_MODE'],
                     'MEMBERS':['ASSIGN_MEMBER','SET_MEMBER_TEST'],
                     'CLEAN':['BATHROOM_CLEAN','SEAT_CLEAN'],
                     'CRITICAL':['CRITICAL_OVERDUE'],
                     'STAFF':['LOGIN','SET_GUESTS']}
                    if cat not in categories:
                        self.send_json({'error':'记录分类无效'},400);return
                    sql='''SELECT e.id,e.action,e.target_id,e.detail_json,e.created_at,s.staff_code
                      FROM audit_events e LEFT JOIN staff s ON s.id=e.staff_id WHERE e.store_id=?'''
                    args=[staff['session_store_id']]
                    if start:sql+=' AND e.created_at>=?';args.append(start)
                    if end:sql+=' AND e.created_at<?';args.append(end)
                    if categories[cat]:
                        sql+=' AND e.action IN ('+','.join('?' for _ in categories[cat])+')';args+=categories[cat]
                    sql+=' ORDER BY e.id DESC LIMIT 300'
                    rows=[dict(x) for x in db.execute(sql,args)]
                    for x in rows:x['detail']=json.loads(x.pop('detail_json'))
                    data={'audit':rows,'category':cat,'store_id':staff['session_store_id']}

                elif path=='/api/history':
                    try:
                        start=bsv_day_filter(q.get('from',[''])[0]);end=bsv_day_filter(q.get('to',[''])[0],True)
                        if start and end and start>=end:raise UserError('结束日期不能早于开始日期')
                        offset_str=q.get('offset',['0'])[0]
                        if not re.fullmatch(r'\d{1,8}',offset_str):raise UserError('分页参数无效')
                        offset=int(offset_str)
                    except UserError as e:self.send_error_json(e);return
                    data=checkout_report(db,staff['session_store_id'],start,end,offset,100)
                    # A closed visit is different from a checkout. Preserve this
                    # secondary list for staff who need the complete order receipt.
                    sql='''SELECT v.id,v.seat_id,v.status,v.created_at,v.closed_at,COALESCE(v.seat_label_snapshot,s.label) AS seat_label
                           FROM visits v JOIN seats s ON s.id=v.seat_id
                           WHERE v.store_id=? AND v.status<>'OPEN' '''
                    args=[staff['session_store_id']]
                    if start:sql+=' AND v.closed_at>=?';args.append(start)
                    if end:sql+=' AND v.closed_at<?';args.append(end)
                    sql+=' ORDER BY v.closed_at DESC LIMIT 100'
                    data['history']=[dict(x) for x in db.execute(sql,args)]
                else:
                    vid=parse_qs(urlparse(self.path).query).get('visit_id',[''])[0]
                    try:data=receipt(db,staff,vid)
                    except UserError as e:self.send_error_json(e);return
            if versioned_catalog:
                data["contract_version"]=registry_version()
                if versioned_catalog=="search":
                    page_by_domain={"C":"C_现场成品","P":"P_预调半成品","M":"M_采购纯饮","K":"K_套餐组合"}
                    for item in data.get("items",[]):
                        item["product_id"]=item["id"]
                        item["attributes"]=semantic_attributes(page_by_domain[item["domain"]],item.get("fields",{}))
                        item["source_fields"]=item.get("fields",{})
                else:
                    sheet=({"C":"C_现场成品","P":"P_预调半成品","M":"M_采购纯饮","K":"K_套餐组合"}
                           .get(str(data.get("fixed_id") or data.get("id") or versioned_id)[:1],"C_现场成品"))
                    source_fields=data.get("fields",{})
                    data["attributes"]=semantic_attributes(sheet,source_fields)
                    data["source_fields"]=source_fields
                    if versioned_catalog=="item":data["product_id"]=data.get("id")
                    else:
                        for operation in data.get("recipe_operations",[]):
                            operation["source_fields"]=operation.get("fields",{})
            self.send_json(data);return
        if path in ('/hq','/hq.html','/hq.js','/hq.css','/menu','/menu.html','/menu.js','/menu.css'):
            staff=self.resolve_auth()
            if not staff:self.fail_auth('请先登录 BSV1');return
            if path.startswith('/hq'):
                with db_read() as db:
                    if not bsv_one.is_hq(db,staff):self.send_json({'error':'需要总部管理员权限'},403);return
        extra={'/hq':'hq.html','/hq.html':'hq.html','/hq.js':'hq.js','/hq.css':'hq.css',
               '/menu':'menu.html','/menu.html':'menu.html','/menu.js':'menu.js','/menu.css':'menu.css'}
        paths={'/':'index.html','/index.html':'index.html','/app.js':'app.js',
               '/style.css':'style.css',
               '/assets/BSV_徽记.png':'assets/BSV_徽记.png',
               '/assets/BSV_完整徽标.png':'assets/BSV_完整徽标.png'}
        f=extra.get(path) or paths.get(path)
        if not f:self.send_error(404);return
        app_dir = "hq-console" if f.startswith("hq.") else "guest-web" if f.startswith("menu.") else "store-console"
        file = APPS / app_dir / "bsv1" / f
        if not file.exists():self.send_error(404);return
        mime='text/html; charset=utf-8' if f.endswith('.html') else 'text/css; charset=utf-8' if f.endswith('.css') else 'application/javascript; charset=utf-8' if f.endswith('.js') else 'image/jpeg' if f.lower().endswith('.jpg') else 'image/png'
        b=file.read_bytes();self.send_response(200);self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(b)));self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b)
    def do_POST(self):
        path=urlparse(self.path).path
        try:
            data=self.read_body()
            if path == "/api/v1/visits/customer-staff/verify":
                self.growth_staff_verify(data)
                return
            if path == "/api/v1/visits/customer-context/verify":
                self.growth_visit_verify(data)
                return
            if path == "/api/pos/device-login":
                self.device_login(data);return
            if device_required() and path in {"/api/logout", "/api/pos/device-forget"}:
                self.device_logout(forget=path.endswith("device-forget"));return
            if ((device_required() or os.environ.get("BSV_POS_IDENTITY_REQUIRED") == "1")
                    and path == "/api/hq/layout/draft"):
                self.hq_layout_draft(data)
                return
            if path=='/api/login':
                if device_required():
                    raise UserError("请先登录员工中心，再核验此点单终端。", 403, "DEVICE_MODE_REQUIRED")
                store_id=required(data,'store_id');code=required(data,'staff_code',48);pin=required(data,'pin',100)
                t=time.monotonic()
                # Reverse proxy peers share localhost; limits apply per staff/store, not all staff.
                key=(store_id,code.upper())
                if len(RATE_LIMIT)>3000:
                    RATE_LIMIT.clear() # bounded prototype state; outer nginx adds rate limiting
                recent=[v for v in RATE_LIMIT.get(key,[]) if t-v<600]
                if len(recent)>=8:raise UserError('此员工代码登录尝试过多，请10分钟后重试',429)
                recent.append(t);RATE_LIMIT[key]=recent
                if data.get('confirmed_store_id')!=store_id:raise UserError('必须再次确认登录门店',400)
                with db_read() as db:
                    staff=db.execute('''SELECT s.* FROM staff s JOIN staff_store_access a ON a.staff_id=s.id
                           WHERE s.staff_code=? AND s.enabled=1 AND a.store_id=?''',(code,store_id)).fetchone()
                if not staff or not hmac.compare_digest(pin_hash(pin,bytes.fromhex(staff['pin_salt'])),staff['pin_digest']):
                    raise UserError('员工代码、PIN或门店授权不匹配',401)
                if not self.group_identity(staff['id'],store_id,'pos.order.read'):
                    raise UserError('集团身份或本店授权未通过',403)
                RATE_LIMIT.pop(key,None)
                token=secrets.token_urlsafe(36);csrf=secrets.token_urlsafe(24)
                with tx() as db:
                    db.execute('DELETE FROM sessions WHERE expires_at<?',(timestamp(),))
                    # A staff member may use multiple devices in one store, but never stay logged into two stores.
                    db.execute('DELETE FROM sessions WHERE staff_id=? AND store_id<>?',(staff['id'],store_id))
                    db.execute('INSERT INTO sessions(token_digest,staff_id,csrf,expires_at,store_id) VALUES (?,?,?,?,?)',
                               (hashlib.sha256(token.encode()).hexdigest(),staff['id'],csrf,timestamp()+SESSION_SECONDS,store_id))
                    collab.heartbeat(db,staff['id'],store_id)
                    collab.rebalance(db,store_id)
                    record(db,dict(staff,session_store_id=store_id),'LOGIN',staff['id'],{'confirmed_store':store_id})
                self.send_json({'ok':True},set_cookie=token);return
            staff=self.resolve_auth()
            if not staff:raise self.auth_error or UserError('登录失效，请重新选择门店',401)
            if self.headers.get('X-BSV-CSRF','')!=staff['csrf']:raise UserError('页面会话校验失败，请刷新',403)
            if (device_required() or os.environ.get("BSV_POS_IDENTITY_REQUIRED") == "1") and path.startswith('/api/hq/'):
                raise UserError('此操作尚未接入集团授权',403)
            if path in ('/api/hq/stores/create','/api/hq/layout/draft','/api/hq/layout/publish','/api/hq/layout/restore','/api/hq/image/upload'):
                try:
                    with tx() as db:
                        bsv_one.require_hq(db,staff)
                        if path=='/api/hq/stores/create':result=bsv_one.create_store(db,staff,data)
                        elif path=='/api/hq/image/upload':
                            result=bsv_one.upload_image(db,staff,data.get('store_id'),data.get('mime'),data.get('base64'))
                        else:
                            sid=data.get('store_id')
                            if type(sid)!=str or not re.fullmatch('[A-Z0-9_-]{3,32}',sid):
                                raise bsv_one.ControlError('门店代码无效')
                            if path=='/api/hq/layout/draft':
                                result=bsv_one.draft(db,staff,sid,data.get('layout'),data.get('base_version'))
                            elif path=='/api/hq/layout/publish':
                                result=bsv_one.publish(db,staff,sid,data.get('revision_id'))
                            else:result=bsv_one.rollback_to(db,staff,sid,data.get('revision_id'))
                    self.send_json(result);return
                except bsv_one.ControlError as e:
                    self.send_json({'error':str(e)},e.status);return
                except bsv_layouts.LayoutError as e:
                    self.send_json({'error':str(e)},409);return
            if path=='/api/logout':
                jar=cookies.SimpleCookie();jar.load(self.headers.get('Cookie',''))
                if jar.get('bsv_session'):
                    with tx() as db:db.execute('DELETE FROM sessions WHERE token_digest=?',
                          (hashlib.sha256(jar['bsv_session'].value.encode()).hexdigest(),))
                self.send_json({'ok':True},delete_cookie=True);return
            if path == "/api/visits/customer-link":
                self.growth_customer_link(data, staff)
                return
            if device_required() or os.environ.get("BSV_POS_IDENTITY_REQUIRED") == "1":
                acceptance_cancel = path == ACCEPTANCE_CANCEL_PATH and "acceptance_run" in data
                if path not in ACCEPTANCE_ORDER_PATHS and not acceptance_cancel:
                    raise UserError('该项操作尚未开放，请核对工作台可用功能。',403,"POS_ACTION_DISABLED")
                if device_required():
                    self.require_loopback_origin()
                    device = device_pos.parse_device_cookie(self.cookie(device_pos.DEVICE_COOKIE))
                    authority = self.authorize_device_context(staff['session_store_id'], device, "pos.order.create")
                    if device_pos.scope_from(authority) != staff.get("authority"):
                        raise self.device_error("POS_SESSION_CHANGED")
                elif not self.group_identity(staff['id'],staff['session_store_id'],'pos.order.create'):
                    raise UserError('集团身份未授权此操作',403)
            self.send_json(handle_action(path,data,staff));return
        except UserError as e:self.send_error_json(e)
        except sqlite3.IntegrityError as e:
            print('DB integrity error:',e);self.send_json({'error':'记录已经变更，请刷新后重新确认'},409)
        except Exception as e:
            print('Server error:',repr(e));self.send_json({'error':'服务器错误，请联系管理员'},500)

def main():
    if device_required() and (MODE != "staging" or os.environ.get("BSV_POS_IDENTITY_REQUIRED") != "1"
                              or os.environ.get("BSV_POS_INTERNAL_STAGE") != "1"
                              or os.environ.get("BSV_PRIVATE_SSH_TUNNEL") != "1"):
        raise RuntimeError("Unified device authorization is limited to the isolated SSH-tunneled stage")
    init_db()
    if MODE=='staging' and not device_required():
        with db_read() as db:
            enabled=db.execute('''SELECT COUNT(*) FROM staff s JOIN staff_store_access a ON a.staff_id=s.id
                   WHERE s.enabled=1 ''').fetchone()[0]
        if enabled==0:
            raise RuntimeError('云端验收模式未配置正式测试员工，请先通过 manage_staff.py 添加账号；不得启用默认演示PIN')
    print(f'BSV1 {application_version()} 多门店独立地图 | http://{HOST}:{PORT} | mode={MODE} | 未接真实支付')
    if MODE=='local': print('仅本地演练；使用 manage_staff.py 交互创建测试账号')
    else: print('云端验收：固定演示账号已禁用，必须通过 HTTPS 反向代理和额外访问门禁访问')
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()

if __name__=='__main__':main()
