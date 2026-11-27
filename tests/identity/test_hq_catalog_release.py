"""Synthetic release control and ID reservation checks."""
import json
import os
from pathlib import Path
from zipfile import ZipFile
import pytest
from services.api.identity import hq_catalog_api
from bsv_hq_ids import allocate
from bsv_hq_release import read_draft,safe_extract

def test_id_history_nonreuse(tmp_path,monkeypatch):
    monkeypatch.setenv("BSV_HQ_CATALOG_ID_HISTORY_VERIFIED","1")
    legacy=tmp_path/"verified-legacy-ids.json"
    legacy.write_text(json.dumps({"status":"HISTORY_RECONCILED","evidence_ref":"synthetic-test","ids":["C000004"]}))
    legacy.chmod(0o600)
    assert allocate(tmp_path,"C","TRA0001",{"C000002"},history={"C000005"})==["C000006"]
    assert allocate(tmp_path,"C","TRA0001",{"C000002"},history={"C000005"})==["C000007"]
    with pytest.raises(ValueError):allocate(tmp_path,None,"TRA0001",set(),requested=["C000006"],history=set())
    with pytest.raises(ValueError):allocate(tmp_path,None,"TRA0001",set(),requested=["C000004"],history=set())
    monkeypatch.delenv("BSV_HQ_CATALOG_ID_HISTORY_VERIFIED")
    with pytest.raises(ValueError):allocate(tmp_path,"C","TRA0001",set(),history=set())

def test_release_requires_different_people_and_explicit_request(tmp_path,monkeypatch):
    monkeypatch.setenv("BSV_HQ_CATALOG_LEGAL_ENTITY_ID","SYNTHETIC")
    key="a"*32;file=tmp_path/(key+".json")
    body={"id":key,"status":"VERIFIED_PACKAGE_NOT_PUBLISHED","created_by":"TRA0001","reviewed_by":"TRA0002","legal_entity":"SYNTHETIC"}
    file.write_text(json.dumps(body))
    with pytest.raises(ValueError):read_draft(tmp_path,key)
    body.update(status="RELEASE_REQUESTED",release_requested_by="TRA0002")
    file.write_text(json.dumps(body));assert read_draft(tmp_path,key)["id"]==key
    body["reviewed_by"]="TRA0001";file.write_text(json.dumps(body))
    with pytest.raises(ValueError):read_draft(tmp_path,key)

def test_release_archive_path_traversal(tmp_path):
    archive=tmp_path/"bad.zip"
    with ZipFile(archive,"w") as z:z.writestr("../outside","no")
    folder=tmp_path/"out";folder.mkdir()
    with pytest.raises(ValueError):safe_extract(archive,folder)
    assert not (tmp_path/"outside").exists()
