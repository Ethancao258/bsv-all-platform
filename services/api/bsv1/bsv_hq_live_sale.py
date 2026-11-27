"""Approved sale snapshot in central PG; SQLite and public menu are projections.
The existing C!AJ price policy is preserved. K/M/Q are not new POS sale domains.
"""
from __future__ import annotations
import hashlib,json,os,re,sqlite3,tempfile,uuid
from pathlib import Path
from bsv_v9_import import unpack_v9,cents_from_price,VALID_PUBLISH
from bsv_catalog_import import _connect,_active_source,sha256
from bsv_catalog_live import require_live_layout,live_enabled

ID=re.compile(r"C\d{6}")

def fingerprint(row):
    # Bind every raw business field (including recipe, label and price).
    return hashlib.sha256(json.dumps(row["fields"],ensure_ascii=False,sort_keys=True,
                         separators=(",",":"),allow_nan=False).encode()).hexdigest()

def facts(pages):
    result={}
    for row in pages["C_现场成品"]:
        result[row["id"]]={"name":row["name"],"price_cents":cents_from_price(row["fields"].get("标注售价")),
                           "fingerprint":fingerprint(row)}
    return result

def plan_sales(current,prior,decisions,legacy=()):
    """Pure deterministic transition; no price-only implicit approvals."""
    if not isinstance(decisions,dict) or not decisions or len(decisions)>500:
        raise ValueError("请明确选择上架或下架商品")
    if any(not ID.fullmatch(k) or v not in ("LIST","UNLIST") or k not in current for k,v in decisions.items()):
        raise ValueError("只允许登记的C商品及明确上架/下架动作")
    if not set(legacy).issubset(decisions):
        raise ValueError("首次接管必须逐项核准既有营业商品")
    items={}
    for key,old in prior.items():
        if key in decisions:continue
        if current.get(key)!=old:
            raise ValueError("原有在售商品已变更，须在本批明确重新核准或下架："+key)
        items[key]=old
    for key,action in decisions.items():
        if action=="LIST":
            row=current[key]
            if not row["name"].strip() or not isinstance(row["price_cents"],int) or row["price_cents"]<=0:
                raise ValueError("上架必须有有效名称和正金额AJ："+key)
            items[key]=row
    return items

def checked_database(path):
    path=Path(path)
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ValueError("必须定位实际现用POS数据库")
    return path

def legacy_ids(path):
    path=checked_database(path)
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=10) as db:
        rows=db.execute("SELECT id,source_domain FROM bsv_products WHERE demo_only=0 AND sale_enabled=1").fetchall()
    if any(domain!="C" or not ID.fullmatch(key) for key,domain in rows):
        raise ValueError("现有营业投影存在未登记售卖域，禁止静默下架")
    return {key for key,_ in rows}

def prepare_release(draft,source,pos_db):
    from psycopg.types.json import Jsonb
    if not live_enabled():raise PermissionError("production sale release disabled")
    pages,_,_,_=unpack_v9(source)
    digest=sha256(source)
    if digest!=draft["baseline_sha256"]:raise ValueError("原始来源与上架审批版本不一致")
    if not any(str(x["fields"].get("审核状态") or "").strip() in VALID_PUBLISH for x in pages["T_门店注册"]):
        raise ValueError("没有经审核门店")
    current=facts(pages);decisions=draft["fields"]
    if draft.get("sale_facts")!={key:current[key] for key in decisions}:
        raise ValueError("审核的名称、金额或内容指纹已变")
    conn=_connect()
    try:
        require_live_layout(conn);conn.commit()
        with conn.transaction(),conn.cursor() as cur:
            cur.execute("LOCK TABLE catalog.active_content IN EXCLUSIVE MODE")
            cur.execute("LOCK TABLE catalog.sale_release IN EXCLUSIVE MODE")
            cur.execute("SELECT release_id::text,source_sha256,items,status,decisions FROM catalog.sale_release WHERE draft_id=%s",(draft["id"],))
            old=cur.fetchone()
            if old:
                if old[1].strip()!=digest or old[4]!=decisions or old[3]=="SUPERSEDED":
                    raise ValueError("已有发布记录不匹配")
                return {"id":old[0],"source_sha256":digest,"items":old[2],"status":old[3]}
            if _active_source(conn)!=digest:raise ValueError("资料版本已经改变，请重新审核")
            cur.execute("SELECT 1 FROM catalog.sale_release WHERE status='PENDING_PROJECTION'")
            if cur.fetchone():raise ValueError("存在待完成发布，先恢复该批次")
            cur.execute("SELECT release_id,items FROM catalog.sale_release WHERE status='ACTIVE'")
            prior=cur.fetchone()
            items=plan_sales(current,prior[1] if prior else {},decisions,() if prior else legacy_ids(pos_db))
            key=str(uuid.uuid4())
            cur.execute("""INSERT INTO catalog.sale_release(release_id,source_sha256,previous_release_id,draft_id,created_by,reviewed_by,legal_entity_id,decisions,items,status)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING_PROJECTION')""",
                        (key,digest,prior[0] if prior else None,draft["id"],draft["created_by"],draft["reviewed_by"],draft["legal_entity"],Jsonb(decisions),Jsonb(items)))
            return {"id":key,"source_sha256":digest,"items":items,"status":"PENDING_PROJECTION"}
    finally:conn.close()

def activate_release(release):
    conn=_connect()
    try:
        with conn.transaction(),conn.cursor() as cur:
            cur.execute("LOCK TABLE catalog.active_content IN EXCLUSIVE MODE")
            cur.execute("LOCK TABLE catalog.sale_release IN EXCLUSIVE MODE")
            cur.execute("SELECT status,source_sha256 FROM catalog.sale_release WHERE release_id=%s",(release["id"],))
            row=cur.fetchone()
            if not row or row[1].strip()!=release["source_sha256"]:raise ValueError("发布记录缺失")
            if row[0]=="ACTIVE":return
            if row[0]!="PENDING_PROJECTION" or _active_source(conn)!=release["source_sha256"]:
                raise ValueError("待生效销售版本已过期")
            cur.execute("UPDATE catalog.sale_release SET status='SUPERSEDED' WHERE status='ACTIVE'")
            cur.execute("UPDATE catalog.sale_release SET status='ACTIVE',activated_at=now() WHERE release_id=%s",(release["id"],))
    finally:conn.close()

def local_state(db):
    row=db.execute("SELECT source_sha,summary_json FROM bsv_v9_sync WHERE one=1").fetchone()
    if not row:return None,{}
    return row[0],json.loads(row[1])

def finalize_pos(path,release):
    with sqlite3.connect(str(path),timeout=20) as db:
        db.execute("BEGIN IMMEDIATE")
        digest,summary=local_state(db)
        if digest!=release["source_sha256"] or summary.get("sale_release_id")!=release["id"]:
            raise ValueError("POS销售投影不是该批次")
        rows=db.execute("SELECT id,price_cents FROM bsv_products WHERE demo_only=0 AND sale_enabled=1").fetchall()
        if dict(rows)!={key:val["price_cents"] for key,val in release["items"].items()}:
            raise ValueError("POS可售商品与中央核准集合不一致")
        summary["sale_projection_ready"]=True
        db.execute("UPDATE bsv_v9_sync SET summary_json=? WHERE one=1",(json.dumps(summary,ensure_ascii=False),))

def menu_payload(source,release,menu):
    from public_menu_projection import from_workbook
    result=from_workbook(source)
    rows=[i for i in result["items"] if i["kind"]=="prepared" and i["product_id"] in release["items"]]
    if {i["product_id"] for i in rows}!=set(release["items"]):raise ValueError("对客投影缺商品")
    for i in rows:
        expected=release["items"][i["product_id"]]["price_cents"]
        if not i["reference_price"] or cents_from_price(i["reference_price"]["amount"])!=expected:
            raise ValueError("顾客酒单价格与核准整数分不一致")
    # Keep the existing K reference catalogue unchanged until a K checkout
    # policy is approved. Do not turn any reference price into a POS price.
    old=json.loads(menu.read_text(encoding="utf-8"))
    if old.get("schema")!="bsv.public-menu.v2":raise ValueError("现有客用菜单格式不兼容")
    legacy=[i for i in old["items"] if i.get("kind")=="bundle"]
    allowed=set(result["items"][0]) if result["items"] else set()
    if legacy and (not allowed or any(set(i)-allowed-{"public_flavor"} for i in legacy)):
        raise ValueError("旧套餐菜单包含非标准公开字段")
    result["items"]=rows+legacy
    result["source_sha256"]=release["source_sha256"]
    result["sale_release_id"]=release["id"]
    result["bundle_source_policy"]="existing_reference_catalogue_unchanged"
    return result

def checked_menu(path):
    path=Path(path)
    if not path.is_absolute() or path.name!="menu-public.json" or path.is_symlink() or not path.is_file() or path.parent.is_symlink():
        raise ValueError("必须配置现用客用菜单JSON的绝对路径")
    return path

def write_menu(path,payload):
    old=path.stat()
    fd,temp=tempfile.mkstemp(prefix=".catalog-menu-",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            os.fchmod(f.fileno(),0o644)
            if os.geteuid()==0:os.fchown(f.fileno(),old.st_uid,old.st_gid)
            json.dump(payload,f,ensure_ascii=False,separators=(",",":"));f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:Path(temp).unlink(missing_ok=True)

def execute_sale(draft,source,pos_db,menu_path):
    from bsv_v9_import import sync_v9
    pos_db=checked_database(pos_db);menu=checked_menu(menu_path)
    release=prepare_release(draft,source,pos_db)
    payload=menu_payload(source,release,menu)
    with sqlite3.connect(str(pos_db),timeout=20) as db:
        digest,summary=local_state(db)
    if digest!=release["source_sha256"] or summary.get("sale_release_id")!=release["id"]:
        sync_v9(pos_db,source,force=True,sale_release=release)
    # Local new prices are fail-closed while pending. A retry of the same
    # durable release id is idempotent; never replay a different draft.
    activate_release(release)
    finalize_pos(pos_db,release)
    write_menu(menu,payload)
    readback=json.loads(menu.read_text(encoding="utf-8"))
    if readback.get("sale_release_id")!=release["id"]:raise ValueError("顾客菜单写入未核验")
    return {"status":"SALE_ACTIVE","draft_id":draft["id"],"sale_release_id":release["id"],
            "source_sha256":release["source_sha256"],"sellable_count":len(release["items"]),
            "pos_projection":"VERIFIED","menu_origin":"VERIFIED","edge_cache":"NOT_VERIFIED"}


def sale_record_state(draft_id):
    conn=_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM catalog.sale_release WHERE draft_id=%s",(draft_id,))
            row=cur.fetchone()
            return row[0] if row else None
    finally:conn.close()

def archive_for_projection(source,catalog_dir,digest):
    """Stable, private exact-byte source readable by the existing POS owner."""
    import shutil
    root=Path(catalog_dir);versions=root/"versions"
    if not root.is_absolute() or root.is_symlink() or not root.is_dir() or root.stat().st_mode&0o077:
        raise ValueError("私有版本目录异常")
    versions.mkdir(mode=0o700,exist_ok=True)
    if versions.is_symlink() or versions.stat().st_mode&0o077:raise ValueError("私有版本子目录异常")
    owner=root.stat()
    if os.geteuid()==0:os.chown(versions,owner.st_uid,owner.st_gid)
    target=versions/(digest+".xlsx")
    if target.exists():
        if target.is_symlink() or sha256(target)!=digest:raise ValueError("历史版本冲突")
        return target
    fd,temp=tempfile.mkstemp(prefix=".live-catalog-",dir=versions)
    try:
        with os.fdopen(fd,"wb") as out,Path(source).open("rb") as inp:
            os.fchmod(out.fileno(),0o600)
            if os.geteuid()==0:os.fchown(out.fileno(),owner.st_uid,owner.st_gid)
            shutil.copyfileobj(inp,out);out.flush();os.fsync(out.fileno())
        if sha256(Path(temp))!=digest:raise ValueError("来源在复制过程中改变")
        try:os.link(temp,target)
        except FileExistsError:
            if target.is_symlink() or sha256(target)!=digest:raise ValueError("版本冲突")
        fd=os.open(versions,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:Path(temp).unlink(missing_ok=True)
    return target
