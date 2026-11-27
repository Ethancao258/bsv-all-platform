from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
import pytest

from services.api.supply.central_transactions import CentralDemo
from services.api.supply.demo import DemoCentral

HQ = "DEMO-E01"
SHOP = "DEMO-E02"
AUDITOR = "DEMO-E03"
WAREHOUSE = "DEMO-WH"
STORE = "BSVS"


class Scenario:
    def __init__(self, path):
        self.now = datetime(2026, 11, 27, 12, tzinfo=timezone.utc)
        self.ledger = DemoCentral(path)
        self.service = CentralDemo(self.ledger, clock=lambda: self.now)

    def mutate(self, op, actor=HQ, shipment_id=None, **body):
        body.setdefault("request_id", str(uuid4()))
        return self.service.mutate(op, body, self.ledger.actor(actor), shipment_id)

    def read(self, kind, actor=HQ, **scope):
        return self.service.snapshot(kind, self.ledger.actor(actor), **scope)

    def plan_body(self):
        return {
            "source_store_id": WAREHOUSE, "dest_store_id": STORE, "item_id": "DEMO-P001",
            "next_delivery_at": (self.now + timedelta(hours=3)).isoformat(),
            "usage_before_next": "0", "reserved": "0", "demand_next_cycle": "1550",
            "safety_stock": "150",
        }

    def batch(self, amounts=("450", "350"), **overrides):
        plan = self.mutate("plan", **self.plan_body())
        production = {
            "plan_id": plan["plan_id"], "produced_at": self.now.isoformat(),
            "recipe_version": "DEMO-RECIPE-1", "ingredient_lot_ids": ["DEMO-LOT-1"],
            "total": "800", "package_amounts": list(amounts), "remainder": "0", "loss": "0",
        }
        return self.mutate("batch", **{**production, **overrides})

    def send(self, batch):
        ids = [p["package_id"] for p in batch["packages"]]
        ship = self.mutate(
            "create", source_store_id=WAREHOUSE, dest_store_id=STORE, package_ids=ids,
            eta=(self.now + timedelta(hours=2)).isoformat(),
        )
        self.mutate("prepare", shipment_id=ship["id"], expected_version=1)
        sent = self.mutate("dispatch", shipment_id=ship["id"], expected_version=2, scanned_codes=ids)
        assert sent["state"] == "DISPATCHED"
        return ship["id"], ids


@pytest.fixture
def scenario(tmp_path):
    return Scenario(tmp_path / "DEMO_ONLY_ledger.sqlite3")


def test_partial_receipt_overlapping_requests_and_legacy_guard(scenario):
    batch = scenario.batch()
    shipment, (first, second) = scenario.send(batch)
    assert any(item["id"] == shipment for item in scenario.ledger.list(scenario.ledger.actor(HQ)))
    with pytest.raises(HTTPException) as err:
        scenario.ledger.mutate(
            "receive", shipment,
            {"request_id": str(uuid4()), "expected_version": 3, "scanned_codes": [first]},
            scenario.ledger.actor(SHOP),
        )
    assert err.value.status_code == 409

    body = {"expected_version": 3, "request_id": str(uuid4()), "accepted_ids": [first], "hold_ids": []}

    def receive(_):
        return scenario.mutate("receive", SHOP, shipment, **body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.map(receive, (1, 2))
    assert one == two
    assert one["state"] == "PARTIAL_RECEIVED"
    with pytest.raises(HTTPException) as err:
        scenario.mutate("receive", SHOP, shipment, **{**body, "accepted_ids": [second]})
    assert err.value.status_code == 409

    scenario.mutate(
        "receive", SHOP, shipment, expected_version=4, accepted_ids=[], hold_ids=[second],
        exception_reasons={second: "运输温度异常"},
    )
    current = scenario.read("inventory", SHOP, store_id=STORE)
    assert {(p["state"], p["remaining"], p["usable"]) for p in current["packages"]} == {
        ("ACCEPTED", "450", True), ("HOLD", "350", False),
    }
    arrivals = scenario.read("shipment", SHOP, shipment_id=shipment)
    assert {r["package"]["package_id"] for r in arrivals["receipts"]} == {first, second}
    assert {p["package_id"] for p in arrivals["planned"]} == {first, second}
    assert arrivals["arrived_at"] == scenario.now.isoformat()
    assert scenario.read("exceptions", AUDITOR, store_id=STORE)["items"][0]["kind"] == "HOLD"
    with pytest.raises(HTTPException) as err:
        scenario.mutate(
            "dispose", AUDITOR, store_id=STORE, package_id=second, expected_version=3,
            amount="350", reason="到货隔离",
        )
    assert err.value.status_code == 403


def test_opened_expiry_historical_stock_and_disposal(scenario):
    first_ship, old = scenario.send(scenario.batch())
    scenario.mutate("receive", SHOP, first_ship, expected_version=3, accepted_ids=old, hold_ids=[])
    old_data = scenario.read("inventory", SHOP, store_id=STORE)["packages"]
    p = next(p for p in old_data if p["package_id"] == old[0])
    opened = scenario.mutate("open", SHOP, store_id=STORE, package_id=old[0], expected_version=p["version"])
    scenario.now += timedelta(hours=1)
    second_ship, new = scenario.send(scenario.batch())
    scenario.mutate("receive", SHOP, second_ship, expected_version=3, accepted_ids=new, hold_ids=[])
    inventory = scenario.read("inventory", SHOP, store_id=STORE)["packages"]
    assert {p["package_id"] for p in inventory} == set(old + new)
    current = next(p for p in inventory if p["package_id"] == old[0])
    assert current["expires_at"] == scenario.now.isoformat() and current["usable"] is False
    assert any(
        task["package_id"] == old[0] and task["handover_required"]
        for task in scenario.read("tasks", SHOP, store_id=STORE, phase="END")["tasks"]
        if task["kind"] == "EXPIRY_REVIEW"
    )
    disposed = scenario.mutate(
        "dispose", SHOP, store_id=STORE, package_id=old[0], expected_version=opened["version"],
        amount="120", reason="实际报损120mL",
    )
    assert disposed["remaining"] == "330"
    assert not scenario.read("inventory", HQ, store_id="BSVM")["packages"]
    with pytest.raises(HTTPException) as err:
        scenario.read("inventory", SHOP, store_id="BSVM")
    assert err.value.status_code == 403


def test_print_reprint_snapshots_and_operator_confirmation(scenario):
    batch = scenario.batch()
    p = batch["packages"][0]
    fields = {"store_id": WAREHOUSE, "package_ids": [p["package_id"]]}
    initial = scenario.mutate("label", operation="PRINT", **fields)
    assert initial["state"] == "PRINT_REQUESTED"
    scenario.now += timedelta(minutes=1)
    again = scenario.mutate("label", operation="REPRINT", **fields)
    assert initial["packages"] == again["packages"]
    confirmed = scenario.mutate("label", operation="CONFIRM", print_request_id=again["request_id"], **fields)
    assert confirmed["state"] == "OPERATOR_CONFIRMED"
    with pytest.raises(HTTPException) as err:
        scenario.mutate("label", operation="CONFIRM", print_request_id=again["request_id"], **fields)
    assert err.value.status_code == 409
    assert len(scenario.read("labels", store_id=WAREHOUSE, package_ids=fields["package_ids"])["history"]) == 3


def test_failed_split_and_expired_receipt_do_not_write(scenario):
    with pytest.raises(HTTPException) as err:
        scenario.batch(("450", "351"))
    assert err.value.status_code == 422
    assert not scenario.read("inventory", store_id=WAREHOUSE)["packages"]
    shipment, ids = scenario.send(scenario.batch())
    scenario.now += timedelta(days=2)
    with pytest.raises(HTTPException) as err:
        scenario.mutate("receive", SHOP, shipment, expected_version=3, accepted_ids=ids, hold_ids=[])
    assert err.value.status_code == 409
    assert scenario.read("shipment", SHOP, shipment_id=shipment)["version"] == 3
    assert scenario.read("shipment", SHOP, shipment_id=shipment)["receipts"] == []
    held = scenario.mutate(
        "receive", SHOP, shipment, expected_version=3, accepted_ids=[], hold_ids=ids,
        exception_reasons={pid: "到货时已过期" for pid in ids},
    )
    assert held["state"] == "RECEIVED"


def test_scoped_revocation_blocks_plan_replay_and_shipment_disclosure(scenario):
    body = {**scenario.plan_body(), "request_id": str(uuid4())}
    plan = scenario.service.mutate("plan", body, scenario.ledger.actor(HQ))
    actor = {**scenario.ledger.actor(HQ), "role_stores": {"dispatch": [WAREHOUSE]}}
    with pytest.raises(HTTPException) as err:
        scenario.service.mutate("plan", body, actor)
    assert err.value.status_code == 403
    assert scenario.service.snapshot("plans", actor, store_id=WAREHOUSE)["plans"] == []
    assert scenario.read("plans", store_id=WAREHOUSE)["plans"][0]["plan_id"] == plan["plan_id"]

    shipment, _ = scenario.send(scenario.batch())
    scoped = {**scenario.ledger.actor(HQ), "role_stores": {"receive": [STORE]}}
    assert scenario.service.snapshot("shipment", scoped, shipment_id=shipment)["dest"] == STORE
    with pytest.raises(HTTPException) as err:
        scenario.service.snapshot("shipment", scoped, shipment_id=shipment, store_id=WAREHOUSE)
    assert err.value.status_code == 403


def test_recall_preserves_in_transit_and_cannot_be_accepted(scenario):
    shipment, (first, second) = scenario.send(scenario.batch())
    data = scenario.read("shipment", SHOP, shipment_id=shipment)
    package = next(p for p in data["packages"] if p["package_id"] == first)
    recall = scenario.mutate(
        "recall", store_id=STORE, package_id=first, expected_version=package["version"],
        reason="演示原料召回",
    )
    assert recall["state"] == "IN_TRANSIT"
    exceptions = scenario.read("exceptions", AUDITOR, store_id=STORE)["items"]
    assert any(item["kind"] == "RECALL" and item["reason"] == "演示原料召回" for item in exceptions)
    with pytest.raises(HTTPException) as err:
        scenario.mutate("receive", SHOP, shipment, expected_version=3, accepted_ids=[first], hold_ids=[])
    assert err.value.status_code == 409
    assert scenario.read("shipment", SHOP, shipment_id=shipment)["receipts"] == []
    final = scenario.mutate(
        "receive", SHOP, shipment, expected_version=3, accepted_ids=[second], hold_ids=[first],
        exception_reasons={first: "召回隔离"},
    )
    assert final["state"] == "RECEIVED"
