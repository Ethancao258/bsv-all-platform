"""True consistent PostgreSQL dump (if credentials permit), encrypted locally using streaming AES-256-GCM."""
import argparse,hashlib,json,os,secrets,shutil,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from services.api.supply.config import load_settings
MAGIC=b'BSVPG02\0'

def key_from_env():
    val=os.environ.get('BSV_BACKUP_AES256_KEY_HEX','')
    if len(val)!=64:raise RuntimeError('BSV_BACKUP_AES256_KEY_HEX 必须是保管在环境变量中的64位十六进制密钥')
    try:return bytes.fromhex(val)
    except ValueError:raise RuntimeError('备份密钥格式错误')

def encrypted_dump(out_dir:Path):
    if not shutil.which('pg_dump') or not shutil.which('pg_restore'):raise RuntimeError('缺少 pg_dump/pg_restore 客户端')
    # Only explicit, privileged DB backup credentials. Never assume an HTTP API snapshot covers every SQL table.
    env={k:os.environ[k] for k in ('PATH','HOME','PGSERVICE','PGHOST','PGPORT','PGUSER','PGDATABASE','PGPASSFILE','PGSSLMODE') if k in os.environ}
    if not env.get('PGSERVICE') and not (env.get('PGHOST') and env.get('PGDATABASE') and env.get('PGUSER')):
        raise RuntimeError('请配置 PG* 备份连接环境变量；不从应用配置猜数据库密码')
    key=key_from_env();out_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.restricted-dump-',dir=out_dir) as td:
        os.chmod(td,0o700)
        plain=Path(td)/'dump.custom'
        p=subprocess.run(['pg_dump','--format=custom','--no-owner','--no-acl','--file',str(plain)],env=env,capture_output=True,text=True,timeout=3600)
        if p.returncode!=0:raise RuntimeError('pg_dump 失败：'+p.stderr[-1200:])
        if plain.stat().st_size<100:raise RuntimeError('数据库导出异常小，请核验')
        ck=subprocess.run(['pg_restore','--list',str(plain)],capture_output=True,text=True,timeout=180)
        if ck.returncode!=0:raise RuntimeError('pg_restore 无法识别备份文件')
        nonce=secrets.token_bytes(12)
        enc=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor()
        target=out_dir/('postgres_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+secrets.token_hex(3)+'.bsvenc')
        temp=target.with_suffix('.tmp')
        sha=hashlib.sha256()
        try:
            fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as o,open(plain,'rb') as i:
                o.write(MAGIC);o.write(nonce)
                while True:
                    ch=i.read(1024*1024)
                    if not ch:break
                    sha.update(ch);o.write(enc.update(ch))
                o.write(enc.finalize());o.write(enc.tag)
                o.flush();os.fsync(o.fileno())
            temp.replace(target)
        finally:
            if temp.exists():temp.unlink()
        return {'file':str(target),'dump_sha256':sha.hexdigest(),'encrypted_size':target.stat().st_size,'note':'须独立恢复演练；当前操作只验证归档结构'}

def decrypt_archive(path:Path,dest:Path):
    if dest.exists():raise RuntimeError('拒绝覆盖任何已有恢复文件')
    key=key_from_env()
    with open(path,'rb') as f:
        if f.read(len(MAGIC))!=MAGIC:raise RuntimeError('不是BSVPG02备份')
        nonce=f.read(12);f.seek(-16,2);tag=f.read(16)
        start=len(MAGIC)+12;end=path.stat().st_size-16
        dec=Cipher(algorithms.AES(key),modes.GCM(nonce,tag)).decryptor()
        f.seek(start);left=end-start
        dest.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        try:
            with os.fdopen(fd,'wb') as o:
                while left>0:
                    ch=f.read(min(left,1024*1024));left-=len(ch)
                    o.write(dec.update(ch))
                o.write(dec.finalize())
        except Exception:
            dest.unlink(missing_ok=True)
            raise
    return str(dest)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--restore-input');ap.add_argument('--restore-output')
    args=ap.parse_args()
    if args.restore_input:
        if not args.restore_output:ap.error('必须给 --restore-output')
        print('解密备份到待验收文件（不会执行数据库恢复）：',decrypt_archive(Path(args.restore_input),Path(args.restore_output)))
    else:
        print(encrypted_dump(load_settings().backup_dir))
