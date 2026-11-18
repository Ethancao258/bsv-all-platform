"""Serve the local synthetic menu and BSV1 exercise."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
MENU = ROOT / "apps/guest-web/preview"
STORE = ROOT / "apps/store-console/preview"
ROUTES = {
    "/": (MENU / "index.html", "text/html"),
    "/menu.json": (MENU / "menu.json", "application/json"),
    "/store/": (STORE / "index.html", "text/html"),
    "/api/v1/menu": (MENU / "menu.json", "application/json"),
}


class PreviewHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = ROUTES.get(urlsplit(self.path).path)
        if route is None:
            self.send_error(404)
            return
        path, content_type = route
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), PreviewHandler) as server:
        server.serve_forever()
