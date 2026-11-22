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


# Explicit route ownership for the isolated ingress. POS is never a fallback.
# Unknown API names stay 404, without trying another subsystem or exposing a page.
HQ_LAYOUT_FILES = {"/hq/stores/layout", "/hq/stores/layout/assets/app.js",
                   "/hq/stores/layout/assets/style.css"}
IDENTITY_PAGES = {"/identity", "/staff", "/hq", "/health/ready", "/health/live"}
IDENTITY_ASSETS = {"/assets/common.js", "/assets/staff.js", "/assets/style.css"}
POS_PAGES = {"/pos", "/index.html", "/app.js", "/style.css",
             "/assets/BSV_徽记.png", "/assets/BSV_完整徽标.png",
             "/hq.html", "/hq.js", "/hq.css",
             "/menu", "/menu.html", "/menu.js", "/menu.css"}
POS_GET_API = {
    "/api/bootstrap", "/api/health", "/api/hq/status", "/api/hq/stores",
    "/api/hq/modules", "/api/hq/layout", "/api/hq/layout/revision",
    "/api/hq/art", "/api/hq/image", "/api/menu-preview", "/api/document",
    "/api/store-layout-art", "/api/reports/checkout-csv",
    "/api/production/photo", "/api/state", "/api/receipt", "/api/history",
    "/api/audit", "/api/members/search", "/api/catalog/item", "/api/catalog/search", "/api/production/recipe",
    "/api/visits/customer-context",
}
POS_POST_API = {
    "/api/login", "/api/logout", "/api/pos/device-login", "/api/pos/device-forget",
    "/api/hq/stores/create", "/api/hq/layout/draft", "/api/hq/layout/publish",
    "/api/hq/layout/restore", "/api/hq/image/upload",
    "/api/presence/heartbeat", "/api/seats/claim-edit", "/api/seats/release-edit",
    "/api/production/claim", "/api/production/finished", "/api/production/serve",
    "/api/production/reassign", "/api/seats/open", "/api/drafts/add",
    "/api/drafts/remove", "/api/orders/submit", "/api/members/assign",
    "/api/orders/add-item", "/api/orders/remove-item", "/api/orders/serve-item",
    "/api/unused-serve-item", "/api/visits/set-member", "/api/visits/set-guests",
    "/api/visits/transfer", "/api/visits/customer-link", "/api/checkouts/settle-demo",
    "/api/visits/depart-demo", "/api/visits/cancel",
    "/api/housekeeping/clean-seat", "/api/housekeeping/clean-bathroom",
    "/api/groups/set-mode",
}


def _pos_command_status_path(path):
    # One opaque command ID, not a wildcard for arbitrary nested POS routes.
    return (path.startswith("/api/pos/commands/")
            and len(path.removeprefix("/api/pos/commands/")) <= 90
            and bool(path.removeprefix("/api/pos/commands/"))
            and "/" not in path.removeprefix("/api/pos/commands/"))


def upstream(path):
    if path.startswith("/supply-ui/"):
        return "supply", path.removeprefix("/supply-ui")
    if path in HQ_LAYOUT_FILES:
        return "pos", path
    if path in IDENTITY_PAGES or path.startswith(("/api/v1/", "/hq-assets/")) or path in IDENTITY_ASSETS:
        return "identity", "/" if path == "/identity" else path
    if path in POS_PAGES or path in POS_GET_API or path in POS_POST_API or _pos_command_status_path(path):
        return "pos", "/" if path == "/pos" else path
    return None


def routed_methods(path):
    if path.startswith(("/supply-ui/", "/api/v1/")):
        # The owning FastAPI service still enforces exact API paths and actions.
        return {"GET", "HEAD", "POST"}
    if path in POS_POST_API:
        return {"POST"}
    if path in POS_GET_API or _pos_command_status_path(path):
        return {"GET", "HEAD"}
    return {"GET", "HEAD"}


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
    routed = upstream(path)
    if routed is None:
        return Response(status_code=404)
    if request.method not in routed_methods(path):
        return Response(status_code=405)
    key, target = routed
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
    nav = ('<nav class="private-menu-return" aria-label="内部工作导航">'
           '<a href="/">返回工作台</a><a href="/member/">免费会员</a>'
           + menu_link + '</nav>')
    page = page.replace('<header class="header">', '<header class="header">' + nav, 1)
    page = page.replace("</head>", '<link rel="stylesheet" href="/menu-internal.css"></head>', 1)
    return HTMLResponse(page, headers={"cache-control": "no-store", "referrer-policy": "no-referrer",
                                        "x-content-type-options": "nosniff"})


class LocalHost:
    def __init__(self, app):
        self.app = app
        self.growth_app = None
        if os.getenv("BSV_STAGE_GROWTH_ENABLED") == "1":
            # Growth remains an isolated, synthetic sub-application in this release.
            # Mount directly in the existing loopback ingress: no parallel public
            # gateway, database authority, port or independent authentication tree.
            if (os.getenv("BSV_GROWTH_ENV") != "isolated"
                    or os.getenv("BSV_GROWTH_TRUST_IDENTITY") != "1"):
                raise RuntimeError("Growth integration requires isolated identity.A sessions")
            from services.api.customer_growth.app import app as growth_app
            self.growth_app = growth_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            hosts = [value for key, value in scope["headers"] if key == b"host"]
            if len(hosts) != 1 or hosts[0].split(b":", 1)[0] not in (b"127.0.0.1", b"localhost"):
                return await Response(status_code=400)(scope, receive, send)
            path = scope["path"]
            if self.growth_app is not None and (
                    path.startswith(("/api/v1/growth/", "/member/", "/staff/growth/"))
                    or path == "/growth/health"):
                # No public forwarding of machine payment/benefit events. These
                # require a separately authorized internal adapter and audit.
                if path.startswith("/api/v1/growth/internal/"):
                    return await Response(status_code=404)(scope, receive, send)
                return await self.growth_app(scope, receive, send)
        await self.app(scope, receive, send)


app = LocalHost(Starlette(routes=[
    Route("/cocktail/", internal_menu, methods=["GET", "HEAD"]),
    Route("/cocktail/index.html", internal_menu, methods=["GET", "HEAD"]),
    Mount("/cocktail", StaticFiles(directory=ROOT / "apps/guest-web/bsv1/site/cocktail", html=True)),
    Route("/{path:path}", proxy, methods=["GET", "HEAD", "POST"]),
]))
