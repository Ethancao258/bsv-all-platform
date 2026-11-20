"""Playwright assertions against the real, private PG17 socket test stack."""
import os
from pathlib import Path
import re
import shutil

from playwright.sync_api import expect, sync_playwright


def login(page, base_url, username, password):
    page.goto(base_url + "/staff")
    page.locator("#login-user").fill(username)
    page.locator("#login-pass").fill(password)
    page.locator("#login-form button").click()
    expect(page.locator("#member-area")).to_be_visible()


def check(base_url, *, username, password, expected_tr):
    base_url = base_url.rstrip("/")
    output = os.environ.get("BSV_STAGE_UI_ARTIFACTS")
    screenshots = Path(output) if output else None
    if screenshots:
        screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        system_chromium = shutil.which("chromium")
        bundled = playwright.chromium.executable_path
        options = {"executable_path": system_chromium} if system_chromium and not Path(bundled).is_file() else {}
        browser = playwright.chromium.launch(**options)
        try:
            mobile = browser.new_page(viewport={"width": 375, "height": 812})
            mobile.goto(base_url + "/")
            expect(mobile.get_by_role("heading", name="BSV 工作台")).to_be_visible()
            expect(mobile.locator("#session-summary")).to_have_text("尚未登录")
            expect(mobile.locator("#supply-status")).to_have_text("暂未启用")
            assert mobile.evaluate("document.documentElement.scrollWidth === innerWidth")
            if screenshots:
                mobile.screenshot(path=screenshots / "workbench-mobile.png", full_page=True)

            desktop = browser.new_page(viewport={"width": 1440, "height": 960})
            login(desktop, base_url, username, password)
            expect(desktop.locator("#tr-view")).to_have_text(expected_tr)
            expect(desktop.locator("#stage-view")).to_contain_text("员工身份：已生效")
            expect(desktop.locator("#stage-view")).to_contain_text("管理身份：已生效")
            desktop.goto(base_url + "/")
            expect(desktop.locator("#pos-status")).to_have_text("可进行门店核验")
            expect(desktop.locator("#store-summary")).to_contain_text("BSVT")
            expect(desktop.locator("#hq-status")).to_have_text("暂未授权")
            expect(desktop.locator("#inspection-status")).to_have_text("仅查看")
            assert desktop.evaluate("document.documentElement.scrollWidth === innerWidth")
            if screenshots:
                desktop.screenshot(path=screenshots / "workbench-desktop.png", full_page=True)

            desktop.get_by_role("navigation", name="工作台导航").get_by_role("link", name="业务").click()
            desktop.get_by_role("link", name="核对督查范围").click()
            expect(desktop.get_by_role("heading", name="独立督查")).to_be_visible()
            expect(desktop.locator("#stage-availability")).to_contain_text("暂不能提交或复核")
            expect(desktop.locator("#stage-authorization")).to_contain_text("独立督查 · BSVT")
            expect(desktop.get_by_role("button", name="提交快检记录")).to_have_count(0)

            desktop.goto(base_url + "/pos")
            expect(desktop.locator(".stage-pos-note")).to_contain_text("先在")
            desktop.locator("#loginDistrict").select_option(index=1)
            selected = desktop.locator("#loginStore option[value='BSVT']")
            if not selected.count():
                for district in desktop.locator("#loginDistrict option").evaluate_all(
                        "(options) => options.map(option => option.value).filter(Boolean)"):
                    desktop.locator("#loginDistrict").select_option(district)
                    if selected.count():
                        break
            desktop.locator("#loginStore").select_option("BSVT")
            desktop.locator("#staffCode").fill("STAGEPOS01")
            desktop.locator("#staffPin").fill("81351593300")
            desktop.locator("#loginForm button").click()
            desktop.locator("#modalConfirm").click()
            expect(desktop.locator("#appPage")).to_be_visible()
            # Use the already opened disposable test desk. Unlike the old UI,
            # this route does not call a seat-claim endpoint unavailable here.
            desktop.locator('.seat-button[data-seat="BSVT-SEAT-0001"]').click()
            desktop.locator("#modalConfirm").click()
            expect(desktop.locator("#quickProductSearch")).to_be_visible()
            desktop.locator("#quickProductSearch").fill("C000001")
            desktop.locator('[data-quick-id="C000001"]').click()
            expect(desktop.locator("#submitOrder")).to_be_enabled()
            desktop.locator("#submitOrder").click()
            expect(desktop.locator("#modalTitle")).to_have_text("提交未付款测试订单")
            expect(desktop.locator("#modeOrderPay")).to_have_count(0)
            desktop.locator("#modalConfirm").click()
            expect(desktop.locator("#toast")).to_contain_text("已记录测试订单，尚未收款。")

            admin = browser.new_page(viewport={"width": 1440, "height": 960})
            login(admin, base_url, "reviewer1", os.environ["BSV_DEMO_ADMIN_1_PASSWORD"])
            admin.goto(base_url + "/hq#audit")
            admin.locator("#people-form-query").fill("TRA0002")
            admin.locator("#people-form button").click()
            expect(admin.locator("#people-result")).to_contain_text("TRA0002")
            admin.get_by_role("link", name="旧码预检").click()
            admin.locator("#legacy-form-rows").fill("bsv1_pos,SYNTH-STAGE-POS-01," + expected_tr)
            admin.locator("#legacy-form button").click()
            expect(admin.locator("#legacy-result")).to_contain_text("无需重复提交")
            expect(admin.locator("#legacy-result details")).to_have_count(1)
            expect(admin.locator("#legacy-result details .mono")).not_to_be_visible()
            if screenshots:
                admin.screenshot(path=screenshots / "hq-legacy-desktop.png", full_page=True)

            # Deliberately interrupt a browser write to validate the presentation
            # of an uncertain result. Actual write authorization is covered by HTTP.
            admin.get_by_role("link", name="岗位与门店授权").click()
            admin.locator("#grant-form-tr").fill(expected_tr)
            admin.locator("#grant-form-store").fill("BSVT")
            admin.locator("#grant-form-start").fill("2026-11-20T08:00")
            admin.locator("#grant-form-reason").fill("演练验证提交结果未确认的提示")
            admin.route("**/api/v1/identity/grants", lambda route: route.abort())
            admin.locator("#grant-form button").click()
            feedback = admin.locator("#grant-form-feedback")
            expect(feedback).to_have_attribute("data-state", "unknown")
            expect(feedback).to_contain_text("结果暂未确认")
            assert not re.search("NETWORK_ERROR|HTTP_503", feedback.inner_text())
            expect(admin.locator("#grant-form-reason")).to_have_value("演练验证提交结果未确认的提示")
        finally:
            browser.close()
    print("PASS_ISOLATED UI: anonymous mobile, four role entries, staff, POS, HQ lookup/alias, write uncertainty")
