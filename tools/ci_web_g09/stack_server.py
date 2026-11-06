from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from wsgiref.simple_server import make_server


def digest(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--a11-root", type=Path, required=True); parser.add_argument("--b11-root", type=Path, required=True); parser.add_argument("--front-port", type=int, required=True); parser.add_argument("--api-port", type=int, required=True); parser.add_argument("--trace", type=Path, required=True); args = parser.parse_args()
    a11, b11 = args.a11_root.resolve(), args.b11_root.resolve(); dist = a11 / "apps" / "price-web" / "frontend" / "dist"; service = b11 / "services" / "price_coupon_v4"
    import sys
    sys.path.insert(0, str(service))
    from price_coupon_v4.server import create_app
    active = service / "fixtures" / "b11_suite" / "active"; database = active / "coupon.sqlite3"; authority = active / "coupon.authority.json"
    before = {"database": digest(database), "authority": digest(authority)}; trace: list[dict] = []
    api = make_server("127.0.0.1", args.api_port, create_app(database, authority, active)); api_thread = threading.Thread(target=api.serve_forever, daemon=True); api_thread.start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *values): return
        def _record(self, status: int, upstream: bool = False): trace.append({"method": self.command, "path": self.path, "status": status, "client": self.client_address[0], "upstream": upstream})
        def _headers(self, status: int, content_type: str, length: int):
            self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(length)); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"); self.send_header("X-Content-Type-Options", "nosniff"); self.end_headers()
        def _host_ok(self): return self.headers.get("Host") in {f"127.0.0.1:{args.front_port}", f"localhost:{args.front_port}"}
        def do_POST(self):
            if not self._host_ok(): self._headers(400, "application/json", 0); self._record(400); return
            if self.path == "/__g09_shutdown": body = b'{"stopping":true}'; self._headers(200, "application/json", len(body)); self.wfile.write(body); self._record(200); threading.Thread(target=server.shutdown, daemon=True).start(); return
            self._headers(405, "application/json", 0); self._record(405)
        def do_GET(self):
            if not self._host_ok(): self._headers(400, "application/json", 0); self._record(400); return
            if self.path.startswith("/cdh-coupon-v4/"):
                target = self.path[len("/cdh-coupon-v4"):]; connection = http.client.HTTPConnection("127.0.0.1", args.api_port, timeout=5); headers = {"Accept": self.headers.get("Accept", "application/json")}
                if self.headers.get("If-None-Match"): headers["If-None-Match"] = self.headers["If-None-Match"]
                connection.request("GET", target, headers=headers); response = connection.getresponse(); body = response.read(); response_headers = response.getheaders(); connection.close(); self.send_response(response.status)
                for name, value in response_headers:
                    if name.casefold() not in {"connection", "transfer-encoding", "content-length", "access-control-allow-origin"}: self.send_header(name, value)
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); self._record(response.status, True); return
            clean = urlsplit(self.path).path; relative = "index.html" if clean == "/" else clean.lstrip("/"); target = (dist / relative).resolve()
            if dist not in target.parents and target != dist: self._headers(400, "text/plain", 0); self._record(400); return
            if not target.is_file(): target = dist / "index.html"
            body = target.read_bytes(); content = mimetypes.guess_type(target.name)[0] or "application/octet-stream"; self._headers(200, content, len(body)); self.wfile.write(body); self._record(200)

    server = ThreadingHTTPServer(("127.0.0.1", args.front_port), Handler)
    print(json.dumps({"status": "READY", "front": f"http://127.0.0.1:{args.front_port}", "api": f"http://127.0.0.1:{args.api_port}"}), flush=True)
    try: server.serve_forever()
    finally:
        api.shutdown(); api_thread.join(timeout=5); api.server_close(); after = {"database": digest(database), "authority": digest(authority)}
        args.trace.parent.mkdir(parents=True, exist_ok=True); args.trace.write_text(json.dumps({"schema": "CDH-G09-STACK-TRACE-1", "requests": trace, "read_only_hashes": {"before": before, "after": after}, "binds": ["127.0.0.1", "127.0.0.1"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
