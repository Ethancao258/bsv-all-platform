from dataclasses import replace
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from services.api.bsv1 import bsv_layouts
from services.api.supply import main
from services.api.supply.cache import LocalCache
from services.api.supply.demo import DEMO_STORES
from services.api.supply.gateway import Unreachable

ROOT = Path(__file__).resolve().parents[2]
CHECKS = ("expiry", "temperature", "hygiene", "equipment", "pricing", "previous_actions")


def test_pos_and_menu_store_ids_and_distinct_catalogue_ids():
    menu = json.loads((ROOT / "apps/guest-web/bsv1/site/cocktail/data/menu-public.json").read_bytes())
    supply = json.loads((ROOT / "ingestion/sources/supply-v9-id-index.json").read_bytes())
    canonical = {x["store_id"] for x in bsv_layouts.registry()}
    assert canonical == {x["store_id"] for x in menu["stores"]}
    assert canonical == {x["store_id"] for x in DEMO_STORES if x["kind"] != "warehouse"}
    assert not ({x["product_id"] for x in menu["items"]} & {x["id"] for x in supply["p"] + supply["m"]})
    assert all(not row["approved"] for row in supply["p"] + supply["m"])
    if name := os.getenv("BSV_SUPPLY_REFERENCE_V9"):
        import sys
        sys.path.insert(0, str(ROOT / "services/api/bsv1"))
        from bsv_v9_import import unpack_v9
        pages, _, _, _ = unpack_v9(Path(name))
        assert {x["id"] for x in supply["p"]} == {x["id"] for x in pages["P_预调半成品"]}
        assert {x["id"] for x in supply["m"]} <= {x["id"] for x in pages["M_采购纯饮"]}
        assert {x["product_id"] for x in menu["items"]} == {
            x["id"] for key in ("C_现场成品", "K_套餐组合") for x in pages[key]
        }
        assert canonical == {x["fields"]["门店ID"] for x in pages["T_门店注册"]}


def test_inspection_separation_and_review_over_http():
    def actor(code):
        return {"X-Demo-Actor": "DEMO-" + code}
    payload = dict(request_id=str(uuid4()), kind="independent", store_id="BSVS",
                   results={k: "NOT_CHECKED" for k in CHECKS})
    with TestClient(main.app) as client:
        assert client.post("/api/inspections", json=payload, headers=actor("E02")).status_code == 403
        response = client.post("/api/inspections", json=payload, headers=actor("E03"))
        assert response.status_code == 200, response.text
        path = "/api/inspections/" + response.json()["inspection_id"] + "/review"
        decision = dict(request_id=str(uuid4()), decision="APPROVED")
        assert client.post(path, json=decision, headers=actor("E03")).status_code == 403
        response = client.post(path, json=decision, headers=actor("E04"))
        assert response.status_code == 200
        assert client.post(path, json=decision, headers=actor("E04")).json() == response.json()
        assert all(x["kind"] == "self_check" for x in client.get("/api/inspections", headers=actor("E02")).json()["data"])
        assert client.post("/api/inspections", json={**payload, "request_id": str(uuid4()), "store_id": "BSVM"},
                           headers=actor("E03")).status_code == 403


def test_offline_replay_is_scoped_and_uses_same_id(tmp_path, monkeypatch):
    actors = {
        "one": dict(employee_id="EMP-A", department_id="DEP", stores=["BSVS"], roles=["inspect"]),
        "two": dict(employee_id="EMP-B", department_id="DEP", stores=["BSVS"], roles=["inspect"]),
    }

    class CentralStub:
        unverified = False
        offline = True

        def __init__(self):
            self.commits = {}

        def read(self, key, path, *, user_token, allow_cache):
            assert (key, path, allow_cache) == ("B", "/auth/me", False)
            if self.unverified:
                raise Unreachable()
            return {"data": actors[user_token]}

        def write(self, key, path, payload, *, user_token):
            assert (key, path, user_token) == ("D", "/inventory/counts", "one")
            if self.offline:
                raise Unreachable()
            self.commits.setdefault(payload["request_id"], payload)
            return {"inventory_adjusted": False}

    central = CentralStub()
    monkeypatch.setattr(main, "demo", None)
    monkeypatch.setattr(main, "settings", replace(main.settings, mode="remote"))
    monkeypatch.setattr(main, "gateway", central)
    monkeypatch.setattr(main, "cache", LocalCache(tmp_path))

    def headers(token):
        return {"Authorization": "Bearer " + token}

    payload = dict(request_id=str(uuid4()), store_id="BSVS", item_id="P000015",
                   full_packages=2, opened_count=1, opened_percent=50)
    with TestClient(main.app) as client:
        assert client.post("/api/stock-count", json=payload, headers=headers("one")).status_code == 202
        assert client.post("/api/stock-count", json=payload, headers=headers("one")).status_code == 202
        assert len(client.get("/api/pending", headers=headers("one")).json()) == 1
        central.offline = False
        assert client.post("/api/pending/sync", headers=headers("two")).json() == {"results": []}
        actors["one"]["stores"] = ["BSVM"]
        assert client.post("/api/pending/sync", headers=headers("one")).json() == {"results": []}
        actors["one"]["stores"] = ["BSVS"]
        central.unverified = True
        assert client.post("/api/pending/sync", headers=headers("one")).status_code == 503
        central.unverified = False
        assert client.post("/api/pending/sync", headers=headers("one")).json() == {
            "results": [{"request_id": payload["request_id"], "state": "COMMITTED"}]
        }
        assert client.post("/api/pending/sync", headers=headers("one")).json() == {"results": []}
    assert list(central.commits) == [payload["request_id"]]


def test_qr_preview_keeps_demo_images_local(monkeypatch):
    from integrations.vision import supply_photo

    def forbid_network(*_, **__):
        pytest.fail("demo image was sent to external vision")

    monkeypatch.setenv("BSV_SUPPLY_VISION_ENABLED", "1")
    monkeypatch.setattr(supply_photo.httpx, "Client", forbid_network)
    with TestClient(main.app) as client:
        response = client.post("/api/photo-preview", data={"consent_external": "true"},
                               files={"file": ("demo", b"synthetic test", "image/jpeg")})
    assert response.status_code == 200
    assert response.json()["mode"] == "LOCAL_QR_ONLY" and not response.json()["posted"]


def test_openapi_and_role_entrypoints_match_contract():
    expected = json.loads((ROOT / "contracts/supply/openapi.json").read_bytes())
    assert main.app.openapi() == expected
    with TestClient(main.app) as client:
        assert client.get("/api/health").json()["production_connected"] is False
        for path in ("/hq/supply", "/store/supply", "/inspector/supply"):
            assert client.get(path).status_code == 200


def test_pg_archive_roundtrip_and_tamper_refusal(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from cryptography.exceptions import InvalidTag
    import runpy
    from unittest.mock import patch

    backup = runpy.run_path(str(ROOT / "platform/lighthouse/supply/postgres_backup.py"))
    monkeypatch.setenv("BSV_BACKUP_AES256_KEY_HEX", os.urandom(32).hex())
    monkeypatch.setenv("PGSERVICE", "synthetic-test")
    payload = b"PGDMP" + bytes(range(256))

    def run_stub(args, **_):
        if args[0] == "pg_dump":
            Path(args[args.index("--file") + 1]).write_bytes(payload)
        else:
            assert args[:2] == ["pg_restore", "--list"]
            assert Path(args[2]).read_bytes() == payload
        return SimpleNamespace(returncode=0)

    with patch("shutil.which", return_value="/dummy"), patch("subprocess.run", side_effect=run_stub):
        archive = Path(backup["encrypted_dump"](tmp_path)["file"])
    restored = tmp_path / "isolated.custom"
    backup["decrypt_archive"](archive, restored)
    assert restored.read_bytes() == payload
    with pytest.raises(RuntimeError):
        backup["decrypt_archive"](archive, restored)
    modified = bytearray(archive.read_bytes())
    modified[-1] ^= 1
    archive.write_bytes(modified)
    rejected = tmp_path / "cannot-restore.custom"
    with pytest.raises(InvalidTag):
        backup["decrypt_archive"](archive, rejected)
    assert not rejected.exists()
