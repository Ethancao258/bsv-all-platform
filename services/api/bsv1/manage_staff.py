#!/usr/bin/env python3
"""仅通过服务器终端管理员工账号；不通过网页暴露新建/重置权限。"""
import argparse, getpass, re, secrets
from pathlib import Path
import app
import bsv_layouts

# 门店从数据目录读取；新增门店不要求修改账号管理程序。
STORES = {item['store_id'] for item in bsv_layouts.registry()}
# Additional stores created by HQ are validated against SQLite after init_db.

def ask_pin():
    pin=getpass.getpass('输入 8—12 位独立数字 PIN（输入不显示）：').strip()
    again=getpass.getpass('再次输入相同 PIN：').strip()
    if not re.fullmatch(r'\d{8,12}',pin):raise SystemExit('拒绝创建：PIN 必须是8—12位数字，不能使用演示PIN')
    if pin in ('246810','135790','12345678','00000000','11111111','88888888','123456789','1234567890'):
        raise SystemExit('拒绝创建：PIN 过于常见')
    if not secrets.compare_digest(pin,again):raise SystemExit('两次输入不一致')
    return pin

def main():
    p=argparse.ArgumentParser(description='BSV1 云端验收员工账号管理')
    sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('add',help='创建新账号，绑定一家门店')
    a.add_argument('--code',required=True);a.add_argument('--store',required=True)
    a.add_argument('--role',choices=['STAFF','MANAGER'],default='STAFF')
    g=sub.add_parser('grant',help='对现有账号增加门店访问权，仍需要登录时明确选店')
    g.add_argument('--code',required=True);g.add_argument('--store',required=True)
    d=sub.add_parser('disable',help='停用账号并退出其所有登录会话')
    d.add_argument('--code',required=True)
    r=sub.add_parser('reset-pin',help='重置已有账号 PIN 并退出所有会话')
    r.add_argument('--code',required=True)
    sub.add_parser('list',help='只输出账号代码、角色、授权门店，不输出PIN')
    args=p.parse_args()
    if app.MODE!='staging':raise SystemExit('账号管理仅允许 BSV_MODE=staging 环境使用')
    app.init_db()
    if args.cmd=='list':
        with app.db_read() as db:
            for row in db.execute('''SELECT s.staff_code,s.role,s.enabled,GROUP_CONCAT(a.store_id) AS stores
                FROM staff s LEFT JOIN staff_store_access a ON a.staff_id=s.id
                GROUP BY s.id ORDER BY s.staff_code'''):
                print(row['staff_code'],row['role'],'启用' if row['enabled'] else '已停用',row['stores'] or '-')
        return
    if args.cmd in ('add','grant'):
        with app.db_read() as db:
            if not db.execute('SELECT 1 FROM stores WHERE id=?',(args.store,)).fetchone():
                raise SystemExit('门店未在 BSV1 数据库中注册')
    code=args.code.strip().upper()
    if not re.fullmatch(r'[A-Z0-9_-]{3,48}',code):raise SystemExit('员工代码格式无效（3—48位英文大写/数字/-/_）')
    demo_codes={entry['store_id']+'-'+acct['suffix']
                for entry in bsv_layouts.registry()
                for acct in entry.get('local_demo_accounts',[])}
    if code in demo_codes or code.endswith('-DEMO'):
        raise SystemExit('禁止启用演示账号或使用演示身份')
    pin=ask_pin() if args.cmd in ('add','reset-pin') else None
    with app.tx() as db:
        old=db.execute('SELECT * FROM staff WHERE staff_code=?',(code,)).fetchone()
        if args.cmd=='add':
            if old:raise SystemExit('员工代码已存在：如需增加授权请使用 grant 命令')
            salt=secrets.token_bytes(16)
            staff_id=app.uid()
            db.execute('INSERT INTO staff(id,staff_code,pin_salt,pin_digest,role,enabled) VALUES (?,?,?,?,?,1)',
                       (staff_id,code,salt.hex(),app.pin_hash(pin,salt),args.role))
            db.execute('INSERT INTO staff_store_access(staff_id,store_id) VALUES (?,?)',(staff_id,args.store))
            print('已创建',code,'授权',args.store,'角色',args.role)
        else:
            if not old:raise SystemExit('员工代码不存在')
            if args.cmd=='grant':
                db.execute('INSERT OR IGNORE INTO staff_store_access(staff_id,store_id) VALUES (?,?)',(old['id'],args.store))
                print('已授权',code,args.store)
            elif args.cmd=='disable':
                db.execute('UPDATE staff SET enabled=0 WHERE id=?',(old['id'],))
                db.execute('DELETE FROM sessions WHERE staff_id=?',(old['id'],))
                print('已停用',code)
            elif args.cmd=='reset-pin':
                salt=secrets.token_bytes(16)
                db.execute('UPDATE staff SET pin_salt=?,pin_digest=? WHERE id=?',
                           (salt.hex(),app.pin_hash(pin,salt),old['id']))
                db.execute('DELETE FROM sessions WHERE staff_id=?',(old['id'],))
                print('已重置 PIN 并清除现有会话：',code)

if __name__=='__main__':main()
