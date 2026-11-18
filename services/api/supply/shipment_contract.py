"""Translate explicit central shipment identifiers at the supply HTTP boundary."""
from fastapi import HTTPException


def _alias(record, canonical, legacy):
    if canonical in record and legacy in record and record[canonical] != record[legacy]:
        raise HTTPException(502, f"Conflicting shipment fields: {canonical}, {legacy}")
    value = record.get(canonical, record.get(legacy))
    if not isinstance(value, str) or not value:
        raise HTTPException(502, f"Missing shipment identifier: {canonical}")
    return value


def shipment_for_console(record, *, detail=False):
    """Preserve canonical fields while providing the original UI aliases."""
    if not isinstance(record, dict):
        raise HTTPException(502, "Invalid shipment projection")
    result = dict(record, id=_alias(record, "shipment_id", "id"))
    if detail or any(key in record for key in ("src", "source_store_id", "dest", "dest_store_id")):
        result.update(src=_alias(record, "source_store_id", "src"),
                      dest=_alias(record, "dest_store_id", "dest"))
    if "packages" in record:
        if not isinstance(record["packages"], list) or any(not isinstance(p,dict) for p in record["packages"]):
            raise HTTPException(502, "Invalid package projection")
        result["packages"] = [
            dict(p, code=_alias(p, "package_id", "code")) for p in record["packages"]
        ]
    return result
