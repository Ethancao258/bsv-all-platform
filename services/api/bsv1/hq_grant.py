#!/usr/bin/env python3
"""Grant/revoke explicit headquarters privileges; invoked only via server-side sudo by Agent."""
import argparse
import app, bsv_one
p=argparse.ArgumentParser(description='BSV ONE HQ role provisioning; requires staging mode')
p.add_argument('operation', choices=['grant','revoke','list'])
p.add_argument('--code',default='')
args=p.parse_args()
if app.MODE!='staging':raise SystemExit('只能在私有 staging 环境运行')
app.init_db()
if args.operation=='list':
    with app.db_read() as db:
        for x in db.execute('SELECT s.staff_code,r.role FROM bsv_hq_roles r JOIN staff s ON s.id=r.staff_id'):
            print(x['staff_code'],x['role'])
    raise SystemExit(0)
if not args.code or args.code.upper().endswith('-DEMO'):raise SystemExit('指定非演示的员工 code')
with app.tx() as db:
    staff=db.execute('SELECT id,role,enabled FROM staff WHERE staff_code=?',(args.code.upper(),)).fetchone()
    if not staff or staff['role']!='MANAGER' or not staff['enabled']:raise SystemExit('仅可以授权已启用的门店经理')
    if args.operation=='grant':
        db.execute("INSERT OR IGNORE INTO bsv_hq_roles(staff_id,role,granted_at) VALUES(?,'HQ_ADMIN',?)",(staff['id'],bsv_one.now()))
    else:
        db.execute('DELETE FROM bsv_hq_roles WHERE staff_id=?',(staff['id'],))
        db.execute('DELETE FROM sessions WHERE staff_id=?',(staff['id'],))
    bsv_one.event(db,dict(staff), 'access',args.operation.upper(),'HQ',{'staff_code':args.code.upper()})
print('HQ_ROLE_OK',args.operation,args.code.upper())
