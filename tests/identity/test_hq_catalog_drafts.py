"""Synthetic-only candidate workflow checks, no real database/files."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from services.api.identity import hq_catalog_api as m

SHA = "a"*64
OTHER = "b"*64
ROWS = {"C_现场成品":[{"id":"C000001","name":"演练","fields":{"商品名称":"演练","标注售价":88,"采购成本":20}}]}

def draft(**kwargs):
    body={"baseline_sha256":SHA,"kind":"edit","domain":"C","record_id":"C000001",
          "fields":{"商品名称":"新名称"},"reason":"这是一个完整演练理由"}
    body.update(kwargs)
    return m.Draft(**body)

def test_fields_and_immutable_id():
    m.check_draft(draft(),ROWS,SHA)
    assert "采购成本" not in m.visible_record(ROWS["C_现场成品"][0],"C")["fields"]
    for body in (draft(baseline_sha256=OTHER), draft(fields={"采购成本":"10"}),
                 draft(fields={"上架状态":"在售"}),draft(record_id="C999999"),
                 draft(domain="T"),draft(kind="create",record_id="C000002")):
        with pytest.raises(HTTPException):
            m.check_draft(body,ROWS,SHA)
    m.check_draft(draft(kind="create",record_id=""),ROWS,SHA)

def test_dual_review_and_stale_baseline(tmp_path):
    one=m.new_draft(tmp_path,"ENTITY","TRA0001",draft().model_dump())
    review=m.Review(decision="approve",reason="已经独立检查全部草稿")
    for entity,actor,active,expected in [
        ("OTHER","TRA0002",SHA,404),("ENTITY","TRA0001",SHA,403),("ENTITY","TRA0002",OTHER,409)]:
        with pytest.raises(HTTPException) as e:
            m.review_draft(tmp_path,one["id"],entity,actor,review,active)
        assert e.value.status_code==expected
    out=m.review_draft(tmp_path,one["id"],"ENTITY","TRA0002",review,SHA)
    assert out["status"]=="REVIEWED_NOT_PUBLISHED"
    assert out["reviewed_by"]=="TRA0002"
    with pytest.raises(HTTPException):
        m.review_draft(tmp_path,one["id"],"ENTITY","TRA0002",review,SHA)

def test_module_disabled_and_authority_fail_closed(monkeypatch):
    app=FastAPI()
    m.install_catalog_routes(app,None,SimpleNamespace(env="production"),None,None,Path("."))
    client=TestClient(app)
    monkeypatch.setenv("BSV_HQ_CATALOG_ENABLE","1")
    assert client.get("/api/v1/hq/catalog/status").status_code==503
    assert client.post("/api/v1/hq/catalog/drafts",json=draft().model_dump()).status_code==503

def test_scanner_missing_rejected(monkeypatch):
    monkeypatch.delenv("BSV_HQ_CATALOG_SCANNER",raising=False)
    with pytest.raises(HTTPException) as e:
        m.scan(b"not a workbook")
    assert e.value.status_code==503

def test_private_directory_permissions(tmp_path,monkeypatch):
    tmp_path.chmod(0o755)
    monkeypatch.setenv("BSV_IMPORT_ROOT",str(tmp_path))
    with pytest.raises(HTTPException):
        m.private_root()
    tmp_path.chmod(0o700)
    assert m.private_root().is_dir()

def test_same_bytes_stale_baseline(tmp_path):
    from bsv_catalog_workbook_preview import preview_workbook
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bsv1"))
    from make_fixture import write_fixture
    file=tmp_path/"base.xlsx"
    write_fixture(file)
    with pytest.raises(ValueError,match="数据库版本"):
        preview_workbook(file.read_bytes(),file,"0"*64)
