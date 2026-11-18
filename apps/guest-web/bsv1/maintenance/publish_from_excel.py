#!/usr/bin/env python3
"""BSV ALL V9 Excel -> 仅对客的商品/套餐JSON（内部工具，不放网站目录）。

运行：python3 publish_from_excel.py /absolute/path/BSV_ALL_V9.xlsx --output /path/to/menu-public.json

定价约定：
- C 现场成品仅取 Excel 列 AJ「标注售价」，门店间完全一致；无价返回 null。
- K 套餐没有 C!AJ，优先 K「区域参考售价」，否则「核心参考售价」；统一展示为“套餐参考价”。
- 所有 C、K 记录公开并允许加入选酒单（依据总部本次指令）。
- 仍是顾客向调酒师出示的选酒意向；此程序不处理真实支付。
"""
from __future__ import annotations
import argparse, json, os, tempfile
from pathlib import Path
from parse_v9_excel import build as parse_excel
from build_public_v9 import build as make_public

def run(src: Path, dst: Path):
    if not src.is_file(): raise FileNotFoundError(src)
    with tempfile.TemporaryDirectory(prefix='bsv_publish_') as tmp:
        temp=Path(tmp)
        parse_excel(str(src), str(temp/'stage.sqlite'), str(temp/'structured.json'))
        records=json.loads((temp/'structured.json').read_text(encoding='utf8'))['records']
        data=make_public(records,source_title='BSV_ALL_V9')
        c=[x for x in data['items'] if x['kind']=='prepared']
        k=[x for x in data['items'] if x['kind']=='bundle']
        # 安全约束：不能创建按门店不同的报价，不允许擅自生成未知的金额。
        assert all(not i.get('price_by_store') for i in data['items'])
        assert all(x['active'] and x['selectable'] for x in data['items'])
        assert len(set(i['product_id'] for i in data['items']))==len(data['items'])
        data['note']='现场成品统一采用C_现场成品AJ列标注售价；套餐参考价来自K_套餐组合。客人可选，最终由调酒师下单并确认实际优惠。'
        dst.parent.mkdir(parents=True,exist_ok=True)
        out=dst.with_suffix('.tmp')
        out.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
        os.replace(out,dst)
        return {'prepared':len(c),'prepared_priced':sum(x['reference_price'] is not None for x in c),
                'prepared_no_price':sum(x['reference_price'] is None for x in c),'bundles':len(k),
                'bundle_priced':sum(x['reference_price'] is not None for x in k),'total_orderable':len(data['items'])}
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('workbook',type=Path);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();print(json.dumps(run(args.workbook,args.output),ensure_ascii=False,indent=2))
