"""HQ catalog candidate: one identity, one verified source, no live writes.
All draft records are private workflow artifacts, not a second product master.
"""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import Request, HTTPException
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ConfigDict

# Reuse the PR40/42 modules exactly as the POS process imports them.
POS = Path(__file__).resolve().parents[1] / "bsv1"
if str(POS) not in sys.path:
    sys.path.insert(0, str(POS))

LIMIT = 4 * 1024 * 1024
ACTIONS = {"read": "hq.catalog.read", "draft": "hq.catalog.draft", "review": "hq.catalog.review", "release":"hq.catalog.release.request"}
SAFE_FIELDS = {"商品名称", "半成品名称", "物料名称", "套餐名称", "商品ID", "半成品ID",
               "物料ID", "套餐ID", "门店ID", "配方文字", "完整制作步骤",
               "制作时长（秒）", "销售系列", "标注售价", "核准售价", "币种",
               "销售渠道", "生效日期", "失效日期", "工序名称", "记录名称", "报价名称",
               "出品关联ID", "投入物料ID", "投料数量", "投料单位", "配方文字｜制作记录",
               "完整制作步骤｜制作记录", "计价单位", "包装量", "包装单位", "保质期", "储存条件",
               "运输条件", "套餐包含内容", "完整商品文案", "门店差异文案", "标注原价",
               "区域参考售价", "核心参考售价", "规格量", "规格单位", "售卖扣减量",
               "英文名称", "产品故事", "风味描述", "过敏原", "酒精属性", "成品图文件名"}
EDIT_FIELDS = SAFE_FIELDS - {"商品ID", "半成品ID", "物料ID", "套餐ID", "门店ID"}

def registered_fields(prefix, confidential=False):
    from bsv_hq_workbook_package import MAIN,table_specs
    permissions={"PUBLIC","INTERNAL"} | ({"CONFIDENTIAL"} if confidential else set())
    return {s["source_header"] for _,s in table_specs()[MAIN[prefix]] if s["permission_class"] in permissions}

def editable_fields(prefix):
    fields=EDIT_FIELDS | ({"商品ID","门店ID"} if prefix=="Q" else set())
    return fields & registered_fields(prefix,True)
PREFIXES = "CPMKRQT"
HEX = re.compile(r"[0-9a-f]{64}")
DRAFT_ID = re.compile(r"[0-9a-f]{32}")

class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_sha256: str
    kind: str
    domain: str = ""
    record_id: str = ""
    fields: dict[str, str] = Field(default_factory=dict)
    reason: str = Field(min_length=8, max_length=500)

class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    reason: str = Field(min_length=8, max_length=500)

def fail(code, message, status=409):
    raise HTTPException(status, detail={"code": code, "message": message})

def now():
    return datetime.now(timezone.utc).isoformat()

def private_root():
    raw = os.getenv("BSV_IMPORT_ROOT", "")
    root = Path(raw)
    if not raw or not root.is_absolute() or root.is_symlink() or not root.is_dir():
        fail("IMPORT_ROOT_REQUIRED", "请配置已有受控私有导入目录。", 503)
    st = root.stat()
    if st.st_uid != os.geteuid() or st.st_mode & 0o077:
        fail("IMPORT_ROOT_PERMISSIONS", "导入目录权限不符合要求。", 503)
    folder = root / "hq-catalog-drafts"
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.is_symlink() or not folder.is_dir() or folder.stat().st_uid != os.geteuid() or folder.stat().st_mode & 0o077:
        fail("IMPORT_ROOT_PERMISSIONS", "草稿目录权限异常。", 503)
    return folder

def active_source():
    from bsv_catalog_config import get_excel_path
    from bsv_hq_ids import repository
    dsn = os.getenv("BSV_HQ_CATALOG_READ_DB_URL", "").strip()
    if not dsn or not os.getenv("BSV_CATALOG_DIR"):
        fail("SOURCE_NOT_CONFIGURED", "未接通经批准的PG目录及原始Excel版本。", 503)
    try:
        # Dedicated read-only connection alias to the same registered central DB;
        # never change the identity.A URL or silently fall back to another database.
        source=repository().source()
        digest=source["sha256"]
        if not HEX.fullmatch(digest):fail("SOURCE_UNAVAILABLE","活动版本异常。",503)
        local=Path(os.getenv("BSV_IMPORT_ROOT",""))/"hq-catalog-drafts"/(digest+".xlsx")
        managed=Path(os.environ["BSV_CATALOG_DIR"])/"versions"/(digest+".xlsx")
        path=next((p for p in (local,managed) if p.is_file() and not p.is_symlink()),None)
        if path is None:path=get_excel_path()
        if not HEX.fullmatch(digest) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            fail("STALE_BASELINE", "Excel与PG活动版本不一致。", 409)
        return path, digest
    except HTTPException:
        raise
    except Exception:
        fail("SOURCE_UNAVAILABLE", "无法核验当前活动目录版本。", 503)

def rows_for(path):
    from bsv_v9_import import unpack_v9
    rows, _, _, _ = unpack_v9(path)
    return rows

def visible_record(row, prefix, confidential=False):
    allowed=registered_fields(prefix,confidential)
    return {"id": row["id"], "name": row["name"] if prefix in "CPMK" else row["id"],
            "fields": {k:v for k,v in row["fields"].items() if k in SAFE_FIELDS and k in allowed}}

def check_draft(body, rows, active):
    if body.baseline_sha256 != active:
        fail("STALE_BASELINE", "活动版本已更新，请刷新后重新提交。")
    if body.kind not in {"create", "edit", "retire", "rollback"}:
        fail("BAD_KIND", "未知变更类型。", 422)
    if body.kind == "rollback":
        if not HEX.fullmatch(body.record_id) or body.record_id == active or body.fields or body.domain:
            fail("BAD_TARGET", "请填写不同于当前版本的目标SHA。", 422)
        return
    if body.domain == "T":
        fail("STORE_READ_ONLY", "门店主数据只能由原组织管理模块维护。", 403)
    if body.domain not in tuple(PREFIXES):
        fail("BAD_DOMAIN", "资料分类无效。", 422)
    if len(body.fields) > 30 or any(k not in editable_fields(body.domain) or not v.strip() or len(v)>4000 for k,v in body.fields.items()):
        fail("BAD_FIELDS", "包含未开放、空白或过长字段。", 422)
    page = next((v for k,v in rows.items() if k.startswith(body.domain+"_")), [])
    if body.kind == "create":
        name_field = {"C":"商品名称", "P":"半成品名称", "M":"物料名称", "K":"套餐名称", "R":"记录名称", "Q":"报价名称"}[body.domain]
        if body.record_id or not body.fields.get(name_field, "").strip():
            fail("ID_ALLOCATION_REQUIRED", "新增须填写名称，永久编号由后台分配。", 422)
        required={"R":{"出品关联ID","投入物料ID","投料数量","投料单位"},"Q":{"商品ID","门店ID","核准售价","币种"}}.get(body.domain,set())
        if not required.issubset(body.fields):fail("REQUIRED_FIELDS","缺少关联、数量或报价必需字段。",422)
    else:
        if not re.fullmatch(body.domain+r"\d{6}", body.record_id) or not any(x["id"]==body.record_id for x in page):
            fail("RECORD_NOT_FOUND", "未找到当前版本的固定编号。", 404)
        if body.kind == "edit":
            target = next(x for x in page if x["id"]==body.record_id)
            if not body.fields or any(k not in target["fields"] for k in body.fields):
                fail("FIELD_NOT_REGISTERED", "请选择现有资料的已登记字段。", 422)
        elif body.fields:
            fail("BAD_FIELDS", "退役只提交申请，不直接删除资料。", 422)

def scan(content):
    # Approved administrator-provisioned scanner; no client-controlled commands.
    executable = Path(os.getenv("BSV_HQ_CATALOG_SCANNER", ""))
    if not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
        fail("SCAN_REQUIRED", "上传扫描器尚未配置，文件没有保存。", 503)
    st = executable.stat()
    if st.st_uid not in {0, os.geteuid()} or st.st_mode & 0o022:
        fail("SCAN_REQUIRED", "扫描器权限异常。", 503)
    with tempfile.TemporaryDirectory(prefix="bsv-hq-scan-") as tmp:
        file = Path(tmp) / "candidate.xlsx"
        file.write_bytes(content)
        try:
            result = subprocess.run([str(executable), str(file)], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, env={"PATH":"/usr/bin:/bin","LANG":"C.UTF-8"}, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            fail("SCAN_UNAVAILABLE", "文件扫描失败，未保存。", 503)
        if result.returncode:
            fail("SCAN_REJECTED", "文件未通过安全扫描。", 422)

def inspect_upload(content, path, digest):
    from bsv_catalog_workbook_preview import preview_workbook
    import zipfile
    from xml.etree import ElementTree
    scan(content)
    try:
        result = preview_workbook(content, path, digest)
        from bsv_hq_sale_gate import validate_raw_change
        with tempfile.TemporaryDirectory(prefix="bsv-hq-gate-") as temp:
            candidate=Path(temp)/"candidate.xlsx";candidate.write_bytes(content)
            gate=validate_raw_change(path,candidate)
    except (ValueError, KeyError, AssertionError, zipfile.BadZipFile, ElementTree.ParseError):
        fail("WORKBOOK_INVALID", "Excel模板、固定ID或工作簿结构异常，请检查七表。", 422)
    # Do not expose raw protected field values or import warnings that may include them.
    changes = result.get("changes", {})
    safe_changes = {}
    for key in ("added", "modified", "pending_retire"):
        safe_changes[key] = [{k:v for k,v in x.items() if k in {"sheet","record_id","changed_fields","status"}}
                             for x in changes.get(key, [])]
    safe_changes["formula_cells"] = changes.get("formula_cells", [])
    safe_changes["bundle_aux_changed"]=gate["bundle_aux_changed"]
    return {"status": result["status"], "source_sha256": result["source_sha256"],
            "baseline_sha256": digest, "schema_compatible": result.get("schema_compatible", False),
            "changes": safe_changes, "write_performed": False,
            "review_ready": result.get("content_contract_compatible", False)
                            and not safe_changes["pending_retire"] and not safe_changes["formula_cells"]
                            and not safe_changes["bundle_aux_changed"],
            "activation": "BLOCKED_PACKAGE_CONVERTER_AND_PG_APPROVAL"}

def save_json(path, value):
    fd, temp = tempfile.mkstemp(prefix=".draft-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, ensure_ascii=False, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def new_draft(root, entity, actor, payload):
    key = uuid.uuid4().hex
    data = {"id": key, "legal_entity": entity, "created_by": actor, "created_at": now(),
            "status": "PENDING_REVIEW", **payload}
    save_json(root / (key+".json"), data)
    return data

def list_drafts(root, entity):
    output = []
    for file in root.glob("*.json"):
        if file.is_symlink() or not DRAFT_ID.fullmatch(file.stem):
            continue
        data = json.loads(file.read_text(encoding="utf-8"))
        if data.get("legal_entity") == entity:
            receipt=root/(file.stem+".release.json")
            if receipt.is_file() and not receipt.is_symlink():
                result=json.loads(receipt.read_text(encoding="utf-8"))
                if result.get("draft_id")==data["id"] and result.get("status") in {"RAW_REVISION_ACTIVE","RELEASE_BLOCKED","RELEASE_RECONCILIATION_REQUIRED"}:
                    data["release_result"]=result
                    data["status"]=result["status"]
            output.append(data)
    return sorted(output, key=lambda x:x["created_at"], reverse=True)

def review_draft(root, key, entity, actor, body, active):
    if not DRAFT_ID.fullmatch(key) or body.decision not in {"approve","reject"}:
        fail("INVALID_REVIEW", "审核动作或草稿编号无效。", 422)
    lock = root / ".review.lock"
    fd = os.open(lock, os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        file = root / (key+".json")
        if not file.is_file() or file.is_symlink():
            fail("NOT_FOUND", "未找到草稿。", 404)
        data = json.loads(file.read_text(encoding="utf-8"))
        if data.get("legal_entity") != entity:
            fail("NOT_FOUND", "未找到草稿。", 404)
        if data["created_by"] == actor:
            fail("SEPARATION_OF_DUTIES", "不得审核本人提交的草稿。", 403)
        if data["status"] != "PENDING_REVIEW":
            fail("ALREADY_REVIEWED", "草稿已经审核。")
        if data["baseline_sha256"] != active:
            fail("STALE_BASELINE", "活动版本已变更，须重新预览。")
        data.update(status="REVIEWED_NOT_PUBLISHED" if body.decision=="approve" else "REJECTED",
                    reviewed_by=actor, reviewed_at=now(), review_reason=body.reason)
        save_json(file, data)
        return data

def install_catalog_routes(app, router, settings, grant_guard, person_for_subject, hq):
    def actor(request, action):
        if settings.env != "isolated" or os.getenv("BSV_HQ_CATALOG_ENABLE") != "1":
            fail("MODULE_DISABLED", "商品中心尚未获准启用。", 503)
        entity = os.getenv("BSV_HQ_CATALOG_LEGAL_ENTITY_ID", "")
        if not entity:
            fail("SCOPE_REQUIRED", "总部法人范围尚未配置。", 503)
        with router.session() as db:
            subject = grant_guard(request, db, ACTIONS[action], entity)
            if action in {"draft","review","release"}:grant_guard(request,db,"hq.catalog.confidential",entity)
            person = person_for_subject(db, subject)
            if not person:
                fail("AUTH_REQUIRED", "需要统一人员身份。", 403)
            return entity, person.tr_code

    def can_confidential(request,entity):
        from domains.workforce.identity.core import DomainError
        with router.session() as db:
            try:grant_guard(request,db,"hq.catalog.confidential",entity)
            except DomainError as exc:
                if exc.status==403:return False
                raise
            return True

    @app.get("/hq/catalog", include_in_schema=False)
    def page():
        # Shell contains no sensitive data; all APIs require live authorization.
        return FileResponse(hq / "catalog.html")

    @app.get("/hq-assets/catalog.js", include_in_schema=False)
    def js():
        return FileResponse(hq / "catalog.js", media_type="text/javascript")

    @app.get("/hq-assets/catalog.css", include_in_schema=False)
    def css():
        return FileResponse(hq / "catalog.css", media_type="text/css")

    @app.get("/api/v1/hq/catalog/status", include_in_schema=False)
    def status(request: Request):
        entity, tr = actor(request, "read")
        path, digest = active_source()
        rows = rows_for(path)
        return {"actor":tr, "legal_entity":entity, "active_sha256":digest,
                "counts":{k[0]:len(v) for k,v in rows.items()},
                "activation":"BLOCKED_PACKAGE_CONVERTER_AND_PG_APPROVAL"}

    @app.get("/api/v1/hq/catalog/records", include_in_schema=False)
    def records(request: Request, domain: str="C", q: str="", offset: int=0):
        entity,_=actor(request, "read")
        confidential=can_confidential(request,entity)
        if domain not in tuple(PREFIXES) or len(q)>100 or not 0<=offset<=100000:
            fail("BAD_QUERY", "筛选参数无效。", 422)
        path, digest = active_source()
        data = next(v for k,v in rows_for(path).items() if k.startswith(domain+"_"))
        q = q.casefold()
        data = [visible_record(x,domain,confidential) for x in data]
        data = [x for x in data if q in x["id"].casefold() or q in x["name"].casefold()]
        return {"active_sha256":digest, "total":len(data), "items":data[offset:offset+100], "editable_fields":sorted(editable_fields(domain)) if confidential and domain!="T" else []}

    @app.post("/api/v1/hq/catalog/preview", include_in_schema=False)
    async def preview(request: Request):
        await run_in_threadpool(actor,request,"draft")
        if request.headers.get("content-type","").split(";")[0] != "application/octet-stream":
            fail("BAD_CONTENT_TYPE", "请选择.xlsx文件。", 415)
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content)>LIMIT:
                fail("TOO_LARGE", "当前网关上传上限4MiB。", 413)
        path, digest = await run_in_threadpool(active_source)
        return await run_in_threadpool(inspect_upload, bytes(content), path, digest)

    @app.post("/api/v1/hq/catalog/excel-drafts", include_in_schema=False)
    async def excel_draft(request: Request):
        entity,tr = await run_in_threadpool(actor,request,"draft")
        if request.headers.get("content-type","").split(";")[0] != "application/octet-stream":
            fail("BAD_CONTENT_TYPE", "请选择.xlsx文件。", 415)
        expected = request.query_params.get("sha","")
        baseline = request.query_params.get("baseline","")
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content)>LIMIT:
                fail("TOO_LARGE", "当前网关上传上限4MiB。", 413)
        def persist():
            path,digest = active_source()
            if baseline != digest or expected != hashlib.sha256(content).hexdigest():
                fail("STALE_PREVIEW", "文件或活动版本已变，请重新预览。")
            result = inspect_upload(bytes(content), path, digest)
            if result["status"]=="IDEMPOTENT_NOOP" or not result["review_ready"]:
                fail("PREVIEW_BLOCKED", "无变化或存在需处理的缺行、公式或模板变更。")
            root=private_root()
            file=root/(expected+".xlsx")
            try:
                fd=os.open(file,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,"wb") as out:
                    out.write(content);out.flush();os.fsync(out.fileno())
            except FileExistsError:
                if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest()!=expected:
                    fail("ARTIFACT_CONFLICT","候选文件冲突。")
            # serialize identical source+baseline submission and avoid duplicate queue entries.
            fd=os.open(root/".submit.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,"r+") as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                for item in list_drafts(root,entity):
                    if item.get("kind")=="excel" and item.get("source_sha256")==expected and item.get("baseline_sha256")==baseline:
                        return item
                from bsv_hq_ids import allocate
                added=[x["record_id"] for x in result["changes"]["added"]]
                if added:
                    try:allocate(root,None,tr,{row["id"] for group in rows_for(path).values() for row in group},requested=added)
                    except ValueError:fail("ID_HISTORY_CONFLICT","上传含未核验或已使用的永久ID。")
                return new_draft(root,entity,tr,{"kind":"excel","baseline_sha256":baseline,
                    "source_sha256":expected,"preview":result,"reason":"Excel批量资料变更"})
        return await run_in_threadpool(persist)

    @app.get("/api/v1/hq/catalog/versions", include_in_schema=False)
    def versions(request:Request):
        actor(request,"read")
        from bsv_hq_ids import repository
        with repository()._connection() as conn,conn.cursor() as cur:
            cur.execute("SELECT source_sha256,package_version,status,imported_at FROM audit.import_batch ORDER BY imported_at DESC LIMIT 100")
            return {"items":[{"sha256":r[0].strip(),"version":r[1],"status":r[2],"imported_at":r[3].isoformat()} for r in cur.fetchall()]}

    @app.get("/api/v1/hq/catalog/drafts", include_in_schema=False)
    def drafts(request: Request):
        # Queue visibility is not inherited from the general read-only grant.
        from domains.workforce.identity.core import DomainError
        try:
            entity,_ = actor(request,"draft")
        except DomainError as exc:
            if exc.status != 403:
                raise
            entity,_ = actor(request,"review")
        return {"items":list_drafts(private_root(),entity)[:100]}

    @app.post("/api/v1/hq/catalog/drafts", include_in_schema=False)
    def create(request: Request, body: Draft):
        entity,tr = actor(request,"draft")
        path,digest = active_source()
        rows=rows_for(path);check_draft(body,rows,digest)
        root=private_root();payload=body.model_dump()
        if body.kind=="create":
            from bsv_hq_ids import allocate
            try:payload["record_id"]=allocate(root,body.domain,tr,{row["id"] for group in rows.values() for row in group})[0]
            except ValueError:fail("ID_HISTORY_REQUIRED","永久ID历史尚未核验或号段耗尽。",409)
        return new_draft(root,entity,tr,payload)

    @app.post("/api/v1/hq/catalog/drafts/{key}/review", include_in_schema=False)
    def review(request: Request, key: str, body: Review):
        entity,tr = actor(request,"review")
        _,digest=active_source()
        return review_draft(private_root(),key,entity,tr,body,digest)


    @app.post("/api/v1/hq/catalog/drafts/{key}/prepare", include_in_schema=False)
    def prepare_package(request: Request, key: str):
        entity,tr=actor(request,"review")
        if not DRAFT_ID.fullmatch(key):
            fail("NOT_FOUND","未找到草稿。",404)
        root=private_root()
        fd=os.open(root/".prepare.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"r+") as lock:
            # Refuse a concurrent converter rather than starting multiple workers.
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                fail("PREPARE_BUSY","另一候选包正在生成，请查询草稿状态。",409)
            file=root/(key+".json")
            if file.is_symlink() or not file.is_file():
                fail("NOT_FOUND","未找到草稿。",404)
            data=json.loads(file.read_text(encoding="utf-8"))
            if data.get("legal_entity")!=entity:
                fail("NOT_FOUND","未找到草稿。",404)
            if data.get("reviewed_by")!=tr:
                fail("REVIEWER_REQUIRED","仅独立审核人可生成本候选包。",403)
            if data["status"]=="VERIFIED_PACKAGE_NOT_PUBLISHED":
                return data
            if data["status"]!="REVIEWED_NOT_PUBLISHED":
                fail("REVIEW_REQUIRED","草稿尚未独立审核。",409)
            path,digest=active_source()
            if data["baseline_sha256"]!=digest:
                fail("STALE_BASELINE","活动版本已变化，请重新审核。",409)
            from bsv_hq_candidate import prepare
            try:
                result=prepare(root,data,path)
            except (ValueError,OSError,KeyError,RuntimeError):
                fail("PACKAGE_PREPARE_BLOCKED","候选包未生成：需核对转换器、固定ID、公式、版本及数据契约。",409)
            data["package"]=result
            data["status"]=result["status"]
            data["prepared_by"]=tr
            data["prepared_at"]=now()
            save_json(file,data)
            return data


    @app.post("/api/v1/hq/catalog/drafts/{key}/release-request",include_in_schema=False)
    def release_request(request:Request,key:str):
        entity,tr=actor(request,"release")
        if not DRAFT_ID.fullmatch(key):fail("NOT_FOUND","未找到草稿。",404)
        root=private_root()
        fd=os.open(root/".prepare.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"r+") as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:fail("PREPARE_BUSY","候选包处理中，请刷新。")
            file=root/(key+".json")
            if file.is_symlink() or not file.is_file():fail("NOT_FOUND","未找到草稿。",404)
            d=json.loads(file.read_text(encoding="utf-8"))
            if d.get("legal_entity")!=entity:fail("NOT_FOUND","未找到草稿。",404)
            if d.get("reviewed_by")!=tr or tr==d["created_by"]:fail("REVIEWER_REQUIRED","须由独立审核人申请发布。",403)
            if d["status"]=="RELEASE_REQUESTED":return d
            expected="REVIEWED_NOT_PUBLISHED" if d["kind"]=="rollback" else "VERIFIED_PACKAGE_NOT_PUBLISHED"
            if d["status"]!=expected:fail("PACKAGE_REQUIRED","请先审核并生成候选包。")
            _,digest=active_source()
            if digest!=d["baseline_sha256"]:fail("STALE_BASELINE","活动版本已变更。")
            if d["kind"]=="rollback":
                from bsv_hq_ids import repository
                with repository()._connection() as conn,conn.cursor() as cur:
                    cur.execute("SELECT status FROM audit.import_batch WHERE source_sha256=%s",(d["record_id"],))
                    row=cur.fetchone()
                    if not row or row[0]!="COMMITTED_RAW":fail("TARGET_NOT_IMPORTED","目标历史版本不存在。")
            d.update(status="RELEASE_REQUESTED",release_requested_by=tr,release_requested_at=now())
            save_json(file,d);return d
