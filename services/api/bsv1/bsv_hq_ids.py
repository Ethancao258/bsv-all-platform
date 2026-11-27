"""Permanent-ID reservations, not another business master."""
import fcntl,json,os,re
from urllib.parse import urlsplit,parse_qs
from bsv_hq_workbook_package import MAIN
from bsv_catalog_repository import PostgresCatalogReadRepository
from services.api.shared.data_contracts import resolve_database
PAT=re.compile(r"[CPMKRQ]\d{6}")

def repository():
    dsn=os.getenv("BSV_HQ_CATALOG_READ_DB_URL","").strip()
    if resolve_database(module="pos",environ={"BSV_DB_URL":dsn})["kind"]!="central":
        raise ValueError("未配置登记目录连接")
    dsn=dsn.replace("postgresql+psycopg://","postgresql://",1)
    parsed=urlsplit(dsn)
    if parsed.hostname not in {"127.0.0.1","localhost","::1"} or set(parse_qs(parsed.query))-{"sslmode","connect_timeout","application_name"}:
        raise ValueError("目录连接参数异常")
    return PostgresCatalogReadRepository(dsn=dsn)

def history_ids():
    with repository()._connection() as conn,conn.cursor() as cur:
        cur.execute("SELECT DISTINCT record_id FROM audit.source_record_staff WHERE entity_table = ANY(%s)",([MAIN[p] for p in "CPMKRQ"],))
        return {str(row[0]) for row in cur.fetchall() if PAT.fullmatch(str(row[0]))}

def allocate(root,prefix,actor,active_ids,requested=None,history=None):
    if os.getenv("BSV_HQ_CATALOG_ID_HISTORY_VERIFIED")!="1":raise ValueError("历史ID未核验")
    legacy=root/"verified-legacy-ids.json"
    if not legacy.is_file() or legacy.is_symlink() or legacy.stat().st_mode&0o077:
        raise ValueError("缺少私有历史永久ID清单")
    info=json.loads(legacy.read_text(encoding="utf-8"))
    if info.get("status")!="HISTORY_RECONCILED" or not info.get("evidence_ref") or not isinstance(info.get("ids"),list):
        raise ValueError("历史清单未经核验")
    if any(not isinstance(x,str) or not PAT.fullmatch(x) for x in info["ids"]):
        raise ValueError("历史ID格式异常")
    used=(history_ids() if history is None else set(history))|set(info["ids"])|set(active_ids)
    fd=os.open(root/"permanent-id-reservations.jsonl",os.O_CREAT|os.O_RDWR|os.O_APPEND|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"a+",encoding="utf-8") as f:
        fcntl.flock(f,fcntl.LOCK_EX);f.seek(0)
        for line in f:
            v=json.loads(line)["id"]
            if not PAT.fullmatch(v):raise ValueError("永久ID账本损坏")
            used.add(v)
        if requested is None:
            if prefix not in tuple("CPMKRQ"):raise ValueError("固定ID域错误")
            n=max([0]+[int(v[1:]) for v in used if v.startswith(prefix)])+1
            if n>999999:raise ValueError("永久ID号段耗尽")
            values=[f"{prefix}{n:06}"]
        else:
            values=list(requested)
            if len(values)!=len(set(values)) or any(not PAT.fullmatch(v) or v in used for v in values):
                raise ValueError("上传包含非法或历史已用永久ID")
        for v in values:f.write(json.dumps({"id":v,"reserved_by":actor})+"\n")
        f.flush();os.fsync(f.fileno())
        return values
