"""V3 operator HTTP driver against real PG17 and the four application sockets."""
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from services.api.identity import api
from services.api.identity.seed_isolated import seed
from .conftest import admin_post, login_admin
from .test_consumers import identity_http
from .test_internal_stage import process

ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / "platform/lighthouse/internal-stage"
PASSWORD3 = "synthetic-admin-password-three-2026"
PIN = "81351593300"


def test_operator_driver_twice(identity_http, tmp_path, monkeypatch):
    supply_python = os.environ.get("BSV_STAGE_SUPPLY_PYTHON")
    if not supply_python or api.router.a.dialect.name != "postgresql":
        pytest.skip("Run with real disposable PG17 and separate locked supply environment")
    monkeypatch.setenv("BSV_DEMO_ADMIN_3_PASSWORD", PASSWORD3)
    seed()
    reviewer = login_admin(2)
    response = admin_post(reviewer, "/api/v1/identity/legacy-import/commit", {
        "legal_entity_id": "DEMO_LEGAL", "reason": "prior synthetic setup", "evidence_ref": "SYNTH-V3",
        "rows": [{"source_system": "bsv1_pos", "legacy_value": "SYNTH-STAGE-POS-01", "tr_code": "TRA0001"}],
    })
    assert response.status_code == 200 and response.json()["write_count"] == 1
    tokens = {
        "pos": {"token": "test-local-pos", "actions": ["pos.order.read", "pos.order.create"],
                "legal_entities": ["DEMO_LEGAL"], "stores": ["BSVT"]},
        "supply": {"token": "test-local-supply", "actions": ["supply.receive", "quality.independent.submit"],
                   "stores": ["BSVT", "BSVS"], "legal_entity_id": "DEMO_LEGAL", "isolated_test_department": "SYNTH-STAGE"},
    }
    monkeypatch.setattr(api, "settings", replace(api.settings, service_tokens=tokens))
    data = tmp_path / "bsv-all-internal-stage" / "pos"
    data.mkdir(parents=True)
    pos_env = {"BSV_MODE": "staging", "BSV_DB_PATH": str(data / "synthetic.sqlite3"),
               "BSV_V9_XLSX": str(data / "synthetic-v9.xlsx"), "BSV_STAGE_POS_PIN": PIN,
               "BSV_PRIVATE_SSH_TUNNEL": "1", "BSV_POS_INTERNAL_STAGE": "1", "BSV_POS_IDENTITY_REQUIRED": "1",
               "BSV_POS_STORE_LEGAL_JSON": '{"BSVT":"DEMO_LEGAL"}', "BSV_POS_IDENTITY_URL": identity_http,
               "BSV_POS_IDENTITY_TOKEN": "test-local-pos"}
    subprocess.run([sys.executable, "-B", STAGE / "seed_pos.py"], check=True, env={**os.environ, **pos_env})
    sources = json.loads((ROOT / "config/modules/supply-sources.example.json").read_text())
    for value in sources["sources"].values():
        value["primary"] = value["standby_read"] = ""
    sources["sources"]["B"]["primary"] = identity_http + "/api/v1"
    config = tmp_path / "sources.json"
    config.write_text(json.dumps(sources))
    supply_env = {"BSV_MODE": "internal-stage", "BSV_SOURCES_CONFIG": str(config),
                  "BSV_SUPPLY_STATE_DIR": str(tmp_path / "supply"), "BSV_SOURCE_B_TOKEN": "test-local-supply"}
    server = ("--host", "127.0.0.1", "--port", "$PORT", "--no-proxy-headers")
    monkeypatch.syspath_prepend(str(STAGE))
    spec = importlib.util.spec_from_file_location("operator_acceptance", STAGE / "acceptance.py")
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    with process((sys.executable, ROOT / "services/api/bsv1/app.py"), "BSV_PORT", pos_env, tmp_path, "pos") as pos:
        with process((supply_python, "-m", "uvicorn", "services.api.supply.main:app", *server),
                     "BSV_SUPPLY_PORT", supply_env, tmp_path, "supply") as supply:
            settings = {"BSV_STAGE_POS_PORT": str(pos), "BSV_STAGE_SUPPLY_PORT": str(supply),
                        "BSV_STAGE_IDENTITY_PORT": identity_http.rsplit(":", 1)[1]}
            with process((sys.executable, "-m", "uvicorn", "--app-dir", STAGE, "ingress:app", *server),
                         "BSV_STAGE_INGRESS_PORT", settings, tmp_path, "ingress") as ingress:
                passwords = [os.environ[f"BSV_DEMO_ADMIN_{i}_PASSWORD"] for i in range(1, 4)]
                for _ in range(2):
                    results = []
                    driver.exercise(f"http://127.0.0.1:{ingress}", passwords, PIN, results, True, str(uuid4()))
                    assert {item["test_id"] for item in results if item["status"] == "BLOCKED"} == {"CENTRAL_D_E"}, results
                    assert any(item["test_id"] == "REVOCATION" and item["status"] == "PASS" for item in results)
