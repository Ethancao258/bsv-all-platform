"""Loopback-only HTTP ingress for the SSH-forwarded internal test edition."""
import os
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[3]
PORTS = {"identity": 18761, "pos": 18762, "supply": 18763}
UPSTREAM = {key: f"http://127.0.0.1:{int(os.getenv('BSV_STAGE_'+key.upper()+'_PORT', port))}"
            for key, port in PORTS.items()}
INBOUND = {b"accept", b"content-type", b"cookie", b"origin", b"x-bsv-csrf", b"x-csrf-token", b"range"}
OUTBOUND = {b"content-type", b"cache-control", b"set-cookie", b"content-disposition",
            b"content-security-policy", b"x-content-type-options", b"x-frame-options", b"referrer-policy", b"accept-ranges", b"content-range"}
LIMIT = 4 * 1024 * 1024
ACADEMY_PAGES = {"/academy": "academy.html", "/academy/admin": "academy-admin.html",
                 "/academy.js": "academy.js", "/academy-admin.js": "academy-admin.js"}
STAFF_PAGES = {"/": "workbench.html", "/workbench.js": "workbench.js",
               "/menu-internal.css": "menu-internal.css", **ACADEMY_PAGES}
INTERNAL_PAGE_HEADERS = {
    "cache-control": "no-store",
    "content-security-policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
                               "img-src 'self'; media-src 'self'; connect-src 'self'; "
                               "form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}


def upstream(path):
    if path.startswith("/supply-ui/"):
        return "supply", path.removeprefix("/supply-ui")
    if path == "/hq/stores/layout" or path.startswith("/hq/stores/layout/assets/"):
        return "pos", path
    if path in {"/identity", "/staff", "/hq", "/health/ready"} or path.startswith(
            ("/api/v1/", "/hq-assets/")) or path in {"/assets/common.js", "/assets/staff.js", "/assets/style.css"}:
        return "identity", "/" if path == "/identity" else path
    return "pos", "/" if path == "/pos" else path


async def proxy(request: Request):
    path = request.url.path
    if path.rstrip("/") in {"/api/v1/identity/authorize", "/api/v1/identity/pos-session",
                             "/api/v1/identity/hq-layout-session", "/api/v1/auth/me",
                             "/api/v1/academy/pos-authorize"}:
        return Response(status_code=404)
    if path in STAFF_PAGES:
        if request.method not in {"GET", "HEAD"}:
            return Response(status_code=405)
        return FileResponse(ROOT / "apps/staff-center/identity" / STAFF_PAGES[path],
                            headers=INTERNAL_PAGE_HEADERS)
    if path == "/craft" or path.startswith("/craft/"):
        return Response("精酿菜单暂时未提供演练入口。", status_code=404)
    # Reject paths that could normalize to a different upstream route.
    if any(part in {".", ".."} for part in path.split("/")) or any(c in path for c in ("%", "\\", "//")):
        return Response(status_code=400)
    key, target = upstream(path)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > LIMIT:
            return Response(status_code=413)
    headers = [(k, v) for k, v in request.headers.raw if k in INBOUND]
    headers.append((b"host", request.headers["host"].encode("ascii")))
    try:
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            url = httpx.URL(UPSTREAM[key]).copy_with(path=target, query=request.scope["query_string"])
            async with client.stream(request.method, url, headers=headers, content=bytes(body)) as result:
                data = bytearray()
                async for chunk in result.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > LIMIT:
                        return Response(status_code=502)
                response = Response(bytes(data), status_code=result.status_code)
                response.raw_headers.extend((k.lower(), v) for k, v in result.headers.raw if k.lower() in OUTBOUND)
                return response
    except (httpx.HTTPError, ValueError):
        return Response(status_code=503)


def internal_menu(request):
    # Private entry only. The published V13.1 directory stays byte-for-byte public.
    if request.method not in {"GET", "HEAD"}:
        return Response(status_code=405)
    page = (ROOT / "apps/guest-web/bsv1/site/cocktail/index.html").read_text(encoding="utf-8")
    menu_link = '<a href="/pos">返回点单台</a>' if request.query_params.get("from") == "pos" else ""
    nav = '<nav class="private-menu-return" aria-label="内部工作导航"><a href="/">返回工作台</a>' + menu_link + '</nav>'
    page = page.replace('<header class="header">', '<header class="header">' + nav, 1)
    page = page.replace("</head>", '<link rel="stylesheet" href="/menu-internal.css"></head>', 1)
    return HTMLResponse(page, headers={"cache-control": "no-store", "referrer-policy": "no-referrer",
                                        "x-content-type-options": "nosniff"})


class LocalHost:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            hosts = [value for key, value in scope["headers"] if key == b"host"]
            if len(hosts) != 1 or hosts[0].split(b":", 1)[0] not in (b"127.0.0.1", b"localhost"):
                return await Response(status_code=400)(scope, receive, send)
        await self.app(scope, receive, send)


app = LocalHost(Starlette(routes=[
    Route("/cocktail/", internal_menu, methods=["GET", "HEAD"]),
    Route("/cocktail/index.html", internal_menu, methods=["GET", "HEAD"]),
    Mount("/cocktail", StaticFiles(directory=ROOT / "apps/guest-web/bsv1/site/cocktail", html=True)),
    Route("/{path:path}", proxy, methods=["GET", "HEAD", "POST"]),
]))
