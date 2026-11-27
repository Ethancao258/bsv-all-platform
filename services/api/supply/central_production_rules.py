"""SUP-59 pure rules and print projections, not a ledger or HTTP service.

Call ONLY after existing identity, scope and authority checks. Input records must
come from approved catalog and committed D facts, never directly from clients.
No database, network, writes, ID allocation, notification or printer side effects.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from zoneinfo import ZoneInfo

CN = ZoneInfo("Asia/Shanghai")
UNITS = frozenset({"mL", "g", "piece"})
WEEK = "一二三四五六日"

def aware(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)

def quantity(value, unit, *, zero=False):
    if unit not in UNITS or isinstance(value, (bool, float)):
        raise ValueError("invalid base unit or quantity type")
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid quantity") from exc
    if not n.is_finite() or n < 0 or (not zero and n == 0):
        raise ValueError("invalid quantity")
    if n > Decimal("99999999999999.9999") or n.as_tuple().exponent < -4:
        raise ValueError("quantity outside NUMERIC(18,4)")
    if unit == "piece" and n != n.to_integral_value():
        raise ValueError("fractional piece")
    return n

def ident(value):
    if not isinstance(value, str) or not value.strip() or len(value)>200:
        raise ValueError("missing or invalid stable reference")
    return value

@dataclass(frozen=True)
class ApprovedRule:
    version: str
    approved: bool
    elapsed_seconds: int
    opened_seconds: int | None = None
    # Adapter converts only verified elapsed duration rules. Other rules need
    # separately validated interpretation; never guess from free-text days.
    def __post_init__(self):
        ident(self.version)
        if self.approved is not True:
            raise ValueError("unapproved shelf life")
        for v in (self.elapsed_seconds, self.opened_seconds):
            if v is not None and (type(v) is not int or not 0<v<=315360000):
                raise ValueError("invalid approved duration")
        if self.elapsed_seconds is None:
            raise ValueError("missing approved duration")

def expiry(rule, produced_at, *, opened_at=None, restriction_at=None):
    start=aware(produced_at)
    end=start+timedelta(seconds=rule.elapsed_seconds)
    if opened_at is not None:
        opened=aware(opened_at)
        if opened<start:
            raise ValueError("opened before produced")
        if rule.opened_seconds is None:
            raise ValueError("unknown opened shelf life")
        end=min(end,opened+timedelta(seconds=rule.opened_seconds))
    if restriction_at is not None:
        end=min(end,aware(restriction_at))
    return end

def validate_split(total, unit, parts, remainder, loss):
    """All quantities in the same explicit unit; no unaccounted production."""
    total=quantity(total,unit)
    parts=list(parts)
    if not parts:
        raise ValueError("no packages")
    seen=set()
    packed=Decimal(0)
    for package_id, amount in parts:
        ident(package_id)
        if package_id in seen:
            raise ValueError("duplicate package")
        seen.add(package_id)
        packed+=quantity(amount,unit)
    if packed+quantity(remainder,unit,zero=True)+quantity(loss,unit,zero=True)!=total:
        raise ValueError("production quantity does not reconcile")
    return packed

@dataclass(frozen=True)
class PackageFact:
    package_id: str
    batch_id: str
    item_id: str
    name: str
    store_id: str
    amount: Decimal
    remaining: Decimal
    unit: str
    produced_at: datetime
    expires_at: datetime
    rule_version: str
    producer_id: str
    storage: str
    usage: str
    state: str
    def __post_init__(self):
        for v in (self.package_id,self.batch_id,self.item_id,self.name,self.store_id,self.rule_version,self.producer_id,self.storage,self.usage):
            ident(v)
        if self.state not in {"READY","IN_TRANSIT","ACCEPTED","HOLD","SCRAPPED","RETURNED"}:
            raise ValueError("invalid state")
        a=quantity(self.amount,self.unit)
        r=quantity(self.remaining,self.unit,zero=True)
        if r>a:
            raise ValueError("remaining exceeds original")
        if aware(self.expires_at)<=aware(self.produced_at):
            raise ValueError("invalid expiry")
        object.__setattr__(self,"amount",a)
        object.__setattr__(self,"remaining",r)

def available(p, now):
    return p.state=="ACCEPTED" and p.remaining>0 and aware(p.produced_at)<=aware(now)<aware(p.expires_at)

def receipt_intent(packages, accepted_ids, hold_ids, *, store_id, now):
    """Pure validation under a D transaction lock. No stock mutation."""
    now=aware(now)
    packages=list(packages)
    by_id={p.package_id:p for p in packages}
    if len(by_id)!=len(packages):
        raise ValueError("duplicate package facts")
    accepted=list(accepted_ids); hold=list(hold_ids)
    chosen=accepted+hold
    if not chosen or len(set(chosen))!=len(chosen):
        raise ValueError("empty or duplicate receipt")
    result=[]
    for pid in chosen:
        p=by_id.get(pid)
        if p is None or p.state!="IN_TRANSIT" or p.store_id!=store_id:
            raise ValueError("wrong store, shipment or package state")
        if p.remaining<=0 or now<aware(p.produced_at):
            raise ValueError("no quantity to receive or invalid chronology")
        if pid in accepted and now>=aware(p.expires_at):
            raise ValueError("expired package must be held")
        result.append((pid,"ACCEPTED" if pid in accepted else "HOLD",p.remaining,p.unit))
    return tuple(result)

def cn_time(value):
    t=aware(value).astimezone(CN)
    return f"{t:%Y-%m-%d} 周{WEEK[t.weekday()]} {t:%H:%M:%S}"

def expiry_rows(packages, *, store_id, now):
    now=aware(now); rows=[]; seen=set()
    for p in packages:
        if p.store_id!=store_id:
            raise ValueError("cross-store projection")
        if p.package_id in seen:
            raise ValueError("duplicate package projection")
        seen.add(p.package_id)
        if p.remaining==0 or p.state not in {"ACCEPTED","HOLD"}:
            continue
        state="隔离" if p.state=="HOLD" else ("已过期" if now>=aware(p.expires_at) else "待使用")
        rows.append((state,p))
    return sorted(rows,key=lambda pair:(pair[0]=="待使用",aware(pair[1].expires_at),pair[1].package_id))

def shift_due(packages, *, store_id, now):
    """Stable task keys for caller's upsert; not attendance or disposal facts."""
    local=aware(now).astimezone(CN)
    return tuple((store_id,p.package_id,"EXPIRY_REVIEW",cn_time(p.expires_at))
        for state,p in expiry_rows(packages,store_id=store_id,now=now)
        if state!="待使用" or aware(p.expires_at).astimezone(CN).date()==local.date())

def _table(title, headers, rows, *, demo, revision, as_of):
    ident(revision)
    h=lambda x: escape(str(x),quote=True)
    cells=lambda xs,tag: "".join(f"<{tag}>{h(x)}</{tag}>" for x in xs)
    body="".join("<tr>"+cells(r,"td")+"</tr>" for r in rows)
    banner="演示·非正式凭证" if demo else "数据投影·以系统最新版本为准"
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<style>@page{size:A4;margin:12mm}body{font:12pt sans-serif}table{width:100%;border-collapse:collapse}th,td{border:1px solid #555;padding:4px;overflow-wrap:anywhere}thead{display:table-header-group}tr{break-inside:avoid}h1{font-size:18pt}</style>'
        f"<title>{h(title)}</title><h1>{h(title)}</h1><p>{h(banner)} | 版本 {h(revision)} | {h(cn_time(as_of))}</p>"
        "<table><thead><tr>"+cells(headers,"th")+"</tr></thead><tbody>"+body+"</tbody></table></html>")

def expiry_sheet(packages, *, store_id, as_of, revision, demo=True):
    rows=[(cn_time(p.expires_at),state,p.name,p.batch_id,p.package_id,p.remaining,p.unit,p.storage,p.usage,"")
          for state,p in expiry_rows(packages,store_id=store_id,now=as_of)]
    return _table(f"物料死期清单 · {store_id}",["禁用时刻","状态","物料","批次","包装","剩余","单位","储存","用法","签字"],rows,demo=demo,revision=revision,as_of=as_of)

def arrival_sheet(receipts, *, store_id, as_of, revision, demo=True):
    """Each row is an immutable, committed receipt projection from D.
    Actual receipt quantities are never derived from current remaining stock.
    This renderer does not establish commit authority.
    """
    rows=[]; seen=set(); totals={}
    for r in receipts:
        p=r["package"]
        if p.store_id!=store_id or p.package_id in seen:
            raise ValueError("invalid receipt projection scope")
        seen.add(p.package_id)
        accepted=quantity(r["accepted"],p.unit,zero=True)
        held=quantity(r["held"],p.unit,zero=True)
        if accepted+held<=0 or accepted+held>p.amount or (accepted>0 and held>0):
            raise ValueError("invalid receipt quantity")
        if r["committed"] is not True:
            raise ValueError("receipt not confirmed")
        source=ident(r["source_store_id"]); sender=ident(r["sender_id"]); receiver=ident(r["receiver_id"])
        sent=aware(r["sent_at"]); received=aware(r["received_at"])
        if not aware(p.produced_at)<=sent<=received<=aware(as_of):
            raise ValueError("invalid receipt chronology")
        if accepted>0 and received>=aware(p.expires_at):
            raise ValueError("expired receipt accepted")
        totals[p.unit]=totals.get(p.unit,Decimal(0))+accepted
        rows.append((p.name,p.batch_id,p.package_id,p.amount,p.unit,accepted,held,cn_time(p.produced_at),cn_time(p.expires_at),p.producer_id,source,sender,cn_time(sent),receiver,cn_time(received),p.storage,p.usage,""))
    # Totals are separated by unit; unlike quantities never summed.
    totals_text=" / ".join(f"{v} {u}" for u,v in sorted(totals.items()))
    return _table(f"到货清单 · {store_id} · 合格实收合计 {totals_text}",["物料","批次","包装","装量","单位","合格","隔离","制作","死期","制作人","来源","发货人","发货时间","收货人","收货时间","储存","用法","签字"],rows,demo=demo,revision=revision,as_of=as_of)

def label_preview(p, *, as_of, demo=True):
    """50x40 mm textual preview ONLY; actual approved device/QR adapter separate."""
    if p.state!="READY" or not aware(p.produced_at)<=aware(as_of)<aware(p.expires_at):
        raise ValueError("label release not eligible")
    h=lambda x: escape(str(x),quote=True)
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<style>@page{size:50mm 40mm;margin:2mm}body{font:8pt sans-serif;margin:0}h1{font-size:11pt;margin:0 0 1mm}p{margin:0;overflow-wrap:anywhere}small{font-size:7pt}</style>'
            f"<h1>{h(p.name)} · {h(p.amount)} {h(p.unit)}</h1>"
            f"<p>制作：{h(cn_time(p.produced_at))}</p>"
            f"<p><strong>死期：{h(cn_time(p.expires_at))}</strong></p>"
            f"<p>{h(p.storage)} | {h(p.producer_id)}</p>"
            f"<p>批次：{h(p.batch_id)}</p><p>包装：{h(p.package_id)}</p>"
            "<small>预览·非正式标签；实际二维码、法定字段及打印须设备验收</small></html>")

def shipment_reconciliation(expected_packages, receipts, *, store_id, as_of, revision):
    """Plan/receipt reconciliation, pure demo projection from a single D snapshot.
    Expected package list is immutable dispatch snapshot; rows are receipt facts.
    Missing package remains unresolved, not necessarily physically missing.
    """
    expected=list(expected_packages); actual=list(receipts)
    by_id={p.package_id:p for p in expected}
    if not expected or len(by_id)!=len(expected) or any(p.store_id!=store_id for p in expected):
        raise ValueError("invalid shipment scope or duplicate planned package")
    # Reuse the receipt validation and rendering; reject unconfirmed facts first.
    arrival_sheet(actual,store_id=store_id,as_of=as_of,revision=revision)
    received={r["package"].package_id:r for r in actual}
    if len(received)!=len(actual) or not received.keys()<=by_id.keys():
        raise ValueError("receipt outside shipment")
    rows=[]; totals={}
    for p in expected:
        r=received.get(p.package_id)
        accepted=held=Decimal(0)
        if r:
            q=r["package"]
            if (q.item_id,q.batch_id,q.unit,q.amount)!=(p.item_id,p.batch_id,p.unit,p.amount):
                raise ValueError("receipt disagrees with dispatch snapshot")
            accepted=quantity(r["accepted"],p.unit,zero=True)
            held=quantity(r["held"],p.unit,zero=True)
        unresolved=p.amount-accepted-held
        totals.setdefault(p.unit,[Decimal(0),Decimal(0),Decimal(0),Decimal(0)])
        for i,v in enumerate((p.amount,accepted,held,unresolved)):totals[p.unit][i]+=v
        rows.append((p.name,p.package_id,p.amount,p.unit,accepted,held,unresolved,
                     r.get("exception_reason","") if r else "未确认收货"))
    summary="；".join(f"{u} 计划{v[0]} / 合格{v[1]} / 隔离{v[2]} / 未确认{v[3]}" for u,v in sorted(totals.items()))
    return _table(f"配送差异核对 · {store_id} · {summary}",["物料","包装","计划量","单位","合格","隔离","未确认","差异说明"],rows,demo=True,revision=revision,as_of=as_of)
