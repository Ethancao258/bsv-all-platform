#!/usr/bin/env python3
"""Render the approved static portal into an independent publication directory."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import tempfile
from html.parser import HTMLParser

class Audit(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.links = []
        self.scripts = 0
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            if a["id"] in self.ids:
                raise ValueError("duplicate id: " + a["id"])
            self.ids.add(a["id"])
        if tag == "a" and "href" in a:
            self.links.append(a["href"])
        if tag == "script":
            self.scripts += 1

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--icp", required=True, help="Verified full website ICP number, including the site suffix")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--craft-live", action="store_true", help="Only after verifying actual craft menu, not a generic HTTP 200")
    p.add_argument("--cocktail-url", default="https://menu.bsvm.cn/cocktail/",
                   choices=["https://menu.bsvm.cn/cocktail/", "https://bsvm.cn/cocktail/"])
    a = p.parse_args()
    icp = a.icp.strip()
    if not re.fullmatch(r"[\u4e00-\u9fff]ICP备[0-9]+号-[0-9]+", icp):
        p.error("Use the actual complete website ICP number from the filing record, not a guessed suffix")
    src = Path(__file__).with_name("index.html")
    page = src.read_text(encoding="utf-8")
    marker = "__BSV_ICP_SITE_NUMBER__"
    if page.count(marker) != 1:
        raise ValueError("ICP marker missing or duplicated")
    page = page.replace(marker, icp)
    page = page.replace('href="https://menu.bsvm.cn/cocktail/"', 'href="' + a.cocktail_url + '"', 1)
    if a.craft_live:
        start, end = "<!-- CRAFT_LINK_START -->", "<!-- CRAFT_LINK_END -->"
        if page.count(start) != 1 or page.count(end) != 1:
            raise ValueError("Craft markers missing or duplicated")
        left, right = page.split(start, 1)
        _, right = right.split(end, 1)
        page = left + '<a class="action" href="https://menu.bsvm.cn/craft/">查看精酿酒单 <span aria-hidden="true">→</span></a>' + right
    parser = Audit()
    parser.feed(page)
    assert not parser.scripts and marker not in page
    assert a.cocktail_url in parser.links
    assert ("https://menu.bsvm.cn/craft/" in parser.links) == a.craft_live
    assert all(x[1:] in parser.ids for x in parser.links if x.startswith("#"))
    assert all(x.startswith(("#", "https://")) or x == "/" for x in parser.links)
    out = a.output.resolve()
    if out == src.parent or out == Path("/"):
        p.error("Use a separate publication directory")
    out.mkdir(parents=True, exist_ok=True)
    data = page.encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=out, prefix=".index-", delete=False) as f:
        tmp = Path(f.name)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    try:
        tmp.chmod(0o644)
        os.replace(tmp, out / "index.html")
    finally:
        tmp.unlink(missing_ok=True)
    print("PORTAL_RENDERED", out / "index.html")
    print("SHA256", hashlib.sha256(data).hexdigest())
    print("COCKTAIL_URL", a.cocktail_url, "CRAFT_LIVE", a.craft_live)

if __name__ == "__main__":
    main()
