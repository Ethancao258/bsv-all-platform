#!/usr/bin/env python3
"""No-dependency deterministic tests for V9 public read model builder."""
import sys,json,tempfile,subprocess
from pathlib import Path
ROOT=(Path(__file__).resolve().parents[2] / 'apps/guest-web/bsv1')
sys.path.insert(0,str(ROOT/'maintenance'))
import build_public_v9
from build_public_v9 import build
records=[
 {'id':'T000001','domain':'T','sku':None,'fields':{'门店ID':'BSVM','门店名称':'密云鸡尾酒吧'}},
 {'id':'C000001','domain':'C','sku':'CAAAA00001','fields':{'商品名称':'测试调酒','英文名称':'Test drink','销售系列':'经典调酒','标注售价':'88','配方文字':'私人配方秘密','产品故事':'一杯来自城市的故事','酒精属性':'含酒精','风味描述':'清爽'}},
 {'id':'C000002','domain':'C','sku':None,'fields':{'商品名称':'无价调酒','销售系列':'经典调酒','标注售价':None,'配方文字':'不得公开'}},
 {'id':'K000001','domain':'K','sku':'KABCA00001','fields':{'套餐名称':'小聚套餐','区域参考售价':'128','完整商品文案':'商品简介：\n三人相聚','套餐包含内容':'三杯酒'}},
]
obj=build(records,'UNIT_TEST')
assert len(obj['items'])==3
assert obj['items'][0]['reference_price']['amount']==88
assert obj['items'][1]['reference_price'] is None
assert obj['items'][2]['reference_price']['amount']==128
raw=json.dumps(obj,ensure_ascii=False)
assert '私人配方秘密' not in raw and '配方文字' not in raw
with tempfile.TemporaryDirectory() as t:
 src=Path(t)/'input.json';dst=Path(t)/'public.json'
 src.write_text(json.dumps({'records':records},ensure_ascii=False),encoding='utf-8')
 p=subprocess.run([sys.executable,str(ROOT/'maintenance/build_public_v9.py'),str(src),'--output',str(dst)],capture_output=True,text=True)
 assert p.returncode==0,(p.stdout,p.stderr)
 assert dst.exists()
 stats=json.loads(p.stdout)
 assert stats['K_with_any_reference_price']==1
 assert stats['C_with_annotated_price']==1
print('PASS: 3 public items; private fields excluded; missing prices preserved; direct CLI price stats fixed')
