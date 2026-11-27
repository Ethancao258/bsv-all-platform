"""Run against a fresh loopback BSV_MODE=demo supply instance."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import shutil
import sys
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def run(url):
    assert urlsplit(url).hostname == "127.0.0.1"
    beijing = timezone(timedelta(hours=8))
    eta = (datetime.now(beijing) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

    with sync_playwright() as pw:
        executable = os.environ.get("BSV_TEST_CHROMIUM")
        if not executable and not Path(pw.chromium.executable_path).is_file():
            executable = shutil.which("chromium")
        options = {"executable_path": executable} if executable else {}
        browser = pw.chromium.launch(**options)
        hq = browser.new_page()
        errors = []
        hq.on("pageerror", lambda error: errors.append(str(error)))
        health = hq.request.get(url + "/api/health").json()
        assert health["mode"] == "demo" and health["central_candidate"] is True
        hq.goto(url + "/hq/supply")
        hq.locator('[data-tab="central"]').click()
        hq.locator("#central-store").select_option("BSVS")

        plan = hq.locator("#central-plan-form")
        plan.locator('[name="next_delivery_at"]').fill(eta)
        plan.locator('[name="demand_next_cycle"]').fill("800")
        plan.get_by_role("button", name="计算建议").click()
        expect(hq.locator("#central-plan-result")).to_contain_text("建议包装数")
        plan.get_by_role("button", name="确认计划").click()
        expect(hq.locator("#feedback")).to_contain_text("已确认制作计划")
        batch = hq.locator("#central-batch-form")
        expect(batch.locator('[name="recipe_version"]')).to_have_value("DEMO-RECIPE-1")
        batch.locator('[name="total"]').fill("800")
        batch.locator('[name="ingredient_lot_ids"]').fill("DEMO-LOT-1")
        batch.locator('[name="package_amounts"]').fill("450\n350")
        batch.get_by_role("button", name="确认制作和放行").click()
        expect(hq.locator("#feedback")).to_contain_text("已放行批次")

        hq.locator("#central-view").select_option("labels")
        expect(hq.locator("#central-store")).to_have_value("DEMO-WH")
        labels = hq.locator("#central-label-form")
        boxes = labels.get_by_role("checkbox")
        expect(boxes).to_have_count(2)
        ids = [box.get_attribute("value") for box in boxes.all()]
        for box in boxes.all():
            box.check()
        labels.get_by_role("button", name="准备打印", exact=True).click()
        dialog = hq.locator("#central-print-dialog")
        expect(dialog).to_be_visible()
        frame = hq.frame_locator("#central-print-frame")
        expect(frame.locator("body")).to_contain_text(ids[0])
        expect(frame.locator("img")).to_have_count(2)
        # Confirm the UI creates a print request. Physical spool/driver acceptance is separate.
        frame.locator("body").evaluate("() => { window.print = () => {}; }")
        dialog.get_by_role("button", name="打印", exact=True).click()
        expect(labels.locator('[name="print_request_id"]')).not_to_have_value("")
        dialog.get_by_role("button", name="关闭").click()
        hq.on("dialog", lambda confirm: confirm.accept())
        labels.get_by_role("button", name="确认实物已印").click()
        expect(hq.locator("#central-label-history-list")).to_contain_text("已确认实物")

        hq.locator("#central-view").select_option("shipment")
        hq.locator("#central-store").select_option("BSVS")
        create = hq.locator("#central-shipment-create")
        create.locator('[name="eta"]').fill(eta)
        create.locator('[name="package_ids"]').fill("\n".join(ids))
        create.get_by_role("button", name="创建配送草稿").click()
        expect(hq.locator("#feedback")).to_contain_text("已创建配送单")
        detail = hq.locator("#central-shipment-action")
        detail.get_by_role("button", name="确认备货").click()
        expect(hq.locator("#feedback")).to_contain_text("备货已提交")
        detail.locator('[name="scanned_codes"]').fill("\n".join(ids))
        detail.get_by_role("button", name="确认发货").click()
        expect(hq.locator("#feedback")).to_contain_text("发货已提交")
        shipment_id = hq.locator('#central-shipment-lookup [name="shipment_id"]').input_value()

        store = browser.new_page(viewport={"width": 390, "height": 844})
        store.on("pageerror", lambda error: errors.append(str(error)))
        store.goto(url + "/store/supply")
        store.locator('[data-tab="central"]').click()
        assert store.evaluate("document.documentElement.scrollWidth === innerWidth")
        lookup = store.locator("#central-shipment-lookup")
        lookup.locator('[name="shipment_id"]').fill(shipment_id)
        lookup.get_by_role("button", name="打开配送单").click()
        receive = store.locator("#central-shipment-action")
        receive.locator('[name="receipt_scan"]').fill(ids[0])
        receive.locator('[name="receipt_scan"]').press("Enter")
        receive.get_by_role("button", name="确认本次签收").click()
        expect(store.locator("#feedback")).to_contain_text("本次实收已提交")
        expect(receive).to_contain_text("部分签收")
        receive.get_by_role("combobox", name="签收结果 " + ids[1]).select_option("HOLD")
        receive.get_by_role("textbox", name="异常原因 " + ids[1]).fill("合成验收：包装异常")
        receive.get_by_role("button", name="确认本次签收").click()
        expect(receive).to_contain_text("已签收")
        receive.get_by_role("button", name="打印 A4 到货清单").click()
        expect(store.frame_locator("#central-print-frame").locator("body")).to_contain_text(ids[1])
        store.locator("#central-print-dialog").get_by_role("button", name="关闭").click()

        store.locator("#central-view").select_option("inventory")
        store.get_by_role("button", name="打印 A4 效期与处置清单").click()
        expect(store.frame_locator("#central-print-frame").locator("body")).to_contain_text(ids[0])
        store.locator("#central-print-dialog").get_by_role("button", name="关闭").click()
        first_row=store.locator("#central-content tr").filter(has_text=ids[0])
        first_row.get_by_role("button",name="登记开封").click()
        store.locator("#central-stock-form").get_by_role("button",name="确认登记实际开封").click()
        expect(store.locator("#feedback")).to_contain_text("已记录开封时间")
        first_row.get_by_role("button",name="登记实际耗用").click()
        store.locator("#central-stock-form [name=amount]").fill("120")
        store.locator("#central-stock-form").get_by_role("button",name="确认登记实际耗用").click()
        expect(store.locator("#feedback")).to_contain_text("已登记实际耗用")
        expect(first_row).to_contain_text("330 / 450")
        store.locator("#central-view").select_option("tasks")
        expect(store.locator("#central-task-list")).to_contain_text("物料使用说明")
        store.locator("#central-phase").select_option("END")
        expect(store.locator("#central-task-list")).to_contain_text("交给下一班")

        inspector = browser.new_page()
        inspector.on("pageerror", lambda error: errors.append(str(error)))
        inspector.goto(url + "/inspector/supply")
        inspector.locator('[data-tab="central"]').click()
        expect(inspector.locator("#central-view")).to_have_value("exceptions")
        expect(inspector.locator("#central-content")).to_contain_text("隔离")
        assert not errors, errors
        browser.close()
    print("PASS: SUP-59 desktop/mobile, plan, batch, label preview/history, shipment, partial receipt, A4, shift and inspection.")


if __name__ == "__main__":
    run(sys.argv[1].rstrip("/"))
