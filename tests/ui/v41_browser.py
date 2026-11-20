"""Responsive Chromium checks against the actual isolated V4.1 ingress."""
import os
from pathlib import Path
import shutil

from playwright.sync_api import expect, sync_playwright


WIDTHS = (320, 375, 390, 430, 768, 1024, 1280, 1440)
PANES = ("工作台", "待办", "业务", "权限", "状态")


def assert_dock(page):
    page.wait_for_function("""() => {
      const d = document.querySelector('.workbench-nav').getBoundingClientRect();
      const v = visualViewport;
      return Math.abs(d.left - v.offsetLeft) < 3 &&
        Math.abs(d.right - (v.offsetLeft + v.width)) < 3 &&
        Math.abs(d.bottom - (v.offsetTop + v.height)) < 3;
    }""")


def check_modal(page, base_url, device_id, device_token):
    page.goto(base_url + "/pos")
    expect(page.locator(".stage-pos-note")).to_contain_text("门店、班次和设备")
    district = page.locator("#loginDistrict")
    expect(district.locator("option").nth(1)).to_be_attached()
    for value in district.locator("option").evaluate_all("(items) => items.map(x => x.value).filter(Boolean)"):
        district.select_option(value)
        if page.locator("#loginStore option[value='BSVT']").count():
            break
    page.locator("#loginStore").select_option("BSVT")
    expect(page.locator("#legacy-code-label")).to_be_hidden()
    page.locator("#device-id").fill(device_id or "BROWSER-DEVICE-SYNTH")
    page.locator("#device-token").fill(device_token or "SYNTHETIC-LAYOUT-CHECK-NOT-A-CREDENTIAL")
    launcher = page.locator("#loginForm button[type=submit]")
    launcher.click()
    modal = page.get_by_role("dialog", name="你确认正在这家店工作吗？")
    confirm = modal.get_by_role("button", name="确认门店并登录")
    expect(confirm).to_be_visible()
    expect(confirm).to_be_focused()
    assert page.locator("#loginPage").evaluate("(el) => el.inert")
    assert page.evaluate("""() => {
      const d = document.querySelector('#modal .modal-card').getBoundingClientRect();
      const v = visualViewport;
      return d.x >= v.offsetLeft && d.right <= v.offsetLeft + v.width + 2 &&
             d.y >= v.offsetTop && d.bottom <= v.offsetTop + v.height + 2;
    }""")
    page.keyboard.press("Tab")
    expect(modal.get_by_role("button", name="返回修改")).to_be_focused()
    page.keyboard.press("Escape")
    expect(modal).to_be_hidden()
    expect(launcher).to_be_focused()
    return launcher


def check(base_url, *, username, password, expected_tr=None, device_id=None, device_token=None):
    base_url = base_url.rstrip("/")
    artifact_dir = os.environ.get("BSV_V41_UI_ARTIFACTS") or os.environ.get("BSV_STAGE_UI_ARTIFACTS")
    artifact_dir = Path(artifact_dir) if artifact_dir else None
    if artifact_dir:
        artifact_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        optional = {}
        chromium = shutil.which("chromium")
        if chromium and not Path(playwright.chromium.executable_path).is_file():
            optional["executable_path"] = chromium
        browser = playwright.chromium.launch(**optional)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page.goto(base_url + "/staff")
            page.locator("#login-user").fill(username)
            page.locator("#login-pass").fill(password)
            page.locator("#login-form button").click()
            expect(page.locator("#member-area")).to_be_visible()
            if expected_tr:
                expect(page.locator("#tr-view")).to_have_text(expected_tr)
            for width in WIDTHS:
                page.set_viewport_size({"width": width, "height": 820})
                page.goto(base_url + "/")
                nav = page.get_by_role("navigation", name="工作台导航")
                for position, caption in enumerate(PANES):
                    expect(nav.get_by_role("link").nth(position)).to_have_accessible_name(caption)
                nav.get_by_role("link", name="权限").click()
                expect(page.get_by_role("heading", name="我的权限")).to_be_visible()
                expect(page.locator("#access-list")).not_to_have_text("正在核对…")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), width
                nav.get_by_role("link", name="业务").click()
                expect(page.get_by_role("heading", name="业务入口")).to_be_visible()
                assert nav.evaluate("(el) => getComputedStyle(el).position") == ("fixed" if width < 768 else "sticky")
                if width < 768:
                    page.evaluate("window.scrollTo(0,document.documentElement.scrollHeight)")
                    assert_dock(page)
                    assert page.locator(".workbench-tools .work-card:last-child").evaluate("""node =>
                      node.getBoundingClientRect().bottom <
                      document.querySelector('.workbench-nav').getBoundingClientRect().top
                    """), width
                if artifact_dir and width in (375, 1440):
                    nav.get_by_role("link", name="工作台").click()
                    page.screenshot(path=artifact_dir / f"v41-workbench-{width}.png")

            page.set_viewport_size({"width": 390, "height": 820})
            page.goto(base_url + "/#business")
            cdp = page.context.new_cdp_session(page)
            cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 2})
            page.wait_for_function("visualViewport.scale === 2")
            assert_dock(page)
            cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})
            page.evaluate("document.documentElement.style.fontSize='200%'")
            assert_dock(page)
            page.set_viewport_size({"width": 390, "height": 380})
            assert_dock(page)
            page.set_viewport_size({"width": 820, "height": 390})
            expect(page.get_by_role("navigation", name="工作台导航")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")

            page.goto(base_url + "/cocktail/")
            expect(page.get_by_role("link", name="返回工作台", exact=True)).to_be_visible()
            page.get_by_role("link", name="返回工作台", exact=True).click()
            expect(page.get_by_role("heading", name="BSV 工作台")).to_be_visible()
            page.goto(base_url + "/cocktail/?from=pos")
            page.get_by_role("link", name="返回点单台", exact=True).click()
            expect(page.locator("#loginForm")).to_be_visible()

            for width in (360, 375, 430, 768):
                page.set_viewport_size({"width": width, "height": 390 if width == 360 else 820})
                launcher = check_modal(page, base_url, device_id, device_token)
                if width == 375 and artifact_dir:
                    launcher.click()
                    page.screenshot(path=artifact_dir / "v41-pos-confirmation.png")
                    page.keyboard.press("Escape")
            if device_id and device_token:
                launcher.click()
                page.get_by_role("dialog").get_by_role("button", name="确认门店并登录").click()
                expect(page.locator("#appPage")).to_be_visible()

            page.goto(base_url + "/academy")
            expect(page.get_by_role("heading", name="我的培训与排班")).to_be_visible()
            expect(page.locator("#academy-status")).to_have_text("已核对本人培训、资格和班次。")
            assert "返回工作台" not in (Path(__file__).resolve().parents[2] /
                       "apps/guest-web/bsv1/site/cocktail/index.html").read_text()
        finally:
            browser.close()
    print("PASS_ISOLATED V4.1 UI: workbench, Academy, menu return, responsive safe modal")
