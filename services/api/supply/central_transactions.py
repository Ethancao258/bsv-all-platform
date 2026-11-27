"""Transactional SUP-59 reference on the existing, local-only DemoCentral ledger.

The production implementation belongs to the designated D authority. These tables
extend the sandbox only; they are neither a production migration nor a fallback.
"""
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from uuid import UUID, uuid4

from .central_production_rules import (
    ApprovedRule, PackageFact, available, aware, expiry, ident, quantity,
    receipt_intent, shift_due, validate_split,
)
from .demo import DEMO_STORES, fail
from .domain import calc_reorder, unique_codes

DEMO_POLICY = {
    "DEMO-P001": {
        "item_id": "DEMO-P001", "name": "演示预调酒", "unit": "mL",
        "recipe_version": "DEMO-RECIPE-1", "sop_version": "DEMO-SOP-1",
        "standard_amount": "450", "storage": "演示储存规则",
        "usage": "演示用法，禁止作为经营依据",
        "rule": ApprovedRule("DEMO-EXPIRY-1", True, 172800, 3600),
        "ingredient_lot_ids": frozenset({"DEMO-LOT-1", "DEMO-LOT-2"}),
    }
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_central_plans (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, destination TEXT NOT NULL,
    item_id TEXT NOT NULL, facts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demo_central_batches (
    id TEXT PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE REFERENCES demo_central_plans(id),
    facts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demo_central_stock (
    package_id TEXT PRIMARY KEY REFERENCES packages(code),
    batch_id TEXT NOT NULL REFERENCES demo_central_batches(id),
    store_id TEXT NOT NULL, state TEXT NOT NULL, version INTEGER NOT NULL,
    remaining TEXT NOT NULL, expires_at TEXT NOT NULL, opened_at TEXT,
    original TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS demo_central_stock_store ON demo_central_stock(store_id);
CREATE TABLE IF NOT EXISTS demo_central_receipts (
    shipment_id TEXT NOT NULL REFERENCES demo_central_shipments(id),
    package_id TEXT NOT NULL REFERENCES demo_central_stock(package_id),
    facts TEXT NOT NULL, PRIMARY KEY(shipment_id, package_id)
);
CREATE TABLE IF NOT EXISTS demo_central_movements (
    id TEXT PRIMARY KEY, request_id TEXT NOT NULL, package_id TEXT NOT NULL
        REFERENCES demo_central_stock(package_id),
    from_state TEXT, to_state TEXT NOT NULL, quantity TEXT NOT NULL, unit TEXT NOT NULL,
    actor_id TEXT NOT NULL, occurred_at TEXT NOT NULL, reason TEXT
);
CREATE TABLE IF NOT EXISTS demo_central_recalls (
    package_id TEXT PRIMARY KEY REFERENCES demo_central_stock(package_id),
    reason TEXT NOT NULL, actor_id TEXT NOT NULL, occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demo_central_prints (
    request_id TEXT NOT NULL, package_id TEXT NOT NULL REFERENCES demo_central_stock(package_id),
    operation TEXT NOT NULL, original_request_id TEXT, actor_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL, PRIMARY KEY(request_id, package_id)
);
"""


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("需要带时区的实际时间")
    return aware(datetime.fromisoformat(value))


def key(prefix):
    return f"DEMO-{prefix}-{uuid4().hex}"


def serialize(package):
    result = asdict(package)
    for column in ("amount", "remaining"):
        result[column] = str(result[column])
    for column in ("produced_at", "expires_at"):
        result[column] = result[column].isoformat()
    return result


def deserialize(data):
    return PackageFact(**{
        **data,
        "produced_at": timestamp(data["produced_at"]),
        "expires_at": timestamp(data["expires_at"]),
    })


class CentralDemo:
    def __init__(self, ledger, *, clock=lambda: datetime.now(timezone.utc)):
        self.ledger = ledger
        self.clock = clock
        self.stores = frozenset(store["store_id"] for store in DEMO_STORES)
        with ledger.lock, closing(ledger._conn()) as conn:
            conn.executescript(SCHEMA)

    def _permit(self, actor, role, store):
        if store not in self.stores:
            fail(422, "未知演示网点")
        self.ledger.authorize(actor, role, store)
        scoped = actor.get("role_stores")
        if scoped is not None and store not in scoped.get(role, ()):
            fail(403, "目标网点未授权该操作")

    @staticmethod
    def _has_role(actor, role, store):
        scoped = actor.get("role_stores")
        return (role in actor["roles"] and store in actor["stores"]
                and (scoped is None or store in scoped.get(role, ())))

    def _can_read(self, actor, store):
        if not any(self._has_role(actor, role, store) for role in (
            "dispatch", "receive", "inspect", "inspect_independent", "review_independent",
        )):
            fail(403, "缺少供货读取权限")

    def _fact(self, row):
        original = json.loads(row["original"])
        fact = deserialize({
            **original, "remaining": row["remaining"], "state": row["state"],
            "store_id": row["store_id"], "expires_at": row["expires_at"],
        })
        return fact

    def _stock(self, conn, package_id):
        row = conn.execute(
            "SELECT * FROM demo_central_stock WHERE package_id=?", (package_id,)
        ).fetchone()
        if row is None:
            fail(404, "未知生产包装")
        return row

    def _shipment(self, conn, shipment_id):
        row = conn.execute(
            """SELECT s.*, c.eta, c.sent_at, c.sender_id, c.arrived_at, c.dispatched
               FROM shipments s JOIN demo_central_shipments c USING (id) WHERE s.id=?""",
            (shipment_id,),
        ).fetchone()
        if row is None:
            fail(404, "未知生产配送单")
        return row

    @staticmethod
    def _selection(values):
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError("包装列表须为数组且最多100项")
        return unique_codes([ident(value) for value in values])

    @staticmethod
    def _version(row, payload):
        expected = payload.get("expected_version")
        if type(expected) is not int or expected != row["version"]:
            fail(409, f"版本冲突；当前版本 {row['version']}")

    @staticmethod
    def _ship_payload(row, packages):
        return {
            "id": row["id"], "source_store_id": row["src"], "dest_store_id": row["dest"],
            "state": row["state"], "version": row["version"], "packages": packages,
        }

    def _movement(self, conn, ctx, p, state, amount, *, reason=None, created=False):
        conn.execute(
            "INSERT INTO demo_central_movements VALUES (?,?,?,?,?,?,?,?,?,?)",
            (key("MOV"), ctx["rid"], p.package_id, None if created else p.state, state, str(amount), p.unit,
             ctx["actor"], ctx["now"].isoformat(), reason),
        )

    def _plan(self, conn, payload, actor, now):
        source = payload["source_store_id"]
        dest = payload["dest_store_id"]
        self._permit(actor, "dispatch", source)
        if source != "DEMO-WH" or dest not in self.stores or source == dest:
            fail(422, "生产来源必须为中央仓，且目的店须有效")
        self._permit(actor, "dispatch", dest)
        policy = DEMO_POLICY.get(payload["item_id"])
        if policy is None:
            fail(422, "缺少已批准的演示规则")
        eta = timestamp(payload["next_delivery_at"])
        if eta <= now:
            fail(422, "下次到货时间必须晚于当前时间")
        unit = policy["unit"]
        rows = conn.execute(
            """SELECT p.* FROM demo_central_stock p
               JOIN packages g ON p.package_id=g.code WHERE p.store_id=? AND g.item_id=?""",
            (dest, policy["item_id"]),
        )
        confirmed = expiring = Decimal(0)
        for row in rows:
            p = self._fact(row)
            if available(p, now):
                confirmed += p.remaining
                if p.expires_at <= eta:
                    expiring += p.remaining
        incoming = Decimal(0)
        rows = conn.execute(
            """SELECT p.*, s.eta AS delivery_eta, r.package_id IS NOT NULL AS recalled
               FROM demo_central_stock p JOIN packages g ON p.package_id=g.code
               JOIN demo_central_shipments s ON s.id=g.shipment_id
               LEFT JOIN demo_central_recalls r ON r.package_id=p.package_id
               WHERE p.store_id=? AND g.item_id=? AND p.state='IN_TRANSIT'""",
            (dest, policy["item_id"]),
        )
        for row in rows:
            p = self._fact(row)
            if not row["recalled"] and now <= timestamp(row["delivery_eta"]) <= eta < p.expires_at:
                incoming += p.remaining
        forecast = {
            name: quantity(payload[name], unit, zero=True)
            for name in ("usage_before_next", "reserved", "demand_next_cycle", "safety_stock")
        }
        result = calc_reorder(
            confirmed_available=confirmed, arrivals_before_next=incoming, expiry_before_next=expiring,
            arrivals_next_cycle=0, pack_size=policy["standard_amount"], max_packs=100, **forecast,
        )
        return {
            **result, "unit": unit, "source_store_id": source, "dest_store_id": dest,
            "item_id": policy["item_id"], "next_delivery_at": eta.isoformat(),
            "confirmed_available": str(confirmed), "eligible_in_transit": str(incoming),
            "expires_before_arrival": str(expiring),
            "recipe_version": policy["recipe_version"], "sop_version": policy["sop_version"],
            "expiry_rule_version": policy["rule"].version,
            "standard_amount": policy["standard_amount"], "storage": policy["storage"],
            **{name: str(value) for name, value in forecast.items()},
        }

    def plan_preview(self, payload, actor):
        with self.ledger.lock, closing(self.ledger._conn()) as conn:
            conn.execute("BEGIN")
            return self._plan(conn, payload, actor, aware(self.clock()))

    def _confirm_plan(self, conn, payload, actor, ctx):
        result = self._plan(conn, payload, actor, ctx["now"])
        if result["status"] != "SUGGESTED" or result["packages"] <= 0:
            fail(409, "当前补货建议不能生成任务")
        plan_id = key("PLAN")
        result.update(plan_id=plan_id, state="CONFIRMED", version=1)
        conn.execute(
            "INSERT INTO demo_central_plans VALUES (?,?,?,?,?)",
            (plan_id, result["source_store_id"], result["dest_store_id"], result["item_id"], dump(result)),
        )
        return result

    def _release_batch(self, conn, payload, plan, ctx):
        rule_snapshot = json.loads(plan["facts"])
        policy = DEMO_POLICY.get(plan["item_id"])
        if not policy or (
            policy["recipe_version"], policy["rule"].version, policy["sop_version"]
        ) != (
            payload["recipe_version"], rule_snapshot["expiry_rule_version"], rule_snapshot["sop_version"]
        ):
            fail(409, "计划引用的配方、SOP或效期规则已变更")
        if conn.execute("SELECT 1 FROM demo_central_batches WHERE plan_id=?", (plan["id"],)).fetchone():
            fail(409, "计划已登记生产批次")
        raw_lots = self._selection(payload["ingredient_lot_ids"])
        if not set(raw_lots) <= policy["ingredient_lot_ids"]:
            fail(422, "原料批次不在演示已批准批次中")
        produced_at = timestamp(payload["produced_at"])
        expires_at = expiry(policy["rule"], produced_at)
        if not produced_at <= ctx["now"] < expires_at:
            fail(409, "制作时间在未来或批次已过期")
        amounts = payload["package_amounts"]
        if not isinstance(amounts, list) or not 1 <= len(amounts) <= 100:
            fail(422, "分装必须有 1 至 100 件")
        parts = [(key("PKG"), amount) for amount in amounts]
        unit = policy["unit"]
        packed = validate_split(payload["total"], unit, parts, payload["remainder"], payload["loss"])
        batch_id = key("BATCH")
        facts = {
            "batch_id": batch_id, "plan_id": plan["id"], "item_id": plan["item_id"],
            "producer_id": ctx["actor"], "produced_at": produced_at.isoformat(),
            "expires_at": expires_at.isoformat(), "recipe_version": policy["recipe_version"],
            "sop_version": policy["sop_version"], "ingredient_lot_ids": raw_lots,
            "total": str(quantity(payload["total"], unit)), "packed": str(packed), "unit": unit,
            "remainder": str(quantity(payload["remainder"], unit, zero=True)),
            "loss": str(quantity(payload["loss"], unit, zero=True)), "state": "RELEASED",
            "expiry_rule_version": policy["rule"].version,
            "approved_rule": asdict(policy["rule"]),
        }
        conn.execute("INSERT INTO demo_central_batches VALUES (?,?,?)", (batch_id, plan["id"], dump(facts)))
        packages = []
        for package_id, amount in parts:
            p = PackageFact(
                package_id, batch_id, plan["item_id"], policy["name"], plan["source"],
                amount, amount, unit, produced_at, expires_at, policy["rule"].version,
                ctx["actor"], policy["storage"], policy["usage"], "READY",
            )
            data = serialize(p)
            conn.execute(
                """INSERT INTO packages(code,shipment_id,item_id,state,batch_id)
                   VALUES (?,NULL,?,'READY',?)""", (p.package_id, p.item_id, batch_id),
            )
            conn.execute(
                "INSERT INTO demo_central_stock VALUES (?,?,?,?,1,?,?,NULL,?)",
                (package_id, batch_id, p.store_id, p.state, str(p.remaining), expires_at.isoformat(), dump(data)),
            )
            self._movement(conn, ctx, p, "READY", p.amount, reason="PRODUCTION", created=True)
            packages.append({**data, "version": 1})
        return {**facts, "packages": packages}

    def _create_shipment(self, conn, payload, ctx):
        src, dest = payload["source_store_id"], payload["dest_store_id"]
        if dest not in self.stores or dest == src or dest == "DEMO-WH":
            fail(422, "配送目的地无效")
        eta = timestamp(payload["eta"])
        if eta <= ctx["now"]:
            fail(422, "预计到货时间必须晚于当前时间")
        ids = self._selection(payload["package_ids"])
        packs = []
        for pid in ids:
            row = self._stock(conn, pid)
            p = self._fact(row)
            assignment = conn.execute("SELECT shipment_id FROM packages WHERE code=?", (pid,)).fetchone()
            if p.store_id != src or p.state != "READY" or assignment[0] is not None:
                fail(409, "包装未放行、已分配或不在来源库")
            if not p.produced_at <= ctx["now"] < eta < p.expires_at:
                fail(409, "预计到达时包装将不可用")
            packs.append(serialize(p))
        sid = key("SHP")
        conn.execute(
            "INSERT INTO shipments VALUES (?,?,?,?,?,?,?)",
            (sid, src, dest, "DRAFT", 1, ctx["actor"], ctx["now"].isoformat()),
        )
        conn.execute("INSERT INTO demo_central_shipments(id,eta) VALUES (?,?)", (sid, eta.isoformat()))
        conn.executemany(
            "UPDATE packages SET shipment_id=?,state='DRAFT' WHERE code=?",
            [(sid, pid) for pid in ids],
        )
        return self._ship_payload(self._shipment(conn, sid), packs)

    def _change_stock(self, conn, p, state, store, *, remaining=None, expires_at=None, opened_at=None):
        conn.execute(
            """UPDATE demo_central_stock
               SET state=?,store_id=?,version=version+1,remaining=?,expires_at=?,
                   opened_at=COALESCE(?,opened_at) WHERE package_id=?""",
            (state, store, str(p.remaining if remaining is None else remaining),
             (expires_at or p.expires_at).isoformat(),
             opened_at.isoformat() if opened_at else None, p.package_id),
        )
        conn.execute("UPDATE packages SET state=? WHERE code=?", (state, p.package_id))

    def _shipment_rows(self, conn, shipment_id):
        return conn.execute(
            """SELECT c.*, r.reason AS recall_reason FROM demo_central_stock c
               JOIN packages p ON c.package_id=p.code
               LEFT JOIN demo_central_recalls r ON r.package_id=c.package_id
               WHERE p.shipment_id=? ORDER BY c.package_id""", (shipment_id,),
        ).fetchall()

    def _shipment_step(self, conn, op, payload, shipment, ctx):
        self._version(shipment, payload)
        sid = shipment["id"]
        rows = self._shipment_rows(conn, sid)
        facts = [self._fact(row) for row in rows]
        allowed = {
            "prepare": {"DRAFT"}, "dispatch": {"READY"},
            "receive": {"DISPATCHED", "PARTIAL_RECEIVED"},
        }
        if shipment["state"] not in allowed[op]:
            fail(409, "配送单当前状态不允许此操作")
        if op in {"prepare", "dispatch"}:
            eta = timestamp(shipment["eta"])
            if not facts or any(p.state != "READY" or p.store_id != shipment["src"] or
                                not p.produced_at <= ctx["now"] < eta < p.expires_at for p in facts):
                fail(409, "包装或预计到达时间需要复核")
        if op == "prepare":
            conn.execute("UPDATE packages SET state='READY' WHERE shipment_id=?", (sid,))
            state = "READY"
        elif op == "dispatch":
            if set(self._selection(payload["scanned_codes"])) != {p.package_id for p in facts}:
                fail(409, "发货扫码不等于计划包装集合")
            for p in facts:
                self._movement(conn, ctx, p, "IN_TRANSIT", p.remaining)
                self._change_stock(conn, p, "IN_TRANSIT", shipment["dest"])
            dispatched = [serialize(self._fact(row)) for row in self._shipment_rows(conn, sid)]
            conn.execute(
                "UPDATE demo_central_shipments SET dispatched=?,sender_id=?,sent_at=? WHERE id=?",
                (dump(dispatched), ctx["actor"], ctx["now"].isoformat(), sid),
            )
            state = "DISPATCHED"
        else:
            state = self._receive(conn, payload, shipment, facts, ctx)
        conn.execute(
            "UPDATE shipments SET state=?,version=version+1 WHERE id=?", (state, sid),
        )
        packs = [
            {**serialize(self._fact(row)), "version": row["version"], "recall_reason": row["recall_reason"]}
            for row in self._shipment_rows(conn, sid)
        ]
        return self._ship_payload(self._shipment(conn, sid), packs)

    def _receive(self, conn, payload, shipment, facts, ctx):
        accepted = self._selection(payload["accepted_ids"]) if payload["accepted_ids"] else []
        held = self._selection(payload["hold_ids"]) if payload["hold_ids"] else []
        reasons = payload.get("exception_reasons", {})
        if any(conn.execute(
            "SELECT 1 FROM demo_central_recalls WHERE package_id=?", (pid,),
        ).fetchone() for pid in accepted):
            fail(409, "召回包装须隔离签收")
        if not isinstance(reasons, dict) or set(reasons) != set(held):
            fail(422, "隔离包装须逐件记录异常原因")
        for reason in reasons.values():
            ident(reason)
        if not timestamp(shipment["sent_at"]) <= ctx["now"]:
            fail(409, "签收时刻早于发货")
        try:
            intent = receipt_intent(facts, accepted, held, store_id=shipment["dest"], now=ctx["now"])
        except ValueError as exc:
            fail(409, str(exc))
        by_id = {p.package_id: p for p in facts}
        sid = shipment["id"]
        for pid, state, amount, _ in intent:
            p = by_id[pid]
            reason = reasons.get(pid)
            self._movement(conn, ctx, p, state, amount, reason=reason)
            self._change_stock(conn, p, state, shipment["dest"])
            receipt = {
                "package": {**serialize(p), "state": state},
                "accepted": str(amount if state == "ACCEPTED" else 0),
                "held": str(amount if state == "HOLD" else 0),
                "committed": True, "source_store_id": shipment["src"],
                "sender_id": shipment["sender_id"], "receiver_id": ctx["actor"],
                "sent_at": shipment["sent_at"], "received_at": ctx["now"].isoformat(),
                "exception_reason": reason or "",
            }
            conn.execute("INSERT INTO demo_central_receipts VALUES (?,?,?)", (sid, pid, dump(receipt)))
        conn.execute(
            "UPDATE demo_central_shipments SET arrived_at=COALESCE(arrived_at,?) WHERE id=?",
            (ctx["now"].isoformat(), sid),
        )
        remaining = conn.execute(
            "SELECT 1 FROM packages WHERE shipment_id=? AND state='IN_TRANSIT'", (sid,),
        ).fetchone()
        return "PARTIAL_RECEIVED" if remaining else "RECEIVED"

    def _inventory_step(self, conn, op, payload, row, ctx):
        self._version(row, payload)
        p = self._fact(row)
        if p.store_id != payload["store_id"]:
            fail(403, "目标包装不在授权门店")
        if op == "open":
            if not available(p, ctx["now"]) or row["opened_at"] is not None:
                fail(409, "只有可使用且未开封的包装可登记开封")
            batch = conn.execute(
                "SELECT facts FROM demo_central_batches WHERE id=?", (p.batch_id,),
            ).fetchone()
            stored_rule = json.loads(batch["facts"])["approved_rule"]
            rule = ApprovedRule(**stored_rule)
            end = expiry(rule, p.produced_at, opened_at=ctx["now"], restriction_at=p.expires_at)
            self._change_stock(conn, p, p.state, p.store_id, expires_at=end, opened_at=ctx["now"])
            self._movement(conn, ctx, p, p.state, p.remaining, reason="OPENED")
        elif op == "recall":
            reason = ident(payload["reason"])
            if p.state not in {"READY", "IN_TRANSIT", "ACCEPTED", "HOLD"} or not p.remaining:
                fail(409, "当前包装状态不可召回")
            if conn.execute("SELECT 1 FROM demo_central_recalls WHERE package_id=?", (p.package_id,)).fetchone():
                fail(409, "包装已召回")
            state = "IN_TRANSIT" if p.state == "IN_TRANSIT" else "HOLD"
            conn.execute(
                "INSERT INTO demo_central_recalls VALUES (?,?,?,?)",
                (p.package_id, reason, ctx["actor"], ctx["now"].isoformat()),
            )
            self._change_stock(conn, p, state, p.store_id)
            self._movement(conn, ctx, p, state, p.remaining, reason=reason)
        else:
            if p.state not in {"ACCEPTED", "HOLD"} or (
                p.state == "ACCEPTED" and ctx["now"] < p.expires_at
            ):
                fail(409, "只允许处置隔离或已过期库存")
            reason = ident(payload["reason"])
            amount = quantity(payload["amount"], p.unit)
            if amount > p.remaining:
                fail(409, "实际处置量超过剩余量")
            remaining = p.remaining - amount
            state = p.state if remaining else "SCRAPPED"
            self._change_stock(conn, p, state, p.store_id, remaining=remaining)
            self._movement(conn, ctx, p, state, amount, reason=reason)
        updated = self._stock(conn, p.package_id)
        return {**serialize(self._fact(updated)), "version": updated["version"]}

    def _label(self, conn, payload, ctx):
        ids = self._selection(payload["package_ids"])
        op = payload["operation"]
        if op not in {"PRINT", "REPRINT", "CONFIRM"}:
            fail(422, "不支持的打印操作")
        original_request = payload.get("print_request_id")
        if op == "CONFIRM":
            original_request = str(UUID(ident(original_request)))
        result = []
        for pid in ids:
            row = self._stock(conn, pid)
            p = self._fact(row)
            if p.store_id != payload["store_id"]:
                fail(403, "目标包装不在授权网点")
            if op == "CONFIRM":
                previous = conn.execute(
                    """SELECT operation,actor_id FROM demo_central_prints
                       WHERE request_id=? AND package_id=?""",
                    (original_request, pid),
                ).fetchone()
                confirmed = conn.execute(
                    """SELECT 1 FROM demo_central_prints WHERE package_id=?
                       AND original_request_id=? AND operation='CONFIRM'""",
                    (pid, original_request),
                ).fetchone()
                if (not previous or previous["operation"] not in {"PRINT", "REPRINT"}
                        or previous["actor_id"] != ctx["actor"] or confirmed):
                    fail(409, "缺少待确认的原打印请求")
            else:
                if p.state != "READY" or not p.produced_at <= ctx["now"] < p.expires_at:
                    fail(409, "物料未放行、已发货或已到期，不能打印")
                earlier = conn.execute(
                    """SELECT request_id FROM demo_central_prints
                       WHERE package_id=? AND operation IN ('PRINT','REPRINT')
                       ORDER BY rowid DESC LIMIT 1""", (pid,),
                ).fetchone()
                if op == "PRINT" and earlier:
                    fail(409, "已生成打印任务，请使用重印")
                if op == "REPRINT" and not earlier:
                    fail(409, "缺少原打印记录")
                original_request = earlier["request_id"] if earlier else None
            conn.execute(
                "INSERT INTO demo_central_prints VALUES (?,?,?,?,?,?)",
                (ctx["rid"], pid, op, original_request, ctx["actor"], ctx["now"].isoformat()),
            )
            result.append(json.loads(row["original"]))
        return {
            "state": "OPERATOR_CONFIRMED" if op == "CONFIRM" else "PRINT_REQUESTED",
            "operation": op, "request_id": ctx["rid"], "packages": result,
        }

    def mutate(self, op, payload, actor, shipment_id=None):
        if op not in {"plan", "batch", "create", "prepare", "dispatch", "receive", "open", "dispose", "recall", "label"}:
            fail(404, "未知中央生产操作")
        try:
            rid = str(UUID(ident(payload["request_id"])))
            fingerprint = sha256(dump({
                "op": "SUP59/" + op, "shipment": shipment_id, "actor": actor["employee_id"],
                "payload": {k: v for k, v in payload.items() if k != "request_id"},
            }).encode()).hexdigest()
        except (ValueError, TypeError, KeyError) as exc:
            fail(422, str(exc))
        ctx = {"rid": rid, "actor": actor["employee_id"], "now": aware(self.clock())}
        with self.ledger.lock, closing(self.ledger._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                resource = self._scope_mutation(conn, op, payload, actor, shipment_id)
                old = self.ledger._idem(conn, rid, fingerprint)
                if old is not None:
                    return old
                if op == "plan":
                    result = self._confirm_plan(conn, payload, actor, ctx)
                elif op == "batch":
                    result = self._release_batch(conn, payload, resource, ctx)
                elif op == "create":
                    result = self._create_shipment(conn, payload, ctx)
                elif op in {"prepare", "dispatch", "receive"}:
                    result = self._shipment_step(conn, op, payload, resource, ctx)
                elif op in {"open", "dispose", "recall"}:
                    result = self._inventory_step(conn, op, payload, resource, ctx)
                else:
                    result = self._label(conn, payload, ctx)
                self.ledger._finish(conn, rid, fingerprint, result)
                entity = (shipment_id or result.get("id") or result.get("batch_id")
                          or result.get("plan_id") or result.get("package_id"))
                conn.execute(
                    "INSERT INTO action_audit VALUES (?,?,?,?,?,?)",
                    (key("AUDIT"), rid, entity, ctx["actor"], "SUP59/" + op, ctx["now"].isoformat()),
                )
                conn.commit()
                return result
            except (ValueError, KeyError, TypeError) as exc:
                fail(422, str(exc))

    def _scope_mutation(self, conn, op, payload, actor, shipment_id):
        if op in {"create", "plan"}:
            self._permit(actor, "dispatch", payload["source_store_id"])
            self._permit(actor, "dispatch", payload["dest_store_id"])
        elif op == "batch":
            plan = conn.execute(
                "SELECT * FROM demo_central_plans WHERE id=?", (payload["plan_id"],),
            ).fetchone()
            if plan is None:
                fail(404, "未知生产计划")
            self._permit(actor, "dispatch", plan["source"])
            self._permit(actor, "dispatch", plan["destination"])
            return plan
        elif op in {"prepare", "dispatch", "receive"}:
            shipment = self._shipment(conn, shipment_id)
            if op == "receive":
                self._permit(actor, "receive", shipment["dest"])
            else:
                self._permit(actor, "dispatch", shipment["src"])
                self._permit(actor, "dispatch", shipment["dest"])
            return shipment
        elif op == "label":
            self._permit(actor, "dispatch", payload["store_id"])
            for pid in self._selection(payload["package_ids"]):
                if self._stock(conn, pid)["store_id"] != payload["store_id"]:
                    fail(403, "包装不在授权网点")
        else:
            self._permit(actor, "dispatch" if op == "recall" else "receive", payload["store_id"])
            row = self._stock(conn, payload["package_id"])
            if row["store_id"] != payload["store_id"]:
                fail(403, "包装不在授权网点")
            return row

    def _snapshot_shipment(self, conn, actor, ship_id, store_id):
        s = self._shipment(conn, ship_id)
        permitted = (
            (s["src"], "dispatch"), (s["dest"], "receive"), (s["dest"], "inspect"),
            (s["dest"], "inspect_independent"), (s["dest"], "review_independent"),
        )
        source_and_destination_dispatch = (
            store_id == s["dest"] and self._has_role(actor, "dispatch", s["src"])
            and self._has_role(actor, "dispatch", s["dest"])
        )
        if not source_and_destination_dispatch and not any(
            (store_id is None or store_id == store) and self._has_role(actor, role, store)
            for store, role in permitted
        ):
            fail(403, "缺少该配送单读取权限")
        current = self._shipment_rows(conn, ship_id)
        packs = [
            {**serialize(self._fact(row)), "version": row["version"], "recall_reason": row["recall_reason"]}
            for row in current
        ]
        receipts = [
            json.loads(row["facts"]) for row in conn.execute(
                "SELECT facts FROM demo_central_receipts WHERE shipment_id=? ORDER BY package_id",
                (ship_id,),
            )
        ]
        return {
            **self._ship_payload(s, packs), "src": s["src"], "dest": s["dest"],
            "planned": json.loads(s["dispatched"]) if s["dispatched"] else [
                serialize(self._fact(row)) for row in current
            ],
            "receipts": receipts, "sender_id": s["sender_id"], "sent_at": s["sent_at"],
            "eta": s["eta"], "arrived_at": s["arrived_at"], "revision": str(s["version"]),
        }

    def _snapshot_labels(self, conn, actor, store, package_ids):
        self._permit(actor, "dispatch", store)
        rows = (
            [self._stock(conn, pid) for pid in self._selection(package_ids)] if package_ids else
            list(conn.execute("SELECT * FROM demo_central_stock WHERE store_id=? ORDER BY package_id", (store,)))
        )
        if any(row["store_id"] != store for row in rows):
            fail(403, "包装不在授权网点")
        now = aware(self.clock())
        packages = [json.loads(row["original"]) for row in rows if (
            row["state"] == "READY" and now < timestamp(row["expires_at"])
        )]
        history = [
            dict(entry) for row in rows for entry in conn.execute(
                "SELECT * FROM demo_central_prints WHERE package_id=? ORDER BY occurred_at DESC LIMIT 100",
                (row["package_id"],),
            )
        ]
        return {"store_id": store, "packages": packages, "history": history}

    def _snapshot_tasks(self, conn, store, phase, facts, now):
        if phase not in {"START", "END"}:
            fail(422, "班次阶段须为 START 或 END")
        by_id = {f.package_id: f for f in facts}
        tasks = [
            {"task_key": f"{s}/{pid}/{kind}", "kind": kind, "package_id": pid,
             "due": time, "item_id": by_id[pid].item_id, "usage": by_id[pid].usage,
             "state": by_id[pid].state}
            for s, pid, kind, time in shift_due(facts, store_id=store, now=now)
        ]
        arrivals = conn.execute(
            """SELECT s.id,c.eta,s.state FROM shipments s JOIN demo_central_shipments c USING(id)
               WHERE s.dest=? AND s.state IN ('READY','DISPATCHED','PARTIAL_RECEIVED')
               ORDER BY c.eta,s.id""", (store,),
        )
        for row in arrivals:
            tasks.append({
                "task_key": f"{store}/{row['id']}/RECEIPT_REVIEW", "kind": "RECEIPT_REVIEW",
                "shipment_id": row["id"], "due": row["eta"], "state": row["state"],
            })
        if phase == "START":
            for p in facts:
                if available(p, now):
                    tasks.append({
                        "task_key": f"{store}/{p.package_id}/USE_GUIDANCE", "kind": "USE_GUIDANCE",
                        "package_id": p.package_id, "item_id": p.item_id, "usage": p.usage,
                    })
        else:
            for task in tasks:
                task["handover_required"] = True
        return {"store_id": store, "phase": phase, "tasks": tasks, "source": "DEMO_TASK_PREVIEW"}

    def _snapshot_exceptions(self, conn, store, facts, now):
        current_events = {
            row["package_id"]: dict(row) for row in conn.execute(
                """SELECT s.package_id,r.reason AS recall_reason,r.occurred_at AS recalled_at,
                          (SELECT m.reason FROM demo_central_movements m
                           WHERE m.package_id=s.package_id AND m.to_state='HOLD'
                             AND m.reason IS NOT NULL AND m.from_state <> m.to_state
                           ORDER BY m.rowid DESC LIMIT 1) AS hold_reason
                   FROM demo_central_stock s LEFT JOIN demo_central_recalls r USING(package_id)
                   WHERE s.store_id=?""", (store,),
            )
        }
        items = []
        for p in facts:
            event = current_events[p.package_id]
            if p.remaining <= 0:
                continue
            if event["recall_reason"]:
                kind, reason = "RECALL", event["recall_reason"]
            elif p.state == "HOLD":
                kind, reason = "HOLD", event["hold_reason"]
            elif p.state == "ACCEPTED" and now >= p.expires_at:
                kind, reason = "EXPIRED", None
            else:
                continue
            items.append({
                "kind": kind, "reason": reason, "package_id": p.package_id, "item_id": p.item_id,
                "remaining": str(p.remaining), "unit": p.unit, "expires_at": p.expires_at.isoformat(),
                "state": p.state, "recalled_at": event["recalled_at"],
            })
        for row in conn.execute(
            """SELECT s.id,c.eta,s.state FROM shipments s JOIN demo_central_shipments c USING(id)
               WHERE s.dest=? AND s.state IN ('DISPATCHED','PARTIAL_RECEIVED') ORDER BY c.eta,s.id""",
            (store,),
        ):
            if timestamp(row["eta"]) <= now or row["state"] == "PARTIAL_RECEIVED":
                items.append({
                    "kind": "UNRECEIVED", "shipment_id": row["id"], "due": row["eta"],
                    "state": row["state"],
                })
        return {"store_id": store, "items": items}

    def snapshot(self, kind, actor, store_id=None, shipment_id=None, package_ids=None, phase="START"):
        now = aware(self.clock())
        with self.ledger.lock, closing(self.ledger._conn()) as conn:
            conn.execute("BEGIN")
            if kind == "shipment":
                return self._snapshot_shipment(conn, actor, shipment_id, store_id)
            if kind == "labels":
                return self._snapshot_labels(conn, actor, store_id, package_ids)
            if kind == "plans":
                self._permit(actor, "dispatch", store_id)
                plans = conn.execute(
                    """SELECT p.facts, p.destination, b.id AS batch_id FROM demo_central_plans p
                       LEFT JOIN demo_central_batches b ON b.plan_id=p.id WHERE p.source=?
                       ORDER BY p.rowid DESC LIMIT 100""", (store_id,),
                )
                return {
                    "store_id": store_id,
                    "plans": [
                        {**json.loads(row["facts"]), "batch_id": row["batch_id"]}
                        for row in plans if self._has_role(actor, "dispatch", row["destination"])
                    ],
                }
            self._can_read(actor, store_id)
            rows = conn.execute(
                "SELECT * FROM demo_central_stock WHERE store_id=? ORDER BY package_id", (store_id,),
            ).fetchall()
            facts = [self._fact(row) for row in rows]
            if kind == "inventory":
                packages = [
                    {**serialize(p), "version": row["version"], "usable": available(p, now),
                     "opened_at": row["opened_at"]}
                    for p, row in zip(facts, rows)
                ]
                revision = sha256(dump(packages).encode()).hexdigest()[:16]
                return {"store_id": store_id, "revision": revision, "packages": packages}
            if kind == "tasks":
                return self._snapshot_tasks(conn, store_id, phase, facts, now)
            if kind == "exceptions":
                return self._snapshot_exceptions(conn, store_id, facts, now)
            fail(404, "未知中央生产投影")
