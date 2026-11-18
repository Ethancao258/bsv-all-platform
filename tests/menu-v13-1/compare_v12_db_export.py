#!/usr/bin/env python3
"""Optional: verify the V13 public snapshot against the external V1.2 portable DB export.
The private DB archive must be supplied by the operator and is NOT included in the public menu package.
"""
import sys, json,zipfile
from pathlib import Path
ROOT=(Path(__file__).resolve().parents[2] / 'apps/guest-web/bsv1')
sys.path.insert(0,str(ROOT/'maintenance'))
from build_public_v9 import build
if len(sys.argv)!=2:
 print('USAGE python tests/compare_v12_db_export.py /absolute/path/BSV_ALL_PG_V1.2_PORTABLE.zip')
 sys.exit(2)
archive=Path(sys.argv[1]);assert archive.is_file()
with zipfile.ZipFile(archive) as z:
 rows=json.loads(z.read('cloud_dump/bsv_import_rows.json'))
records=[{'id':r['stable_id'],'domain':r['sheet_code'],'sku':r['sku'],
 'fields':{k:(v.get('v') if isinstance(v,dict) else v) for k,v in r['raw_data'].items() if k not in 'ABCDEFGHI'}}
 for r in rows if r['section']=='record']
fresh=build(records,source_title='BSV_ALL_V9')['items']
released=json.loads((ROOT/'site/cocktail/data/menu-public.json').read_text())['items']
a={r['product_id']:r for r in fresh};b={r['product_id']:r for r in released}
assert len(fresh)==len(released)==84
assert a==b,'The database derived read model differs from published V13 items'
print('PASS: 84 product identities and every public product field match DB V1.2 export; order normalized by immutable ID')
