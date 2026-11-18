#!/usr/bin/env python3
"""Static-only integrity audit. No cloud or network side effects."""
from pathlib import Path
import json, sys, hashlib
root=Path(__file__).resolve().parent.parent

errors=[]
def read(name):
    try: return json.loads((root/name).read_text(encoding='utf-8'))
    except Exception as exc: errors.append(f'{name}: {exc}'); return {}
lock=read('config/architecture-lock.json')
cap=read('config/circles-and-capabilities.json')
dom=read('config/domain-registry.json')
apps=read('config/app-registry.json')
own=read('config/data-ownership.json')
res=read('config/resource-registry.json')

expected=set(lock.get('frozen_top_level',[]))
actual={p.name for p in root.iterdir() if p.is_dir() and p.name != '.git'}
missing=expected-actual; extra=actual-expected
if missing: errors.append(f'Missing frozen dirs {sorted(missing)}')
if extra: errors.append(f'Unexpected top-level dirs {sorted(extra)}')

circle_ids=set(cap.get('business_circles',{}))
domains=dom.get('domains',[])
domain_ids=[x.get('id') for x in domains]
if len(domain_ids)!=len(set(domain_ids)): errors.append('duplicate domain ids')
if len(domain_ids)!=20: errors.append('domain inventory count changed without ADR')
cap_ids=[x.get('id') for x in cap.get('capabilities',[])]
if len(cap_ids)!=len(set(cap_ids)): errors.append('duplicate capability ids')
if len(cap_ids)!=17: errors.append('V5.0 capability count mismatch')
for x in cap.get('capabilities',[]):
    if x.get('circle') not in circle_ids: errors.append(f'bad circle {x}')
    if not (root/x['module_path']/'README.md').exists(): errors.append(f'missing capability README: {x["id"]}')
    for d in x.get('domain_ids',[]):
        if d not in domain_ids: errors.append(f'unknown domain {d} in {x["id"]}')
for x in domains:
    if not (root/x['root_path']/'README.md').exists(): errors.append(f'missing domain README {x["id"]}')
for x in apps.get('apps',[]):
    if not (root/x['path']/'README.md').exists(): errors.append(f'missing app README {x["id"]}')
    if x['circle'] not in circle_ids|{'cross'}: errors.append(f'unknown app circle {x["id"]}')

keys={}
for x in domains:
    for k in x['entity_keys']:
        if k in keys: errors.append(f'duplicate entity owner: {k} ({keys[k]}, {x["id"]})')
        keys[k]=x['id']
if own.get('key_owners')!=keys: errors.append('data ownership key map drift')
use=read('config/use-case-registry.json')
capset=set(cap_ids)
appset={x.get('id') for x in apps.get('apps',[])}
use_ids=[]
for u in use.get('use_cases',[]):
    use_ids.append(u.get('id'))
    if u.get('capability_id') not in capset: errors.append(f'unknown capability in usecase {u.get("id")}')
    if u.get('app_id') not in appset: errors.append(f'unknown application in usecase {u.get("id")}')
    for d in u.get('domain_ids',[]):
        if d not in domain_ids: errors.append(f'unknown domain {d} in usecase {u.get("id")}')
    if not u.get('fallback'): errors.append(f'missing fallback for {u.get("id")}')
if len(set(use_ids))!=len(use_ids): errors.append('duplicate usecase ID')
rs=[x.get('id') for x in res.get('resources',[])]
if len(rs)!=len(set(rs)): errors.append('duplicate resource ids')

src=root/'docs/governance/BSV-GOV-ARCH-2026-005_V5.0_20261118.md'
if not src.exists(): errors.append('missing V5 governance source')
elif hashlib.sha256(src.read_bytes()).hexdigest()!=lock.get('source_doc_sha256'): errors.append('original governance source modified without decision')
if not (root/'cloudbase/migrations/README.md').exists():errors.append('missing official migration location')
if (root/'database').exists():errors.append('second database root forbidden; use cloudbase and domains')
if (root/'cloudbase/migrations/schema_migrations.sql').exists():errors.append('hand-rolled migration ledger forbidden')

if errors:
    for e in errors: print('FAIL',e)
    sys.exit(1)
print(f'PASS: {len(use_ids)} mapped usecases; {len(expected)} frozen roots; {len(domain_ids)} unique domains; {len(cap_ids)} V5 capabilities; {len(apps.get("apps",[]))} UI channels; {len(keys)} unique ID owners; source SHA verified')
