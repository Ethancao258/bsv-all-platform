"""Read-only source-owner adapters. Use existing catalog/organization, no new master.

The pinned file is a private, approved projection published by the existing
owner, not a second editable catalog/organization database. Never infer approval
from imported raw shelf-life text or demonstration IDs.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import re

from fastapi import APIRouter, HTTPException, Request
from .central_production_rules import ApprovedRule, aware, ident, quantity


def pinned(path, expected):
    if not path or not isinstance(expected,str) or not re.fullmatch(r"[0-9a-fA-F]{64}",expected):
        raise ValueError("owner-pinned projection is required")
    raw=Path(path).read_bytes()
    if sha256(raw).hexdigest()!=expected.lower():
        raise ValueError("owner projection digest mismatch")
    value=json.loads(raw)
    if not isinstance(value,dict) or value.get("schema_version")!=1:
        raise ValueError("unknown projection format")
    ident(value.get("approval_reference"))
    return value


def organization_from_env(*,now=None):
    value=pinned(os.getenv("BSV_SUP59_ORG_PROJECTION_FILE",""),os.getenv("BSV_SUP59_ORG_PROJECTION_SHA256",""))
    now=aware(now or datetime.now(timezone.utc))
    start=aware(datetime.fromisoformat(value["as_of"]))
    end=aware(datetime.fromisoformat(value["valid_until"]))
    if not start<=now<end or end-start>timedelta(hours=72):
        raise ValueError("organization projection is stale or invalid")
    legal=ident(value.get("legal_entity_id"))
    if legal.upper().startswith(("DEMO","SYNTH","TEST")):
        raise ValueError("fixture legal entity rejected")
    stores=value.get("stores")
    if not isinstance(stores,list) or not stores:
        raise ValueError("no approved stores")
    result=[]; seen=set()
    for row in stores:
        store=ident(row["store_id"]); name=ident(row["name_zh"])
        if (store in seen or store.upper().startswith(("DEMO","SYNTH","TEST"))
            or row.get("kind") not in {"warehouse","store","partner"} or row.get("approved") is not True):
            raise ValueError("unapproved or duplicate store")
        if row.get("legal_entity_id")!=legal:
            raise ValueError("cross-entity store projection")
        seen.add(store)
        result.append(dict(store_id=store,name_zh=name,kind=row["kind"],legal_entity_id=legal,approved=True))
    departments=value.get("department_by_tr")
    if not isinstance(departments,dict) or any(
       not re.fullmatch(r"TR[A-Z][0-9]{4}",tr) or not isinstance(dept,str) or not dept.strip()
       or dept.upper().startswith(("DEMO","SYNTH","TEST")) for tr,dept in departments.items()):
        raise ValueError("invalid organization department projection")
    return dict(legal_entity_id=legal,stores=result,department_by_tr=departments)


class CatalogPolicyAdapter:
    def __init__(self,repository,manifest_path,manifest_sha):
        self.repository=repository;self.path=manifest_path;self.digest=manifest_sha

    def manifest(self):
        value=pinned(self.path,self.digest)
        revision=ident(value.get("catalog_source_sha256"))
        if not re.fullmatch(r"[0-9a-f]{64}",revision):
            raise ValueError("catalog revision SHA required")
        policies=value.get("policies")
        if not isinstance(policies,list) or len(policies)>10000:
            raise ValueError("invalid approved policy list")
        items={}
        for row in policies:
            item=ident(row["item_id"])
            if item in items or not re.fullmatch(r"P[0-9]{6}",item):
                raise ValueError("duplicate or invalid semifinished ID")
            items[item]=row
        return revision,items

    def record(self,item,revision):
        record=self.repository.get_product(item)
        if not record or record.get("product_id")!=item:
            raise ValueError("catalog stable item missing")
        actual=record.get("source_sha256") or (record.get("source") or {}).get("sha256")
        if actual!=revision:
            raise ValueError("approved policy is stale for current catalog")
        return record

    def validate(self,row,revision):
        item=row["item_id"]
        if row.get("duration_basis")!="PRODUCED_AT" or row.get("approved") is not True:
            raise ValueError("unapproved expiry rule")
        ident(row.get("approval_reference"))
        record=self.record(item,revision)
        status=(record.get("source_fields") or {}).get("审核状态") or (record.get("source_fields") or {}).get("内容审核状态")
        if record.get("production_standard_approved") is not True and status not in {"已批准","已核准","审核通过"}:
            raise ValueError("source production standard not approved")
        rule=ApprovedRule(row.get("rule_version"),True,row.get("elapsed_seconds"),row.get("opened_seconds"))
        unit=row.get("unit")
        yield_amount=quantity(row.get("yield_amount"),unit)
        standard=quantity(row.get("standard_amount"),unit)
        inputs=row.get("recipe_inputs")
        if not isinstance(inputs,list) or not 1<=len(inputs)<=100:
            raise ValueError("structured recipe inputs required")
        material_ids=set(); normalized=[]
        for ingredient in inputs:
            material=ident(ingredient["material_id"])
            if not re.fullmatch(r"M[0-9]{6}",material) or material in material_ids:
                raise ValueError("invalid or duplicate raw material stable ID")
            self.record(material,revision)
            material_ids.add(material)
            normalized.append(dict(material_id=material,unit=ingredient["unit"],amount=str(quantity(ingredient["amount"],ingredient["unit"]))))
        return dict(item_id=item,name=ident(record.get("name")),approved=True,duration_basis="PRODUCED_AT",
                    rule_version=rule.version,elapsed_seconds=rule.elapsed_seconds,opened_seconds=rule.opened_seconds,
                    unit=unit,yield_amount=str(yield_amount),standard_amount=str(standard),recipe_inputs=normalized,
                    **{key:ident(row.get(key)) for key in ("recipe_version","sop_version","storage","usage")})

    def production_policy(self,item_id,recipe_version=None):
        revision,items=self.manifest()
        if item_id not in items:
            raise ValueError("no approved production policy")
        result=self.validate(items[item_id],revision)
        if recipe_version and result["recipe_version"]!=recipe_version:
            raise ValueError("requested recipe version not approved")
        return result

    def items(self):
        revision,items=self.manifest()
        result=[]
        for row in items.values():
            try:
                p=self.validate(row,revision)
            except (ValueError,TypeError,KeyError):
                continue
            result.append(dict(item_id=p["item_id"],name_zh=p["name"],unit=p["unit"],package_size=p["standard_amount"],
                               approved=True,track_package=True,stockable=True))
        return result


def catalog_router(adapter,authorize):
    """Mount within existing A owner; authorize(request) checks service and current actor."""
    router=APIRouter()
    @router.get("/items")
    def items(request:Request,stockable:bool=True):
        authorize(request)
        try:return adapter.items()
        except (OSError,ValueError,KeyError,TypeError):raise HTTPException(503,"批准商品目录不可用")
    @router.get("/production-policy")
    def policy(item_id:str,request:Request,recipe_version:str|None=None):
        authorize(request)
        try:return adapter.production_policy(item_id,recipe_version)
        except (ValueError,KeyError,TypeError):raise HTTPException(409,"物料生产规则尚未批准或版本不一致")
        except OSError:raise HTTPException(503,"批准商品目录不可用")
    return router


def organization_router(authorize):
    """Mount within C owner. authorize(request) returns current B actor."""
    router=APIRouter()
    @router.get("/stores")
    def stores(request:Request):
        actor=authorize(request)
        try:value=organization_from_env()
        except (OSError,ValueError,KeyError,TypeError):raise HTTPException(503,"公司组织目录未批准或已过期")
        if not isinstance(actor,dict) or actor.get("legal_entity_id")!=value["legal_entity_id"]:
            raise HTTPException(403,"无本公司门店权限")
        allowed=actor.get("stores",[])
        return [row for row in value["stores"] if row["store_id"] in allowed]
    return router
