"""Prepare a verified, private WorkBuddy candidate from an approved HQ draft.

This adapter intentionally cannot sign, import, activate, or publish. The approved
converter must be installed by the deployment owner; no guessing source mappings.
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile

from bsv_catalog_import import _verified_package, sha256
from bsv_catalog_workbook_preview import preview_workbook, MAX_WORKBOOK_BYTES
from bsv_v9_import import unpack_v9

def _trusted_converter():
    raw=os.getenv("BSV_HQ_CATALOG_CONVERTER","")
    path=Path(raw)
    if not raw or not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("未配置经审查的WorkBuddy标准包转换器")
    st=path.stat()
    if st.st_uid not in {0,os.geteuid()} or st.st_mode&0o022 or not os.access(path,os.X_OK):
        raise ValueError("转换器权限无效")
    return path

def _original(package):
    files=list((package/"original").glob("*.xlsx"))
    if len(files)!=1 or files[0].is_symlink() or files[0].stat().st_size>MAX_WORKBOOK_BYTES:
        raise ValueError("规范包必须包含唯一原始Excel")
    return files[0]

def _indexes(path):
    data,extras,quotes,_=unpack_v9(path)
    return {(sheet,row["id"]):row["fields"] for sheet,rows in data.items() for row in rows},extras,quotes

def verify_draft_change(draft, baseline, candidate):
    """Verify a row-edit against its approved field set; reject unrelated mutations.

    Create requests remain blocked pending the authoritative permanent-ID allocator.
    A retirement or rollback request is never interpreted as deletion or activation.
    """
    if draft["kind"]=="excel":
        if sha256(candidate)!=draft["source_sha256"]:
            raise ValueError("转换器输出不匹配已审核Excel字节")
        return
    if draft["kind"] not in {"edit","create"}:
        raise ValueError("退役/恢复须走独立发布审批服务")
    before,bextras,_=_indexes(baseline)
    after,aextras,_=_indexes(candidate)
    key=next((k for k in after if k[1]==draft["record_id"] and k[0].startswith(draft["domain"]+"_")),None)
    if draft["kind"]=="create":
        if not key or key in before or set(after)!=set(before)|{key} or bextras!=aextras:
            raise ValueError("新增必须只增加已预留的永久ID")
        for field,value in draft["fields"].items():
            if str(after[key].get(field))!=value:raise ValueError("新增值不匹配已审核草稿")
        from bsv_hq_workbook_package import MAIN,table_specs
        ids={s["source_header"] for _,s in table_specs()[MAIN[draft["domain"]]] if s["source_column"]=="L"}
        if any(v not in (None,"") for f,v in after[key].items() if f not in draft["fields"] and f not in ids):
            raise ValueError("新增出现未审核字段")
    elif not key or set(before)!=set(after) or bextras!=aextras:
        raise ValueError("可视化修改不得改变固定ID、记录集合或套餐子区")
    for k,row in before.items():
        current=after[k]
        if set(row)!=set(current):
            raise ValueError("转换器改变了已登记字段")
        allowed=draft["fields"] if k==key and draft["kind"]=="edit" else {}
        for field,value in row.items():
            if field in allowed:
                # Values have been proposed as text; no hidden coercion.
                if str(current[field])!=allowed[field]:
                    raise ValueError("转换结果与已审核字段值不同")
            elif current[field]!=value:
                raise ValueError("转换器产生了未审核字段变更")

def prepare(root, draft, baseline):
    root=Path(root)
    if draft["status"]!="REVIEWED_NOT_PUBLISHED":
        raise ValueError("只有已独立审核且未发布的草稿可生成候选包")
    if sha256(baseline)!=draft["baseline_sha256"]:
        raise ValueError("活动版本已变化")
    if draft["kind"] not in {"excel","edit","create"}:
        raise ValueError("本候选仅支持Excel、新增或现有记录修改")
    converter=_trusted_converter() if os.getenv("BSV_HQ_CATALOG_CONVERTER") else None
    with tempfile.TemporaryDirectory(prefix="bsv-hq-package-",dir=root) as tmp:
        tmp=Path(tmp)
        request=tmp/"draft.json"
        request.write_text(json.dumps(draft,ensure_ascii=False),encoding="utf-8")
        # Pass only private file paths to one provisioned executable; no shell or
        # inherited database credentials. The external converter must emit the
        # exact existing WorkBuddy directory and archive, not invent a new format.
        args=[str(converter),"--baseline",str(baseline),"--draft",str(request),"--output",str(tmp)]
        if draft["kind"]=="excel":
            source=root/(draft["source_sha256"]+".xlsx")
            if source.is_symlink() or not source.is_file() or sha256(source)!=draft["source_sha256"]:
                raise ValueError("审核的Excel候选已缺失或改变")
            args.extend(["--candidate",str(source)])
        if converter:
            try:
                result=subprocess.run(args,env={"PATH":"/usr/bin:/bin","LANG":"C.UTF-8"},
                                      stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                      timeout=75,check=False)
            except (OSError,subprocess.TimeoutExpired) as exc:
                raise ValueError("转换器运行失败") from exc
            if result.returncode:
                raise ValueError("转换器未生成有效规范包")
        else:
            from bsv_hq_workbook_package import make_package,patch_workbook
            if draft["kind"]!="excel":
                source=tmp/"edited.xlsx"
                patch_workbook(baseline,draft,source)
            make_package(source,tmp)
        package=tmp/"package";archive=tmp/"package.zip"
        if package.is_symlink() or not package.is_dir() or archive.is_symlink() or not archive.is_file():
            raise ValueError("转换器未返回预期产物")
        if archive.stat().st_size>128*1024*1024:
            raise ValueError("候选包超出128MiB上限")
        with ZipFile(archive) as z:
            entries=z.infolist()
            if len(entries)>4096 or sum(x.file_size for x in entries)>512*1024*1024:
                raise ValueError("候选包展开超出限制")
        candidate=_original(package)
        manifest,archive_sha,_=_verified_package(package,archive)
        if manifest["source_sha256"]!=sha256(candidate):
            raise ValueError("原始Excel与规范包来源哈希不符")
        verify_draft_change(draft,baseline,candidate)
        preview=preview_workbook(candidate.read_bytes(),baseline,draft["baseline_sha256"])
        if (not preview.get("content_contract_compatible") or preview["changes"]["pending_retire"]
                or preview["changes"]["formula_cells"]):
            raise ValueError("候选包含未审核的结构、退役或公式变更")
        # Keep the archive private, immutable by name. Re-run importer checks at
        # the release gate. Never expose archive bytes to the browser.
        name=archive_sha+".zip";dest=root/name
        try:
            fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,"wb") as out, archive.open("rb") as source:
                for chunk in iter(lambda:source.read(1024*1024),b""):
                    out.write(chunk)
                out.flush();os.fsync(out.fileno())
        except FileExistsError:
            if dest.is_symlink() or sha256(dest)!=archive_sha:
                raise ValueError("已存在的候选包哈希冲突")
        return {"status":"VERIFIED_PACKAGE_NOT_PUBLISHED","archive_sha256":archive_sha,
                "source_sha256":manifest["source_sha256"],
                "manifest_sha256":sha256(package/"manifest.json"),
                "write_performed":False}
