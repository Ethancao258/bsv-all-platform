import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/api/bsv1"))
sys.path.insert(0, str(ROOT / "tests/bsv1"))
from make_fixture import write_fixture
from public_menu_projection import from_workbook, project_records
from bsv_v9_import import unpack_v9, cents_from_price
from bsv_layouts import registry

snapshot = ROOT / "apps/guest-web/bsv1/site/cocktail/data/menu-public.json"
assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == "ca7d6a12ff62c91e31fa98f9fb98bf88767fc1b50d5ef4d08b653a7f4c6e7faf"
released = json.loads(snapshot.read_bytes())
schema = json.loads((ROOT / "contracts/menu/public-menu-v2.schema.json").read_bytes())
Draft202012Validator.check_schema(schema)
validator = Draft202012Validator(schema)
validator.validate(released)
stores = {store["store_id"]: store for store in released["stores"]}
assert set(stores) == {store["store_id"] for store in registry()}
assert {key for key, store in stores.items() if store["menu_type"] == "craft"} == {"BSVF"}
items = released["items"]
assert len({item["product_id"] for item in items}) == 84
assert [(sum(item["kind"] == k for item in items),
         sum(item["kind"] == k and item["reference_price"] is not None for item in items))
        for k in ("prepared", "bundle")] == [(63, 52), (21, 20)]
assert all(item["status"] == "menu_catalogue" and not item["price_by_store"] for item in items)

with tempfile.TemporaryDirectory() as folder:
    workbook = Path(folder) / "synthetic.xlsx"
    write_fixture(workbook)
    pages, _, _, _ = unpack_v9(workbook)
    pages["K_套餐组合"] = [
        {"id": f"K{n:06}", "fields": dict(fields, 套餐名称=f"合成套餐{n}", 采购价="PRIVATE")}
        for n, fields in enumerate(({"区域参考售价": "128.50", "核心参考售价": "99"},
                                   {"核心参考售价": "99"}, {}), 1)
    ]
    result = project_records(pages)
    validator.validate(result)
    assert len(result["stores"]) == 4
    assert "PRIVATE" not in json.dumps(result)
    prices = {item["product_id"]: item["reference_price"] for item in result["items"]}
    assert [prices[f"K{n:06}"]["amount"] for n in (1, 2)] == [128.5, 99]
    assert prices["K000003"] is None and prices["C000063"] is None
    assert cents_from_price(prices["C000001"]["amount"]) == 2835
    assert from_workbook(workbook)["stores"] == result["stores"]

if path := os.environ.get("BSV_MENU_REFERENCE_V9"):
    result = from_workbook(path)
    assert result["stores"] == released["stores"]
    assert {item["product_id"]: item for item in result["items"]} == {
        item["product_id"]: item for item in items
    }
    print("PASS: original V9, all 84 published items and 4 stores match the POS reader")
print("PASS: published identity, synthetic POS projection, C AJ and K regional/core/missing price")
