"""Encrypted local archives of Database A (disaster recovery only, never permission fallback).

Production backup: pg_dump streams directly into AES-256-GCM ciphertext.
Restore requires isolated target and operator action. No production restore subcommand.
"""
import argparse
import base64
import hashlib
import io
import json
import os
import secrets
import shutil
import sqlite3
import struct
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from .config import load_settings

MAGIC=b"BSVIDBACKUP2\x00"
CHUNK=1024*256


def get_key(path):
    if not path:
        raise RuntimeError("BSV_BACKUP_KEY_FILE missing; do not back up unencrypted")
    st=os.stat(path)
    if st.st_mode & 0o077:
        raise RuntimeError("Backup key file permissions must be 0600")
    data=Path(path).read_bytes().strip()
    key=base64.urlsafe_b64decode(data)
    if len(key)!=32:
        raise RuntimeError("Expected 32 byte AES-256 key")
    return key


def make_key(path):
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(target,os.O_CREAT|os.O_WRONLY|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(base64.urlsafe_b64encode(secrets.token_bytes(32))+b"\n")
    except Exception:
        target.unlink(missing_ok=True)
        raise
    print("LOCAL_BACKUP_KEY_GENERATED: preserve separately, never commit this key")


def _pg_env(url):
    u=urlparse(url.replace("postgresql+psycopg", "postgresql"))
    if u.scheme!="postgresql":raise RuntimeError("PostgreSQL connection required")
    if not u.hostname or not u.path.strip("/"):raise RuntimeError("Incomplete PostgreSQL URL")
    env=os.environ.copy()
    env.update({"PGHOST":u.hostname,"PGPORT":str(u.port or 5432),"PGUSER":unquote(u.username or ""),
                "PGDATABASE":unquote(u.path.lstrip("/")),"PGPASSWORD":unquote(u.password or ""),
                "PGSSLMODE":os.getenv("BSV_DB_SSLMODE", "verify-full")})
    return env


def _input_stream(settings):
    url=settings.db_a_url
    if url.startswith("sqlite"):
        if settings.env!="isolated":raise RuntimeError("SQLite backup only in isolated mode")
        path=url.split("///",1)[1]
        return "sqlite", Path(path), None
    if url.startswith("postgresql+psycopg://"):
        return "postgresql", None, _pg_env(url)
    raise RuntimeError("Unsupported database backup source A")


def create_archive(settings=None):
    s=settings or load_settings()
    key=get_key(s.backup_key_file)
    kind,sqlite_path,pg_env=_input_stream(s)
    target=Path(s.backup_dir);target.mkdir(parents=True,exist_ok=True,mode=0o700)
    if target.stat().st_mode & 0o077:
        os.chmod(target,0o700)
    timestamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    nonce=os.urandom(12)
    # Keep the pre-catalog identity archive filename and authenticated source
    # metadata stable across f6d8 and newer releases. Catalog is a distinct
    # source, never an alias for the legacy identity-A archive.
    source_label=os.getenv("BSV_BACKUP_SOURCE_LABEL", "identity-A")
    if source_label not in {"identity-A", "catalog"}:
        raise RuntimeError("Invalid backup source label")
    archive_source = "A" if source_label == "identity-A" else "catalog"
    output=target / f"{source_label}-{timestamp}-{secrets.token_hex(3)}.bsvenc"
    tmp=output.with_suffix(".tmp")
    proc=None
    sqlite_temp=None
    try:
        if kind=="sqlite":
            fd,path=tempfile.mkstemp(prefix="bsv-sqlite-snapshot-",dir=str(target));os.close(fd)
            os.chmod(path,0o600);sqlite_temp=Path(path)
            source=sqlite3.connect(str(sqlite_path));snapshot=sqlite3.connect(str(sqlite_temp))
            try:source.backup(snapshot)
            finally:source.close();snapshot.close()
            source_file=sqlite_temp.open("rb")
        else:
            if not shutil.which("pg_dump"):
                raise RuntimeError("pg_dump not installed; cannot claim PostgreSQL backup")
            proc=subprocess.Popen(["pg_dump","--format=custom","--no-owner","--no-privileges"],
                                  stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=pg_env)
            source_file=proc.stdout
        encryptor=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor()
        head=json.dumps({"created_at":timestamp,"source":archive_source,"type":kind,"format":2},sort_keys=True).encode()
        encryptor.authenticate_additional_data(head)
        fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"wb") as dest,source_file:
            dest.write(MAGIC+struct.pack(">I",len(head))+head+nonce)
            while block:=source_file.read(CHUNK):
                dest.write(encryptor.update(block))
            dest.write(encryptor.finalize())
            dest.write(encryptor.tag)
            dest.flush();os.fsync(dest.fileno())
        if proc:
            code=proc.wait()
            if code:raise RuntimeError(f"pg_dump exit {code}: archive discarded")
        tmp.rename(output)
        digester=hashlib.sha256()
        with output.open("rb") as snapshot:
            while block:=snapshot.read(CHUNK):
                digester.update(block)
        checksum=digester.hexdigest()
        print(json.dumps({"archive":str(output),"sha256":checksum,"source":archive_source,"encrypted":True},ensure_ascii=False))
        return output
    except Exception:
        tmp.unlink(missing_ok=True)
        if proc and proc.poll() is None:proc.kill();proc.wait()
        raise
    finally:
        if sqlite_temp:sqlite_temp.unlink(missing_ok=True)


def decrypt_to_isolated(archive, settings=None, target=None, dry_run=True):
    s=settings or load_settings()
    if s.env!="isolated":raise RuntimeError("Restore is isolated-only; never use on a production mode")
    key=get_key(s.backup_key_file)
    archive=Path(archive)
    with archive.open("rb") as src:
        if src.read(len(MAGIC))!=MAGIC:raise RuntimeError("Invalid encrypted archive")
        length=struct.unpack(">I",src.read(4))[0]
        if length>4096:raise RuntimeError("Invalid archive header")
        head=src.read(length)
        meta=json.loads(head)
        nonce=src.read(12)
        src.seek(0,os.SEEK_END);size=src.tell()
        payload_offset=len(MAGIC)+4+length+12
        if size < payload_offset+16:raise RuntimeError("Archive truncated")
        src.seek(size-16);tag=src.read(16);src.seek(payload_offset)
        decryptor=Cipher(algorithms.AES(key),modes.GCM(nonce,tag)).decryptor()
        decryptor.authenticate_additional_data(head)
        with tempfile.NamedTemporaryFile(dir=s.backup_dir,prefix="recovery-",delete=False) as scratch:
            plain=Path(scratch.name);os.chmod(plain,0o600)
            try:
                toread=size-payload_offset-16
                while toread:
                    block=src.read(min(CHUNK,toread))
                    if not block:raise RuntimeError("Archive truncated")
                    scratch.write(decryptor.update(block));toread-=len(block)
                scratch.write(decryptor.finalize())
            except Exception:
                scratch.close();plain.unlink(missing_ok=True)
                raise
    try:
        if dry_run:
            print(json.dumps({"integrity":"AES_GCM_VERIFIED","meta":meta,"restore":"DRY_RUN_NO_WRITE"}))
            return
        if not target or any(x in target.lower() for x in ("prod", "cloudbase")):
            raise RuntimeError("Explicit disposable isolated restore target required")
        if meta["type"]=="sqlite":
            dest=Path(target)
            if dest.exists():raise RuntimeError("Target must not exist to avoid overwrite")
            shutil.copyfile(plain,dest);os.chmod(dest,0o600)
        elif meta["type"]=="postgresql":
            from dataclasses import replace
            from .cli import isolated_guard
            isolated_guard(replace(s, db_a_url=target))
            if _pg_env(target)["PGDATABASE"] == _pg_env(s.db_a_url)["PGDATABASE"]:
                raise RuntimeError("Restore target must be distinct from source A")
            if not shutil.which("pg_restore"):raise RuntimeError("pg_restore not installed")
            env=_pg_env(target.replace("postgresql+psycopg","postgresql"))
            subprocess.run(["pg_restore","--exit-on-error","--single-transaction","--no-owner","--no-privileges",
                            "--dbname",env["PGDATABASE"],str(plain)],
                           check=True,env=env)
        else:raise RuntimeError("Unrecognized archive type")
        print("ISOLATED_RESTORE_COMPLETE")
    finally:plain.unlink(missing_ok=True)


def archives(settings=None):
    s=settings or load_settings()
    return sorted(Path(s.backup_dir).glob("identity-A-*.bsvenc"), key=lambda p:p.name,reverse=True)


def prune_archives(settings=None, keep_days=30, keep_last=7):
    """Conservative retention: never remove the most recent N archives."""
    from datetime import timedelta
    s=settings or load_settings()
    if keep_days<7 or keep_last<7:
        raise RuntimeError("Retention floor is seven days and seven copies")
    ordered=archives(s)
    cutoff=datetime.now(timezone.utc)-timedelta(days=keep_days)
    deleted=[]
    for i,item in enumerate(ordered):
        if i<keep_last:
            continue
        if datetime.fromtimestamp(item.stat().st_mtime,timezone.utc)<cutoff:
            item.unlink()
            deleted.append(item.name)
    print(json.dumps({"checked":len(ordered),"pruned":deleted,"last_n_protected":keep_last}))


def main():
    parser=argparse.ArgumentParser()
    subs=parser.add_subparsers(dest="cmd",required=True)
    g=subs.add_parser("generate-key");g.add_argument("--path",required=True)
    subs.add_parser("create")
    subs.add_parser("list")
    p=subs.add_parser("prune");p.add_argument("--keep-days",type=int,default=30);p.add_argument("--keep-last",type=int,default=7)
    r=subs.add_parser("restore");r.add_argument("--archive",required=True);r.add_argument("--target");r.add_argument("--apply-isolated",action="store_true")
    args=parser.parse_args()
    if args.cmd=="generate-key":make_key(args.path)
    if args.cmd=="create":create_archive()
    if args.cmd=="list":print(json.dumps([str(x) for x in archives()],ensure_ascii=False))
    if args.cmd=="prune":prune_archives(keep_days=args.keep_days,keep_last=args.keep_last)
    if args.cmd=="restore":decrypt_to_isolated(args.archive,target=args.target,dry_run=not args.apply_isolated)


if __name__=="__main__":main()
