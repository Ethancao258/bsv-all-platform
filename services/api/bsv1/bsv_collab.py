"""BSV multi-device scheduling and production task collaboration.
Server is authoritative: no client-generated assignments, locks or amounts.
"""
from __future__ import annotations
import json,re,sqlite3,time,uuid
import os
from datetime import datetime,timezone
from pathlib import Path

ACTIVE_SECONDS=75
LOCK_SECONDS=90
CLAIM_SECONDS=180

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def uid():return uuid.uuid4().hex
def schema(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS staff_presence (
  staff_id TEXT NOT NULL,store_id TEXT NOT NULL,last_seen_at INTEGER NOT NULL,
  PRIMARY KEY(staff_id,store_id));
 CREATE INDEX IF NOT EXISTS ix_presence_store ON staff_presence(store_id,last_seen_at);
 CREATE TABLE IF NOT EXISTS seat_edit_locks (
  seat_id TEXT PRIMARY KEY,store_id TEXT NOT NULL,staff_id TEXT NOT NULL,expires_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS production_tasks (
  line_id TEXT PRIMARY KEY,store_id TEXT NOT NULL,visit_id TEXT NOT NULL,
  assigned_staff_id TEXT,claimed_by TEXT,claim_until INTEGER,
  state TEXT NOT NULL DEFAULT 'PENDING' CHECK(state IN('PENDING','CLAIMED','SERVED','CANCELLED')),
  assigned_at TEXT NOT NULL,claimed_at TEXT);
 CREATE INDEX IF NOT EXISTS ix_tasks_store ON production_tasks(store_id,state,assigned_staff_id);
 CREATE TABLE IF NOT EXISTS production_finishes (
   line_id TEXT PRIMARY KEY, store_id TEXT NOT NULL,visit_id TEXT NOT NULL,
   maker_staff_id TEXT NOT NULL,finished_at TEXT NOT NULL,
   FOREIGN KEY(line_id) REFERENCES production_tasks(line_id));
 CREATE INDEX IF NOT EXISTS ix_production_finishes_store ON production_finishes(store_id,finished_at);
 CREATE TABLE IF NOT EXISTS production_deliveries (
   line_id TEXT PRIMARY KEY, store_id TEXT NOT NULL,visit_id TEXT NOT NULL,
   deliverer_staff_id TEXT NOT NULL,delivered_at TEXT NOT NULL,
   FOREIGN KEY(line_id) REFERENCES production_tasks(line_id));
 CREATE INDEX IF NOT EXISTS ix_production_deliveries_store ON production_deliveries(store_id,delivered_at);
 ''')

def initials(s):
 """GBK Hanzi initials with known pinyin ambiguities; supports prefix search with CJK fallback.
 Not a full phonetic dictionary and user aliases can be added to PINYIN_ALIAS.
 """
 borders=[-20319,-20284,-19775,-19218,-18711,-18527,-18240,-17923,-17418,-16475,-16213,-15641,-15166,-14923,-14915,-14631,-14150,-14091,-13319,-12839,-12557,-11848,-11056,-10247,-10232,-10000]
 letters='abcdefghjklmnopqrstwxyz' # GB2312 has no i,u,v
 out=[]
 for c in s:
  if c.isascii() and c.isalnum():out.append(c.lower());continue
  try:
   raw=c.encode('gbk')
   if len(raw)!=2:continue
   code=raw[0]*256+raw[1]-65536
   for i in range(len(letters)):
    if borders[i]<=code<borders[i+1]:out.append(letters[i]);break
  except (UnicodeEncodeError,ValueError):pass
 return ''.join(out)

def heartbeat(db,staff_id,store_id,seat_id=None):
 t=int(time.time())
 db.execute('''INSERT INTO staff_presence(staff_id,store_id,last_seen_at) VALUES(?,?,?)
   ON CONFLICT(staff_id,store_id) DO UPDATE SET last_seen_at=excluded.last_seen_at''',(staff_id,store_id,t))
 if seat_id:
  db.execute('UPDATE seat_edit_locks SET expires_at=? WHERE seat_id=? AND store_id=? AND staff_id=?',
             (t+LOCK_SECONDS,seat_id,store_id,staff_id))
 db.execute('''UPDATE production_tasks SET claim_until=?
     WHERE store_id=? AND claimed_by=? AND state='CLAIMED' ''',
     (t+CLAIM_SECONDS,store_id,staff_id))

def live_staff(db,store_id):
 return [r['staff_id'] for r in db.execute('''SELECT p.staff_id FROM staff_presence p
   JOIN staff s ON s.id=p.staff_id WHERE p.store_id=? AND p.last_seen_at>=? AND s.enabled=1
   ORDER BY p.staff_id''',(store_id,int(time.time())-ACTIVE_SECONDS))]

def claim_seat(db,seat_id,store_id,staff_id):
 t=int(time.time())
 r=db.execute('SELECT staff_id,expires_at FROM seat_edit_locks WHERE seat_id=?',(seat_id,)).fetchone()
 if r and r['expires_at']>t and r['staff_id']!=staff_id:
  other=db.execute('SELECT staff_code FROM staff WHERE id=?',(r['staff_id'],)).fetchone()
  return {'ok':False,'editor':other['staff_code'] if other else '其他员工','remaining_seconds':r['expires_at']-t}
 db.execute('''INSERT INTO seat_edit_locks(seat_id,store_id,staff_id,expires_at) VALUES(?,?,?,?)
  ON CONFLICT(seat_id) DO UPDATE SET store_id=excluded.store_id,staff_id=excluded.staff_id,expires_at=excluded.expires_at''',
  (seat_id,store_id,staff_id,t+LOCK_SECONDS))
 return {'ok':True,'expires_at':t+LOCK_SECONDS}

def assert_editable(db,visit_id,store_id,staff_id):
 """Enforce a server-side edit lease even when the caller skips the map UI.

 Any order mutation implicitly claims an unlocked table. Prevents two devices
 bypassing claim via the active-visits panel or a direct endpoint call.
 """
 v=db.execute('SELECT seat_id FROM visits WHERE id=? AND store_id=?',(visit_id,store_id)).fetchone()
 if not v:return
 result=claim_seat(db,v['seat_id'],store_id,staff_id)
 if not result['ok']:
  raise ValueError('该桌正在由其他员工点单，请稍候或联系该员工')

def rebalance(db,store_id):
 live=live_staff(db,store_id)
 # Claimed tasks whose lease expired return to pending. Never auto mark served.
 t=int(time.time())
 # SAFETY: do not automatically reassign claimed tasks based on a phone/browser
 # timeout. A bartender may still be preparing the drink after losing connection.
 # Reassignment of a claimed task requires an explicit manager confirmation.
 # Pending tasks rebalance as employees join or leave.
 tasks=db.execute('''SELECT line_id,claimed_by FROM production_tasks WHERE store_id=? AND state='PENDING'
  ORDER BY assigned_at,line_id''',(store_id,)).fetchall()
 if not live:
  db.execute("UPDATE production_tasks SET assigned_staff_id=NULL WHERE store_id=? AND state='PENDING'",(store_id,))
  return
 loads={s:db.execute("SELECT COUNT(*) FROM production_tasks t LEFT JOIN production_finishes f ON f.line_id=t.line_id WHERE t.store_id=? AND t.state='CLAIMED' AND t.claimed_by=? AND f.line_id IS NULL",(store_id,s)).fetchone()[0] for s in live}
 for task in tasks:
  who=min(live,key=lambda s:(loads[s],s))
  db.execute("UPDATE production_tasks SET assigned_staff_id=? WHERE line_id=?",(who,task['line_id']))
  loads[who]+=1

def add_tasks(db,line_ids,store_id,visit_id):
 at=now()
 for lid in line_ids:
  db.execute('''INSERT OR IGNORE INTO production_tasks
    (line_id,store_id,visit_id,state,assigned_at) VALUES(?,?,?,'PENDING',?)''',
    (lid,store_id,visit_id,at))
 rebalance(db,store_id)

def tasks_for_store(db,store_id):
 rows=db.execute('''SELECT t.*,s.staff_code AS assigned_code,c.staff_code AS claimed_code,
  l.product_id,l.product_name_snapshot,l.quantity,l.created_at,l.status AS line_status,
  CASE WHEN f.line_id IS NOT NULL THEN 'READY_TO_SERVE' ELSE t.state END AS workflow_state,
  f.maker_staff_id,f.finished_at,m.staff_code AS maker_code,
  v.seat_id,seat.label AS seat_label
  FROM production_tasks t JOIN order_lines l ON l.id=t.line_id
  JOIN visits v ON v.id=t.visit_id JOIN seats seat ON seat.id=v.seat_id
  LEFT JOIN staff s ON s.id=t.assigned_staff_id LEFT JOIN staff c ON c.id=t.claimed_by
  LEFT JOIN production_finishes f ON f.line_id=t.line_id LEFT JOIN staff m ON m.id=f.maker_staff_id
  WHERE t.store_id=? AND t.state<>'CANCELLED' AND l.status='PENDING'
  ORDER BY l.created_at,l.id''',(store_id,)).fetchall()
 return [dict(r) for r in rows]

def _media_file(product_id, filename):
 """Resolve a private product image, preferring durable media outside releases.

    BSV_PRODUCT_MEDIA_ROOT is the persistent root on Lighthouse. The packaged
    legacy root remains a read-only compatibility fallback for existing assets.
    """
 if not isinstance(filename,str) or not filename.strip():return None
 name=Path(filename.strip()).name
 if name!=filename.strip() or name in ('.','..') or Path(name).suffix.lower() not in ('.jpg','.jpeg','.png','.webp'):
  return None
 fixed=product_id if isinstance(product_id,str) and re.fullmatch(r'C\d{6}',product_id) else ''
 legacy_root=Path(__file__).resolve().parent/'resources'/'product_images'
 configured=os.environ.get('BSV_PRODUCT_MEDIA_ROOT','/var/lib/bsv-all/media/products').strip()
 persistent_root=Path(configured).expanduser() if configured else Path('/var/lib/bsv-all/media/products')
 candidates=[persistent_root/fixed/name,legacy_root/fixed/name,legacy_root/name]
 for file in candidates:
  try:
   root=file.parents[1] if file.parent.name==fixed else file.parent
   if root.is_symlink() or file.parent.is_symlink() or file.is_symlink() or not file.is_file():continue
   resolved=file.resolve(strict=True)
   if root.resolve() not in resolved.parents:continue
   if resolved.stat().st_size<=12*1024*1024:return resolved
  except (OSError,RuntimeError):
   continue
 return None

def recipe(db,store_id,product_id):
 # The authenticated task/store is validated by the API; the commodity ID is global.
 if not isinstance(product_id,str) or not re.fullmatch(r'C\d{6}',product_id):
  return {'name':'未关联成品主数据','fields':{},'photos':{},'warning':'当前商品缺少有效制作教程'}
 pid=product_id
 row=db.execute('SELECT display_name,fields_json FROM bsv_v9_record WHERE fixed_id=?',(pid,)).fetchone()
 if not row:return {'name':'资料已变更','fields':{},'photos':{},'warning':'该商品在最新 V9 中不存在，请联系管理员核实'}
 f=json.loads(row['fields_json'])
 keys=['配方文字','完整制作步骤','寻酒指引','杯具','制作时长（秒）','过敏原','制作要求','单品配方',
  '操作方式','操作力度','风味标签','风味描述','产品故事','补充制作说明','门店操作备注','配方版本','销售系列']
 photos={}
 for kind,key in [('materials','配方图文件名｜首次确认'),('review','配方图文件名｜二次复核'),('final','成品图文件名')]:
  name=f.get(key)
  photos[kind]={'filename':str(name or ''),'available':bool(_media_file(product_id,name))}
 operations=[]
 for record in db.execute("SELECT fixed_id,source_row,fields_json FROM bsv_v9_record WHERE page='R_配方耗用' ORDER BY source_row"):
  item=json.loads(record['fields_json'])
  if str(item.get('出品关联ID') or '').strip()==pid:
   material_id=str(item.get('投入物料ID') or '').strip()
   material=db.execute("SELECT fixed_id,display_name,fields_json,page FROM bsv_v9_record WHERE fixed_id=? AND page IN ('M_采购纯饮','P_预调半成品')",
                       (material_id,)).fetchone() if material_id else None
   material_fields=json.loads(material['fields_json']) if material else {}
   if material and material['page']=='M_采购纯饮':
    material_fields={k:v for k,v in material_fields.items()
     if not any(word in str(k).casefold() for word in ('采购价','成本','供应商','进货价','单价','价格','金额'))}
   operations.append({'record_id':record['fixed_id'],'source_row':record['source_row'],
    'fields':item,'material_id':material_id or None,
    'material_link_status':'LINKED_BY_ID' if material else 'UNRESOLVED_MATERIAL_ID' if material_id else 'NO_MATERIAL_ID',
    'material':({'id':material['fixed_id'],'name':material['display_name'],'fields':material_fields} if material else None)})
 source=db.execute('SELECT source_sha,imported_at FROM bsv_v9_sync WHERE one=1').fetchone()
 return {'name':row['display_name'],'fixed_id':pid,
  'fields':{k:f[k] for k in keys if f.get(k) not in ('',None)},'photos':photos,
  'recipe_operations':operations,
  'source':{'sha256':source['source_sha'],'imported_at':source['imported_at']} if source else None,
  'warning':'仅供制作资料查询，不代表获准销售。请以核准配方为准；过敏原或原料资料未核实前必须人工复核。'}
