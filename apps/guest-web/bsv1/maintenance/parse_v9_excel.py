"""BSV ALL one-database staging importer.

Run: python BSV_ALL_V9_入库验证工具.py <workbook.xlsx> <result.sqlite> <result.json>
Uses Python standard library only. Recomputes classification SKUs from dictionary,
not from stale spreadsheet formula caches. No payment or stock movement.
"""
from __future__ import annotations
import sys, os, re, json, zipfile, sqlite3, collections, xml.etree.ElementTree as ET
from pathlib import Path

NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
def getbook(path):
 with zipfile.ZipFile(path) as z:
  strings=[]
  if 'xl/sharedStrings.xml' in z.namelist():
   root=ET.fromstring(z.read('xl/sharedStrings.xml'))
   for si in root.findall('m:si',NS):strings.append(''.join((t.text or '') for t in si.findall('.//m:t',NS)))
  rels={r.get('Id'):r.get('Target').lstrip('/') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
  book=ET.fromstring(z.read('xl/workbook.xml'));out={}
  for sh in book.findall('m:sheets/m:sheet',NS):
   name=sh.get('name');path1=rels[sh.get('{%s}id'%NS['r'])]
   if not path1.startswith('xl/'):path1='xl/'+path1
   root=ET.fromstring(z.read(path1));data={}
   for c in root.findall('.//m:sheetData/m:row/m:c',NS):
    ref=c.get('r');t=c.get('t');v=c.find('m:v',NS)
    if t=='inlineStr':val=''.join(z.text or '' for z in c.findall('.//m:t',NS))
    elif v is None:val=None
    elif t=='s':val=strings[int(v.text)]
    elif t in ('str','e'):val=v.text
    elif v.text is None:val=None
    else:
     try:
      x=float(v.text);val=int(x) if x.is_integer() else x
     except (ValueError,TypeError):val=v.text
    data[ref]=val
   out[name]=data
 return out

def colno(col):
 n=0
 for ch in col:n=n*26+ord(ch)-64
 return n

def xlcol(num):
 s=''
 while num:
  num,r=divmod(num-1,26);s=chr(65+r)+s
 return s

def normvalue(value,field):
 if value is None or value=='':return None
 if field in ('标注售价','标注原价','区域参考售价','核心参考售价','酒精度数','制作时长（秒）','投料数量','包装量','整批成本','份量','采购价','售卖扣减量','原包装容量','规格量','折旧月数','N需求率','P支付转化率','S场景实现率','NPS计算结果','消费人数','建议人数','目标人数','核准售价'):
  try:
   if isinstance(value,str):
    if value.endswith('%'):return float(value[:-1])/100
    if not re.fullmatch(r'[-+]?\d+(\.\d+)?',value.strip()):return value
   x=float(value);return int(x) if x.is_integer() else x
  except (TypeError,ValueError):pass
 return value

def build(workbook,db_path,json_path):
 sheets=getbook(workbook)
 expected=['C_现场成品','P_预调半成品','M_采购纯饮','K_套餐组合','R_配方耗用','Q_门店报价','T_门店注册']
 if list(sheets)!=expected:raise ValueError('七张业务表名称或顺序不符合接口契约')
 dictionaries={};validpaths={};records=[];sku_seen=set();id_seen=set(); issues=[];domain_stats={}
 for name in expected:
  d=sheets[name];domain=d.get('B2')
  if domain!=name[0]:raise ValueError('工作表代码不匹配:'+name)
  dct={};ordered=[]
  for level,(cc,dd) in enumerate([('A','B'),('C','D'),('E','F'),('G','H')],1):
   mp={};seq=[];names=set()
   for r in range(9,101):
    code=d.get(f'{cc}{r}');term=d.get(f'{dd}{r}')
    if code is None and term is None:continue
    if not isinstance(code,str) or not re.fullmatch('[A-Z]',code) or not isinstance(term,str) or not term:
     issues.append(f'{name}：L{level}字典空值或非英文单字母代码：{r}');continue
    if term in mp or code in names:issues.append(f'{name}：L{level}定义重复：{r}');continue
    mp[term]=code;names.add(code)
   seq=[d.get(f'{dd}{r}') for r in range(9,101)]
   ordered.append(seq);dct[level]=mp
  dictionaries[domain]=dct
  paths=set()
  for r in range(9,1001):
   idx=[d.get(f'{cc}{r}') for cc in ['JA','JB','JC','JD']]
   if all(v is None for v in idx):continue
   if not all(isinstance(v,int) and v>0 for v in idx):issues.append(f'{name}：合法路径序位不是整数：{r}');continue
   try: path=''.join(dct[level+1][ordered[level][num-1]] for level,num in enumerate(idx))
   except (IndexError,KeyError,TypeError):issues.append(f'{name}：非法路径引用：{r}');continue
   if path in paths:issues.append(f'{name}：合法路径重复：{r}')
   paths.add(path)
  validpaths[domain]=paths
  header_cols={xlcol(i):d.get(f'{xlcol(i)}8') for i in range(colno('K'),colno('EA')) if d.get(f'{xlcol(i)}8') not in (None,'')}
  if not {'K','L','M'}.issubset(header_cols):raise ValueError(name+'缺少SKU/ID/名称')
  seq_col='T' if domain in ('C','K') else 'R'
  cat_cols=['P','Q','R','S'] if domain in ('C','K') else ['N','O','P','Q']
  domain_records=[];blank_streak=0
  for rownum in range(9,100000):
   recordid=d.get(f'L{rownum}');recordname=d.get(f'M{rownum}')
   if recordid is None and recordname is None:
    blank_streak+=1
    if blank_streak>=30:break
    continue
   blank_streak=0
   if not isinstance(recordid,str) or not recordid.startswith(domain):issues.append(f'{name}:{rownum}实体ID错误');continue
   if recordid in id_seen:issues.append(f'{name}:{rownum}实体ID重复');continue
   id_seen.add(recordid)
   cats=[d.get(f'{c}{rownum}') for c in cat_cols]
   member=d.get(f'{seq_col}{rownum}')
   status='分类待补';sku=None
   if all(isinstance(v,str) and v for v in cats) and member is not None:
    try:
     clas=''.join(dct[i+1][cats[i]] for i in range(4));num=int(member)
     if clas not in paths:status='非法分类路径'
     elif not (1<=num<=99999):status='序号越界'
     else:
      sku=domain+clas+f'{num:05d}';status='结构合格'
      if sku in sku_seen:issues.append(f'{name}:{rownum}SKU重复 {sku}')
      sku_seen.add(sku)
    except (KeyError,TypeError,ValueError):status='无效分类或序号'
   # Business fields only; never export computed helper columns or formula caches.
   fields={hdr:normvalue(d.get(f'{col}{rownum}'),hdr) for col,hdr in header_cols.items() if col not in ('K','L')}
   out={'id':recordid,'domain':domain,'sku':sku,'classification_status':status,'fields':fields}
   domain_records.append(out);records.append(out)
  domain_stats[domain]={'records':len(domain_records),'classified':sum(bool(x['sku']) for x in domain_records),'pending':sum(not x['sku'] for x in domain_records)}
 if issues:raise ValueError('入库校验失败：'+json.dumps(issues[:30],ensure_ascii=False))
 refids={r['id'] for r in records}
 # Same-sheet secondary relation regions; do not force unspecific package text into fabricated SKU links.
 k=sheets['K_套餐组合'];bundle_slots=[];nps=[]
 for r in range(9,10000):
  pid=k.get(f'CR{r}')
  if pid is not None:
   if pid not in refids:raise ValueError('套餐明细关联不存在的套餐ID')
   cid=k.get(f'CW{r}')
   if cid is not None and cid not in refids:raise ValueError('套餐候选商品不存在')
   bundle_slots.append({'bundle_id':pid,'slot_code':k.get(f'CS{r}'),'slot_name':k.get(f'CT{r}'),'quantity':k.get(f'CU{r}'),'select_rule':k.get(f'CV{r}'),'candidate_id':cid,'constraints':k.get(f'DA{r}')})
  bid=k.get(f'DC{r}')
  if bid is not None:
   if bid not in refids:raise ValueError('套餐NPS关联不存在')
   nps.append({'bundle_id':bid,'store_id':k.get(f'DD{r}'),'n':k.get(f'DE{r}'),'p':k.get(f'DF{r}'),'s':k.get(f'DG{r}'),'status':k.get(f'DH{r}'),'notes':k.get(f'DI{r}')})
  if r>9 and pid is None and bid is None and all(k.get(f'{col}{i}') is None for i in range(r-2,r+1) for col in ['CR','DC']):break
 conn=sqlite3.connect(db_path)
 try:
  conn.execute('PRAGMA foreign_keys=ON')
  conn.executescript('''
  CREATE TABLE classification_definitions(domain TEXT NOT NULL, level INTEGER NOT NULL, code TEXT NOT NULL, meaning TEXT NOT NULL, PRIMARY KEY(domain,level,code), UNIQUE(domain,level,meaning));
  CREATE TABLE valid_paths(domain TEXT NOT NULL, path TEXT NOT NULL, PRIMARY KEY(domain,path));
  CREATE TABLE entity_records(id TEXT PRIMARY KEY, domain TEXT NOT NULL, sku TEXT UNIQUE, name TEXT NOT NULL, status TEXT NOT NULL, fields_json TEXT NOT NULL);
  CREATE TABLE recipe_links(recipe_id TEXT PRIMARY KEY REFERENCES entity_records(id), output_id TEXT REFERENCES entity_records(id), input_id TEXT REFERENCES entity_records(id));
  CREATE TABLE bundle_slots(bundle_id TEXT NOT NULL REFERENCES entity_records(id), slot_code TEXT, slot_name TEXT, quantity REAL, select_rule TEXT, candidate_id TEXT REFERENCES entity_records(id), constraints_text TEXT);
  CREATE TABLE bundle_store_nps(bundle_id TEXT NOT NULL REFERENCES entity_records(id), store_id TEXT NOT NULL, n TEXT, p TEXT, s TEXT, status TEXT, notes TEXT);
  CREATE TABLE store_ids(store_id TEXT PRIMARY KEY, record_id TEXT UNIQUE NOT NULL REFERENCES entity_records(id));
  CREATE TABLE price_quotes(quote_record_id TEXT PRIMARY KEY REFERENCES entity_records(id), store_id TEXT REFERENCES store_ids(store_id), item_id TEXT REFERENCES entity_records(id), quote_id TEXT UNIQUE, amount NUMERIC, approval_status TEXT);
  CREATE INDEX idx_records_domain_sku ON entity_records(domain,sku);
  CREATE INDEX idx_recipe_output ON recipe_links(output_id);
  CREATE INDEX idx_bundle_choice ON bundle_slots(bundle_id,slot_code);
  ''')
  for domain,levs in dictionaries.items():
   for level,mp in levs.items():
    conn.executemany('INSERT INTO classification_definitions VALUES(?,?,?,?)',[(domain,level,code,meaning) for meaning,code in mp.items()])
   conn.executemany('INSERT INTO valid_paths VALUES(?,?)',[(domain,x) for x in validpaths[domain]])
  conn.executemany('INSERT INTO entity_records VALUES(?,?,?,?,?,?)',[(x['id'],x['domain'],x['sku'],str(x['fields'].get('商品名称') or x['fields'].get('半成品名称') or x['fields'].get('物料名称') or x['fields'].get('套餐名称') or x['fields'].get('记录名称') or x['fields'].get('报价名称') or x['fields'].get('门店名称') or ''),x['classification_status'],json.dumps(x['fields'],ensure_ascii=False)) for x in records])
  for x in records:
   f=x['fields']
   if x['domain']=='R':
    output=f.get('出品关联ID');inp=f.get('投入物料ID')
    if output and output not in refids:raise ValueError('制作记录关联ID失效 '+x['id'])
    if inp and inp not in refids:raise ValueError('物料关联ID失效 '+x['id'])
    conn.execute('INSERT INTO recipe_links VALUES(?,?,?)',(x['id'],output,inp))
   if x['domain']=='T' and f.get('门店ID'):
    conn.execute('INSERT INTO store_ids VALUES(?,?)',(f['门店ID'],x['id']))
  conn.executemany('INSERT INTO bundle_slots VALUES(?,?,?,?,?,?,?)',[(x['bundle_id'],x['slot_code'],x['slot_name'],x['quantity'],x['select_rule'],x['candidate_id'],x['constraints']) for x in bundle_slots])
  conn.executemany('INSERT INTO bundle_store_nps VALUES(?,?,?,?,?,?,?)',[(x['bundle_id'],x['store_id'],x['n'],x['p'],x['s'],x['status'],x['notes']) for x in nps])
  if conn.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('外键完整性校验失败')
  conn.commit()
  stats={'records':domain_stats,'dictionary_terms':conn.execute('SELECT COUNT(*) FROM classification_definitions').fetchone()[0], 'legal_paths':conn.execute('SELECT COUNT(*) FROM valid_paths').fetchone()[0], 'recipe_links':conn.execute('SELECT COUNT(*) FROM recipe_links').fetchone()[0], 'bundle_slot_rows':len(bundle_slots),'linked_bundle_items':sum(bool(x['candidate_id']) for x in bundle_slots), 'store_nps_rows':len(nps), 'store_ids':conn.execute('SELECT COUNT(*) FROM store_ids').fetchone()[0], 'quotes':conn.execute('SELECT COUNT(*) FROM price_quotes').fetchone()[0], 'foreign_key_violations':0}
 finally:conn.close()
 payload={'database':'BSV_ALL','schema':'1.0','records':records,'dictionary':{dom:{str(i):[{'code':code,'meaning':term} for term,code in lev.items()] for i,lev in levels.items()} for dom,levels in dictionaries.items()},'legal_paths':{k:sorted(list(v)) for k,v in validpaths.items()},'bundle_slots':bundle_slots,'bundle_store_nps':nps,'audit':stats}
 Path(json_path).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(stats,ensure_ascii=False,indent=2))
 return stats

if __name__=='__main__':
 src=sys.argv[1] if len(sys.argv)>1 else 'BSV_ALL_统一业务主数据库_V9_正式导入底座.xlsx'
 db=sys.argv[2] if len(sys.argv)>2 else 'BSV_ALL_V9_入库验收.sqlite'
 js=sys.argv[3] if len(sys.argv)>3 else 'BSV_ALL_V9_结构化导入数据.json'
 if os.path.exists(db):os.remove(db)
 build(src,db,js)
