from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from services.api.supply.central_routes import central_router
from services.api.supply.demo import DemoCentral


def test_production_department_to_store_documents(tmp_path):
    demo = DemoCentral(tmp_path / "private" / "demo.sqlite3")
    application = FastAPI()

    def actor(request: Request):
        return demo.actor(request.headers.get("X-Demo-Actor", "DEMO-E01"))

    application.include_router(central_router(
        mode="demo", demo=demo, enabled=True, gateway=None, actor=actor, token_of=lambda r: None,
    ))
    now = datetime.now(timezone.utc)
    eta = (now + timedelta(hours=1)).isoformat()
    store = {"X-Demo-Actor": "DEMO-E02"}
    inspector = {"X-Demo-Actor": "DEMO-E03"}
    with TestClient(application) as client:
        def post(operation, payload, headers=None, *, committed=True):
            response = client.post("/api/central/" + operation, json=payload, headers=headers)
            assert response.status_code == 200, response.text
            data = response.json()
            if committed:
                assert data["state"] == "DEMO_COMMITTED"
            return data["data"]

        plan_inputs = dict(
            source_store_id="DEMO-WH", dest_store_id="BSVS", item_id="DEMO-P001",
            next_delivery_at=eta, usage_before_next="0", reserved="0", demand_next_cycle="800",
            safety_stock="0",
        )
        assert post("plan-preview", plan_inputs, committed=False)["packages"] == 2
        plan = post("plan", {**plan_inputs, "request_id": str(uuid4())})
        batch = post("batch", dict(
            request_id=str(uuid4()), plan_id=plan["plan_id"], produced_at=(now-timedelta(minutes=1)).isoformat(),
            recipe_version="DEMO-RECIPE-1", ingredient_lot_ids=["DEMO-LOT-1"], total="800",
            package_amounts=["450", "350"], remainder="0", loss="0",
        ))
        first, second = [p["package_id"] for p in batch["packages"]]
        print_id = str(uuid4())
        post("label", dict(request_id=print_id, package_ids=[first, second],
                           store_id="DEMO-WH", operation="PRINT"))
        labels = client.get("/api/central/print/labels", params=[
            ("store_id", "DEMO-WH"), ("package_ids", first), ("package_ids", second),
        ])
        assert labels.status_code == 200, labels.text
        assert labels.headers["Cache-Control"] == "no-store" and "50mm 40mm" in labels.text
        post("label", dict(request_id=str(uuid4()), package_ids=[first, second],
                           store_id="DEMO-WH", operation="CONFIRM", print_request_id=print_id))
        ship = post("create", dict(request_id=str(uuid4()), source_store_id="DEMO-WH",
                                   dest_store_id="BSVS", package_ids=[first, second], eta=eta))
        sid = ship["id"]
        prepared = post("prepare", dict(request_id=str(uuid4()), shipment_id=sid, expected_version=ship["version"]))
        sent = post("dispatch", dict(request_id=str(uuid4()), shipment_id=sid,
                                     expected_version=prepared["version"], scanned_codes=[first, second]))
        receipt = dict(request_id=str(uuid4()), shipment_id=sid, expected_version=sent["version"],
                       accepted_ids=[first], hold_ids=[], exception_reasons={})
        assert client.post("/api/central/receive", json=receipt, headers=inspector).status_code == 403
        partly = post("receive", receipt, store)
        assert partly["state"] == "PARTIAL_RECEIVED"
        assert post("receive", receipt, store) == partly
        arrival = client.get("/api/central/print/arrival", params={"shipment_id": sid}, headers=store)
        assert arrival.status_code == 200, arrival.text
        assert "合格 450" in arrival.text and "待核 350" in arrival.text
        post("receive", dict(request_id=str(uuid4()), shipment_id=sid, expected_version=partly["version"],
                             accepted_ids=[], hold_ids=[second], exception_reasons={second: "温控异常"}), store)

        denied = client.get("/api/central/inventory", params={"store_id": "BSVT"}, headers=store)
        assert denied.status_code == 403
        expiry = client.get("/api/central/print/expiry", params={"store_id": "BSVS"}, headers=store)
        assert expiry.status_code == 200 and first in expiry.text and second in expiry.text
        end_tasks = client.get("/api/central/tasks", params={"store_id": "BSVS", "phase": "END"}, headers=store)
        assert end_tasks.status_code == 200 and end_tasks.json()["data"]["phase"] == "END"
        exceptions = client.get("/api/central/exceptions", params={"store_id": "BSVS"}, headers=inspector)
        assert exceptions.status_code == 200 and any(
            item["package_id"] == second for item in exceptions.json()["data"]["items"]
        )
