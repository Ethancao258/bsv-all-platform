"""Serve the integrated build and optionally compare the attached V13 baseline."""
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import tempfile
import threading
from zipfile import ZipFile

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "apps/guest-web/bsv1/site"


@contextmanager
def serve(path):
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=path)) as server:
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            worker.join()


def capture(browser, base, current):
    page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1,
                            locale="zh-CN", reduced_motion="reduce", color_scheme="dark")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base + ("/?store=BSVS#preview" if current else "/cocktail/?store=BSVS#preview"))
    page.wait_for_url("**/cocktail/?store=BSVS#preview")
    page.locator("[data-product]").first.wait_for()
    page.evaluate("""async () => {
        await document.fonts.ready;
        await Promise.all([...document.images].map(image => image.decode().catch(() => {})));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }""")
    assert page.locator("[data-product]").count() == 84
    assert page.locator("#store").input_value() == "BSVS"
    assert page.locator("#store option").evaluate_all("(nodes)=>nodes.map(n=>n.value)") == ["", "BSVM", "BSVS", "BSVT"]
    assert not errors, errors
    image = page.screenshot(animations="disabled")
    flavor = page.evaluate("""() => Object.fromEntries(state.data.items.map(p => [p.product_id, flavorCopy(p)]))""")
    if current:
        assert page.evaluate("Object.keys(guestFlavorEdits).length") == 15
        assert page.evaluate("Object.keys(guestFlavorEdits).every(id => state.data.items.some(p => p.product_id === id))")
        page.locator("[data-product]").first.click()
        page.locator('#modalHost [data-action="add"]').click()
        selection = page.evaluate("BSVMenuBridge.getSelection()")
        assert selection["store_id"] == "BSVS" and not selection["submitted"]
        assert set(selection["lines"][0]) == {"product_id", "sku", "quantity"}
    page.close()
    return image, flavor


with sync_playwright() as p:
    executable = Path("/usr/bin/chromium")
    browser = p.chromium.launch(executable_path=str(executable) if executable.exists() else None,
                                args=["--no-sandbox"])
    with serve(SITE) as url:
        image, flavor = capture(browser, url, True)
    print("PASS: HTTP site, QR redirect query/hash, 390x844 layout loaded and price-free intent")
    if baseline := os.environ.get("BSV_MENU_V13_BASELINE"):
        with tempfile.TemporaryDirectory() as tmp, ZipFile(baseline) as archive:
            for source in SITE.rglob("*"):
                if not source.is_file():
                    continue
                name = source.relative_to(SITE)
                target = Path(tmp) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name.as_posix()))
            with serve(tmp) as url:
                old_image, old_flavor = capture(browser, url, False)
        assert old_flavor == flavor
        assert old_image == image, "Mobile screenshots differ from original V13"
        print("PASS: 390x844 PNG byte-identical to V13; all rendered flavors match")
    browser.close()
