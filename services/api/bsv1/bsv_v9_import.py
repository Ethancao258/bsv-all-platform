"""BSV ALL V9 OOXML只读导入器，纯Python标准库；不改变Excel，不用Excel作并发订单数据库。

从每页第8行实际表头和第9行数据读取，固定ID为L列。对公式只读取文件
已保存的缓存值，*不会*调用Excel重算、也不把缺失缓存猜填。
导入前解析/校验全部行，在单个SQLite事务中原子替换上一版只读镜像。
"""
from __future__ import annotations
import hashlib, json, re, sqlite3, zipfile, posixpath, xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from bsv_catalog_config import get_excel_path, SHOW_LOCAL_TRAINING_ITEMS
import bsv_layouts

NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'p':'http://schemas.openxmlformats.org/package/2006/relationships'}
SHEETS=['C_现场成品','P_预调半成品','M_采购纯饮','K_套餐组合','R_配方耗用','Q_门店报价','T_门店注册']
ID_PREFIX=dict(zip(SHEETS,list('CPMKRQT')))
MAIN_LAST={'C_现场成品':'AZ','P_预调半成品':'AO','M_采购纯饮':'AM','K_套餐组合':'BH',
 'R_配方耗用':'AG','Q_门店报价':'AD','T_门店注册':'Y'}
VALID_PUBLISH={'已批准','已核准','审核通过'}
VALID_ACTIVE={'在售','已上架','已发布','正常销售'}
VALID_CURRENCY={'CNY','人民币','RMB','元'}
# 唯一标价来源：V9 / C_现场成品 / AJ列（标注售价）。
PRICE_POLICY='C_AJ_GLOBAL_CANONICAL_V2'

def col_num(label):
    n=0
    for c in label.upper():n=n*26+ord(c)-64
    return n

def a1(addr):
    m=re.fullmatch(r'([A-Z]+)(\d+)',addr)
    if not m:return None
    return col_num(m.group(1)),int(m.group(2))

def text_elem(element):
    return ''.join(t.text or '' for t in element.iter('{%s}t'%NS['m']))

def workbook_read(path:Path):
    with zipfile.ZipFile(path) as z:
        corrupt=z.testzip()
        if corrupt:raise ValueError('Excel ZIP CRC检验失败：'+corrupt)
        wb=ET.fromstring(z.read('xl/workbook.xml'))
        rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        mapping={rel.get('Id'):rel.get('Target') for rel in rels}
        ss=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            sroot=ET.fromstring(z.read('xl/sharedStrings.xml'))
            ss=[text_elem(si) for si in sroot.findall('m:si',NS)]
        sheets={}
        for sheet in wb.findall('.//m:sheets/m:sheet',NS):
            name=sheet.get('name')
            if name not in SHEETS:continue
            target=mapping.get(sheet.get('{%s}id'%NS['r']))
            if not target:raise ValueError('工作表映射缺失：'+name)
            target=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
            root=ET.fromstring(z.read(target))
            rows={}
            for r in root.findall('.//m:sheetData/m:row',NS):
                rn=int(r.get('r'))
                if rn<8:continue
                cells={}
                for c in r.findall('m:c',NS):
                    ref=a1(c.get('r',''))
                    if not ref:continue
                    ci=ref[0]
                    value=c.find('m:v',NS)
                    t=c.get('t','')
                    if t=='inlineStr':
                        istr=c.find('m:is',NS)
                        datum=text_elem(istr) if istr is not None else None
                    elif value is None:
                        datum=None
                    elif t=='s':
                        index=int(value.text or '0')
                        datum=ss[index] if 0<=index<len(ss) else None
                    elif t in ('str','e'):
                        datum=value.text
                    elif t=='b':
                        datum=value.text=='1'
                    else:
                        raw=value.text
                        if raw is None:datum=None
                        else:
                            try:
                                dec=Decimal(raw)
                                datum=int(dec) if dec==dec.to_integral_value() else float(dec)
                            except InvalidOperation:datum=raw
                    if datum is not None:cells[ci]=datum
                if cells:rows[rn]=cells
            sheets[name]=rows
        missing=set(SHEETS)-set(sheets)
        if missing:raise ValueError('V9缺少必需工作表：'+','.join(sorted(missing)))
        return sheets

def sheet_records(rows,page):
    head=rows.get(8,{})
    if head.get(12) not in ('商品ID','半成品ID','物料ID','套餐ID','工序记录ID','报价记录ID','网点记录ID'):
        raise ValueError(page+'的L8固定ID表头异常，已停止导入')
    last=col_num(MAIN_LAST[page])
    output=[]
    for rno,cells in sorted(rows.items()):
        if rno<9:continue
        key=cells.get(12)
        if key in (None,''):continue
        if not isinstance(key,str) or not re.fullmatch(r'[CPMKRQT]\d{6}',key):
            raise ValueError(f'{page}第{rno}行固定ID格式异常：{key!r}')
        if not key.startswith(ID_PREFIX[page]):raise ValueError(f'{page}第{rno}行固定ID域错误')
        raw={str(head[c]):cells.get(c) for c in range(11,last+1) if head.get(c) not in (None,'')}
        output.append({'id':key,'name':str(cells.get(13) or ''),'row':rno,'fields':raw})
    ids=[r['id'] for r in output]
    if len(ids)!=len(set(ids)):
        dups=[k for k,v in Counter(ids).items() if v>1]
        raise ValueError(page+'的L列固定ID重复：'+str(dups[:8]))
    return output

def date_iso(value):
    if value is None or value=='':return None
    if isinstance(value,(int,float)):
        try:return (date(1899,12,30)+timedelta(days=int(value))).isoformat()
        except (OverflowError,ValueError):return None
    s=str(value).strip().replace('/','-')
    return s[:10] if re.fullmatch(r'\d{4}-\d{1,2}-\d{1,2}',s[:10]) else None

def cents_from_price(value):
    try:
        if isinstance(value,bool) or value is None:return None
        d=Decimal(str(value))
        if d<=0 or d>Decimal('100000') or d*100!=(d*100).to_integral_value():return None
        return int(d*100)
    except (InvalidOperation,ValueError):return None

def unpack_v9(path:Path):
    sheets=workbook_read(path)
    data={page:sheet_records(sheets[page],page) for page in SHEETS}
    ids={p:{x['id'] for x in data[p]} for p in SHEETS}
    store_ids={str(r['fields'].get('门店ID')) for r in data['T_门店注册']}
    if not store_ids or any(not re.fullmatch(r'[A-Z][A-Z0-9_-]{2,31}',x) for x in store_ids):
        raise ValueError('T页门店代码无效；不得使用别名或空ID')
    extras=[]
    krows=sheets['K_套餐组合']; h=krows.get(8,{})
    for zone, start,end in [('K_套餐槽位','CR','DA'),('K_门店NPS','DC','DI')]:
        a,b=col_num(start),col_num(end)
        for rn,c in sorted(krows.items()):
            if rn<9 or c.get(a) in (None,''):continue
            item={str(h.get(i)):c.get(i) for i in range(a,b+1) if h.get(i)}
            extras.append({'section':zone,'row':rn,'fields':item})
    # 只将已核价、内容审核、门店审核、报价审核全通过的条目授权点单。
    cidx={r['id']:r for r in data['C_现场成品']}
    kidx={r['id']:r for r in data['K_套餐组合']}
    midx={r['id']:r for r in data['M_采购纯饮']}
    tidx={r['fields'].get('门店ID'):r for r in data['T_门店注册']}
    quotes=[]; warnings=[]; grouped={}
    for row in data['Q_门店报价']:
        f=row['fields'];store=f.get('门店ID');item_id=f.get('商品ID')
        if store not in tidx or item_id not in (cidx.keys()|kidx.keys()|midx.keys()):
            warnings.append(f'Q:{row["id"]}引用的门店或商品固定ID无效');continue
        if str(f.get('审核状态') or '') not in VALID_PUBLISH:continue
        p=cents_from_price(f.get('核准售价'))
        if p is None:warnings.append(f'Q:{row["id"]}核准售价无效');continue
        curr=str(f.get('币种') or 'CNY').strip()
        if curr not in VALID_CURRENCY:
            warnings.append(f'Q:{row["id"]}币种不受支持：{curr}');continue
        product=cidx.get(item_id) or kidx.get(item_id) or midx.get(item_id)
        a=product['fields']
        typ='C' if item_id.startswith('C') else 'K' if item_id.startswith('K') else 'M'
        reasons=[]
        if str(tidx[store]['fields'].get('审核状态') or '') not in VALID_PUBLISH:reasons.append('门店资料未核准')
        if typ=='C':
            if str(a.get('内容审核状态') or '') not in VALID_PUBLISH:reasons.append('商品内容未核准')
            if str(a.get('上架状态') or '') not in VALID_ACTIVE:reasons.append('商品尚未上架')
        elif typ=='K':
            if str(a.get('审批状态') or '') not in VALID_PUBLISH or str(a.get('业务审批状态') or '') not in VALID_PUBLISH:
                reasons.append('套餐审批未通过')
            if str(a.get('销售状态') or '') not in VALID_ACTIVE:reasons.append('套餐尚未上架')
            slots=[x for x in extras if x['section']=='K_套餐槽位' and x['fields'].get('套餐ID')==item_id]
            if not slots or not all(x['fields'].get('候选商品ID') in (ids['C_现场成品']|ids['M_采购纯饮']) for x in slots):
                reasons.append('套餐槽位未完成固定ID关联')
        else:
            if str(a.get('是否可售') or '')!='是' or str(a.get('审核状态') or '') not in VALID_PUBLISH:
                reasons.append('物料不可售或未核准')
        channel=str(f.get('销售渠道') or '门店').strip()
        valid_from=date_iso(f.get('生效日期'))
        valid_to=date_iso(f.get('失效日期'))
        if f.get('生效日期') not in ('',None) and not valid_from:reasons.append('生效日期无效')
        if f.get('失效日期') not in ('',None) and not valid_to:reasons.append('失效日期无效')
        if valid_from and valid_to and valid_from>valid_to:reasons.append('报价有效期倒置')
        quote={'quote_id':row['id'],'store_id':store,'item_id':item_id,'channel':channel,'price_cents':p,
               'valid_from':valid_from,'valid_to':valid_to,'eligible':not reasons,'reason':'；'.join(reasons)}
        quotes.append(quote)
        if quote['eligible']:grouped.setdefault((store,item_id,channel),[]).append(quote)
    # 两笔已批准报价在同一门店/商品/渠道交叉有效 → 两笔都阻止自动应用。
    for key,group in grouped.items():
        for i,one in enumerate(group):
            for two in group[i+1:]:
                if (one['valid_from'] or '0000-01-01') <= (two['valid_to'] or '9999-12-31') and (two['valid_from'] or '0000-01-01') <= (one['valid_to'] or '9999-12-31'):
                    one['eligible']=two['eligible']=False
                    one['reason']=two['reason']='核准报价有效期重叠，必须人工核准'
                    warnings.append('价格冲突：'+str(key))
    # AJ必须是C表第36列（按列位置校验，不仅信任重命名的字段）。
    assert sheets['C_现场成品'].get(8,{}).get(36)=='标注售价', 'C_现场成品!AJ8不是标注售价，停止同步'
    c_priced=[x for x in data['C_现场成品'] if cents_from_price(x['fields'].get('标注售价')) is not None]
    c_missing=[{'id':x['id'],'name':x['name'],'row':x['row']} for x in data['C_现场成品'] if cents_from_price(x['fields'].get('标注售价')) is None]
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    summary={p.split('_')[0]:len(v) for p,v in data.items()}
    approved_c = sum(
        str(x['fields'].get('内容审核状态') or '').strip() in VALID_PUBLISH
        and str(x['fields'].get('上架状态') or '').strip() in VALID_ACTIVE
        for x in data['C_现场成品'])
    summary.update({'source_sha256':digest,'source_file':path.name,'quotes':len(quotes),
                    'eligible_quotes':sum(x['eligible'] for x in quotes),'warnings':warnings,
                    'not_calculated_formulas':True,'extras':len(extras),
                    'price_policy':PRICE_POLICY,'c_aj_priced':len(c_priced),'c_aj_missing':c_missing,
                    'c_aj_total':len(data['C_现场成品']),'c_content_and_listing_approved':approved_c,
                    'c_sale_eligible':sum(
                        cents_from_price(x['fields'].get('标注售价')) is not None
                        and str(x['fields'].get('内容审核状态') or '').strip() in VALID_PUBLISH
                        and str(x['fields'].get('上架状态') or '').strip() in VALID_ACTIVE
                        for x in data['C_现场成品']),
                    'store_ids':[r['store_id'] for r in bsv_layouts.registry()]})
    return data,extras,quotes,summary

def ensure_catalog_schema(db:sqlite3.Connection):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS bsv_v9_record (
      page TEXT NOT NULL, fixed_id TEXT NOT NULL, display_name TEXT NOT NULL,
      source_row INTEGER NOT NULL, fields_json TEXT NOT NULL, imported_sha TEXT NOT NULL,
      PRIMARY KEY(page,fixed_id));
    CREATE INDEX IF NOT EXISTS ix_v9_record_display ON bsv_v9_record(page,display_name);
    CREATE TABLE IF NOT EXISTS bsv_v9_extra (
      section TEXT NOT NULL, source_row INTEGER NOT NULL, fields_json TEXT NOT NULL,
      PRIMARY KEY(section,source_row));
    CREATE TABLE IF NOT EXISTS bsv_v9_quote (
      quote_id TEXT PRIMARY KEY,store_id TEXT NOT NULL,item_id TEXT NOT NULL,channel TEXT NOT NULL,
      price_cents INTEGER NOT NULL, valid_from TEXT,valid_to TEXT,
      eligible INTEGER NOT NULL,reason TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS bsv_v9_sync (
      one INTEGER PRIMARY KEY CHECK(one=1),source_path TEXT NOT NULL,
      source_sha TEXT NOT NULL,imported_at TEXT NOT NULL,summary_json TEXT NOT NULL);
    ''')
    cols={row[1] for row in db.execute('PRAGMA table_info(bsv_products)')}
    for col,spec in [('source_domain','TEXT'),('store_id','TEXT'),
                     ('sale_enabled','INTEGER NOT NULL DEFAULT 1'),('catalog_sha','TEXT'),('price_policy','TEXT')]:
        if col not in cols:db.execute(f'ALTER TABLE bsv_products ADD COLUMN {col} {spec}')

def sync_v9(dbpath:Path, excelpath:Path, force=False, *, sale_release=None):
    from bsv_catalog_live import live_enabled
    if live_enabled() and sale_release is None:
        raise PermissionError("正式商品投影必须由获批销售版本执行器生成")
    data,extras,quotes,summary=unpack_v9(excelpath)
    if sale_release is not None:
        from bsv_hq_live_sale import facts
        current=facts(data)
        if sale_release["source_sha256"]!=summary["source_sha256"] or any(current.get(k)!=v for k,v in sale_release["items"].items()):
            raise ValueError("核准销售版本与原始商品内容不匹配")
        # Effective approvals are a projection of the PG sale ledger, not
        # fabricated or modified original Excel status cells.
        for row in data["C_现场成品"]:
            listed=row["id"] in sale_release["items"]
            row["fields"]["内容审核状态"]="已批准" if listed else "待审核"
            row["fields"]["上架状态"]="已上架" if listed else "未上架"
        summary.update(sale_release_id=sale_release["id"],sale_projection_ready=False,c_sale_eligible=len(sale_release["items"]))
    db=sqlite3.connect(str(dbpath),timeout=20)
    try:
        db.execute('PRAGMA busy_timeout=20000')
        db.execute('PRAGMA foreign_keys=ON')
        ensure_catalog_schema(db)
        old=db.execute('SELECT source_sha FROM bsv_v9_sync WHERE one=1').fetchone()
        # 版本切换：即使Excel文件未变，旧的逐店Q表/临时价仍需强制转换为AJ统一价。
        prior=db.execute('SELECT summary_json FROM bsv_v9_sync WHERE one=1').fetchone() if old else None
        if prior and sale_release is None:
            try:previous_meta=json.loads(prior[0])
            except (ValueError,TypeError):previous_meta={}
            if previous_meta.get("sale_release_id"):
                raise PermissionError("已接管的正式销售投影禁止被旧Excel同步任务覆盖")
        try: old_policy=json.loads(prior[0]).get('price_policy') if prior else None
        except (ValueError,TypeError):old_policy=None
        try: old_store_ids=json.loads(prior[0]).get('store_ids') if prior else None
        except (ValueError,TypeError):old_store_ids=None
        if old and old[0]==summary['source_sha256'] and old_policy==PRICE_POLICY and old_store_ids==summary['store_ids'] and not force:
            return {'unchanged':True,**summary}
        if old:
            # Every source update may alter sellability; make a consistent SQLite backup first.
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            backup=dbpath.with_name(dbpath.stem+'_V9同步前备份_'+stamp+'.sqlite3')
            target=sqlite3.connect(str(backup))
            try:db.backup(target)
            finally:target.close()
        # schema/DDL is committed, replace records and active priced catalog transactionally
        db.execute('BEGIN IMMEDIATE')
        for name in ('bsv_v9_record','bsv_v9_extra','bsv_v9_quote'):db.execute('DELETE FROM '+name)
        for page,rows in data.items():
            for item in rows:
                db.execute('INSERT INTO bsv_v9_record VALUES(?,?,?,?,?,?)',(
                    page,item['id'],item['name'],item['row'],json.dumps(item['fields'],ensure_ascii=False,default=str),summary['source_sha256']))
        for item in extras:
            db.execute('INSERT INTO bsv_v9_extra VALUES (?,?,?)',(
                item['section'],item['row'],json.dumps(item['fields'],ensure_ascii=False,default=str)))
        for item in quotes:
            db.execute('INSERT INTO bsv_v9_quote VALUES(?,?,?,?,?,?,?,?,?)',(
                item['quote_id'],item['store_id'],item['item_id'],item['channel'],item['price_cents'],
                item['valid_from'],item['valid_to'],int(item['eligible']),item['reason']))
        # 禁止旧产品被继续售卖；已销售记录保留订单快照和稳定ID。
        db.execute("UPDATE bsv_products SET sale_enabled=0 WHERE demo_only=0")
        # Catalog visibility is independent of POS sellability. A price alone never
        # approves a draft or unlisted item; historical order snapshots are untouched.
        for item in data['C_现场成品']:
            fixed_id=item['id']
            cents=cents_from_price(item['fields'].get('标注售价'))
            if cents is None:continue
            fields=item['fields']
            sale_enabled=int(
                str(fields.get('内容审核状态') or '').strip() in VALID_PUBLISH
                and str(fields.get('上架状态') or '').strip() in VALID_ACTIVE)
            # One product_id globally. Store visibility is an access policy, not a second SKU.
            db.execute('''INSERT INTO bsv_products
              (id,name,price_cents,demo_only,discount_eligible,source_domain,store_id,sale_enabled,catalog_sha,price_policy)
              VALUES (?,?,?,0,1,'C',NULL,?,?,?)
              ON CONFLICT(id) DO UPDATE SET name=excluded.name,price_cents=excluded.price_cents,
                source_domain='C',store_id=NULL,
                sale_enabled=excluded.sale_enabled,catalog_sha=excluded.catalog_sha,price_policy=excluded.price_policy''',
              (fixed_id,item['name'],cents,sale_enabled,summary['source_sha256'],PRICE_POLICY))
        db.execute('''INSERT INTO bsv_v9_sync VALUES(1,?,?,?,?) ON CONFLICT(one) DO UPDATE SET
          source_path=excluded.source_path,source_sha=excluded.source_sha,
          imported_at=excluded.imported_at,summary_json=excluded.summary_json''',(
          str(excelpath),summary['source_sha256'],datetime.now(timezone.utc).isoformat(timespec='seconds'),json.dumps(summary,ensure_ascii=False)))
        db.commit()
    except Exception:
        db.rollback();raise
    finally:db.close()
    return summary

def price_is_current(db,product,store_id):
    """仅以C表AJ的同步值授权，不接受门店本地改价或Q页价格。

    绑定Excel版本和销售镜像：改价后旧草稿需重新确认，历史订单价格快照不改变。
    """
    from bsv_catalog_live import live_enabled
    if live_enabled():
        state=db.execute("SELECT summary_json FROM bsv_v9_sync WHERE one=1").fetchone()
        if not state:return False
        try:metadata=json.loads(state[0])
        except (ValueError,TypeError):return False
        if not metadata.get("sale_release_id") or metadata.get("sale_projection_ready") is not True:return False
    if not product or not product['sale_enabled'] or product['store_id'] not in (None,store_id):
        return False
    if product['source_domain']!='C' or product['price_policy']!=PRICE_POLICY:
        return False
    record=db.execute("SELECT * FROM bsv_v9_record WHERE page='C_现场成品' AND fixed_id=?",
                      (product['id'],)).fetchone()
    sync=db.execute('SELECT source_sha FROM bsv_v9_sync WHERE one=1').fetchone()
    if not record or not sync or product['catalog_sha']!=sync['source_sha'] or record['imported_sha']!=sync['source_sha']:
        return False
    fields=json.loads(record['fields_json'])
    if (str(fields.get('内容审核状态') or '').strip() not in VALID_PUBLISH
            or str(fields.get('上架状态') or '').strip() not in VALID_ACTIVE):
        return False
    store_rows=db.execute("SELECT fields_json FROM bsv_v9_record WHERE page='T_门店注册'").fetchall()
    store_approved=False
    for store_row in store_rows:
        registered=json.loads(store_row['fields_json'])
        if (str(registered.get('门店ID') or '').strip()==store_id
                and str(registered.get('审核状态') or '').strip() in VALID_PUBLISH):
            store_approved=True
            break
    if not store_approved:
        return False
    cents=cents_from_price(fields.get('标注售价'))
    return cents is not None and cents==product['price_cents']

def catalog_for_store(db,store_id,limit=120):
    rows=db.execute('''SELECT fixed_id,display_name,page,fields_json FROM bsv_v9_record
      WHERE page IN ('C_现场成品','K_套餐组合') ORDER BY CASE page WHEN 'C_现场成品' THEN 0 ELSE 1 END, source_row LIMIT ?''',(limit,)).fetchall()
    allitems=[]
    for r in rows:
        f=json.loads(r['fields_json']);fix=r['fixed_id']
        priced=db.execute('''SELECT * FROM bsv_products WHERE id=? AND sale_enabled=1''',(fix,)).fetchone()
        ready=price_is_current(db,priced,store_id)
        approval=f.get('内容审核状态') if fix[0]=='C' else f.get('审批状态')
        allitems.append({'id':fix,'name':r['display_name'],'domain':fix[0],
            'series':str(f.get('销售系列') or ('套餐' if fix[0]=='K' else '')),
            'readable_sku':str(f.get('SKU') or ''),
            'approval':str(approval or '待核准'),'sale_enabled':bool(ready),
            'price_cents':priced['price_cents'] if ready else None,
            'listed':True,'price_source':'C_现场成品!AJ' if fix[0]=='C' else None,
            'reason':None if ready else ('AJ列标注售价为空或无效，请在Excel中补齐后同步' if fix[0]=='C' else '套餐不在C表，尚无统一售价来源')})
    return allitems
