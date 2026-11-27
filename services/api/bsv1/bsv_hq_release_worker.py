"""Optional isolated release worker, no listening port, disabled without root approval."""
from __future__ import annotations
import argparse, fcntl, json, os, re, subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from bsv_hq_release import execute,receipt

def policy(path):
    if os.geteuid()!=0 or not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise PermissionError("root-controlled policy required")
    st=path.stat()
    if st.st_uid!=0 or st.st_mode&0o077:raise PermissionError("private root policy required")
    info=json.loads(path.read_text(encoding="utf-8"))
    from bsv_catalog_live import live_enabled,import_enabled
    wanted="APPROVED_PRODUCTION_CATALOG" if live_enabled() else "APPROVED_ISOLATED_RAW_ONLY"
    if info.get("status")!=wanted or not import_enabled():raise PermissionError("worker disabled")
    if info.get("legal_entity")!=os.getenv("BSV_HQ_CATALOG_LEGAL_ENTITY_ID") or not info.get("legal_entity"):
        raise PermissionError("legal scope differs")
    expiry=datetime.fromisoformat(info["expires_at"])
    if expiry.tzinfo is None or expiry<=datetime.now(timezone.utc):raise PermissionError("policy expired")
    if not re.fullmatch(r"[a-f0-9]{40}",info.get("approved_git_sha","")) or not info.get("approval_ref"):
        raise PermissionError("approved deployment evidence missing")
    repo=Path(__file__).resolve().parents[3]
    try:
        head=subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True,timeout=5).strip()
        changes=subprocess.check_output(["git","-C",str(repo),"status","--porcelain","--untracked-files=no"],text=True,timeout=5).strip()
    except (OSError,subprocess.SubprocessError) as exc:raise PermissionError("approved Git worktree required") from exc
    if head!=info["approved_git_sha"] or changes:raise PermissionError("running source is not the clean approved revision")
    return info

def run_once(info):
    root=Path(info["draft_root"]);approvals=Path(info["approval_dir"]);catalog=Path(info["catalog_dir"])
    if any(not p.is_absolute() or p.is_symlink() or not p.is_dir() or p.stat().st_mode&0o077 for p in (root,approvals,catalog)):
        raise PermissionError("unsafe runtime directory")
    if approvals.stat().st_uid!=0 or root.resolve()==approvals.resolve() or root.resolve() in approvals.resolve().parents:
        raise PermissionError("approval boundary missing")
    fd=os.open(approvals/".worker.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"r+") as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {"status":"WORKER_BUSY"}
        for file in sorted(root.glob("*.json"),key=lambda p:p.stat().st_mtime):
            if file.is_symlink() or not re.fullmatch(r"[a-f0-9]{32}",file.stem):continue
            d=json.loads(file.read_text(encoding="utf-8"));key=file.stem
            if d.get("status")!="RELEASE_REQUESTED" or (root/(key+".release.json")).exists():continue
            if d.get("legal_entity")!=info["legal_entity"]:continue
            approval=approvals/(key+".approval.json")
            args=SimpleNamespace(draft_root=root,draft_id=key,approval_dir=approvals,catalog_dir=catalog,
                    rollback_archive=None,apply=True,confirm_isolated=d.get("baseline_sha256"))
            try:
                if d["kind"]=="sale":
                    from bsv_catalog_live import live_enabled
                    from bsv_hq_live_sale import execute_sale
                    from bsv_hq_release import read_draft,require_grants,assert_source
                    if not live_enabled():raise PermissionError("正式销售发布未启用")
                    d=read_draft(root,key);require_grants(d)
                    source=assert_source(d["baseline_sha256"],root,catalog)
                    result=execute_sale(d,source,Path(info["pos_database"]),Path(info["public_menu_json"]))
                    receipt(root,key,result);return result
                if approval.exists():raise RuntimeError("prior signing attempt")
                if d["kind"]=="rollback":
                    archive=info.get("rollback_archives",{}).get(d["record_id"])
                    if not archive:raise ValueError("missing historical package")
                    args.rollback_archive=Path(archive)
                return execute(args)
            except Exception as exc:
                result={"status":"RELEASE_RECONCILIATION_REQUIRED" if approval.exists() or d.get("kind")=="sale" else "RELEASE_BLOCKED",
                        "draft_id":key,"error_type":type(exc).__name__}
                if not (root/(key+".release.json")).exists():receipt(root,key,result)
                return result
        return {"status":"NO_PENDING_RELEASE"}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--policy",type=Path,required=True)
    args=p.parse_args()
    try:
        result=run_once(policy(args.policy));print(json.dumps(result,ensure_ascii=False));return 0
    except Exception as exc:
        print(json.dumps({"status":"WORKER_DISABLED_OR_BLOCKED","error_type":type(exc).__name__}));return 2

if __name__=="__main__":raise SystemExit(main())
