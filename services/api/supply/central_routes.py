"""SUP-59 transport for the existing supply app and its sole D authority."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from .central_production_rules import PackageFact
from .gateway import Unreachable

Reference = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,100}$")]
Version = Annotated[int, Field(strict=True, ge=1)]
Amount = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,14}(\.[0-9]{1,4})?$")]
PackageIds = Annotated[list[Reference], Field(min_length=1, max_length=100)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Command(Input):
    request_id: UUID


class PlanPreview(Input):
    source_store_id: Reference
    dest_store_id: Reference
    item_id: Reference
    next_delivery_at: AwareDatetime
    usage_before_next: Amount
    reserved: Amount
    demand_next_cycle: Amount
    safety_stock: Amount


class Plan(PlanPreview, Command):
    pass


class Batch(Command):
    plan_id: Reference
    produced_at: AwareDatetime
    recipe_version: Reason
    ingredient_lot_ids: PackageIds
    total: Amount
    package_amounts: Annotated[list[Amount], Field(min_length=1, max_length=100)]
    remainder: Amount
    loss: Amount


class ShipmentCreate(Command):
    source_store_id: Reference
    dest_store_id: Reference
    package_ids: PackageIds
    eta: AwareDatetime


class Transition(Command):
    shipment_id: Reference | None = None
    expected_version: Version


class Dispatch(Transition):
    scanned_codes: PackageIds


class Receipt(Transition):
    accepted_ids: Annotated[list[Reference], Field(max_length=100)]
    hold_ids: Annotated[list[Reference], Field(max_length=100)]
    exception_reasons: Annotated[dict[Reference, Reason], Field(max_length=100)]


class Open(Command):
    package_id: Reference
    expected_version: Version
    store_id: Reference


class Recall(Open):
    reason: Reason


class Dispose(Recall):
    amount: Amount


class Consume(Open):
    amount: Amount


class RawReceive(Command):
    store_id: Reference
    recipe_item_id: Reference
    recipe_version: Reason
    item_id: Reference
    unit: Reason
    amount: Amount
    receipt_ref: Reason
    supplier_lot_ref: Reason
    expiry_evidence_ref: Reason
    received_at: AwareDatetime
    expires_at: AwareDatetime
    unopened: Literal[True]
    quality_accepted: Literal[True]


class RawDispose(Command):
    store_id: Reference
    stock_lot_id: Reference
    expected_version: Version
    reason: Reason


class OpeningImport(Command):
    store_id: Reference
    evidence_ids: PackageIds


class Label(Command):
    package_ids: PackageIds
    store_id: Reference
    operation: Literal["PRINT", "REPRINT", "CONFIRM"]
    print_request_id: UUID | None = None


COMMANDS = {
    "plan-preview": PlanPreview, "plan": Plan, "batch": Batch, "create": ShipmentCreate,
    "prepare": Transition, "dispatch": Dispatch, "receive": Receipt, "open": Open,
    "consume": Consume, "dispose": Dispose, "recall": Recall, "label": Label, "opening-import": OpeningImport, "raw-receive": RawReceive, "raw-dispose": RawDispose,
}
DISPATCH_COMMANDS = {"plan-preview", "plan", "batch", "create", "prepare", "dispatch", "recall", "label", "opening-import"}
SNAPSHOTS = {"inventory", "shipment", "shipments", "labels", "tasks", "exceptions", "plans", "opening-candidates"}
INSPECTION_ROLES = {"inspect_independent", "review_independent"}
OPERATION_ROLES = {"dispatch", "receive"}


def _authorized(me, roles, store_id=None):
    allowed = set(me["roles"]) & roles
    scoped = me.get("role_stores")
    if scoped is not None and (not isinstance(scoped, dict) or any(
        not isinstance(stores, list) or any(not isinstance(store, str) for store in stores)
        for stores in scoped.values()
    )):
        raise HTTPException(502, "身份服务返回无效的门店授权")
    if not allowed or (store_id and (
        store_id not in me["stores"] or (
            scoped is not None and not any(store_id in scoped.get(role, ()) for role in allowed)
        )
    )):
        raise HTTPException(403, "无此操作或门店权限")


def _datetime(value):
    return datetime.fromisoformat(value)


def _package(fact):
    fields = {name: fact[name] for name in PackageFact.__dataclass_fields__}
    for date_field in ("produced_at", "expires_at"):
        fields[date_field] = _datetime(fields[date_field])
    return PackageFact(**fields)


def central_router(*, mode, demo, enabled, gateway, actor, token_of):
    if mode == "demo":
        from .central_transactions import CentralDemo
        local = CentralDemo(demo)
    else:
        local = None
    router = APIRouter(prefix="/api/central", tags=["central supply"])

    def require_enabled():
        if not enabled:
            raise HTTPException(503, "中央供货事务服务尚未启用")

    def read(kind, request, current, store_id, shipment_id, package_ids, phase):
        require_enabled()
        if kind not in SNAPSHOTS:
            raise HTTPException(404, "未知供货视图")
        roles = {"dispatch"} if kind in {"plans", "labels", "opening-candidates"} else OPERATION_ROLES
        if kind == "exceptions":
            roles = roles | INSPECTION_ROLES
        _authorized(current, roles, store_id)
        if (kind == "shipment" and not shipment_id) or (kind != "shipment" and not store_id):
            raise HTTPException(422, "缺少配送单或门店编号")
        if local and kind=="opening-candidates":
            raise HTTPException(503,"历史期初库存仅可从真实D导入")
        if local:
            try:
                return local.snapshot(kind, current, store_id=store_id, shipment_id=shipment_id,
                                      package_ids=package_ids, phase=phase)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        params = [(k, v) for k, v in (("store_id", store_id), ("shipment_id", shipment_id),
                                      ("phase", phase)) if v is not None]
        params.extend(("package_ids", p) for p in package_ids or ())
        try:
            result = gateway.read("D", f"/supply/central/v1/{kind}", params=params,
                                  user_token=token_of(request), allow_cache=False, primary_only=True)
        except Unreachable as exc:
            raise HTTPException(503, "D 权威快照不可用") from exc
        if not isinstance(result["data"], dict):
            raise HTTPException(502, "D 返回无效的供货快照")
        return result["data"]

    @router.get("/{kind}")
    def snapshot(kind: str, request: Request, store_id: Reference | None = None,
                 shipment_id: Reference | None = None, phase: Literal["START", "END"] = "START",
                 package_ids: list[Reference] | None = Query(None, min_length=1, max_length=100), current=Depends(actor)):
        return {"data": read(kind, request, current, store_id, shipment_id, package_ids, phase)}

    @router.post("/{operation}")
    def command(operation: str, body: dict, request: Request, shipment_id: Reference | None = None,
                current=Depends(actor)):
        require_enabled()
        model = COMMANDS.get(operation)
        if model is None:
            raise HTTPException(404, "未知供货操作")
        try:
            payload = model.model_validate(body).model_dump(mode="json", exclude_none=True)
        except ValidationError as exc:
            raise HTTPException(422, "供货命令字段缺失或格式无效") from exc
        body_shipment = payload.pop("shipment_id", None)
        if body_shipment and shipment_id and body_shipment != shipment_id:
            raise HTTPException(422, "配送单编号不一致")
        shipment_id = body_shipment or shipment_id
        if issubclass(model, Transition) and not shipment_id:
            raise HTTPException(422, "缺少配送单编号")
        roles = {"dispatch"} if operation in DISPATCH_COMMANDS else {"receive"}
        _authorized(current, roles, payload.get("source_store_id") or payload.get("store_id"))
        if local and operation in {"opening-import","raw-receive","raw-dispose"}:
            raise HTTPException(503,"原料台账操作仅可在真实D执行")
        if local:
            try:
                if operation == "plan-preview":
                    return {"data": local.plan_preview(payload, current)}
                data = local.mutate(operation, payload, current, shipment_id=shipment_id)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            return {"data": data, "state": "DEMO_COMMITTED"}
        if shipment_id:
            payload["shipment_id"] = shipment_id
        try:
            outcome = gateway.write("D", f"/supply/central/v1/{operation}", payload,
                                    user_token=token_of(request),
                                    expected_state="PREVIEW" if operation == "plan-preview" else "COMMITTED")
        except (Unreachable, ValueError) as exc:
            raise HTTPException(503, "D 未确认结果，请保留原请求编号") from exc
        if (not isinstance(outcome.get("data"), dict)
                or (operation != "plan-preview" and outcome.get("request_id") != payload["request_id"])):
            raise HTTPException(502, "D 回执无法对应当前请求")
        return outcome

    @router.get("/print/{document}", response_class=HTMLResponse)
    def print_document(document: Literal["arrival", "expiry", "labels"], request: Request,
                       store_id: Reference | None = None, shipment_id: Reference | None = None,
                       package_ids: list[Reference] | None = Query(None, min_length=1, max_length=100), current=Depends(actor)):
        from .central_print import render_arrival, render_expiry, render_labels
        now = datetime.now(timezone.utc)
        if document == "labels" and not package_ids:
            raise HTTPException(422, "请选择至少一件包装")
        kind = {"arrival": "shipment", "expiry": "inventory", "labels": "labels"}[document]
        facts = read(kind, request, current, store_id, shipment_id, package_ids, "START")
        try:
            if document == "arrival":
                if not facts.get("sent_at"):
                    raise ValueError("shipment not dispatched")
                receipts = [{**row, "package": _package(row["package"]),
                             "received_at": _datetime(row["received_at"]),
                             "sent_at": _datetime(row["sent_at"])} for row in facts["receipts"]]
                html = render_arrival(
                    [_package(row) for row in facts["planned"]], receipts,
                    store_id=facts["dest"], reference=facts["id"], as_of=now,
                    revision=facts["version"], demo=bool(local),
                    dispatch={
                        "source_store_id": facts["src"], "sender_id": facts.get("sender_id"),
                        **{key: _datetime(facts[field]) for key, field in (
                            ("sent_at", "sent_at"), ("eta_at", "eta"), ("arrived_at", "arrived_at")
                        ) if facts.get(field)},
                    },
                )
            else:
                packages = [_package(row) for row in facts["packages"]]
                if document == "labels":
                    if {row.package_id for row in packages} != set(package_ids or ()):
                        raise ValueError("ineligible label selection")
                    html = render_labels(packages, as_of=now, demo=bool(local))
                else:
                    html = render_expiry(packages, store_id=store_id, as_of=now,
                                         revision=facts["revision"], demo=bool(local))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(409, "清单或标签快照不完整，无法打印") from exc
        except ImportError as exc:
            raise HTTPException(503, "标签二维码组件不可用") from exc
        return HTMLResponse(html, headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'",
        })

    return router
