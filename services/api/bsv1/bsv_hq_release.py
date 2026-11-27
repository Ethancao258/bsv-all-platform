"""Isolated catalog release operator. Does not modify POS sales or production.
Run from repository root with the original restricted catalog-import environment.
The browser never gets the signing key or the catalog owner connection.
"""
from __future__ import annotations
import argparse
import fcntl
import getpass
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime,timezone
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from bsv_catalog_import import (_verified_package, _connect, _active_source, _catalog_layout_state,
    create_approval, import_package, activate_source_revision, sha256)
from bsv_catalog_workbook_preview import _validate_xlsx_bytes
from bsv_hq_candidate import verify_draft_change

def refuse(msg):
    raise ValueError(msg)

def read_draft(root,key):
    if not re.fullmatch(r"[a-f0-9]{32}",key):refuse("草稿ID错误")
    path=root/(key+".json")
    if path.is_symlink() or not path.is_file():refuse("草稿不存在")
    d=json.loads(path.read_text(encoding="utf-8"))
    if d.get("id")!=key or d.get("status")!="RELEASE_REQUESTED":refuse("不是待发布草稿")
    if not d.get("reviewed_by") or d.get("created_by")==d["reviewed_by"]:refuse("双人审核证据缺失")
    if d.get("legal_entity")!=os.getenv("BSV_HQ_CATALOG_LEGAL_ENTITY_ID") or not d.get("legal_entity"):
        refuse("法人范围不匹配")
    if d.get("release_requested_by")!=d["reviewed_by"]:refuse("发布申请人须为独立审核人")
    return d

def require_grants(d):
    from services.api.identity.config import load_settings
    from services.api.identity.database import SourceRouter
    from domains.workforce.identity.models import AuthLink
    from domains.workforce.identity.core import has_action
    from sqlalchemy import select
    settings=load_settings()
    from bsv_catalog_live import live_enabled
    if settings.env=="isolated":
        if not os.getenv("BSV_DB_A_URL"):refuse("未明确配置原隔离身份A")
    elif not live_enabled() or settings.env!="production" or settings.auth_provider!="cloudbase_jwks" or not settings.cookie_secure:
        refuse("未配置正式统一身份A及安全认证")
    router=SourceRouter(settings)
    try:
        with router.session() as db:
            for tr,actions in [(d["created_by"],["hq.catalog.draft","hq.catalog.confidential"]),
                               (d["reviewed_by"],["hq.catalog.review","hq.catalog.confidential","hq.catalog.release.request"])]:
                subjects=list(db.scalars(select(AuthLink.auth_subject_id).where(AuthLink.tr_code==tr,AuthLink.revoked_at.is_(None))))
                if not any(all(has_action(db,sub,action,None,d["legal_entity"]) for action in actions) for sub in subjects):
                    refuse("提交或审核人员已失去当前授权")
    finally:
        router.a.dispose()

def safe_extract(archive,folder):
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size>128*1024*1024:
        refuse("候选包路径或大小异常")
    with ZipFile(archive) as z:
        infos=z.infolist();names=[i.filename for i in infos]
        if len(names)!=len(set(names)) or len(infos)>4096 or sum(i.file_size for i in infos)>512*1024*1024:
            refuse("候选包超出限制")
        for i in infos:
            p=Path(i.filename)
            if p.is_absolute() or ".." in p.parts or "\\" in i.filename or i.is_dir() or stat.S_ISLNK(i.external_attr>>16):
                refuse("候选包成员非法")
            target=folder/p;target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            with z.open(i) as src,target.open("xb") as out:shutil.copyfileobj(src,out)

def current_sha():
    conn=_connect()
    try:
        from bsv_catalog_live import live_enabled,require_live_layout
        if live_enabled():require_live_layout(conn)
        else:
            state,_=_catalog_layout_state(conn)
            if state!="MANAGED_SCHEMA":refuse("现有隔离库未完成审核迁移")
        return _active_source(conn)
    finally:conn.close()

def assert_source(digest,root,catalog_dir):
    for p in (root/(digest+".xlsx"),catalog_dir/"versions"/(digest+".xlsx")):
        if p.is_file() and not p.is_symlink() and sha256(p)==digest:return p
    refuse("缺少与来源SHA一致的私有原始Excel")

def receipt(root,key,result):
    st=root.stat()
    path=root/(key+".release.json")
    if path.exists() or path.is_symlink():refuse("发布回执已存在，请先核对")
    fd,tmp=tempfile.mkstemp(prefix=".release-",dir=root)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            if os.geteuid()==0:os.fchown(f.fileno(),st.st_uid,st.st_gid)
            json.dump(result,f,ensure_ascii=False,sort_keys=True)
            f.flush();os.fsync(f.fileno())
        os.link(tmp,path)
    finally:Path(tmp).unlink(missing_ok=True)

def execute(args):
    from bsv_catalog_live import import_enabled
    if not import_enabled():refuse("未取得当前环境明确的目录发布授权")
    root=args.draft_root
    if not root.is_absolute() or not root.is_dir() or root.is_symlink() or root.stat().st_mode&0o077:
        refuse("草稿根目录不安全")
    approval_dir=args.approval_dir
    if not approval_dir.is_absolute() or not approval_dir.is_dir() or approval_dir.is_symlink() or approval_dir.stat().st_mode&0o077 or approval_dir.stat().st_uid!=os.geteuid():
        refuse("审批目录必须独立且为签发人私有")
    if root.resolve()==approval_dir.resolve() or root.resolve() in approval_dir.resolve().parents:
        refuse("审批密钥和凭证不能放在网页草稿目录内")
    fd=os.open(approval_dir/".hq-release.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"r+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        d=read_draft(root,args.draft_id);require_grants(d)
        baseline=d["baseline_sha256"]
        if not re.fullmatch(r"[a-f0-9]{64}",baseline):refuse("活动SHA无效")
        active=current_sha()
        rollback=d["kind"]=="rollback"
        if rollback:
            target=d["record_id"];archive=args.rollback_archive
            if archive is None:refuse("需从既有私有版本归档提供目标原包")
        else:
            package=d.get("package") or {}
            archive_sha=package.get("archive_sha256","")
            target=package.get("source_sha256","")
            if not re.fullmatch(r"[a-f0-9]{64}",archive_sha):refuse("候选包未校验")
            archive=root/(archive_sha+".zip")
            if archive.is_symlink() or not archive.is_file() or sha256(archive)!=archive_sha:refuse("候选包已改变")
        if not re.fullmatch(r"[a-f0-9]{64}",target) or target==baseline:refuse("目标版本无效")
        catalog_dir=args.catalog_dir
        original=assert_source(target,root,catalog_dir)
        old=assert_source(baseline,root,catalog_dir)
        with tempfile.TemporaryDirectory(prefix="bsv-hq-release-",dir=approval_dir) as tmp:
            folder=Path(tmp)
            # Copy the web-owned archive into operator-private storage before
            # extracting/signing; never approve mutable browser-owned bytes.
            snapshot=folder/"snapshot.zip"
            if archive.is_symlink() or not archive.is_file() or archive.stat().st_size>128*1024*1024:refuse("候选包异常")
            with archive.open("rb") as src,snapshot.open("xb") as out:shutil.copyfileobj(src,out)
            if not rollback and sha256(snapshot)!=d["package"]["archive_sha256"]:refuse("候选包复制后不匹配")
            extracted=folder/"package";extracted.mkdir(mode=0o700)
            safe_extract(snapshot,extracted)
            folder=extracted;archive=snapshot
            manifest,archive_sha,_=_verified_package(folder,archive)
            originals=list((folder/"original").glob("*.xlsx"))
            if len(originals)!=1 or sha256(originals[0])!=target or manifest["source_sha256"]!=target:
                refuse("规范包原始Excel不匹配")
            _validate_xlsx_bytes(original.read_bytes())
            if not rollback:
                if sha256(folder/"manifest.json")!=d["package"]["manifest_sha256"]:refuse("清单已改变")
                from bsv_hq_sale_gate import validate_raw_change,detailed_changes
                gate=validate_raw_change(old,originals[0]);details=detailed_changes(old,originals[0])
                if details["blocked_count"] or details["truncated"]:refuse("候选含未经核验的数据变化")
                if gate["bundle_aux_changed"] and d["kind"]!="excel":refuse("套餐子区未独立核验")
                if d["kind"]=="excel" and details!=d.get("preview",{}).get("changes",{}).get("cell_review"):refuse("已审核细项与发布包不匹配")
                verify_draft_change(d,old,originals[0])
            if active!=baseline:
                # A crash after PG commit but before receipt never triggers a
                # second write. A separate operator must reconcile the audit.
                refuse("活动版本已改变；检查PG审计，禁止盲目重试")
            info={"status":"PREFLIGHT_OK_NOT_APPLIED","draft_id":d["id"],"action":"activate" if rollback else "import",
                  "baseline_sha256":baseline,"target_sha256":target,"archive_sha256":archive_sha}
            if not args.apply:return info
            if args.confirm_isolated!=baseline:refuse("显式确认必须填写当前活动SHA")
            if (root/(d["id"]+".release.json")).exists():refuse("已有发布回执")
            approval=approval_dir/(d["id"]+".approval.json")
            if approval.exists() or approval.is_symlink():refuse("已有签名审批，先审计再恢复")
            approver=os.environ.get("SUDO_USER") or getpass.getuser()
            create_approval(folder,archive,approver=approver,change_id="HQ-CATALOG/"+d["id"],
                            expected_active_source_sha256=baseline,output=approval,
                            action="activate" if rollback else "import")
            require_grants(d)
            result=activate_source_revision(target,folder,archive,approval) if rollback else import_package(folder,archive,approval)
            if current_sha()!=target:refuse("PG活动版本未确认，停止；不得重复写入")
            info.update(status="RAW_REVISION_ACTIVE",result_status=result["status"],
                        completed_at=datetime.now(timezone.utc).isoformat(),sale_projection="UNCHANGED")
            receipt(root,d["id"],info)
            return info

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--draft-root",type=Path,required=True);p.add_argument("--draft-id",required=True)
    p.add_argument("--approval-dir",type=Path,required=True);p.add_argument("--catalog-dir",type=Path,required=True)
    p.add_argument("--rollback-archive",type=Path);p.add_argument("--apply",action="store_true")
    p.add_argument("--confirm-isolated")
    args=p.parse_args()
    try:print(json.dumps(execute(args),ensure_ascii=False,sort_keys=True));return 0
    except Exception as exc:
        # Do not print database credentials, raw cells or absolute private paths.
        print(json.dumps({"status":"RELEASE_BLOCKED","error_type":type(exc).__name__},ensure_ascii=False));return 2

if __name__=="__main__":raise SystemExit(main())
