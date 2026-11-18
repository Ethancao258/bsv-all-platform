"""Build a candidate DB-A public projection from the same V9 reader as POS."""
from pathlib import Path
import sys

from bsv_layouts import registry
from bsv_v9_import import SHEETS, unpack_v9

MAINTENANCE = Path(__file__).resolve().parents[3] / "apps/guest-web/bsv1/maintenance"


def project_records(pages):
    """Read-only transformation. Never publish, write a database, or authorize a sale."""
    sys.path.insert(0, str(MAINTENANCE))
    try:
        from build_public_v9 import build
    finally:
        sys.path.pop(0)

    records = [
        dict(id=row["id"], domain=page[0], sku=row["fields"].get("SKU"), fields=row["fields"])
        for page in SHEETS if page[0] in "CKT"
        for row in pages[page]
    ]
    expected_stores = {store["store_id"] for store in registry()}
    source_stores = [row["fields"].get("门店ID") for row in records if row["domain"] == "T"]
    if len(source_stores) != len(expected_stores) or set(source_stores) != expected_stores:
        raise ValueError("V9 store IDs differ from the BSV1 store registry")
    return build(records, source_title="BSV_ALL_V9")


def from_workbook(path):
    pages, _, _, _ = unpack_v9(Path(path))
    return project_records(pages)
