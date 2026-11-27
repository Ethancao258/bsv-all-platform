"""Printable SUP-59 projections from authorized, consistent D snapshots."""

from base64 import b64encode
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from html import escape
from itertools import groupby
import re
from unicodedata import east_asian_width

from .central_production_rules import (
    CN, aware, cn_time, expiry_rows, ident, quantity,
)

A4_CSS = """
@page { size: A4 portrait; margin: 12mm; }
body { color: #000; background: #fff; margin: 0; font: 10pt/1.35 sans-serif; }
h1 { font-size: 17pt; margin: 0 0 3mm; }
h2 { font-size: 12pt; margin: 3mm 0 1mm; break-after: avoid; }
p { margin: 2mm 0; overflow-wrap: anywhere; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; margin-bottom: 2mm; }
th, td { border: .25mm solid #000; text-align: left; padding: 1.15mm;
         vertical-align: top; overflow-wrap: anywhere; }
th { font-weight: bold; }
thead { display: table-header-group; }
tbody tr { break-inside: avoid; }
.signatures { break-inside: avoid; margin-top: 5mm; }
@media screen { body { max-width: 186mm; margin: 12px auto; padding: 0 12px; } }
"""

LABEL_CSS = """
@page { size: 50mm 40mm; margin: 0; }
html, body { margin: 0; color: #000; background: #fff; }
.label { box-sizing: border-box; width: 50mm; height: 40mm; padding: 1.5mm;
         overflow: hidden; break-inside: avoid; font: 7pt/1.15 sans-serif; }
.label + .label { break-before: page; }
h1 { margin: 0 0 .8mm; font-size: 8pt; font-weight: bold; overflow-wrap: anywhere; }
p { margin: 0 0 .65mm; overflow-wrap: anywhere; }
.bottom { display: grid; grid-template-columns: 1fr 17mm; gap: 1mm; align-items: start; }
.bottom img { display: block; width: 17mm; height: 17mm; image-rendering: pixelated; }
.demo { font-weight: bold; }
@media screen { .label { border: .2mm dashed #555; margin: 3mm; } }
"""

# Compact IDs keep a reliable module size on 203 dpi printers and match the
# existing scanner payload: the package ID, with no URL or personal data.
QR_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")


def h(value):
    return escape(str(value), quote=True)


def document(title, css, body):
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f'<title>{h(title)}</title><style>{css}</style></head><body>{body}</body></html>'
    )


def qr_data_uri(package_id):
    import cv2
    import numpy as np

    if not QR_ID.fullmatch(package_id):
        raise ValueError("unsupported package ID for 50×40 label")
    matrix = cv2.QRCodeEncoder_create().encode(package_id)
    # OpenCV already adds a border. At least four white modules remain even
    # if another supported OpenCV build returns the bare QR matrix.
    image = np.pad(matrix, 4, constant_values=255).repeat(8, axis=0).repeat(8, axis=1)
    ok, png = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("label QR encoding failed")
    return "data:image/png;base64," + b64encode(png.tobytes()).decode("ascii")


def label_text(value, width):
    text = str(value)
    if any(c in text for c in "\r\n\t") or sum(
        2 if east_asian_width(c) in {"F", "W"} else 1 for c in text
    ) > width:
        raise ValueError("label field exceeds 50×40 layout")
    return h(text)


def local_time(value):
    return f"{aware(value).astimezone(CN):%Y-%m-%d %H:%M:%S}"


def render_labels(packages, *, as_of, demo=True):
    now = aware(as_of)
    labels = []
    seen = set()
    for p in packages:
        if p.package_id in seen or len(seen) >= 100:
            raise ValueError("duplicate package or label batch exceeds 100")
        seen.add(p.package_id)
        if p.state not in {"READY", "IN_TRANSIT", "ACCEPTED"} or not (
            aware(p.produced_at) <= now < aware(p.expires_at)
        ):
            raise ValueError("package is ineligible for printing")
        if p.remaining <= 0:
            raise ValueError("package has no remaining quantity")
        qr = qr_data_uri(p.package_id)
        name = label_text(p.name, 30)
        producer = label_text(p.producer_id, 48)
        storage = label_text(p.storage, 48)
        batch = label_text(p.batch_id, 48)
        amount = label_text(f"{p.amount:f} {p.unit}", 24)
        demo_mark = '<p class="demo">演示标签</p>' if demo else ''
        labels.append(
            f'<section class="label">{demo_mark}<h1>{name} · {amount}</h1>'
            f'<p>制作 北京时间 {local_time(p.produced_at)}</p>'
            f'<p><strong>死期 {local_time(p.expires_at)}</strong></p>'
            '<div class="bottom"><div>'
            f'<p>储存 {storage}</p><p>制作人 {producer}</p><p>批次 {batch}</p>'
            f'</div><img alt="包装追溯二维码" src="{qr}"></div>'
            f'<p>包装 {h(p.package_id)}</p></section>'
        )
    if not labels:
        raise ValueError("no labels requested")
    return document("中央供货 50×40 mm 标签", LABEL_CSS, "".join(labels))


def header(title, *, as_of, revision, demo):
    if type(revision) is int and revision >= 0:
        revision = str(revision)
    ident(revision)
    warning = "演示 · 非正式凭证" if demo else "纸质清单以系统当前版本为准"
    return (
        f"<h1>{h(title)}</h1><p>{warning} · 版本 {h(revision)} · "
        f"生成 {h(cn_time(as_of))}（北京时间）</p>"
    )


def table(headers, rows):
    headings = "".join(f'<th scope="col">{h(c)}</th>' for c in headers)
    contents = "".join(
        "<tr>" + "".join(f"<td>{h(c)}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{headings}</tr></thead><tbody>{contents}</tbody></table>"


def shipment_rows(expected, receipts, *, store_id, as_of):
    dispatch = {p.package_id: p for p in expected}
    if not dispatch or len(dispatch) != len(expected) or any(
        p.store_id != store_id for p in expected
    ):
        raise ValueError("invalid dispatch scope or duplicate package")
    actual = {}
    for r in receipts:
        p = r["package"]
        original = dispatch.get(p.package_id)
        if original is None or p.package_id in actual or p.store_id != store_id:
            raise ValueError("receipt outside shipment or duplicate package")
        fields = ("item_id", "batch_id", "unit", "amount", "produced_at", "rule_version")
        if any(getattr(p, f) != getattr(original, f) for f in fields):
            raise ValueError("receipt disagrees with dispatch snapshot")
        if r["committed"] is not True:
            raise ValueError("receipt not committed")
        accepted = quantity(r["accepted"], p.unit, zero=True)
        held = quantity(r["held"], p.unit, zero=True)
        if (accepted > 0 and held > 0) or not 0 < accepted + held <= p.amount:
            raise ValueError("invalid receipt quantity")
        sent, received = aware(r["sent_at"]), aware(r["received_at"])
        if not aware(p.produced_at) <= sent <= received <= aware(as_of):
            raise ValueError("invalid receipt chronology")
        expires_at = min(aware(p.expires_at), aware(original.expires_at))
        if accepted and received >= expires_at:
            raise ValueError("expired receipt accepted")
        actor = f'{ident(r["receiver_id"])} · {cn_time(received)}'
        actual[p.package_id] = (
            accepted, held, actor, str(r.get("exception_reason") or ""),
            expires_at,
        )
    return actual


def render_arrival(expected, receipts, *, store_id, reference, as_of, revision,
                   demo=True, dispatch=None):
    expected = tuple(expected)
    receipts = tuple(receipts)
    results = shipment_rows(expected, receipts, store_id=store_id, as_of=as_of)
    totals = defaultdict(lambda: [0, 0, 0, 0])
    counts = [0, 0, 0]
    rows = []
    for p in expected:
        accepted, held, signature, exception, expires_at = results.get(
            p.package_id, (Decimal(0), Decimal(0), "", "未确认", p.expires_at)
        )
        pending = p.amount - accepted - held
        counts[0] += int(bool(accepted))
        counts[1] += int(bool(held))
        counts[2] += int(p.package_id not in results)
        for i, value in enumerate((p.amount, accepted, held, pending)):
            totals[p.unit][i] += value
        rows.append((
            f"{p.name} · 批次 {p.batch_id} · 包装 {p.package_id}",
            f"原装 {p.amount:f}；合格 {accepted:f}；隔离 {held:f}；待核 {pending:f} {p.unit}",
            f"制作 {cn_time(p.produced_at)}；死期 {cn_time(expires_at)}",
            f"{p.storage}；{p.usage}",
            " · ".join(filter(None, (signature, exception))),
        ))
    title = f"门店到货清单 · {store_id}"
    body = header(title, as_of=as_of, revision=revision, demo=demo)
    body += f"<p>配送单 {h(ident(reference))}</p>"
    if dispatch is None and receipts:
        dispatch = receipts[0]
    if dispatch:
        fields = (
            ("来源", "source_store_id"), ("发货人", "sender_id"),
            ("发货时间", "sent_at"), ("预计到达", "eta_at"),
            ("实际到达", "arrived_at"),
        )
        values = []
        for label, key in fields:
            val = dispatch.get(key)
            if val is not None:
                values.append(f"{label} {cn_time(val) if isinstance(val, datetime) else val}")
        if values:
            body += f'<p>{h(" · ".join(values))}</p>'
    body += (
        f"<p>计划 {len(expected)} 件 · 合格 {counts[0]} 件 · 隔离 {counts[1]} 件 · "
        f"未确认 {counts[2]} 件</p>"
    )
    for unit, (volume, accepted, held, pending) in sorted(totals.items()):
        body += (
            f"<p>{h(unit)} · 计划 {volume:f} · 合格 {accepted:f} · "
            f"隔离 {held:f} · 待核 {pending:f}</p>"
        )
    body += table(("物料与追溯", "装量与差异", "制作与死期", "储存与使用", "实收人员与异常"), rows)
    body += '<p class="signatures">发货人签字 __________________　收货人签字 __________________</p>'
    return document(title, A4_CSS, body)


def render_expiry(packages, *, store_id, as_of, revision, demo=True):
    title = f"门店物料死期及处置清单 · {store_id}"
    body = header(title, as_of=as_of, revision=revision, demo=demo)
    displayed = expiry_rows(packages, store_id=store_id, now=as_of)
    body += "<p>包含仍有余额的历史与本次入库。过期或隔离物料不可使用。</p>"
    if not displayed:
        body += "<p>当前无待检查物料。</p>"
    groups = groupby(displayed, key=lambda row: (
        row[0] == "待使用", aware(row[1].expires_at).astimezone(CN).date()
    ))
    for (usable, due_date), group in groups:
        body += f'<h2>{"" if usable else "已过期或隔离 · "}{due_date.isoformat()}</h2>'
        rows = [(
            cn_time(p.expires_at), state,
            f"{p.name} · 批次 {p.batch_id} · 包装 {p.package_id}",
            f"{p.remaining:f} {p.unit}", f"{p.storage}；{p.usage}",
            "时间：________　数量：________　人员：________",
        ) for state, p in group]
        body += table(("死期", "状态", "物料与追溯", "剩余", "储存与使用", "处置与确认"), rows)
    return document(title, A4_CSS, body)
