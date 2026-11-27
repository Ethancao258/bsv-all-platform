"""Smoke tests for paper rendering and the real local QR decoder."""

from base64 import b64decode
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
from unittest import TestCase

import cv2
import numpy as np

from services.api.supply.central_production_rules import PackageFact
from services.api.supply.central_print import render_arrival, render_expiry, render_labels

NOW = datetime(2026, 11, 27, 12, 30, tzinfo=timezone.utc)


def package(package_id, *, expires_at=NOW + timedelta(hours=1), **kwargs):
    values = dict(
        batch_id="batch-demo",
        item_id="item-demo",
        name="合成样品",
        store_id="TEST-STORE",
        amount=Decimal("450"),
        remaining=Decimal("450"),
        unit="mL",
        produced_at=NOW - timedelta(days=1),
        expires_at=expires_at,
        rule_version="recipe-demo-v1",
        producer_id="maker-demo",
        storage="合成储存规则",
        usage="合成示例用法",
        state="ACCEPTED",
    )
    return PackageFact(package_id=package_id, **(values | kwargs))


class Images(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.sources = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        if tag == "img":
            self.sources.append(dict(attributes)["src"])


class PrintTests(TestCase):
    def test_batch_labels_encode_scannable_existing_package_ids(self):
        packages = [
            package("pack-demo-001", amount=Decimal("450")),
            package("a9ff05fc-09a9-46a8-915e-8d1913ab9cc0", amount=Decimal("350"),
                    remaining=Decimal("350")),
        ]
        output = render_labels(packages, as_of=NOW)
        self.assertIn("size: 50mm 40mm", output)
        self.assertIn("break-before: page", output)
        self.assertIn("450 mL", output)
        self.assertIn("350 mL", output)
        self.assertEqual(output.count("2026-11-27 21:30:00"), 2)
        images = Images(output).sources
        self.assertEqual(len(images), len(packages))
        detector = cv2.QRCodeDetector()
        for p, source in zip(packages, images, strict=True):
            payload = b64decode(source.removeprefix("data:image/png;base64,"))
            image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            decoded, _, _ = detector.detectAndDecode(image)
            self.assertEqual(decoded, p.package_id)
            # 17 mm QR at a synthetic 203 dpi device resolution. This checks
            # raster sampling only; physical paper and print optics vary.
            thermal = cv2.resize(image, (136, 136), interpolation=cv2.INTER_NEAREST)
            self.assertEqual(detector.detectAndDecode(thermal)[0], p.package_id)
        self.assertEqual(output, render_labels(packages, as_of=NOW + timedelta(minutes=5)))
        with self.assertRaises(ValueError):
            render_labels(packages, as_of=packages[0].expires_at)
        with self.assertRaises(ValueError):
            render_labels([replace(packages[0], state="HOLD")], as_of=NOW)

    def test_arrival_contains_partial_receipts_and_escapes_notes(self):
        a = package("pack-demo-1")
        b = package("pack-demo-2", amount=Decimal("350"), remaining=Decimal("350"))
        receipt = {
            "package": a,
            "accepted": "450",
            "held": "0",
            "committed": True,
            "source_store_id": "CENTRAL-DEMO",
            "sender_id": "sender-demo",
            "receiver_id": "receiver-demo",
            "sent_at": NOW - timedelta(hours=2),
            "received_at": NOW - timedelta(hours=1),
            "exception_reason": '<script>alert("demo")</script>',
        }
        kwargs = dict(store_id=a.store_id, as_of=NOW, revision="rev-demo", reference="ship-demo")
        result = render_arrival([a, b], [receipt], **kwargs)
        for part in ("A4 portrait", "计划 800", "合格 450", "待核 350", "未确认 1 件",
                     "pack-demo-2", "合格 0", "sender-demo", "receiver-demo",
                     "&lt;script&gt;", "收货人签字"):
            self.assertIn(part, result)
        self.assertNotIn("<script>", result)
        with self.assertRaises(ValueError):
            render_arrival([a, b], [receipt | {"committed": False}], **kwargs)
        with self.assertRaises(ValueError):
            render_arrival([a, b], [receipt | {"package": replace(a, store_id="ANOTHER")}], **kwargs)

    def test_expiry_lists_held_and_historical_stock_first(self):
        old = package("old-package", expires_at=NOW, remaining=Decimal("100"))
        held = package("held-package", state="HOLD")
        new = package("new-package", expires_at=NOW + timedelta(days=1))
        consumed = package("consumed-package", remaining=Decimal("0"))
        result = render_expiry([new, held, old, consumed], store_id=old.store_id,
                               as_of=NOW, revision="inventory-v2")
        self.assertLess(result.index(old.package_id), result.index(new.package_id))
        self.assertLess(result.index(held.package_id), result.index(new.package_id))
        self.assertNotIn(consumed.package_id, result)
        for part in ("已过期", "隔离", "100 mL", "周", "inventory-v2", "处置与确认"):
            self.assertIn(part, result)
        with self.assertRaises(ValueError):
            render_expiry([old, replace(new, store_id="ANOTHER")], store_id=old.store_id,
                          as_of=NOW, revision="inventory-v2")
