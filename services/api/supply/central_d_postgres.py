"""D-owned PostgreSQL SUP59 candidate against the reviewed *proposal*, not live schema.

Uses existing shipment/package/movement/idempotency tables. No runtime DDL,
no demo ledger, no connections to production by default. The inventory owner
must wire the actual identity, catalog, location, raw-lot and audit/outbox
callbacks using the same authoritative transaction. All callbacks are required.
"""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4
import json

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import ValidationError

from .central_authority import commit_d_command, RequestConflict
from .central_production_rules import (
    ApprovedRule, PackageFact, available, aware, expiry, ident, quantity,
    receipt_intent, shift_due, validate_split,
)
from .central_routes import COMMANDS, SNAPSHOTS, Reference
from .domain import calc_reorder, unique_codes


def fail(code, message):
    raise HTTPException(code, message)


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def uid(value=None):
    return str(UUID(str(value))) if value is not None else str(uuid4())


def at(value):
    return aware(value if isinstance(value, datetime) else datetime.fromisoformat(value))


def iso(value):
    return at(value).isoformat() if value is not None else None


def serial(p):
    result = asdict(p)
    for key in ("amount", "remaining"):
        result[key] = str(result[key])
    for key in ("produced_at", "expires_at"):
        result[key] = iso(result[key])
    return result


def rows(cursor, sql, args=()):
    cursor.execute(sql, args)
    names = [d.name for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def one(cursor, sql, args=(), message="记录不存在"):
    result = rows(cursor, sql, args)
    if not result:
        fail(404, message)
    return result[0]


def selection(values, *, allow_empty=False):
    if not isinstance(values, list) or len(values)>100:
        fail(422, "包装列表最多100项")
    if allow_empty and not values:
        return []
    ids=sorted(uid(v) for v in unique_codes(values))
    if len(ids)!=len(set(ids)):
        fail(422,"重复包装编号")
    return ids


def fact(row):
    original = row["original"]
    return PackageFact(**{
        **original, "state":row["state"], "store_id":row["stock_location_id"],
        "remaining":row["remaining_base"], "produced_at":at(original["produced_at"]),
        "expires_at":at(row["expires_at"]),
    })


def projection(row, now):
    p = fact(row)
    return {**serial(p), "version":row["version"], "usable":available(p, now) and not row["recall_reason"],
            "opened_at":iso(row["opened_at"]), "recall_reason":row["recall_reason"]}


class DWorker:
    def __init__(self, *, connect, identity, location, policy, consume_ingredients, record_event,
                 clock=lambda:datetime.now(timezone.utc), opening_provider=None):
        # The provided connection MUST be clean psycopg tuple-row connection to D.
        # identity(cursor, token) resolves CURRENT grants. For writes the D owner
        # must ensure authorization remains valid for the transaction.
        # policy(cursor, legal, item) reads the approved A snapshot from its owner.
        # consume_ingredients(cursor, ctx, policy, raw_lots, total, batch_id, source, produced_at)
        # atomically validates actual recipe/lot quantities and posts raw consumption.
        # record_event(cursor, ctx, operation, data) posts existing D audit + outbox.
        callbacks=(connect,identity,location,policy,consume_ingredients,record_event,clock)
        if not all(callable(f) for f in callbacks):
            raise TypeError("all authoritative callbacks are required")
        self.connect,self.identity,self.location,self.policy,self.consume_ingredients,self.record_event,self.clock=callbacks
        self.opening_provider=opening_provider

    def context(self, c, token, *, write=False, payload=None):
        me=self.identity(c, token)
        if not isinstance(me,dict):
            fail(403,"身份不可用")
        legal=ident(me.get("legal_entity_id"))
        actor=ident(me.get("employee_id"))
        grants=me.get("role_stores")
        if not isinstance(grants,dict) or any(not isinstance(v,list) or any(not isinstance(s,str) for s in v) for v in grants.values()):
            fail(403,"门店动作授权不可用")
        if write:
            # Small-business candidate serializes SUP59 by legal entity; legacy
            # D operations must use the same guard or reject central packages.
            c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",("SUP59/"+legal,))
            c.execute("SELECT set_config('bsv.sup59_command','1',true)")
        return dict(legal=legal,actor=actor,grants=grants,now=aware(self.clock()),token=token,
                    rid=uid(payload["request_id"]) if write else None)

    def permit(self,c,ctx,role,store):
        ident(store)
        if store not in ctx["grants"].get(role,[]):
            fail(403,"无该门店动作权限")
        value=self.location(c,ctx,store)
        if not isinstance(value,dict) or value.get("store_id")!=store or value.get("kind") not in {"warehouse","store","partner"}:
            fail(403,"无有效网点或库位")
        return value

    def pack(self,c,ctx,pid,lock=False):
        return one(c,"SELECT * FROM supply.shipment_package WHERE central_legal=%s AND package_id=%s"+(" FOR UPDATE" if lock else ""),
                   (ctx["legal"],uid(pid)),"未知包装")

    def shipment(self,c,ctx,sid,lock=False):
        return one(c,"SELECT * FROM supply.shipment WHERE central_legal=%s AND shipment_id=%s"+(" FOR UPDATE" if lock else ""),
                   (ctx["legal"],uid(sid)),"未知配送单")

    def plan_row(self,c,ctx,pid,lock=False):
        return one(c,"SELECT * FROM supply.central_plan WHERE legal_entity_id=%s AND plan_id=%s"+(" FOR UPDATE" if lock else ""),
                   (ctx["legal"],uid(pid)),"未知计划")

    def ship_packages(self,c,ctx,sid,lock=False):
        return rows(c,"SELECT * FROM supply.shipment_package WHERE central_legal=%s AND shipment_id=%s ORDER BY package_id"+(" FOR UPDATE" if lock else ""),
                    (ctx["legal"],sid))

    def scope(self,c,ctx,op,p):
        # Run before replay as well as the initial mutation.
        if op in {"plan-preview","plan","create"}:
            src=self.permit(c,ctx,"dispatch",p["source_store_id"])
            dest=self.permit(c,ctx,"dispatch",p["dest_store_id"])
            if src["kind"]!="warehouse" or dest["kind"]=="warehouse" or src==dest:
                fail(422,"中央仓及配送目的地无效")
            if op=="create":
                for pid in selection(p["package_ids"]):
                    if self.pack(c,ctx,pid,True)["stock_location_id"] not in {p["source_store_id"],p["dest_store_id"]}:
                        fail(403,"包装不在来源仓")
        elif op=="opening-import":
            self.permit(c,ctx,"dispatch",p["store_id"])
            self.permit(c,ctx,"receive",p["store_id"])
        elif op=="batch":
            r=self.plan_row(c,ctx,p["plan_id"],True)
            self.permit(c,ctx,"dispatch",r["source_location_id"])
            self.permit(c,ctx,"dispatch",r["dest_location_id"])
            return r
        elif op in {"prepare","dispatch","receive"}:
            r=self.shipment(c,ctx,p["shipment_id"],True)
            if op=="receive":
                self.permit(c,ctx,"receive",r["dest_location_id"])
            else:
                self.permit(c,ctx,"dispatch",r["source_location_id"])
                self.permit(c,ctx,"dispatch",r["dest_location_id"])
            return r
        elif op=="label":
            self.permit(c,ctx,"dispatch",p["store_id"])
            for pid in selection(p["package_ids"]):
                if self.pack(c,ctx,pid,True)["stock_location_id"]!=p["store_id"]:
                    fail(403,"包装不在授权网点")
        else:
            self.permit(c,ctx,"dispatch" if op=="recall" else "receive",p["store_id"])
            r=self.pack(c,ctx,p["package_id"],True)
            if r["stock_location_id"]!=p["store_id"]:
                fail(403,"包装不在授权网点")
            return r

    def approved(self,c,ctx,item):
        policy=self.policy(c,ctx,item)
        if not isinstance(policy,dict) or policy.get("item_id")!=item or not isinstance(policy.get("rule"),ApprovedRule):
            fail(409,"缺少已批准的生产规则")
        for k in ("name","recipe_version","sop_version","storage","usage"):
            ident(policy.get(k))
        quantity(policy["standard_amount"],policy["unit"])
        return policy

    def plan_preview(self,c,ctx,p):
        policy=self.approved(c,ctx,p["item_id"])
        eta=at(p["next_delivery_at"])
        if eta<=ctx["now"]:
            fail(422,"配送时刻必须在未来")
        stock=rows(c,"""SELECT p.*,s.eta AS delivery_eta FROM supply.shipment_package p
                 LEFT JOIN supply.shipment s ON s.shipment_id=p.shipment_id
                 WHERE p.central_legal=%s AND p.stock_location_id=%s AND p.item_id=%s""",
                   (ctx["legal"],p["dest_store_id"],p["item_id"]))
        confirmed=expiring=incoming=Decimal(0)
        for row in stock:
            f=fact(row)
            if row["recall_reason"] or f.unit!=policy["unit"]:
                continue
            if available(f,ctx["now"]):
                confirmed+=f.remaining
                if f.expires_at<=eta: expiring+=f.remaining
            elif f.state=="IN_TRANSIT" and row["delivery_eta"] and ctx["now"]<=at(row["delivery_eta"])<=eta<f.expires_at:
                incoming+=f.remaining
        forecast={k:quantity(p[k],policy["unit"],zero=True) for k in ("usage_before_next","reserved","demand_next_cycle","safety_stock")}
        # No intra-period demand curve is asserted: expiry subtraction is conservative.
        result=calc_reorder(confirmed_available=confirmed,arrivals_before_next=incoming,
             expiry_before_next=expiring,arrivals_next_cycle=0,pack_size=policy["standard_amount"],max_packs=100,**forecast)
        return {**result,"unit":policy["unit"],"source_store_id":p["source_store_id"],"dest_store_id":p["dest_store_id"],
                "item_id":p["item_id"],"next_delivery_at":iso(eta),"confirmed_available":str(confirmed),
                "eligible_in_transit":str(incoming),"expires_before_arrival":str(expiring),
                "recipe_version":policy["recipe_version"],"sop_version":policy["sop_version"],
                "expiry_rule_version":policy["rule"].version,"standard_amount":str(policy["standard_amount"]),
                "storage":policy["storage"],**{k:str(v) for k,v in forecast.items()}}

    def movement(self,c,ctx,p,src,dest,amount,kind,shipment_id=None):
        c.execute("""INSERT INTO supply.movement(movement_id,request_id,shipment_id,package_id,item_id,lot_id,
                 from_location_id,to_location_id,qty_base,actor_employee_id,occurred_at,central_kind)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                  (uid(),ctx["rid"],shipment_id,p.package_id,p.item_id,p.batch_id,src,dest,amount,ctx["actor"],ctx["now"],kind))

    def change(self,c,ctx,p,state,store,*,remaining=None,expires=None,opened=None,recall=None):
        c.execute("""UPDATE supply.shipment_package SET state=%s,stock_location_id=%s,
               remaining_base=%s,expires_at=%s,opened_at=COALESCE(%s,opened_at),version=version+1,
               recall_reason=COALESCE(%s,recall_reason),recalled_at=CASE WHEN %s::text IS NULL THEN recalled_at ELSE %s END
               WHERE package_id=%s AND central_legal=%s""",
            (state,store,p.remaining if remaining is None else remaining,expires or p.expires_at,
             opened,recall,recall,ctx["now"],p.package_id,ctx["legal"]))

    def release(self,c,ctx,p,plan):
        policy=self.approved(c,ctx,plan["item_id"])
        old=plan["facts"]
        if (p["recipe_version"],policy["recipe_version"],policy["sop_version"],policy["rule"].version)!=(
             old["recipe_version"],old["recipe_version"],old["sop_version"],old["expiry_rule_version"]):
            fail(409,"批准规则已改变，请重新计划")
        if rows(c,"SELECT batch_id FROM supply.central_batch WHERE plan_id=%s",(plan["plan_id"],)):
            fail(409,"计划已登记制作")
        start=at(p["produced_at"]); end=expiry(policy["rule"],start)
        if not start<=ctx["now"]<end: fail(409,"制作时间无效或已过期")
        total=quantity(p["total"],policy["unit"])
        parts=[(uid(),x) for x in p["package_amounts"]]
        packed=validate_split(total,policy["unit"],parts,p["remainder"],p["loss"])
        if total>Decimal(old["quantity"]): fail(409,"实际制作量超过批准计划")
        # Unpacked residue cannot silently become usable inventory.
        if quantity(p["remainder"],policy["unit"],zero=True)>0:
            fail(409,"剩余物料须独立分装或确认损耗后再放行")
        batch=uid(); lots=unique_codes(p["ingredient_lot_ids"])
        self.consume_ingredients(c,ctx,policy,lots,total,batch,plan["source_location_id"],start)
        facts=dict(batch_id=batch,plan_id=str(plan["plan_id"]),item_id=plan["item_id"],producer_id=ctx["actor"],
             produced_at=iso(start),expires_at=iso(end),recipe_version=policy["recipe_version"],sop_version=policy["sop_version"],
             ingredient_lot_ids=lots,total=str(total),packed=str(packed),unit=policy["unit"],remainder=p["remainder"],loss=p["loss"],
             state="RELEASED",expiry_rule_version=policy["rule"].version,approved_rule=asdict(policy["rule"]))
        c.execute("INSERT INTO supply.central_batch VALUES (%s,%s,%s,%s::jsonb)",(batch,plan["plan_id"],ctx["legal"],dump(facts)))
        packages=[]
        for pid,amount in parts:
            f=PackageFact(pid,batch,plan["item_id"],policy["name"],plan["source_location_id"],amount,amount,policy["unit"],
                          start,end,policy["rule"].version,ctx["actor"],policy["storage"],policy["usage"],"READY")
            orig=serial(f)
            c.execute("""INSERT INTO supply.shipment_package(package_id,shipment_id,item_id,lot_id,base_uom,qty_base,state,
                  central_legal,stock_location_id,remaining_base,version,expires_at,original)
                  VALUES (%s,NULL,%s,%s,%s,%s,'READY',%s,%s,%s,1,%s,%s::jsonb)""",
                  (pid,f.item_id,batch,f.unit,f.amount,ctx["legal"],f.store_id,f.remaining,end,dump(orig)))
            self.movement(c,ctx,f,"SUP59:PRODUCTION:"+f.store_id,f.store_id,f.amount,"PRODUCTION")
            packages.append({**orig,"version":1})
        return {**facts,"packages":packages}

    def opening_candidates(self,c,ctx,store):
        self.permit(c,ctx,"dispatch",store)
        self.permit(c,ctx,"receive",store)
        if not self.opening_provider:
            return []
        records=self.opening_provider(c,ctx,store)
        if not isinstance(records,list) or len(records)>10000:
            fail(503,"期初凭证来源无效")
        existing={r["opening_evidence_id"] for r in rows(c,"SELECT opening_evidence_id FROM supply.shipment_package WHERE central_legal=%s AND opening_evidence_id IS NOT NULL",(ctx["legal"],))}
        seen=set(); result=[]
        for r in records:
            if r.get("legal_entity_id")!=ctx["legal"] or r.get("store_id")!=store:
                fail(403,"期初凭证越权")
            eid=ident(r["evidence_id"])
            if eid in seen:fail(409,"重复期初凭证")
            seen.add(eid)
            if eid not in existing:result.append(r)
        return result

    def opening_import(self,c,ctx,p):
        candidates={r["evidence_id"]:r for r in self.opening_candidates(c,ctx,p["store_id"])}
        ids=unique_codes(p["evidence_ids"])
        if len(ids)!=len(p["evidence_ids"]):fail(422,"重复期初凭证")
        result=[]
        for eid in ids:
            r=candidates.get(eid)
            if not r or r.get("approved") is not True or r.get("not_already_accounted") is not True:
                fail(409,"无已批准且未入账期初凭证")
            ident(r["approval_reference"])
            policy=self.approved(c,ctx,r["item_id"])
            if r["rule_version"]!=policy["rule"].version or r["unit"]!=policy["unit"]:
                fail(409,"历史规则须由权威目录复核")
            start=at(r["produced_at"]); observed=at(r["observed_at"]); end=at(r["expires_at"])
            if not start<=observed<=ctx["now"] or (ctx["now"]-observed).total_seconds()>86400:
                fail(409,"历史库存须在最近24小时内实盘")
            if type(r.get("opened")) is not bool or bool(r.get("opened_at"))!=r["opened"]:
                fail(409,"开封记录缺失")
            opened=at(r["opened_at"]) if r["opened"] else None
            if opened and not start<=opened<=observed:fail(409,"历史开封时间无效")
            if end>expiry(policy["rule"],start,opened_at=opened):
                fail(409,"历史有效期超出已批准规则")
            state="HOLD" if r.get("quality_accepted") is not True or end<=ctx["now"] else "ACCEPTED"
            pid=uid(r["package_id"]); batch=uid(r["batch_id"])
            f=PackageFact(pid,batch,r["item_id"],policy["name"],p["store_id"],r["amount"],r["remaining"],r["unit"],start,end,r["rule_version"],r["producer_id"],policy["storage"],policy["usage"],state)
            if f.remaining<=0:fail(409,"零库存无需入账")
            if rows(c,"SELECT package_id FROM supply.shipment_package WHERE package_id=%s",(pid,)):fail(409,"包装已存在，不得重复期初入账")
            batch_facts=dict(batch_id=batch,item_id=f.item_id,origin_kind="OPENING",approved_rule=asdict(policy["rule"]),recipe_version=policy["recipe_version"])
            c.execute("INSERT INTO supply.central_batch(batch_id,plan_id,legal_entity_id,facts) VALUES (%s,NULL,%s,%s::jsonb) ON CONFLICT(batch_id) DO NOTHING",(batch,ctx["legal"],dump(batch_facts)))
            prior=one(c,"SELECT legal_entity_id,facts FROM supply.central_batch WHERE batch_id=%s",(batch,))
            if prior["legal_entity_id"]!=ctx["legal"] or prior["facts"]!=batch_facts:fail(409,"批次与已存在事实不一致")
            c.execute("""INSERT INTO supply.shipment_package(package_id,shipment_id,item_id,lot_id,base_uom,qty_base,state,
                central_legal,stock_location_id,remaining_base,version,opened_at,expires_at,original,opening_evidence_id)
                VALUES (%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s::jsonb,%s)""",
                (pid,f.item_id,batch,f.unit,f.amount,state,ctx["legal"],f.store_id,f.remaining,opened,end,dump(serial(f)),eid))
            self.movement(c,ctx,f,"SUP59:OPENING:"+f.store_id,f.store_id if state=="ACCEPTED" else "SUP59:HOLD:"+f.store_id,f.remaining,"OPENING")
            result.append({**serial(f),"evidence_id":eid,"approval_reference":r["approval_reference"],"observed_at":iso(observed),"version":1})
        return {"packages":result}

    def ship_result(self,c,ctx,r):
        sid=str(r["shipment_id"])
        return dict(id=sid,source_store_id=r["source_location_id"],dest_store_id=r["dest_location_id"],
                    state=r["state"],version=r["version"],packages=[projection(x,ctx["now"]) for x in self.ship_packages(c,ctx,sid)])

    def create(self,c,ctx,p):
        eta=at(p["eta"]); src=p["source_store_id"]; dest=p["dest_store_id"]
        if eta<=ctx["now"]: fail(422,"预计到达须在未来")
        ids=selection(p["package_ids"])
        for pid in ids:
            row=self.pack(c,ctx,pid,True); f=fact(row)
            if row["shipment_id"] is not None or f.state!="READY" or row["recall_reason"] or f.store_id!=src or not f.produced_at<=ctx["now"]<eta<f.expires_at:
                fail(409,"包装不可配送或已分配")
        sid=uid()
        c.execute("""INSERT INTO supply.shipment(shipment_id,source_location_id,dest_location_id,state,version,
                  created_by_employee_id,created_at,central_legal,eta) VALUES (%s,%s,%s,'DRAFT',1,%s,%s,%s,%s)""",
                  (sid,src,dest,ctx["actor"],ctx["now"],ctx["legal"],eta))
        for pid in ids:
            c.execute("UPDATE supply.shipment_package SET shipment_id=%s,version=version+1 WHERE package_id=%s",(sid,pid))
        return self.ship_result(c,ctx,self.shipment(c,ctx,sid))

    def ship_step(self,c,ctx,op,p,r):
        if p["expected_version"]!=r["version"]: fail(409,"配送单版本冲突")
        sid=str(r["shipment_id"]); src=r["source_location_id"]; dest=r["dest_location_id"]
        packs=self.ship_packages(c,ctx,sid,True); facts=[fact(x) for x in packs]
        if op in {"prepare","dispatch"}:
            if r["state"]!=("DRAFT" if op=="prepare" else "READY") or not facts or any(
               f.state!="READY" or f.store_id!=src or x["recall_reason"] or not f.produced_at<=ctx["now"]<r["eta"]<f.expires_at for f,x in zip(facts,packs)):
                fail(409,"配送状态或包装须复核")
            state="READY"
            if op=="dispatch":
                if set(selection(p["scanned_codes"]))!={f.package_id for f in facts}:fail(409,"扫码不等于计划包装集合")
                for f in facts:
                    self.movement(c,ctx,f,src,"SUP59:TRANSIT:"+sid,f.remaining,"DISPATCH",sid)
                    self.change(c,ctx,f,"IN_TRANSIT",dest)
                dispatched=[serial(fact(x)) for x in self.ship_packages(c,ctx,sid)]
                c.execute("UPDATE supply.shipment SET sent_at=%s,sender_id=%s,dispatched=%s::jsonb WHERE shipment_id=%s",
                          (ctx["now"],ctx["actor"],dump(dispatched),sid))
                state="DISPATCHED"
        else:
            if r["state"] not in {"DISPATCHED","PARTIAL_RECEIVED"} or not r["sent_at"] or r["sent_at"]>ctx["now"]:
                fail(409,"配送尚未发出或已结束")
            accepted=selection(p["accepted_ids"],allow_empty=True); held=selection(p["hold_ids"],allow_empty=True); reasons=p["exception_reasons"]
            if set(reasons)!=set(held):fail(422,"隔离须逐件登记原因")
            by_id={f.package_id:(f,x) for f,x in zip(facts,packs)}
            if any(by_id[pid][1]["recall_reason"] for pid in accepted if pid in by_id):fail(409,"召回包装不得合格签收")
            try:intent=receipt_intent(facts,accepted,held,store_id=dest,now=ctx["now"])
            except ValueError as exc:fail(409,str(exc))
            for pid,state,amount,_ in intent:
                f=by_id[pid][0]; target=dest if state=="ACCEPTED" else "SUP59:HOLD:"+dest
                self.movement(c,ctx,f,"SUP59:TRANSIT:"+sid,target,amount,"RECEIVE",sid)
                self.change(c,ctx,f,state,dest)
                receipt=dict(package={**serial(f),"state":state},accepted=str(amount if state=="ACCEPTED" else 0),
                    held=str(amount if state=="HOLD" else 0),committed=True,source_store_id=src,sender_id=r["sender_id"],
                    receiver_id=ctx["actor"],sent_at=iso(r["sent_at"]),received_at=iso(ctx["now"]),exception_reason=reasons.get(pid,""))
                c.execute("INSERT INTO supply.central_receipt VALUES (%s,%s,%s::jsonb)",(sid,pid,dump(receipt)))
            c.execute("UPDATE supply.shipment SET arrived_at=COALESCE(arrived_at,%s) WHERE shipment_id=%s",(ctx["now"],sid))
            state="PARTIAL_RECEIVED" if any(x["state"]=="IN_TRANSIT" for x in self.ship_packages(c,ctx,sid)) else "RECEIVED"
        c.execute("UPDATE supply.shipment SET state=%s,version=version+1 WHERE shipment_id=%s",(state,sid))
        return self.ship_result(c,ctx,self.shipment(c,ctx,sid))

    def inventory_step(self,c,ctx,op,p,r):
        f=fact(r); now=ctx["now"]
        if r["version"]!=p["expected_version"]:fail(409,"包装版本冲突")
        if op=="open":
            if not available(f,now) or r["opened_at"] or r["recall_reason"]:fail(409,"包装不可开封")
            batch=one(c,"SELECT facts FROM supply.central_batch WHERE batch_id=%s AND legal_entity_id=%s",(uid(f.batch_id),ctx["legal"]))
            end=expiry(ApprovedRule(**batch["facts"]["approved_rule"]),f.produced_at,opened_at=now,restriction_at=f.expires_at)
            self.change(c,ctx,f,f.state,f.store_id,expires=end,opened=now)
        elif op=="consume":
            if not available(f,now) or not r["opened_at"] or r["recall_reason"]:fail(409,"包装不可耗用")
            amount=quantity(p["amount"],f.unit)
            if amount>f.remaining:fail(409,"耗用量超过余量")
            self.movement(c,ctx,f,f.store_id,"SUP59:CONSUMED:"+f.store_id,amount,"CONSUMED",r["shipment_id"])
            self.change(c,ctx,f,f.state,f.store_id,remaining=f.remaining-amount)
        elif op=="recall":
            if r["recall_reason"] or not f.remaining or f.state not in {"READY","ACCEPTED","HOLD","IN_TRANSIT"}:fail(409,"不可召回")
            state="IN_TRANSIT" if f.state=="IN_TRANSIT" else "HOLD"
            if f.state in {"READY","ACCEPTED"}:
                self.movement(c,ctx,f,f.store_id,"SUP59:HOLD:"+f.store_id,f.remaining,"RECALL",r["shipment_id"])
            self.change(c,ctx,f,state,f.store_id,recall=ident(p["reason"]))
        else:
            if f.state not in {"HOLD","ACCEPTED"} or (f.state=="ACCEPTED" and now<f.expires_at):
                fail(409,"仅隔离或过期包装可处置")
            amount=quantity(p["amount"],f.unit)
            if amount>f.remaining:fail(409,"处置量超过余量")
            src="SUP59:HOLD:"+f.store_id if f.state=="HOLD" else f.store_id
            self.movement(c,ctx,f,src,"SUP59:SCRAPPED:"+f.store_id,amount,"DISPOSED",r["shipment_id"])
            self.change(c,ctx,f,f.state if f.remaining>amount else "SCRAPPED",f.store_id,remaining=f.remaining-amount)
        return projection(self.pack(c,ctx,f.package_id),now)

    def label(self,c,ctx,p):
        result=[]; op=p["operation"]
        for pid in selection(p["package_ids"]):
            row=self.pack(c,ctx,pid); f=fact(row)
            history=rows(c,"SELECT * FROM supply.central_print WHERE package_id=%s ORDER BY occurred_at DESC,request_id DESC",(pid,))
            prior=next((x for x in history if x["operation"] in {"PRINT","REPRINT"}),None)
            orig=None
            if op=="CONFIRM":
                orig=uid(p["print_request_id"])
                previous=next((x for x in history if str(x["request_id"])==orig and x["operation"] in {"PRINT","REPRINT"} and x["actor_id"]==ctx["actor"]),None)
                if not previous or any(x["operation"]=="CONFIRM" and str(x["original_request_id"])==orig for x in history):
                    fail(409,"无待确认原打印请求")
            else:
                if f.state!="READY" or row["recall_reason"] or not f.produced_at<=ctx["now"]<f.expires_at:fail(409,"包装不可打印")
                if (op=="PRINT" and prior) or (op=="REPRINT" and not prior):fail(409,"打印与重印状态不匹配")
                orig=str(prior["request_id"]) if prior else None
            c.execute("INSERT INTO supply.central_print VALUES (%s,%s,%s,%s,%s,%s)",(ctx["rid"],pid,op,orig,ctx["actor"],ctx["now"]))
            result.append(row["original"])
        return dict(state="OPERATOR_CONFIRMED" if op=="CONFIRM" else "PRINT_REQUESTED",operation=op,request_id=ctx["rid"],packages=result)

    def command(self,operation,payload,token):
        model=COMMANDS.get(operation)
        if not model:fail(404,"未知供货操作")
        try:
            p=model.model_validate(payload).model_dump(mode="json",exclude_none=True)
            if operation in {"prepare","dispatch","receive"} and not p.get("shipment_id"):fail(422,"缺少配送单编号")
            with self.connect() as conn:
                if operation=="plan-preview":
                    with conn.transaction(),conn.cursor() as c:
                        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                        ctx=self.context(c,token); self.scope(c,ctx,operation,p)
                        return dict(state="PREVIEW",data=self.plan_preview(c,ctx,p))
                state={}
                def authorize(c):
                    ctx=self.context(c,token,write=True,payload=p)
                    state.update(ctx=ctx,resource=self.scope(c,ctx,operation,p))
                    return sha256(dump([ctx["legal"],ctx["actor"]]).encode()).hexdigest()
                def mutate(c):
                    ctx=state["ctx"]; resource=state["resource"]
                    if operation=="plan":
                        data=self.plan_preview(c,ctx,p)
                        if data["status"]!="SUGGESTED" or data["packages"]<=0:fail(409,"补货建议需要复核")
                        data.update(plan_id=uid(),state="CONFIRMED",version=1)
                        c.execute("INSERT INTO supply.central_plan VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)",
                                  (data["plan_id"],ctx["legal"],p["source_store_id"],p["dest_store_id"],p["item_id"],dump(data),ctx["now"]))
                    elif operation=="batch":data=self.release(c,ctx,p,resource)
                    elif operation=="opening-import":data=self.opening_import(c,ctx,p)
                    elif operation=="create":data=self.create(c,ctx,p)
                    elif operation in {"prepare","dispatch","receive"}:data=self.ship_step(c,ctx,operation,p,resource)
                    elif operation=="label":data=self.label(c,ctx,p)
                    else:data=self.inventory_step(c,ctx,operation,p,resource)
                    self.record_event(c,ctx,operation,{"input":p,"result":data})
                    return data
                return commit_d_command(conn,operation=operation,payload=p,authorize=authorize,mutate=mutate)
        except RequestConflict as exc:fail(409,str(exc))
        except (ValueError,ValidationError,KeyError,TypeError) as exc:fail(422,"供货命令或权威事实不完整")

    def snapshot(self,kind,token,*,store_id=None,shipment_id=None,package_ids=None,phase="START"):
        if kind not in SNAPSHOTS:fail(404,"未知供货视图")
        try:
            with self.connect() as conn,conn.transaction(),conn.cursor() as c:
                c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                ctx=self.context(c,token); now=ctx["now"]; legal=ctx["legal"]
                if kind=="shipment":
                    s=self.shipment(c,ctx,shipment_id)
                    src=s["source_location_id"];dest=s["dest_location_id"]
                    scope=store_id or None
                    roles=[(src,"dispatch"),(dest,"receive"),(dest,"inspect"),(dest,"inspect_independent"),(dest,"review_independent")]
                    if scope==dest and src in ctx["grants"].get("dispatch",[]) and dest in ctx["grants"].get("dispatch",[]):roles.append((dest,"dispatch"))
                    allowed=[(loc,role) for loc,role in roles if (not scope or scope==loc) and loc in ctx["grants"].get(role,[])]
                    if not allowed:fail(403,"无配送单权限")
                    self.permit(c,ctx,allowed[0][1],allowed[0][0])
                    sid=str(s["shipment_id"]); result=self.ship_result(c,ctx,s)
                    result.update(src=src,dest=dest,planned=s["dispatched"] or [serial(fact(x)) for x in self.ship_packages(c,ctx,sid)],
                         receipts=[x["facts"] for x in rows(c,"SELECT facts FROM supply.central_receipt WHERE shipment_id=%s ORDER BY package_id",(sid,))],
                         sender_id=s["sender_id"],sent_at=iso(s["sent_at"]),eta=iso(s["eta"]),arrived_at=iso(s["arrived_at"]),revision=str(s["version"]))
                    return result
                if not store_id:fail(422,"缺少门店")
                roles={"dispatch"} if kind in {"plans","labels","opening-candidates"} else {"dispatch","receive"}
                if kind=="exceptions":roles|={"inspect","inspect_independent","review_independent"}
                allowed=next((r for r in sorted(roles) if store_id in ctx["grants"].get(r,[])),None)
                if not allowed:fail(403,"无门店权限")
                self.permit(c,ctx,allowed,store_id)
                if kind=="opening-candidates":
                    return {"items":self.opening_candidates(c,ctx,store_id)}
                if kind=="shipments":
                    found=rows(c,"""SELECT shipment_id,source_location_id,dest_location_id,state,version,created_at
                          FROM supply.shipment WHERE central_legal=%s AND (source_location_id=%s OR dest_location_id=%s)
                          ORDER BY created_at DESC,shipment_id LIMIT 200""",(legal,store_id,store_id))
                    return {"items":[dict(id=str(x["shipment_id"]),src=x["source_location_id"],dest=x["dest_location_id"],
                            state=x["state"],version=x["version"],created_at=iso(x["created_at"])) for x in found if (
                            x["source_location_id"]==store_id and store_id in ctx["grants"].get("dispatch",[]) or
                            x["dest_location_id"]==store_id and (store_id in ctx["grants"].get("receive",[]) or
                            store_id in ctx["grants"].get("dispatch",[]) and x["source_location_id"] in ctx["grants"].get("dispatch",[]))
                            )]}
                if kind=="plans":
                    plans=rows(c,"""SELECT p.*,b.batch_id FROM supply.central_plan p LEFT JOIN supply.central_batch b USING(plan_id)
                            WHERE p.legal_entity_id=%s AND p.source_location_id=%s ORDER BY p.created_at DESC LIMIT 100""",(legal,store_id))
                    return dict(store_id=store_id,plans=[{**x["facts"],"batch_id":str(x["batch_id"]) if x["batch_id"] else None} for x in plans if x["dest_location_id"] in ctx["grants"].get("dispatch",[])])
                stock=rows(c,"SELECT * FROM supply.shipment_package WHERE central_legal=%s AND stock_location_id=%s ORDER BY package_id",(legal,store_id))
                if kind=="labels" and package_ids:
                    stock=[self.pack(c,ctx,pid) for pid in selection(package_ids)]
                    if any(x["stock_location_id"]!=store_id for x in stock):fail(403,"包装不在授权网点")
                packs=[projection(x,now) for x in stock]; facts=[fact(x) for x in stock]
                if kind=="inventory":
                    return dict(store_id=store_id,packages=packs,revision=sha256(dump(packs).encode()).hexdigest()[:16])
                if kind=="labels":
                    history=[]
                    for x in stock:
                        for e in rows(c,"SELECT * FROM supply.central_print WHERE package_id=%s ORDER BY occurred_at DESC LIMIT 100",(x["package_id"],)):
                            history.append({**e,"package_id":str(e["package_id"]),"request_id":str(e["request_id"]),
                              "original_request_id":str(e["original_request_id"]) if e["original_request_id"] else None,"occurred_at":iso(e["occurred_at"])})
                    return dict(store_id=store_id,packages=[x["original"] for x in stock if x["state"]=="READY" and not x["recall_reason"] and x["expires_at"]>now],history=history)
                arriving=rows(c,"SELECT * FROM supply.shipment WHERE central_legal=%s AND dest_location_id=%s AND state IN ('READY','DISPATCHED','PARTIAL_RECEIVED') ORDER BY eta,shipment_id",(legal,store_id))
                if kind=="tasks":
                    if phase not in {"START","END"}:fail(422,"班次阶段无效")
                    tasks=[dict(task_key=f"{s}/{pid}/{k}",package_id=pid,kind=k,due=time) for s,pid,k,time in shift_due(facts,store_id=store_id,now=now)]
                    tasks += [dict(task_key=f"{store_id}/{x['shipment_id']}/RECEIPT_REVIEW",kind="RECEIPT_REVIEW",shipment_id=str(x["shipment_id"]),due=iso(x["eta"]),state=x["state"]) for x in arriving]
                    if phase=="START":
                        tasks += [dict(task_key=f"{store_id}/{p['package_id']}/USE_GUIDANCE",kind="USE_GUIDANCE",package_id=p["package_id"],item_id=p["item_id"],usage=p["usage"]) for p in packs if p["usable"]]
                    else:
                        for t in tasks:t["handover_required"]=True
                    return dict(store_id=store_id,phase=phase,tasks=tasks,source="D_TASK_PROJECTION")
                items=[]
                for x,p in zip(stock,packs):
                    if Decimal(p["remaining"])<=0:continue
                    k="RECALL" if x["recall_reason"] else "HOLD" if p["state"]=="HOLD" else "EXPIRED" if p["state"]=="ACCEPTED" and x["expires_at"]<=now else None
                    if k:items.append({**p,"kind":k,"reason":x["recall_reason"]})
                items += [dict(kind="UNRECEIVED",shipment_id=str(x["shipment_id"]),due=iso(x["eta"]),state=x["state"]) for x in arriving if x["state"]=="PARTIAL_RECEIVED" or (x["state"]=="DISPATCHED" and x["eta"]<=now)]
                return dict(store_id=store_id,items=items)
        except (ValueError,KeyError,TypeError):fail(422,"供货快照或权威事实不完整")


def d_router(worker, *, authenticate_service):
    """Mount only inside D owner's application; validate service credentials first."""
    router=APIRouter(prefix="/supply/central/v1")
    def token(request):
        authenticate_service(request)
        h=request.headers.get("Authorization","")
        if not h.startswith("Bearer ") or not h[7:].strip():fail(401,"缺少统一身份")
        return h[7:].strip()
    @router.post("/{operation}")
    def command(operation:str,body:dict,request:Request):
        return worker.command(operation,body,token(request))
    @router.get("/{kind}")
    def snapshot(kind:str,request:Request,store_id:Reference|None=None,shipment_id:Reference|None=None,
                 package_ids:list[Reference]|None=Query(None,min_length=1,max_length=100),phase:str="START"):
        return worker.snapshot(kind,token(request),store_id=store_id,shipment_id=shipment_id,package_ids=package_ids,phase=phase)
    return router
