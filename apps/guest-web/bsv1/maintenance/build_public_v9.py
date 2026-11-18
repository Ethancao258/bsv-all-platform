#!/usr/bin/env python3
"""BSV ALL V9 -> customer-facing JSON; safe field whitelist, preserve actual price values.
Source can be V9 structured export (.json) or V9 SQLite (.sqlite/.db).
Not a payment endpoint: price annotations are not approved sale prices.
"""
from __future__ import annotations
import argparse,datetime,json,re,sqlite3,sys
from pathlib import Path

BASE=Path(__file__).resolve().parent.parent
STORES={'BSVM':'密云鸡尾酒吧','BSVS':'顺义鸡尾酒吧','BSVT':'通州鸡尾酒吧','BSVF':'富民街精酿酒馆'}
CATEGORY={'环球精选经典鸡尾酒':'环球精选','特调鸡尾酒':'本季特调','经典调酒':'经典调酒','非菜单经典调酒':'更多鸡尾酒'}

def st(v):return v.strip() if isinstance(v,str) else ''
def money(v):
 if v is None or isinstance(v,bool):return None
 try:
  t=float(v)
  if not 0<=t<1000000:return None
  return int(t) if t.is_integer() else round(t,2)
 except (ValueError,TypeError,OverflowError):return None

def load_records(source:Path):
 if source.suffix.lower() in ('.sqlite','.db'):
  with sqlite3.connect(f'file:{source}?mode=ro',uri=True) as cx:
   cx.row_factory=sqlite3.Row
   rec=[]
   for r in cx.execute('SELECT id,domain,sku,status,name,fields_json FROM entity_records'):
    rec.append({'id':r['id'],'domain':r['domain'],'sku':r['sku'],'classification_status':r['status'],'fields':json.loads(r['fields_json'])})
  return rec
 if source.suffix.lower()=='.json':
  content=json.loads(source.read_text(encoding='utf-8'))
  if not isinstance(content.get('records'),list):raise ValueError('JSON没有V9 records[]')
  return content['records']
 raise ValueError('本工具只接受V9数据库.sqlite或V9结构化导出.json，不能在浏览器直接读取Excel')

# Public copy filters: do not leak staff procedures or non-final commercial terms.
PRIVATE_STORY_TOKENS=('预调','摇足','提前调好','每杯只倒','加淡奶油','最后放','改比例','员工','制作步骤','SOP','SKU','后台','出品只取','切段摆盘','打60秒','装进冰过的杯子','香草冰淇淋上淋','冰淇淋淋10毫升','用朗姆风味的冰淇淋做','制作方法','切成七块','十二颗豆肉卷炸','薯角现炸')
PRIVATE_BUNDLE_TOKENS=('上架前','待核准','待审批','后台','内部用','须锁定','SKU')
def customer_story(value):
 text=st(value)
 if any(token.lower() in text.lower() for token in PRIVATE_STORY_TOKENS):return ''
 return text

def customer_bundle_description(value,active):
 value=st(value)
 if not value:return ''
 headings={'套餐内容':'contents','包含内容':'contents','可选':'choices','商品简介':'summary','商品介绍':'summary','使用说明':'notes','购买须知':'notes'}
 groups={'summary':[],'contents':[],'choices':[],'notes':[]}
 section=None
 for raw in value.replace('\r','').split('\n'):
  line=raw.strip()
  if not line:continue
  if line in ('商品标题','商品名称'):section='skip';continue
  matched=False
  for title,key in headings.items():
   if line==title or line==title+'：' or line.startswith(title+'：'):
    section=key;rest=line[len(title):].lstrip('：').strip()
    if rest:groups[key].append(rest)
    matched=True;break
  if matched or section=='skip':continue
  if section is None:section='summary'
  if not any(tok in line for tok in PRIVATE_BUNDLE_TOKENS):groups[section].append(line)
 out=[]
 for key,title in [('summary','商品简介'),('contents','套餐内容'),('choices','可选'),('notes','使用说明')]:
  if key=='notes' and not active:continue
  if groups[key]:out.append(title+'：\n'+'\n'.join(groups[key]))
 return '\n\n'.join(out)

def build(records:list, source_title='BSV_ALL_V9'):
 store_recs=[x for x in records if x['domain']=='T']
 stores=[]
 for sid,name in STORES.items():
  rec=next((x for x in store_recs if st(x['fields'].get('门店ID'))==sid),None)
  if rec:
   stores.append({'store_id':sid,'name':st(rec['fields'].get('门店名称')) or name,'menu_type':'craft' if sid=='BSVF' else 'cocktail'})
 prices={}; ambiguous=set()
 for r in records:
  if r['domain']!='Q':continue
  f=r['fields']; sid=st(f.get('门店ID')); pid=st(f.get('商品ID'))
  if sid not in STORES or not pid or st(f.get('审核状态')) not in ('已核准','核准生效'):continue
  amount=money(f.get('核准售价'))
  if amount is None:continue
  # Official quotes need usable date; omitted date can be treated as unapproved.
  start=st(f.get('生效日期'));end=st(f.get('失效日期'))
  today=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date()
  try:
   if not start or datetime.date.fromisoformat(start[:10])>today:continue
   if end and datetime.date.fromisoformat(end[:10])<today:continue
  except ValueError:continue
  channel=st(f.get('销售渠道'))
  if channel not in ('','门店现场','店内现场','线下','堂食'):continue
  key=(sid,pid)
  if key in prices:ambiguous.add(key)
  prices[key]={'amount':amount,'status':'approved','currency':'CNY','label':'门店核准价'}
 for key in ambiguous:prices.pop(key,None)
 items=[];seen=set()
 for r in records:
  dom=r['domain'];f=r.get('fields') or {};iid=st(r['id']);sku=st(r.get('sku')) or None
  if dom=='C':
   name=st(f.get('商品名称'))
   if not name:continue
   series=st(f.get('销售系列'));l2=st(f.get('L2'))
   cat=CATEGORY.get(series)
   if not cat:
    if l2 in ('佐酒小吃','轻正餐','餐食','小吃'):cat='佐酒与分享'
    elif l2 in ('甜点','无酒精饮品','无酒精调饮','咖啡茶饮'):cat='饮品与甜点'
    else:cat='更多鸡尾酒'
   rprice=money(f.get('标注售价'))
   item={'product_id':iid,'sku':sku,'kind':'prepared','name':name,'name_en':st(f.get('英文名称')),
    'category':cat,'family':l2,'series':series,'flavor':st(f.get('展示风味说明')) or st(f.get('风味描述')),
    'flavor_tag':st(f.get('风味标签')),'story':customer_story(f.get('产品故事')),
    'alcohol':'non_alcoholic' if st(f.get('酒精属性'))=='无酒精' or l2 in ('无酒精调饮','无酒精饮品') else 'alcoholic' if st(f.get('酒精属性'))=='含酒精' or l2=='含酒精调饮' else 'unknown',
    'reference_price': {'amount':rprice,'label':'酒单标价'} if rprice is not None else None,
    'reference_prices':None,'price_by_store':{},'status':'menu_catalogue','active':True,'selectable':True,
    'contents':'','description':'','store_variant':'','photo':None}
  elif dom=='K':
   name=st(f.get('套餐名称'))
   if not name:continue
   status=st(f.get('销售状态')) or st(f.get('审批状态')) or '待核准'
   reg=money(f.get('区域参考售价'));core=money(f.get('核心参考售价'))
   content=st(f.get('套餐包含内容'))
   desc=st(f.get('完整商品文案'))
   item={'product_id':iid,'sku':sku,'kind':'bundle','name':name,'name_en':'',
    'category':'套餐与分享','family':'套餐','series':st(f.get('适用渠道')),
    'flavor':(customer_bundle_description(desc,True).split('商品简介：\n')[-1].split('\n')[0][:185] if desc else '欢迎向调酒师了解分享选择。'),
    'flavor_tag':'',
    'story':'','alcohol':'unknown',
    'reference_price':({'amount':reg if reg is not None else core,'label':'套餐参考价'} if reg is not None or core is not None else None),'reference_prices':None,
    'price_by_store':{},'status':'menu_catalogue',
    'active':True,
    'selectable':True,
    'contents':('' if any(x in content for x in PRIVATE_BUNDLE_TOKENS) else content),'description':customer_bundle_description(desc,True),'store_variant':'','photo':None}
  else:continue
  # 可选总部已核准公开风味文字：未来DB-A可提供此字段；不改变V9旧快照。
  if dom=='C' and st(f.get('对客风味文案')):
   public_flavor=customer_story(f.get('对客风味文案'))
   if public_flavor:item['public_flavor']=public_flavor
  if iid in seen:raise ValueError('重复商品ID：'+iid)
  seen.add(iid)
  # POS/门店报价Q页不影响顾客菜单的统一商品标价。
  items.append(item)
 payload={'schema':'bsv.public-menu.v2','source':source_title,
  'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
  'stores':stores,'items':items,'currency':'CNY',
  'note':'酒单价及套餐参考价供浏览，最终金额与供应由门店确认；此页不提交订单或付款。'}
 # Strict serialization allowlist: no recipe, SOP, procurement, NPS, cost, assets, staff identifiers.
 text=json.dumps(payload,ensure_ascii=False)
 for forbidden_key in ('配方文字','完整制作步骤','寻酒指引','采购价','采购链接','N需求输入','P支付输入','S场景输入','配方图文件名'):
  if f'"{forbidden_key}"' in text:raise ValueError('内部字段泄露：'+forbidden_key)
 return payload

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('source',type=Path)
 ap.add_argument('--output',type=Path,required=True)
 args=ap.parse_args()
 result=build(load_records(args.source))
 args.output.parent.mkdir(parents=True,exist_ok=True)
 args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 vals=result['items']
 stats={'items':len(vals),'prepared':sum(x['kind']=='prepared' for x in vals),'bundles':sum(x['kind']=='bundle' for x in vals),'bundle_draft':sum(x['kind']=='bundle' and not x['active'] for x in vals), 'C_with_annotated_price':sum(x['kind']=='prepared' and x['reference_price'] is not None for x in vals), 'K_with_any_reference_price':sum(x['kind']=='bundle' and x['reference_price'] is not None for x in vals),'approved_store_prices':sum(len(x['price_by_store']) for x in vals)}
 print(json.dumps(stats,ensure_ascii=False,indent=2))
 return stats
if __name__=='__main__':main()
