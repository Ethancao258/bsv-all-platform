"""BSV ONE BSV1 多门店地图数据层（统一规范主键候选版）。

这里没有任何门店专用坐标、座位编号或邻接规则。
数据源：store_layouts/stores.json + 每店独立 JSON + 对应 SVG。
服务端将每店地图快照镜像到 SQLite；已有订单不会被地图更新覆盖。
"""
from __future__ import annotations
import hashlib,json,re,xml.etree.ElementTree as ET
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
MAP_DIR=ROOT/'store_layouts'
STORE_PATTERN=re.compile(r'^[A-Z0-9_-]{2,32}$')
SEAT_ID_PATTERN=re.compile(r'^[A-Z][A-Z0-9_-]{1,31}-SEAT-[0-9]{4}$')
GROUP_ID_PATTERN=re.compile(r'^[A-Z][A-Z0-9_-]{1,31}-GROUP-[0-9]{4}$')
RESTROOM_ID_PATTERN=re.compile(r'^[A-Z][A-Z0-9_-]{1,31}-RESTROOM-[0-9]{4}$')
VALID_TYPES={'SOFA','ROUND','BAR','WINDOW','BOOTH','TEMP','TABLE','OTHER'}
class LayoutError(ValueError):pass

def _read_json(path):
    try:return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception as e:raise LayoutError(f'无法读取地图配置 {path.name}: {e}') from e

def registry():
    records=_read_json(MAP_DIR/'stores.json')
    if not isinstance(records,list) or not records:raise LayoutError('stores.json 必须为非空数组')
    seen=set()
    for st in records:
        if not isinstance(st,dict):raise LayoutError('门店必须为对象')
        sid=st.get('store_id')
        if not isinstance(sid,str) or not STORE_PATTERN.fullmatch(sid) or sid in seen:raise LayoutError('门店代码无效或重复')
        seen.add(sid)
        if not all(isinstance(st.get(k),str) and st[k].strip() for k in ('name','district','business_type')):raise LayoutError(sid+' 门店信息不全')
        if type(st.get('design_max_guests'))!=int or st['design_max_guests']<0:raise LayoutError(sid+' 设计载客量无效')
        if st.get('layout_file') not in (None,sid+'.json'):raise LayoutError(sid+' 地图文件必须命名为 '+sid+'.json')
        if 'local_demo_accounts' in st:raise LayoutError(sid+' 正式底座禁止内置演示账号')
    return records

def _svg_file(store_id,file_name):
    if file_name != 'art/'+store_id+'.svg':raise LayoutError(store_id+' 底图文件命名不符合门店隔离规则')
    f=MAP_DIR/file_name
    if not f.is_file():raise LayoutError(store_id+' 底图缺失')
    raw=f.read_bytes()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise LayoutError(store_id+' SVG 禁止实体声明')
    try:root=ET.fromstring(raw)
    except Exception as e:raise LayoutError(store_id+' SVG 不能解析') from e
    if root.tag.split('}')[-1]!='svg':raise LayoutError(store_id+' 不是 SVG')
    for e in root.iter():
        if e.tag.split('}')[-1] in ('script','foreignObject','iframe','image','use','a'):
            raise LayoutError(store_id+' SVG 含禁止元素 '+e.tag)
        if any(k.split('}')[-1].lower().startswith('on') or 'href' in k.lower() for k in e.attrib):
            raise LayoutError(store_id+' SVG 包含外部引用或事件属性')
    return f,hashlib.sha256(raw).hexdigest()

def load_layout(store_id):
    if not STORE_PATTERN.fullmatch(store_id):raise LayoutError('无效门店代码')
    cfg=_read_json(MAP_DIR/(store_id+'.json'))
    if not isinstance(cfg,dict) or cfg.get('store_id')!=store_id:raise LayoutError(store_id+' 地图主键不匹配')
    if cfg.get('schema_version')!=1 or type(cfg.get('layout_version'))!=int or cfg['layout_version']<1:
        raise LayoutError(store_id+' 地图版本格式错误')
    art,art_sha=_svg_file(store_id,cfg.get('background_svg'))
    if cfg.get('viewport')!={'width':1100,'height':580}:raise LayoutError(store_id+' 当前视口统一为1100×580')
    seats=cfg.get('seats')
    if not isinstance(seats,list) or not seats or len(seats)>1000:raise LayoutError(store_id+' 座位必须为1—1000条')
    ids=set();labels=set();orders=set()
    for s in seats:
        if not isinstance(s,dict):raise LayoutError(store_id+' 座位格式错误')
        sid=s.get('id');label=s.get('label');order=s.get('order')
        if (not isinstance(sid,str) or not SEAT_ID_PATTERN.fullmatch(sid) or sid in ids
                or not sid.startswith(store_id+'-') or not sid.startswith(store_id+'-SEAT-')):
            raise LayoutError(store_id+' 座位ID不符合门店前缀规范或重复')
        if not isinstance(label,str) or not label.strip() or len(label)>32 or label in labels:raise LayoutError(store_id+' 显示座位号无效或重复')
        if s.get('kind') not in VALID_TYPES:raise LayoutError(store_id+' 座位类型未授权')
        if type(order)!=int or order in orders:raise LayoutError(store_id+' 排序号重复')
        if any(type(s.get(axis)) not in (int,float) or not 1<=s[axis]<=99 for axis in ('x','y')):raise LayoutError(store_id+' 座位坐标必须是1-99百分比')
        if s.get('capacity') is not None and (type(s['capacity'])!=int or not 1<=s['capacity']<=100):raise LayoutError(store_id+' 载客上限无效')
        if type(s.get('is_secondary'))!=bool:raise LayoutError(store_id+' is_secondary应为布尔值')
        ids.add(sid);labels.add(label);orders.add(order)
    neighbors=cfg.get('neighbors')
    if not isinstance(neighbors,dict) or set(neighbors)!=ids:raise LayoutError(store_id+' 邻接表必须覆盖全部座位')
    for sid,link in neighbors.items():
        if not isinstance(link,dict) or any(link.get(k) is not None and (link[k] not in ids or link[k]==sid) for k in ('left','right')):
            raise LayoutError(store_id+' 邻接目标无效 '+sid)
    groups=cfg.get('groups',[]);group_ids=set()
    for grp in groups:
        if (not isinstance(grp,dict) or not isinstance(grp.get('id'),str)
                or not GROUP_ID_PATTERN.fullmatch(grp['id']) or grp['id'] in group_ids
                or not grp['id'].startswith(store_id+'-GROUP-')):
            raise LayoutError(store_id+' 合分桌组ID无效')
        if grp.get('primary_seat') not in ids or grp.get('secondary_seat') not in ids or grp['primary_seat']==grp['secondary_seat']:
            raise LayoutError(store_id+' 合分桌引用无效')
        if grp.get('default_mode') not in ('SPLIT','MERGED'):raise LayoutError(store_id+' 合桌模式无效')
        group_ids.add(grp['id'])
    for s in seats:
        if s.get('group_id') is not None and s['group_id'] not in group_ids:raise LayoutError(store_id+' 座位关联不存在的分组')
    for grp in groups:
        linked={s['id'] for s in seats if s.get('group_id')==grp['id']}
        if linked!={grp['primary_seat'],grp['secondary_seat']}:raise LayoutError(store_id+' 合分桌组成员与引用不一致：'+grp['id'])
    baths=cfg.get('bathrooms',[])
    for b in baths:
        if not isinstance(b,dict) or not isinstance(b.get('id'),str) or not RESTROOM_ID_PATTERN.fullmatch(b['id']) or not b['id'].startswith(store_id+'-RESTROOM-'):
            raise LayoutError(store_id+' 卫生间标识错误')
        pin=b.get('pin',{})
        if any(type(pin.get(k)) not in (int,float) or not 0<=pin[k]<=100 for k in ('x','y')):
            raise LayoutError(store_id+' 卫生间坐标错误')
        if type(b.get('interval_seconds'))!=int or b['interval_seconds']<60:raise LayoutError(store_id+' 清洁周期无效')
    digest=hashlib.sha256(json.dumps(cfg,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()+art_sha.encode()).hexdigest()
    return cfg,digest,art

def all_configs():
    result=[]
    global_seat_ids=set()
    global_group_ids=set()
    for s in registry():
        cfg=None;digest=None;art=None
        if s.get('layout_file'):
            cfg,digest,art=load_layout(s['store_id'])
            seat_ids={x['id'] for x in cfg['seats']}
            group_ids={x['id'] for x in cfg.get('groups',[])}
            if global_seat_ids & seat_ids or global_group_ids & group_ids or seat_ids & group_ids:
                raise LayoutError('跨门店实体ID冲突：'+s['store_id'])
            global_seat_ids.update(seat_ids)
            global_group_ids.update(group_ids)
        result.append((s,cfg,digest,art))
    return result

def apply_data(db,configs,force=False,activate=False):
    """在调用方的事务中增量导入。禁止改换已有座位主键；旧订单原样保留。"""
    db.execute('''CREATE TABLE IF NOT EXISTS store_layout_data(
       store_id TEXT PRIMARY KEY REFERENCES stores(id),layout_version INTEGER NOT NULL,
       content_sha TEXT NOT NULL,config_json TEXT NOT NULL,applied_at TEXT NOT NULL)''')
    for store,cfg,digest,_ in configs:
        code=store['store_id']
        # Published HQ maps + store metadata are authoritative. Never overwrite on restart.
        if not force:
            try:
                if db.execute("SELECT 1 FROM bsv_layout_ownership WHERE store_id=? AND origin='HQ_PUBLISHED'",(code,)).fetchone():
                    continue
            except Exception:
                pass  # legacy schema only
        db.execute('INSERT OR IGNORE INTO stores(id,name,design_max_guests,orientation,created_at) VALUES(?,?,?,?,?)',
                   (code,store['name'],store['design_max_guests'],'以吧台内调酒师为左右基准',datetime.now(timezone.utc).isoformat()))
        db.execute('UPDATE stores SET name=?,district=?,business_type=?,design_max_guests=?,layout_ready=? WHERE id=?',
                   (store['name'],store['district'],store['business_type'],store['design_max_guests'],int(cfg is not None and activate),code))
        if cfg is None:continue
        old=db.execute('SELECT * FROM store_layout_data WHERE store_id=?',(code,)).fetchone()
        if old and old['content_sha']==digest and not force:continue
        # One store cannot borrow another store’s physical IDs or group IDs.
        rows=cfg['seats'];ids={r['id'] for r in rows}
        for s in rows:
            existing=db.execute('SELECT store_id FROM seats WHERE id=?',(s['id'],)).fetchone()
            if existing and existing['store_id']!=code:raise LayoutError('跨店座位主键冲突：'+s['id'])
        prior=db.execute('SELECT id FROM seats WHERE store_id=?',(code,)).fetchall()
        removed=[r['id'] for r in prior if r['id'] not in ids]
        for rid in removed:
            if db.execute("SELECT 1 FROM visits WHERE seat_id=? AND status='OPEN'",(rid,)).fetchone():
                raise LayoutError('仍有客人的座位不可从地图移除：'+rid)
            db.execute('UPDATE seats SET layout_enabled=0 WHERE id=?',(rid,))
        for grp in cfg.get('groups',[]):
            db.execute('INSERT OR IGNORE INTO table_groups(id,store_id,primary_seat,secondary_seat,mode) VALUES(?,?,?,?,?)',
                       (grp['id'],code,grp['primary_seat'],grp['secondary_seat'],grp['default_mode']))
            old_grp=db.execute('SELECT store_id FROM table_groups WHERE id=?',(grp['id'],)).fetchone()
            if old_grp['store_id']!=code:raise LayoutError('跨店合分桌组冲突')
        for s in rows:
            if s.get('capacity') is not None:
                crowded=db.execute("SELECT MAX(guests) FROM visits WHERE seat_id=? AND status='OPEN'",(s['id'],)).fetchone()[0]
                if crowded is not None and crowded>s['capacity']:
                    raise LayoutError('在店客人人数超过新容量，请先调整桌次：'+s['label'])
            # 不允许新座位重用历史座位的显示名，防止 SQLite 唯一约束
            # 导致 INSERT OR IGNORE 静默失败、而地图同步状态却显示完成。
            occupied=db.execute('SELECT id FROM seats WHERE store_id=? AND label=?',(code,s['label'])).fetchone()
            if occupied and occupied['id']!=s['id']:
                raise LayoutError('显示座位号与其他（含历史）座位冲突：'+s['label'])
            params=(s['label'],s['kind'],s['x'],s['y'],s['order'],s.get('group_id'),int(s['is_secondary']),s.get('capacity'))
            db.execute('''INSERT OR IGNORE INTO seats(id,store_id,label,seat_type,x,y,display_order,group_id,is_secondary,seat_capacity,layout_enabled)
                       VALUES(?,?,?,?,?,?,?,?,?,?,1)''',
                       (s['id'],code,s['label'],s['kind'],s['x'],s['y'],s['order'],s.get('group_id'),int(s['is_secondary']),s.get('capacity')))
            updated=db.execute('''UPDATE seats SET label=?,seat_type=?,x=?,y=?,display_order=?,group_id=?,is_secondary=?,seat_capacity=?,layout_enabled=1
                       WHERE id=? AND store_id=?''',params+(s['id'],code))
            if updated.rowcount!=1:
                raise LayoutError('座位主键无法导入，停止发布不完整地图：'+s['id'])
            db.execute("INSERT OR IGNORE INTO seat_cleaning(seat_id,store_id,state) VALUES(?,?,'CLEAN')",(s['id'],code))
        for bath in cfg.get('bathrooms',[]):
            db.execute('INSERT OR IGNORE INTO bathrooms(id,store_id,label,interval_seconds) VALUES(?,?,?,?)',
                       (bath['id'],code,bath['label'],bath['interval_seconds']))
            db.execute('UPDATE bathrooms SET label=?,interval_seconds=? WHERE id=? AND store_id=?',
                       (bath['label'],bath['interval_seconds'],bath['id'],code))
        db.execute('''INSERT INTO store_layout_data(store_id,layout_version,content_sha,config_json,applied_at)
            VALUES(?,?,?,?,?) ON CONFLICT(store_id) DO UPDATE SET layout_version=excluded.layout_version,
              content_sha=excluded.content_sha,config_json=excluded.config_json,applied_at=excluded.applied_at''',
            (code,max(cfg['layout_version'],int(old['layout_version'])+1 if old else 1),digest,json.dumps(cfg,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))

def runtime_layout(db,store_id):
    row=db.execute('SELECT layout_version,config_json FROM store_layout_data WHERE store_id=?',(store_id,)).fetchone()
    if row is None:return None
    cfg=json.loads(row['config_json'])
    return {'version':row['layout_version'],'viewport':cfg['viewport'],'orientation':cfg['orientation'],
            'neighbors':cfg['neighbors'],'bathroom_pins':{x['id']:x['pin'] for x in cfg.get('bathrooms',[])},
            'background_url':f'/api/store-layout-art?store_id={store_id}&v={row["layout_version"]}'}

def art_for_store(db,store_id):
    row=db.execute('SELECT config_json FROM store_layout_data WHERE store_id=?',(store_id,)).fetchone()
    if not row:raise LayoutError('此店尚未导入地图')
    cfg=json.loads(row['config_json'])
    try:
        art,_=_svg_file(store_id,cfg['background_svg'])
        return art
    except LayoutError:
        # New stores have no physical SVG yet; use a generic clearly-labeled canvas.
        import bsv_one
        return bsv_one.default_svg(store_id)
