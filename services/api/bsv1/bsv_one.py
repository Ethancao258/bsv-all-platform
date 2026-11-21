"""BSV ONE v0.1: explicitly gated HQ map governance; additive SQLite schema.

The POS is authoritative for seats and orders. The V9 workbook is the current
product master; CloudBase PostgreSQL remains a separate, unconnected project.
No public endpoints or payment processing are implemented here.
"""
from __future__ import annotations
import base64, hashlib, json, re, uuid, struct
from datetime import datetime, timezone
import bsv_layouts

ID_RE=re.compile(r'^[A-Z][A-Z0-9_-]{2,31}$')
SEAT_RE=re.compile(r'^[A-Z][A-Z0-9_-]{1,31}-SEAT-[0-9]{4}$')
GROUP_RE=re.compile(r'^[A-Z][A-Z0-9_-]{1,31}-GROUP-[0-9]{4}$')
RESTROOM_RE=re.compile(r'^[A-Z][A-Z0-9_-]{1,31}-RESTROOM-[0-9]{4}$')
TYPES={'SOFA','ROUND','BAR','WINDOW','BOOTH','TEMP','TABLE','OTHER'}

class ControlError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message); self.status=status

class HQLayoutActor:
    """In-process identity.A actor scoped to one authorized draft operation."""
    __slots__ = ("staff_id", "tr_code", "action", "legal_entity_id", "store_id", "request_id")

    def __init__(self, staff_id, tr_code, action, legal_entity_id, store_id, request_id):
        if (action != "hq.layout.edit" or not isinstance(tr_code, str)
                or not re.fullmatch(r"TR[ABCDEFGHJKLMNPQRSTUVWXYZ][0-9]{4}", tr_code)
                or not isinstance(staff_id, str) or not staff_id
                or not legal_entity_id or not store_id or not request_id):
            raise ControlError("总部地图操作人身份无效", 403)
        self.staff_id = staff_id
        self.tr_code = tr_code
        self.action = action
        self.legal_entity_id = legal_entity_id
        self.store_id = store_id
        self.request_id = request_id

    def __getitem__(self, key):
        if key == "id":
            return self.staff_id
        raise KeyError(key)

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def compact(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(x): return hashlib.sha256(compact(x).encode()).hexdigest()

def schema(db):
    # New canonical databases only; upgrading older POS databases in-place is forbidden.
    db.executescript('''
      CREATE TABLE IF NOT EXISTS bsv_platform_identity(
        profile TEXT PRIMARY KEY CHECK(profile='BSV_ONE_CANONICAL_V1'),
        instance_uuid TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS bsv_hq_roles(
        staff_id TEXT PRIMARY KEY REFERENCES staff(id),role TEXT NOT NULL CHECK(role='HQ_ADMIN'),
        granted_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS bsv_layout_ownership(
        store_id TEXT PRIMARY KEY REFERENCES stores(id),origin TEXT NOT NULL CHECK(origin='HQ_PUBLISHED'),
        published_revision TEXT NOT NULL,published_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS bsv_layout_revisions(
        revision_id TEXT PRIMARY KEY,store_id TEXT NOT NULL REFERENCES stores(id),
        status TEXT NOT NULL CHECK(status IN ('DRAFT','PUBLISHED','SUPERSEDED')),
        base_version INTEGER NOT NULL,version INTEGER,
        payload_json TEXT NOT NULL,sha256 TEXT NOT NULL,
        created_by TEXT REFERENCES staff(id),created_at TEXT NOT NULL,
        published_by TEXT REFERENCES staff(id),published_at TEXT);
      CREATE INDEX IF NOT EXISTS ix_bsv_layout_rev_store ON bsv_layout_revisions(store_id,created_at);
      CREATE UNIQUE INDEX IF NOT EXISTS ux_bsv_layout_pub ON bsv_layout_revisions(store_id) WHERE status='PUBLISHED';
      CREATE TABLE IF NOT EXISTS bsv_layout_images(
        asset_id TEXT PRIMARY KEY,store_id TEXT NOT NULL REFERENCES stores(id),
        mime TEXT NOT NULL CHECK(mime IN ('image/png','image/jpeg')),
        sha256 TEXT NOT NULL,content BLOB NOT NULL,
        created_by TEXT NOT NULL REFERENCES staff(id),created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS bsv_platform_events(
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,actor_staff_id TEXT REFERENCES staff(id),
        module TEXT NOT NULL,action TEXT NOT NULL,entity_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,created_at TEXT NOT NULL);
      CREATE TRIGGER IF NOT EXISTS bsv_canonical_seat_insert BEFORE INSERT ON seats
        WHEN NEW.id NOT GLOB (NEW.store_id || '-SEAT-[0-9][0-9][0-9][0-9]')
        BEGIN SELECT RAISE(ABORT,'noncanonical seat_id'); END;
      CREATE TRIGGER IF NOT EXISTS bsv_immutable_seat_key BEFORE UPDATE OF id,store_id ON seats
        BEGIN SELECT RAISE(ABORT,'seat_id/store_id immutable'); END;
      CREATE TRIGGER IF NOT EXISTS bsv_canonical_group_insert BEFORE INSERT ON table_groups
        WHEN NEW.id NOT GLOB (NEW.store_id || '-GROUP-[0-9][0-9][0-9][0-9]')
        BEGIN SELECT RAISE(ABORT,'noncanonical group_id'); END;
      CREATE TRIGGER IF NOT EXISTS bsv_immutable_group_key BEFORE UPDATE OF id,store_id ON table_groups
        BEGIN SELECT RAISE(ABORT,'group_id/store_id immutable'); END;
      CREATE TRIGGER IF NOT EXISTS bsv_canonical_restroom_insert BEFORE INSERT ON bathrooms
        WHEN NEW.id NOT GLOB (NEW.store_id || '-RESTROOM-[0-9][0-9][0-9][0-9]')
        BEGIN SELECT RAISE(ABORT,'noncanonical restroom_id'); END;
      CREATE TRIGGER IF NOT EXISTS bsv_immutable_restroom_key BEFORE UPDATE OF id,store_id ON bathrooms
        BEGIN SELECT RAISE(ABORT,'restroom_id/store_id immutable'); END;
    ''')
    db.execute("INSERT OR IGNORE INTO bsv_platform_identity(profile,instance_uuid,created_at) VALUES('BSV_ONE_CANONICAL_V1',?,?)",(uuid.uuid4().hex,now()))

def seed_revisions(db):
    """Seed new canonical layouts only. Legacy POS DBs are refused before this stage."""
    for row in db.execute('SELECT store_id,layout_version,config_json FROM store_layout_data').fetchall():
        if db.execute("SELECT 1 FROM bsv_layout_revisions WHERE store_id=? AND status='PUBLISHED'",(row['store_id'],)).fetchone():
            continue
        # A partial/failed publish should be treated as a fatal conflict; never guess.
        rev='CANDIDATE-'+row['store_id']+'-'+str(row['layout_version'])
        cfg=json.loads(row['config_json'])
        db.execute('''INSERT OR IGNORE INTO bsv_layout_revisions
            (revision_id,store_id,status,base_version,version,payload_json,sha256,created_by,created_at,published_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (rev,row['store_id'],'DRAFT',row['layout_version'],row['layout_version'],compact(cfg),digest(cfg),None,now(),None))

def is_hq(db,staff):
    if not staff or staff.get('role')!='MANAGER':return False
    return bool(db.execute("SELECT 1 FROM bsv_hq_roles WHERE staff_id=? AND role='HQ_ADMIN'",(staff['id'],)).fetchone())

def require_hq(db,staff):
    if not is_hq(db,staff):raise ControlError('仅总部授权管理员可操作',403)

def modules():
    # States are intentionally honest; readiness is NOT inferred from this list.
    return [
      {'code':'pos','name':'座位点单/历史订单','state':'RUNNING_PREVIEW','owner':'BSV1 SQLite','path':'/'},
      {'code':'bartending','name':'视觉调酒/制作任务','state':'RUNNING_PREVIEW','owner':'BSV1 SQLite','path':'/'},
      {'code':'layout','name':'总部门店/座位地图','state':'STAGING_FEATURE','owner':'BSV1 SQLite / versioned HQ revisions','path':'/hq'},
      {'code':'catalog','name':'商品主数据与售价','state':'V9_EXCEL_IMPORT','owner':'V9 C_现场成品!AJ','path':'/menu'},
      {'code':'menu','name':'电子菜单预览','state':'PRIVATE_PREVIEW','owner':'BSV1 catalog read-only projection','path':'/menu'},
      {'code':'supply','name':'中央供货/批次/跨店调拨','state':'CONTRACT_ONLY','owner':'Future supply bounded context','path':None},
      {'code':'labels','name':'标签打印/批次追踪','state':'CONTRACT_ONLY','owner':'Future label bounded context','path':None},
      {'code':'people','name':'人事/培训/排班','state':'CONTRACT_ONLY','owner':'Future workforce bounded context','path':None},
      {'code':'finance','name':'支付核验/财务对账','state':'NOT_CONNECTED','owner':'Licensed payment acquirer','path':None},
      {'code':'cloudbase','name':'CloudBase PostgreSQL商品库','state':'SEPARATE_UNVERIFIED','owner':'Existing external CloudBase project','path':None},
    ]

def stores(db):
    result=[]
    for r in db.execute('''SELECT s.id,s.name,s.district,s.business_type,s.design_max_guests,s.layout_ready,
            l.layout_version AS version FROM stores s LEFT JOIN store_layout_data l ON l.store_id=s.id ORDER BY s.id'''):
        d=dict(r); d['seats']=db.execute('SELECT COUNT(*) FROM seats WHERE store_id=? AND layout_enabled=1',(d['id'],)).fetchone()[0];result.append(d)
    return result

def create_store(db,staff,data):
    require_hq(db,staff)
    sid=data.get('store_id'); name=data.get('name');district=data.get('district');btype=data.get('business_type')
    if type(sid)!=str or not ID_RE.fullmatch(sid):raise ControlError('门店代码应为3-32位大写字母/数字/-/_')
    for a,n in ((name,'名称'),(district,'行政区'),(btype,'业态')):
        if type(a)!=str or not a.strip() or len(a)>70:raise ControlError(n+'不合法')
    cap=data.get('design_max_guests',0)
    if type(cap)!=int or not 0<=cap<=10000:raise ControlError('设计人数上限无效')
    if db.execute('SELECT 1 FROM stores WHERE id=?',(sid,)).fetchone():raise ControlError('门店代码已存在',409)
    db.execute('''INSERT INTO stores(id,name,design_max_guests,orientation,created_at,district,business_type,layout_ready)
           VALUES(?,?,?,?,?,?,?,0)''',(sid,name.strip(),cap,'以吧台内调酒师工作视角为准',now(),district.strip(),btype.strip()))
    # Allow the acting HQ admin to log into the new store separately.
    db.execute('INSERT INTO staff_store_access(staff_id,store_id) VALUES(?,?)',(staff['id'],sid))
    event(db,staff,'stores','CREATE',sid,{'name':name.strip()})
    return {'ok':True,'store_id':sid,'layout_ready':False}

def event(db,staff,module,action,entity,details):
    db.execute('INSERT INTO bsv_platform_events(actor_staff_id,module,action,entity_id,payload_json,created_at) VALUES(?,?,?,?,?,?)',
               (staff['id'] if staff else None,module,action,entity,compact(details),now()))

def clean_layout(db,store_id,raw):
    if type(raw)!=dict or raw.get('store_id')!=store_id:raise ControlError('地图门店与选择门店不匹配')
    cfg=json.loads(compact(raw))  # make a JSON-only copy
    if cfg.get('schema_version')!=1 or cfg.get('viewport')!={'width':1100,'height':580}:
        raise ControlError('不支持的地图结构/视口')
    cfg['layout_version']=int(cfg.get('layout_version',1))
    cfg['orientation']='以吧台内调酒师工作位为准，左右关系由邻接表定义，不按坐标推断'
    cfg['background_svg']='art/'+store_id+'.svg'
    seats=cfg.get('seats')
    if type(seats)!=list or not 1<=len(seats)<=500:raise ControlError('必须有1到500个有效座位')
    used=set();labels=set();orders=set()
    for s in seats:
        if type(s)!=dict:raise ControlError('座位记录无效')
        sid=s.get('id');label=s.get('label');order=s.get('order')
        if (type(sid)!=str or sid in used or not SEAT_RE.fullmatch(sid)
                or not sid.startswith(store_id+'-SEAT-')):
            raise ControlError('座位ID不符合唯一规范（门店ID-座位ID）：'+str(sid))
        if type(label)!=str or not label.strip() or len(label)>32 or label in labels:raise ControlError('座位名重复或无效')
        if s.get('kind') not in TYPES:raise ControlError('座位类型无效：'+sid)
        if type(order)!=int or order<1 or order in orders:raise ControlError('排序号重复或无效：'+sid)
        if any(type(s.get(k)) not in (int,float) or not 1<=s[k]<=99 for k in ('x','y')):raise ControlError('坐标仅允许百分比1至99：'+sid)
        cap=s.get('capacity')
        if cap is not None and (type(cap)!=int or not 1<=cap<=100):raise ControlError('容量无效：'+sid)
        if type(s.get('is_secondary'))!=bool:raise ControlError('座位次要位置标记不合法：'+sid)
        used.add(sid);labels.add(label);orders.add(order)
    links=cfg.get('neighbors')
    if type(links)!=dict or set(links)!=used:raise ControlError('左右邻接表需覆盖全部座位')
    for sid,lr in links.items():
        if type(lr)!=dict or set(lr)!={'left','right'}:raise ControlError('邻接定义格式错误')
        for dr in ('left','right'):
            v=lr[dr]
            if v is not None and (v not in used or v==sid):raise ControlError('邻接引用不存在：'+sid)
    groups=cfg.get('groups',[])
    if type(groups)!=list:raise ControlError('分组结构错误')
    gnames=set()
    for g in groups:
        if (type(g)!=dict or type(g.get('id'))!=str or g['id'] in gnames
                or not GROUP_RE.fullmatch(g['id']) or not g['id'].startswith(store_id+'-GROUP-')):
            raise ControlError('合分桌组ID必须是门店ID-GROUP-四位数字且唯一')
        if g.get('primary_seat') not in used or g.get('secondary_seat') not in used or g.get('primary_seat')==g.get('secondary_seat'):
            raise ControlError('合分桌引用无效')
        if g.get('default_mode') not in ('SPLIT','MERGED'):raise ControlError('合分桌模式无效')
        gnames.add(g['id'])
    for s in seats:
        if s.get('group_id') is not None and s['group_id'] not in gnames:raise ControlError('座位分组引用无效')
    for g in groups:
        linked={s['id'] for s in seats if s.get('group_id')==g['id']}
        if linked!={g['primary_seat'],g['secondary_seat']}:raise ControlError('合分桌组成员与关联座位不一致：'+g['id'])
    baths=cfg.get('bathrooms',[])
    if type(baths)!=list:raise ControlError('卫生间记录错误')
    for b in baths:
        if type(b)!=dict or type(b.get('id'))!=str or not RESTROOM_RE.fullmatch(b['id']) or not b['id'].startswith(store_id+'-RESTROOM-'):
            raise ControlError('卫生间ID无效')
        p=b.get('pin')
        if type(p)!=dict or any(type(p.get(k)) not in (int,float) or not 0<=p[k]<=100 for k in ('x','y')):
            raise ControlError('卫生间坐标无效')
        if type(b.get('interval_seconds'))!=int or b['interval_seconds']<60:raise ControlError('卫生间清洁周期无效')
    asset_id=cfg.get('background_asset_id')
    if asset_id is not None:
        if type(asset_id)!=str or not re.fullmatch(r'IMG-[a-f0-9]{32}',asset_id):
            raise ControlError('底图资产标识不合法')
        if db is None or not db.execute('SELECT 1 FROM bsv_layout_images WHERE asset_id=? AND store_id=?',(asset_id,store_id)).fetchone():
            raise ControlError('底图不属于当前门店或不存在')
    if len(compact(cfg))>60000:raise ControlError('地图配置过大')
    return cfg

def current(db,store_id):
    r=db.execute('SELECT * FROM store_layout_data WHERE store_id=?',(store_id,)).fetchone()
    if r:return {'store_id':store_id,'version':r['layout_version'],'layout':json.loads(r['config_json'])}
    return {'store_id':store_id,'version':0,'layout':{'schema_version':1,'store_id':store_id,
       'layout_version':1,'orientation':'调酒师视角','background_svg':'art/'+store_id+'.svg',
       'viewport':{'width':1100,'height':580},'seats':[],'neighbors':{},'groups':[],'bathrooms':[]}}

def draft(db,staff,store_id,payload,base_version):
    if isinstance(staff, HQLayoutActor):
        if staff.action != "hq.layout.edit" or staff.store_id != store_id:
            raise ControlError('总部地图操作人授权范围不匹配',403)
    else:
        require_hq(db,staff)
    if not db.execute('SELECT 1 FROM stores WHERE id=?',(store_id,)).fetchone():raise ControlError('门店不存在',404)
    old=current(db,store_id)
    if type(base_version)!=int or old['version']!=base_version:raise ControlError('布局已被其他人发布，请刷新后重新编辑',409)
    cfg=clean_layout(db,store_id,payload)
    rid='REV-'+uuid.uuid4().hex
    db.execute('''INSERT INTO bsv_layout_revisions(revision_id,store_id,status,base_version,payload_json,sha256,created_by,created_at)
         VALUES(?,?,?,?,?,?,?,?)''',(rid,store_id,'DRAFT',base_version,compact(cfg),digest(cfg),staff['id'],now()))
    details={'revision':rid,'base_version':base_version}
    if isinstance(staff, HQLayoutActor):
        details.update({'actor_tr_code':staff.tr_code,'request_id':staff.request_id})
    event(db,staff,'layout','SAVE_DRAFT',store_id,details)
    return {'ok':True,'revision_id':rid,'base_version':base_version}

def revisions(db,store_id):
    return [dict(r) for r in db.execute('''SELECT revision_id,status,base_version,version,sha256,created_at,published_at
          FROM bsv_layout_revisions WHERE store_id=? ORDER BY created_at DESC,revision_id DESC LIMIT 100''',(store_id,))]

def publish(db,staff,store_id,rid):
    require_hq(db,staff)
    rev=db.execute('SELECT * FROM bsv_layout_revisions WHERE revision_id=? AND store_id=?',(rid,store_id)).fetchone()
    if not rev or rev['status']!='DRAFT':raise ControlError('未找到可发布草稿',404)
    if db.execute("SELECT COUNT(*) FROM visits WHERE store_id=? AND status='OPEN'",(store_id,)).fetchone()[0]:
        raise ControlError('门店有未结束桌次，禁止发布地图',409)
    cfg=json.loads(rev['payload_json']);cfg=clean_layout(db,store_id,cfg)
    old=current(db,store_id)
    if old['version']!=rev['base_version']:raise ControlError('地图已有新版本，需重新生成草稿',409)
    # Existing group semantics cannot be silently mutated by the current POS engine.
    old_groups={g['id']:(g['primary_seat'],g['secondary_seat']) for g in old['layout'].get('groups',[])}
    new_groups={g['id']:(g['primary_seat'],g['secondary_seat']) for g in cfg.get('groups',[])}
    if any(new_groups.get(gid)!=relation for gid,relation in old_groups.items()):
        raise ControlError('已发布合分桌关联不得直接改写；须走专门的分组迁移流程',409)
    # bsv_layouts.apply_data rejects seat reuse, historical label collisions and unsafe removals.
    import bsv_layouts as layouts
    st=db.execute('SELECT * FROM stores WHERE id=?',(store_id,)).fetchone()
    cfg['layout_version']=old['version']+1
    layouts.apply_data(db,[(dict(st,store_id=store_id),cfg,digest(cfg),None)],force=True,activate=True)
    db.execute("UPDATE bsv_layout_revisions SET status='SUPERSEDED' WHERE store_id=? AND status='PUBLISHED'",(store_id,))
    db.execute('''UPDATE bsv_layout_revisions SET status='PUBLISHED',version=?,payload_json=?,sha256=?,published_by=?,published_at=?
           WHERE revision_id=?''',(cfg['layout_version'],compact(cfg),digest(cfg),staff['id'],now(),rid))
    db.execute('''INSERT INTO bsv_layout_ownership(store_id,origin,published_revision,published_at) VALUES(?,'HQ_PUBLISHED',?,?)
       ON CONFLICT(store_id) DO UPDATE SET origin='HQ_PUBLISHED',published_revision=excluded.published_revision,
       published_at=excluded.published_at''',(store_id,rid,now()))
    event(db,staff,'layout','PUBLISH',store_id,{'revision':rid,'version':cfg['layout_version']})
    return {'ok':True,'version':cfg['layout_version'],'revision_id':rid}

def rollback_to(db,staff,store_id,rid):
    require_hq(db,staff)
    old=db.execute('SELECT * FROM bsv_layout_revisions WHERE store_id=? AND revision_id=? AND status IN (\'SUPERSEDED\',\'PUBLISHED\')',(store_id,rid)).fetchone()
    if not old:raise ControlError('未找到已发布历史版本',404)
    cfg=json.loads(old['payload_json']);return draft(db,staff,store_id,cfg,current(db,store_id)['version'])

def default_svg(store_id):
    # Generic blank working surface for new stores. Never infer real-world geometry.
    title=store_id if ID_RE.fullmatch(store_id) else 'NEW'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="580" viewBox="0 0 1100 580">'
            f'<rect width="1100" height="580" fill="#f5f7f5"/><rect x="10" y="10" width="1080" height="560" fill="none" stroke="#bdc9cb" stroke-width="2"/>'
            f'<text x="550" y="295" font-family="sans-serif" font-size="23" fill="#9ca9ae" text-anchor="middle">{title} · 请上传现场图并核对坐标</text></svg>').encode()

def upload_image(db,staff,store_id,mime,encoded):
    require_hq(db,staff)
    if not db.execute('SELECT 1 FROM stores WHERE id=?',(store_id,)).fetchone():
        raise ControlError('门店不存在',404)
    if mime not in ('image/png','image/jpeg') or type(encoded)!=str or len(encoded)>2700000:
        raise ControlError('仅支持不超过约2MB的 PNG/JPEG 原始图纸')
    try:raw=base64.b64decode(encoded,validate=True)
    except Exception:raise ControlError('图片 base64 格式无效')
    if not 1000<=len(raw)<=2000000:raise ControlError('图片大小不在允许范围内')
    if mime=='image/png':
        if not raw.startswith(b'\x89PNG\r\n\x1a\n') or len(raw)<24 or raw[12:16]!=b'IHDR':
            raise ControlError('PNG 格式不合法')
        w,h=struct.unpack('>II',raw[16:24])
        if not (64<=w<=10000 and 64<=h<=10000):raise ControlError('PNG 分辨率不合法')
    else:
        if not (raw.startswith(b'\xff\xd8\xff') and raw.endswith(b'\xff\xd9')):
            raise ControlError('JPEG 格式不合法')
    aid='IMG-'+uuid.uuid4().hex
    db.execute('INSERT INTO bsv_layout_images VALUES(?,?,?,?,?,?,?)',
               (aid,store_id,mime,hashlib.sha256(raw).hexdigest(),raw,staff['id'],now()))
    event(db,staff,'layout','UPLOAD_IMAGE',store_id,{'asset_id':aid,'size':len(raw)})
    return {'ok':True,'asset_id':aid,'mime':mime,'size':len(raw)}

def image_by_id(db,store_id,asset_id):
    r=db.execute('SELECT mime,content FROM bsv_layout_images WHERE asset_id=? AND store_id=?',(asset_id,store_id)).fetchone()
    if not r:raise ControlError('未找到本店的图片资产',404)
    return r['mime'],r['content']

def layout_art(db,store_id):
    row=db.execute('SELECT config_json FROM store_layout_data WHERE store_id=?',(store_id,)).fetchone()
    if row:
        aid=json.loads(row['config_json']).get('background_asset_id')
        if aid:return image_by_id(db,store_id,aid)
    try: f=bsv_layouts.art_for_store(db,store_id)
    except bsv_layouts.LayoutError: return 'image/svg+xml',default_svg(store_id)
    return 'image/svg+xml', f.read_bytes() if hasattr(f,'read_bytes') else f
