"""Clearly isolated local TEST backend. Never deployed as real central ledger."""
from __future__ import annotations
import hashlib, json, sqlite3, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException
from .domain import unique_codes

from services.api.bsv1 import bsv_layouts

DEMO_STORES = [{"store_id":"DEMO-WH","name_zh":"演示中央仓（非正式网点）","kind":"warehouse"}]
DEMO_STORES.extend(
    {"store_id": store["store_id"], "name_zh": store["name"],
     "kind": "partner" if store["store_id"] == "BSVF" else "store"}
    for store in bsv_layouts.registry()
)
DEMO_ITEMS = [
    {"item_id":"DEMO-P001","sku":"DEMO-P-01","name_zh":"演示预调酒450mL（虚拟）","unit":"pcs","package_size":"1","approved":True,"track_package":True},
    {"item_id":"DEMO-M001","sku":"DEMO-M-01","name_zh":"演示整瓶酒（虚拟）","unit":"pcs","package_size":"1","approved":True,"track_package":True},
]
DEMO_ACTORS = [
    {"employee_id":"DEMO-E01","name":"演示总部配送","department_id":"DEMO-DEPT-SUPPLY","stores":["DEMO-WH","BSVM","BSVS","BSVT","BSVF"],"roles":["dispatch","receive","inspect","admin"]},
    {"employee_id":"DEMO-E02","name":"演示顺义收货","department_id":"DEMO-DEPT-BSVS","stores":["BSVS"],"roles":["receive","inspect"]},
    {"employee_id":"DEMO-E03","department_id":"DEMO-DEPT-AUDIT","stores":["BSVS"],
     "roles":["inspect_independent","review_independent"]},
    {"employee_id":"DEMO-E04","department_id":"DEMO-DEPT-REVIEW","stores":["BSVS"],
     "roles":["review_independent","inspect_independent"]},
]

def utc(): return datetime.now(timezone.utc).isoformat()

def fail(code,detail):raise HTTPException(code,detail)

class DemoCentral:
    def __init__(self,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.parent.chmod(0o700)
        self.path=path
        self.lock=threading.RLock()
        with self._conn() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS shipments(id TEXT PRIMARY KEY,src TEXT,dest TEXT,state TEXT,version INTEGER,created_by TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS packages(code TEXT PRIMARY KEY, shipment_id TEXT,item_id TEXT,state TEXT,FOREIGN KEY(shipment_id) REFERENCES shipments(id));
            CREATE TABLE IF NOT EXISTS balances(location TEXT,item_id TEXT,qty INTEGER NOT NULL CHECK(qty>=0), PRIMARY KEY(location,item_id));
            CREATE TABLE IF NOT EXISTS movements(id TEXT PRIMARY KEY,shipment_id TEXT,item_id TEXT,src TEXT,dest TEXT,qty INTEGER,occurred_at TEXT,actor_id TEXT);
            CREATE TABLE IF NOT EXISTS idempotency(request_id TEXT PRIMARY KEY, fingerprint TEXT,response TEXT);
            CREATE TABLE IF NOT EXISTS action_audit(id TEXT PRIMARY KEY, request_id TEXT,shipment_id TEXT,actor_id TEXT,operation TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS counts(id TEXT PRIMARY KEY,store_id TEXT,item_id TEXT,observer TEXT,full_packages INTEGER,opened_count INTEGER,opened_percent INTEGER,method TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS inspections(id TEXT PRIMARY KEY,store_id TEXT, inspector TEXT,department TEXT,subject_department TEXT,
                  subject_employee TEXT,results TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS inspection_kind(id TEXT PRIMARY KEY REFERENCES inspections(id),kind TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS inspection_reviews(id TEXT PRIMARY KEY REFERENCES inspections(id),
                reviewer TEXT NOT NULL, decision TEXT NOT NULL, created_at TEXT NOT NULL);
            ''')
            # Demo-only forward migration; never alters company production databases.
            names={row[1] for row in c.execute('PRAGMA table_info(movements)')}
            if 'actor_id' not in names:
                c.execute('ALTER TABLE movements ADD COLUMN actor_id TEXT')
            if 'batch_id' not in {row[1] for row in c.execute('PRAGMA table_info(packages)')}:
                c.execute("ALTER TABLE packages ADD COLUMN batch_id TEXT")
                c.execute("UPDATE packages SET batch_id='DEMO-BATCH-' || shipment_id || '-' || item_id")
            for item,qty in (("DEMO-P001",40),("DEMO-M001",30)):
                c.execute("INSERT OR IGNORE INTO balances VALUES ('DEMO-WH',?,?)",(item,qty))
        self.path.chmod(0o600)
    def _conn(self):
        c=sqlite3.connect(self.path,timeout=20,isolation_level=None)
        c.execute("PRAGMA foreign_keys=ON")
        c.row_factory=sqlite3.Row
        return c
    @staticmethod
    def actor(actor_id):
        for a in DEMO_ACTORS:
            if a['employee_id']==actor_id:return a
        fail(401,"未知演示员工。生产必须使用公司统一人事认证")
    @staticmethod
    def authorize(actor,role,store=None):
        if role not in actor['roles']:fail(403,"没有该操作权限")
        if store and store not in actor['stores']:fail(403,"员工没有目标网点权限")
    @staticmethod
    def _check_version(c,sid,expected_version):
        r=c.execute('SELECT * FROM shipments WHERE id=?',(sid,)).fetchone()
        if not r:fail(404,'配送单不存在')
        if expected_version is None or int(expected_version)!=r['version']:
            fail(409,f"配送单版本冲突；当前版本为 {r['version']}")
        return dict(r)
    @staticmethod
    def _idem(c,rid,fp):
        old=c.execute('SELECT * FROM idempotency WHERE request_id=?',(rid,)).fetchone()
        if not old:return None
        if old['fingerprint']!=fp:fail(409,'request_id 重用但业务参数不同')
        return json.loads(old['response'])
    @staticmethod
    def _finish(c,rid,fp,r):
        c.execute('INSERT INTO idempotency VALUES (?,?,?)',(rid,fp,json.dumps(r,ensure_ascii=False)))
        return r
    @staticmethod
    def _move(c,sid,item,src,dest,qty,actor_id):
        if qty<=0:fail(422,'数量必须大于0')
        row=c.execute('SELECT qty FROM balances WHERE location=? AND item_id=?',(src,item)).fetchone()
        if not row or row[0]<qty:fail(409,f'库存不足：{src}/{item}')
        c.execute('UPDATE balances SET qty=qty-? WHERE location=? AND item_id=?',(qty,src,item))
        c.execute('INSERT INTO balances(location,item_id,qty) VALUES (?,?,?) ON CONFLICT(location,item_id) DO UPDATE SET qty=qty+excluded.qty',(dest,item,qty))
        c.execute('INSERT INTO movements VALUES (?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),sid,item,src,dest,qty,utc(),actor_id))
    def _pack(self,c,sid):
        return [dict(x) for x in c.execute('SELECT code,item_id,state,batch_id FROM packages WHERE shipment_id=? ORDER BY code',(sid,))]
    def view(self,sid,actor):
        with self.lock,self._conn() as c:
            row=c.execute('SELECT * FROM shipments WHERE id=?',(sid,)).fetchone()
            if not row:fail(404,'配送单不存在')
            s=dict(row)
            if s['src'] not in actor['stores'] and s['dest'] not in actor['stores']:fail(403,'无该单据权限')
            packs=self._pack(c,sid)
            s['packages']=packs
            s['expected_count']=len(packs)
            s['received_count']=len([p for p in packs if p['state'] in ('ACCEPTED','HOLD')])
            return s
    def list(self,actor,store_id=None):
        if store_id and store_id not in actor['stores']:fail(403,'无该网点权限')
        with self.lock,self._conn() as c:
            r=[dict(x) for x in c.execute('SELECT * FROM shipments ORDER BY created_at DESC LIMIT 100')]
        return [x for x in r if (x['src'] in actor['stores'] or x['dest'] in actor['stores']) and
                (not store_id or x['src']==store_id or x['dest']==store_id)]
    def inventory(self,actor,store_id):
        if store_id and store_id not in actor['stores']:fail(403,'无该网点权限')
        with self.lock,self._conn() as c:
            r=[dict(x) for x in c.execute('SELECT location,item_id,qty FROM balances ORDER BY location,item_id')]
            shipments={x['id']:dict(x) for x in c.execute('SELECT id,src,dest FROM shipments')}
        def visible(x):
            loc=x['location']
            if loc.startswith('IN_TRANSIT:'):
                shipment=shipments.get(loc.split(':',1)[1])
                return bool(shipment) and (shipment['src'] in actor['stores'] or shipment['dest'] in actor['stores']) and (not store_id or shipment['src']==store_id or shipment['dest']==store_id)
            if loc.startswith('QUARANTINE:'):
                target=loc.split(':',1)[1]
                return target in actor['stores'] and (not store_id or target==store_id)
            return loc in actor['stores'] and (not store_id or loc==store_id)
        return [x for x in r if visible(x)]
    def mutate(self,op,sid,payload,actor):
        rid=payload.get('request_id')
        try:uuid.UUID(str(rid))
        except (ValueError,TypeError):fail(422,'request_id 必须为 UUID')
        fp=hashlib.sha256(json.dumps({'op':op,'sid':sid,'payload':{k:v for k,v in payload.items() if k!='request_id'},'actor':actor['employee_id']},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.lock,self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                if op=='create':
                    self.authorize(actor,'dispatch',payload.get('source_store_id'))
                else:
                    shipment=c.execute('SELECT src,dest FROM shipments WHERE id=?',(sid,)).fetchone()
                    if shipment is None:fail(404,'配送单不存在')
                    self.authorize(actor,'receive' if op=='receive' else 'dispatch',
                                   shipment['dest'] if op=='receive' else shipment['src'])
                old=self._idem(c,rid,fp)
                if old is not None:c.execute('COMMIT');return old
                if op=='create':
                    src=payload.get('source_store_id');dest=payload.get('dest_store_id')
                    self.authorize(actor,'dispatch',src)
                    if src not in [s['store_id'] for s in DEMO_STORES] or dest not in [s['store_id'] for s in DEMO_STORES] or src==dest:fail(422,'来源/目的地点错误')
                    lines=payload.get('lines')
                    if not isinstance(lines,list) or not lines or len(lines)>30:fail(422,'配送行不合法')
                    counts={}
                    for ln in lines:
                        item_id=ln.get('item_id');count=ln.get('packages')
                        if item_id not in [x['item_id'] for x in DEMO_ITEMS] or not isinstance(count,int) or isinstance(count,bool) or not 1<=count<=100:fail(422,'仅允许已核准测试物料与整数包装数')
                        counts[item_id]=counts.get(item_id,0)+count
                    sid='DEMO-SHP-'+uuid.uuid4().hex[:10].upper()
                    c.execute('INSERT INTO shipments VALUES (?,?,?,?,?,?,?)',(sid,src,dest,'DRAFT',1,actor['employee_id'],utc()))
                    for item,n in counts.items():
                        for _ in range(n):
                            c.execute('INSERT INTO packages VALUES (?,?,?,?,?)',('DEMO-PKG-'+uuid.uuid4().hex[:16].upper(),sid,item,'DRAFT','DEMO-BATCH-'+sid+'-'+item))
                    ret={'id':sid,'state':'DRAFT','version':1,'packages':self._pack(c,sid)}
                else:
                    s=self._check_version(c,sid,payload.get('expected_version'))
                    if op=='prepare':
                        self.authorize(actor,'dispatch',s['src'])
                        if s['state']!='DRAFT':fail(409,'只能备货草稿单')
                        c.execute("UPDATE packages SET state='READY' WHERE shipment_id=?",(sid,))
                        state='READY'; ret={'id':sid,'state':state,'version':s['version']+1}
                    elif op=='dispatch':
                        self.authorize(actor,'dispatch',s['src'])
                        if s['state']!='READY':fail(409,'只能发货已备货的单据')
                        codes=unique_codes(payload.get('scanned_codes',[]))
                        expected={x['code'] for x in self._pack(c,sid)}
                        if set(codes)!=expected:fail(409,'发货扫码不等于计划包装集合；请逐件核对')
                        counts={}
                        for p in self._pack(c,sid): counts[p['item_id']]=counts.get(p['item_id'],0)+1
                        for item,n in counts.items():self._move(c,sid,item,s['src'],'IN_TRANSIT:'+sid,n,actor['employee_id'])
                        c.execute("UPDATE packages SET state='IN_TRANSIT' WHERE shipment_id=?",(sid,))
                        state='DISPATCHED';ret={'id':sid,'state':state,'version':s['version']+1,'dispatched':len(codes)}
                    elif op=='receive':
                        self.authorize(actor,'receive',s['dest'])
                        if s['state'] not in ('DISPATCHED','PARTIAL_RECEIVED','DISPUTED'):fail(409,'当前状态不允许收货')
                        codes=unique_codes(payload.get('scanned_codes',[]))
                        accepts=payload.get('condition','ACCEPTED')
                        if accepts not in ('ACCEPTED','HOLD'):fail(422,'质量状态必须为 ACCEPTED 或 HOLD')
                        packs={x['code']:x for x in self._pack(c,sid)}
                        if any(code not in packs or packs[code]['state']!='IN_TRANSIT' for code in codes):fail(409,'存在错单或已收货包装码')
                        counts={}
                        for code in codes:
                            item=packs[code]['item_id'];counts[item]=counts.get(item,0)+1
                        dest=s['dest'] if accepts=='ACCEPTED' else 'QUARANTINE:'+s['dest']
                        for item,n in counts.items():self._move(c,sid,item,'IN_TRANSIT:'+sid,dest,n,actor['employee_id'])
                        for code in codes:c.execute('UPDATE packages SET state=? WHERE code=?',(accepts,code))
                        rem=c.execute("SELECT COUNT(*) FROM packages WHERE shipment_id=? AND state='IN_TRANSIT'",(sid,)).fetchone()[0]
                        state='RECEIVED' if rem==0 else 'PARTIAL_RECEIVED'
                        ret={'id':sid,'state':state,'version':s['version']+1,'received':len(codes),'pending_in_transit':rem,'quality':accepts}
                    else:fail(404,'未知操作')
                    c.execute('UPDATE shipments SET state=?,version=? WHERE id=?',(state,s['version']+1,sid))
                result=self._finish(c,rid,fp,ret)
                c.execute('INSERT INTO action_audit VALUES (?,?,?,?,?,?)',(str(uuid.uuid4()),rid,sid,actor['employee_id'],op,utc()))
                c.execute('COMMIT');return result
            except Exception:
                c.execute('ROLLBACK');raise
    def record_count(self,payload,actor,observation):
        self.authorize(actor,'inspect',payload['store_id'])
        rid=payload['request_id']
        fingerprint=hashlib.sha256(json.dumps({'payload':payload,'actor':actor['employee_id']},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.lock,self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                old=self._idem(c,rid,fingerprint)
                if old is not None:c.execute('COMMIT');return old
                count_id='DEMO-COUNT-'+uuid.uuid4().hex[:12]
                c.execute('INSERT INTO counts VALUES (?,?,?,?,?,?,?,?,?)',(count_id,payload['store_id'],payload['item_id'],
                          actor['employee_id'],payload['full_packages'],payload['opened_count'],
                          payload.get('opened_percent'),observation['method'],utc()))
                result={'count_id':count_id,'status':'OBSERVATION_ONLY','observation':observation,'inventory_adjusted':False}
                result=self._finish(c,rid,fingerprint,result)
                c.execute('COMMIT');return result
            except Exception:c.execute('ROLLBACK');raise
    def counts(self,actor):
        with self.lock,self._conn() as c:
            return [dict(x) for x in c.execute('SELECT * FROM counts ORDER BY created_at DESC LIMIT 100') if x['store_id'] in actor['stores']]

    def inspect(self,payload,actor):
        kind=payload.get('kind','self_check')
        if kind not in ('self_check','independent'):fail(422,'无效检查类型')
        self.authorize(actor,'inspect_independent' if kind=='independent' else 'inspect',payload.get('store_id'))
        fields=payload.get('results',{})
        required=['expiry','temperature','hygiene','equipment','pricing','previous_actions']
        if set(fields)!=set(required) or any(fields[x] not in ('OK','ISSUE','NOT_CHECKED') for x in required):
            fail(422,'六项快检字段不完整')
        rid=payload.get('request_id')
        fingerprint=hashlib.sha256(json.dumps({'payload':payload,'actor':actor['employee_id']},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.lock,self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                old=self._idem(c,rid,fingerprint)
                if old is not None:c.execute('COMMIT');return old
                sid='DEMO-INS-'+uuid.uuid4().hex[:12]
                c.execute('INSERT INTO inspections VALUES (?,?,?,?,?,?,?,?)',(sid,payload['store_id'],actor['employee_id'],
                          actor['department_id'],payload.get('subject_department',''),payload.get('subject_employee',''),
                          json.dumps(fields),utc()))
                c.execute('INSERT INTO inspection_kind VALUES (?,?)',(sid,kind))
                result=self._finish(c,rid,fingerprint,{'kind':kind,'inspection_id':sid,'issues':[k for k,v in fields.items() if v=='ISSUE'],'state':'RECORDED'})
                c.execute('COMMIT');return result
            except Exception:c.execute('ROLLBACK');raise
    def review_inspection(self,inspection_id,payload,actor):
        self.authorize(actor,'review_independent')
        rid=payload['request_id']
        fingerprint=hashlib.sha256(json.dumps(['review',inspection_id,payload,actor['employee_id']],sort_keys=True).encode()).hexdigest()
        with self.lock,self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                row=c.execute("""SELECT i.*, k.kind FROM inspections i
                    JOIN inspection_kind k ON k.id=i.id WHERE i.id=?""",(inspection_id,)).fetchone()
                if not row:fail(404,'检查编号不存在或缺少历史类型')
                self.authorize(actor,'review_independent',row['store_id'])
                if row['kind']!='independent':fail(409,'门店自检不进入独立复核')
                if actor['employee_id'] in (row['inspector'],row['subject_employee']):
                    fail(403,'检查人或被检查人不可自行复核')
                old=self._idem(c,rid,fingerprint)
                if old is not None:
                    c.execute('COMMIT')
                    return old
                if c.execute('SELECT 1 FROM inspection_reviews WHERE id=?',(inspection_id,)).fetchone():
                    fail(409,'检查已复核')
                c.execute('INSERT INTO inspection_reviews VALUES (?,?,?,?)',
                          (inspection_id,actor['employee_id'],payload['decision'],utc()))
                result=self._finish(c,rid,fingerprint,{'inspection_id':inspection_id,'state':payload['decision']})
                c.execute('COMMIT')
                return result
            except Exception:
                c.execute('ROLLBACK')
                raise

    def inspections(self,actor):
        with self.lock,self._conn() as c:
            rows=c.execute("""SELECT i.*, COALESCE(k.kind,'self_check') AS kind,
                r.decision FROM inspections i LEFT JOIN inspection_kind k ON k.id=i.id
                LEFT JOIN inspection_reviews r ON r.id=i.id ORDER BY i.created_at DESC LIMIT 100""")
            return [dict(x) for x in rows if x['store_id'] in actor['stores']
                    and (x['kind']=='self_check' or 'inspect_independent' in actor['roles']
                         or 'review_independent' in actor['roles'])]
