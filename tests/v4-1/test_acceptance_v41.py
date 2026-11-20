"""Isolated V3 -> V4.1 PostgreSQL upgrade and browser/HTTP workflows against real listeners."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import tarfile
import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / "platform/lighthouse/internal-stage"
AUTH = "/api/v1/auth"
V3 = "0e8b3c00544ccd533eebd1258598f2622c5b0984"
PASSWORDS = ("synthetic-password-first-2026", "synthetic-password-second-2026", "synthetic-password-third-2026")
ALIAS = {"legal_entity_id": "DEMO_LEGAL", "reason": "Existing isolated test mapping preserved",
         "evidence_ref": "SYNTHETIC-V3",
         "rows": [{"source_system": "bsv1_pos", "legacy_value": "SYNTH-STAGE-POS-01", "tr_code": "TRA0001"}]}


@contextmanager
def listen(argv, env, directory, component, source=ROOT):
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    cmd = [str(port) if arg == "$PORT" else str(arg) for arg in argv]
    settings = {**os.environ, **env, "BSV_PORT": str(port), "PYTHONPATH": str(source)}
    logfile = directory / (component + ".log")
    with logfile.open("w") as log:
        process = subprocess.Popen(cmd, env=settings, cwd=source, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(80):
                if process.poll() is not None:
                    break
                try:
                    connection = socket.create_connection(("127.0.0.1", port), timeout=0.1)
                except OSError:
                    time.sleep(0.15)
                    continue
                connection.close()
                yield port
                return
            pytest.fail(f"{component} did not start: {logfile.read_text()}")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)


def run(*cmd, env=None):
    return subprocess.run(cmd, check=True, cwd=ROOT, env={**os.environ, **(env or {})})


def migrate(revision):
    run(sys.executable, "-m", "alembic", "-c", ROOT / "platform/lighthouse/identity/alembic.ini", "upgrade", revision)


def test_v4_authority_two_devices_on_upgraded_v3_data(tmp_path, monkeypatch):
    if os.getenv("BSV_V41_TEST_ACTIVE") != "1":
        pytest.skip("Use bash tests/v4-1/check.sh to supply disposable PostgreSQL 17")
    dsn = make_url(os.environ["BSV_DB_A_URL"])
    assert dsn.host == "127.0.0.1" and dsn.database == "bsv_identity_isolated_v41"
    database = create_engine(dsn)
    with database.connect() as db:
        assert int(db.exec_driver_sql("SHOW server_version_num").scalar_one()) // 10000 == 17
    service_tokens = {"pos": {"token": "test-pos-service-isolated", "actions": ["pos.order.read", "pos.order.create"],
                              "legal_entities": ["DEMO_LEGAL"], "stores": ["BSVT", "BSVS"]},
                      "supply": {"token": "test-supply-service-isolated", "actions": ["supply.receive"],
                                 "legal_entity_id": "DEMO_LEGAL", "stores": ["BSVT"],
                                 "isolated_test_department": "SYNTH-STAGE"}}
    env = {"BSV_SERVICE_TOKENS_JSON": json.dumps(service_tokens)}
    env.update({f"BSV_DEMO_ADMIN_{i}_PASSWORD": item for i, item in enumerate(PASSWORDS, 1)})
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    with subprocess.Popen(["git", "archive", V3], cwd=ROOT, stdout=subprocess.PIPE) as archive:
        with tarfile.open(fileobj=archive.stdout, mode="r|") as stream:
            stream.extractall(legacy, filter="data")
        assert archive.wait() == 0
    migrate("bsv_identity_0001")
    subprocess.run([sys.executable, "-m", "services.api.identity.seed_isolated", "--i-understand-isolated"],
                   check=True, cwd=legacy, env={**os.environ, **env, "PYTHONPATH": str(legacy)})
    args = ("--host", "127.0.0.1", "--port", "$PORT", "--no-proxy-headers")
    identity = (sys.executable, "-m", "uvicorn", "services.api.identity.api:app", *args)
    with listen(identity, env, tmp_path, "identity-v3", source=legacy) as identity_port:
        with httpx.Client(base_url=f"http://127.0.0.1:{identity_port}", trust_env=False) as client:
            response = client.post(AUTH + "/isolated/login", json={"username": "reviewer2", "password": PASSWORDS[1]})
            assert response.status_code == 200, response.text
            result = client.post("/api/v1/identity/legacy-import/commit", json=ALIAS,
                                 headers={"X-CSRF-Token": client.cookies["bsv_csrf"]})
            assert result.status_code == 200 and result.json()["write_count"] == 1
    with database.connect() as db:
        people = list(db.exec_driver_sql("SELECT tr_code FROM bsv_identity_people ORDER BY tr_code").scalars())
    assert people == ["TRA0001", "TRA0002", "TRA0003"]
    migrate("head")
    with database.connect() as db:
        assert list(db.exec_driver_sql("SELECT tr_code FROM bsv_identity_people ORDER BY tr_code").scalars()) == people
        assert db.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "bsv_academy_0002"

    data = tmp_path / "bsv-all-internal-stage" / "pos"
    data.mkdir(parents=True)
    pos_env = {"BSV_MODE": "staging", "BSV_DB_PATH": str(data / "synthetic.sqlite3"),
               "BSV_V9_XLSX": str(data / "synthetic-v9.xlsx"), "BSV_STAGE_POS_PIN": "81351593300",
               "BSV_PRIVATE_SSH_TUNNEL": "1", "BSV_POS_INTERNAL_STAGE": "1", "BSV_POS_IDENTITY_REQUIRED": "1",
               "BSV_POS_DEVICE_REQUIRED": "1", "BSV_POS_STORE_LEGAL_JSON": '{"BSVT":"DEMO_LEGAL","BSVS":"DEMO_LEGAL"}',
               "BSV_POS_IDENTITY_TOKEN": "test-pos-service-isolated"}
    run(sys.executable, STAGE / "seed_pos.py", env=pos_env)
    assert (data / "synthetic.sqlite3").is_file()
    supply_python = os.environ.get("BSV_STAGE_SUPPLY_PYTHON", sys.executable)
    supply = (supply_python, "-m", "uvicorn", "services.api.supply.main:app", *args)
    ingress = (sys.executable, "-m", "uvicorn", "--app-dir", STAGE, "ingress:app", *args)
    monkeypatch.syspath_prepend(str(STAGE))
    driver = runpy.run_path(str(STAGE / "acceptance_v41.py"))
    with listen(identity, env, tmp_path, "identity-v4") as identity_port:
        orig = f"http://127.0.0.1:{identity_port}"
        pos_env["BSV_POS_IDENTITY_URL"] = orig
        sources = json.loads((ROOT / "config/modules/supply-sources.example.json").read_text())
        for value in sources["sources"].values():
            value["primary"] = value["standby_read"] = ""
        sources["sources"]["B"]["primary"] = orig + "/api/v1"
        cfg = tmp_path / "sources.json"
        cfg.write_text(json.dumps(sources))
        sup_env = {"BSV_MODE": "internal-stage", "BSV_SOURCES_CONFIG": str(cfg),
                   "BSV_SUPPLY_STATE_DIR": str(tmp_path / "supply"), "BSV_SOURCE_B_TOKEN": "test-supply-service-isolated"}
        with listen((sys.executable, ROOT / "services/api/bsv1/app.py"), pos_env, tmp_path, "pos") as pos:
            with listen(supply, sup_env, tmp_path, "supply") as sup:
                settings = {"BSV_STAGE_POS_PORT": str(pos), "BSV_STAGE_SUPPLY_PORT": str(sup),
                            "BSV_STAGE_IDENTITY_PORT": str(identity_port)}
                with listen(ingress, settings, tmp_path, "ingress") as port:
                    base = f"http://127.0.0.1:{port}"
                    browser_check = None
                    if os.getenv("BSV_V41_BROWSER") == "1":
                        browser = runpy.run_path(str(ROOT / "tests/ui/v41_browser.py"))

                        def browser_check(terminal):
                            browser["check"](base, username="reviewer1", password=PASSWORDS[0], expected_tr="TRA0001",
                                             device_id=terminal["device_id"], device_token=terminal["device_token"])

                    for index in range(2):
                        results = []
                        driver["run_flow"](base, PASSWORDS, results, str(uuid4()),
                                           browser_check=browser_check if index == 1 else None)
                        assert {r["test_id"] for r in results if r["status"] == "BLOCKED"} == {"CENTRAL_D_E"}, results
                        assert all(any(r["test_id"] == check and r["status"] == "PASS" for r in results)
                                   for check in {"IDENTITY", "LEGACY_ALIAS", "TRAINING", "SHIFT", "POS", "CROSS_STORE"})
    # A code rollback leaves the additive tables in place. The actual pinned V3
    # process must still authenticate the existing synthetic person and alias.
    with listen(identity, env, tmp_path, "identity-v3-restored-code", source=legacy) as identity_port:
        with httpx.Client(base_url=f"http://127.0.0.1:{identity_port}", trust_env=False) as client:
            assert client.get("/health/ready").json()["status"] == "ready"
            login = client.post(AUTH + "/isolated/login", json={"username": "reviewer2", "password": PASSWORDS[1]})
            assert login.status_code == 200
            preview = client.post("/api/v1/identity/legacy-import/dry-run",
                                  json={"legal_entity_id": "DEMO_LEGAL", "rows": ALIAS["rows"]},
                                  headers={"X-CSRF-Token": client.cookies["bsv_csrf"]})
            assert preview.json()["records"][0]["issues"] == ["ALREADY_MAPPED"]
