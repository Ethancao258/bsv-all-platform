#!/usr/bin/env python3
"""SQLite 在线一致性备份；可由 systemd timer 调用。备份后应另行异地保存。"""
import os,sqlite3,datetime,pathlib
from app import DB_PATH
if not DB_PATH.exists():raise SystemExit('数据库不存在，拒绝创建空备份')
dest=pathlib.Path(os.environ.get('BSV_BACKUP_DIR',DB_PATH.parent.parent/'backups'))
dest.mkdir(parents=True,exist_ok=True)
now=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
path=dest/f'{DB_PATH.stem}_backup_{now}.sqlite3'
with sqlite3.connect(str(DB_PATH)) as src, sqlite3.connect(str(path)) as dst:
    src.backup(dst)
    result=dst.execute('PRAGMA quick_check').fetchone()[0]
    if result!='ok':raise RuntimeError('备份完整性检查失败：'+str(result))
os.chmod(path,0o600)
print('备份成功：',path)
