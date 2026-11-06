from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib
import json
import mimetypes
import secrets
import sys
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from wsgiref.simple_server import WSGIServer, make_server

B11_SHA256 = "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"
B15_SHA256 = "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe"
B16_SHA256 = "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7"
BUNDLE_MANIFEST_SCHEMA = "CDH-A17-RUNTIME-BUNDLE-MANIFEST-1"
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), microphone=(), payment=(), usb=()",
}


class PreviewError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundle(bundle_root: Path) -> dict[str, object]:
    root = bundle_root.resolve(strict=True)
    manifest_path = root / "A17_RUNTIME_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise PreviewError(f"A17_RUNTIME_MANIFEST_INVALID: {exc}") from exc
    if set(manifest) != {"schema_version", "source_releases", "files"} or manifest.get("schema_version") != BUNDLE_MANIFEST_SCHEMA:
        raise PreviewError("A17_RUNTIME_MANIFEST_SCHEMA_MISMATCH")
    if not isinstance(manifest.get("source_releases"), dict) or not isinstance(manifest.get("files"), list):
        raise PreviewError("A17_RUNTIME_MANIFEST_CONTENT_INVALID")
    expected: dict[str, tuple[int, str]] = {}
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise PreviewError("A17_RUNTIME_MANIFEST_ENTRY_INVALID")
        path, size, digest = entry.get("path"), entry.get("size"), entry.get("sha256")
        if not isinstance(path, str) or not isinstance(size, int) or not isinstance(digest, str):
            raise PreviewError("A17_RUNTIME_MANIFEST_ENTRY_INVALID")
        relative = _safe_relative("vendor/" + path, "vendor/")
        if relative is None or relative.as_posix() in expected:
            raise PreviewError("A17_RUNTIME_MANIFEST_PATH_INVALID_OR_DUPLICATE")
        expected[relative.as_posix()] = (size, digest)
    vendor = root / "vendor"
    actual = {
        item.relative_to(vendor).as_posix(): (item.stat().st_size, sha256_file(item))
        for item in vendor.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
    }
    if actual != expected:
        raise PreviewError("A17_RUNTIME_BUNDLE_CONTENT_MISMATCH")
    return {
        "manifest_sha256": sha256_file(manifest_path),
        "file_count": len(actual),
        "source_releases": manifest["source_releases"],
    }


def verify_dist(dist: Path) -> dict[str, object]:
    manifest_path = dist / "A11_DIST_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise PreviewError(f"A11_DIST_MANIFEST_INVALID: {exc}") from exc
    if set(manifest) != {"schema_version", "files"} or manifest.get("schema_version") != "CDH-A11-DIST-MANIFEST-1" or not isinstance(manifest.get("files"), list):
        raise PreviewError("A11_DIST_MANIFEST_SCHEMA_MISMATCH")
    expected: dict[str, tuple[int, str]] = {}
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"} or not isinstance(entry["path"], str) or not isinstance(entry["size"], int) or not isinstance(entry["sha256"], str):
            raise PreviewError("A11_DIST_MANIFEST_ENTRY_INVALID")
        relative = _safe_relative("dist/" + entry["path"], "dist/")
        if relative is None or relative.as_posix() in expected:
            raise PreviewError("A11_DIST_MANIFEST_PATH_INVALID_OR_DUPLICATE")
        expected[relative.as_posix()] = (entry["size"], entry["sha256"])
    actual_files = [item for item in dist.rglob("*") if item.is_file() and item != manifest_path]
    actual = {item.relative_to(dist).as_posix(): (item.stat().st_size, sha256_file(item)) for item in actual_files}
    if actual != expected:
        raise PreviewError("A11_DIST_CONTENT_MISMATCH")
    return {"file_count": len(actual), "manifest_sha256": sha256_file(manifest_path)}


def _safe_relative(name: str, prefix: str) -> Path | None:
    normalized = name.replace("\\", "/")
    if not normalized.startswith(prefix) or normalized.endswith("/"):
        return None
    relative = PurePosixPath(normalized[len(prefix):])
    if not relative.parts or relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise PreviewError(f"UNSAFE_ARCHIVE_MEMBER: {name}")
    return Path(*relative.parts)


def create_b11_wsgi(service_root: Path):
    sys.path.insert(0, str(service_root))
    try:
        server_module = importlib.import_module("price_coupon_v4.server")
        fixture_root = service_root / "fixtures" / "b11_suite" / "active"
        return server_module.create_app(
            fixture_root / "coupon.sqlite3",
            fixture_root / "coupon.authority.json",
            fixture_root,
            allowed_origins=(),
        )
    finally:
        if sys.path and sys.path[0] == str(service_root):
            sys.path.pop(0)


def create_b15_wsgi(service_root: Path, data_root: Path, allowed_project_root: Path, release_root: Path, allowed_origins: tuple[str, ...]):
    sys.path.insert(0, str(service_root))
    try:
        api_module = importlib.import_module("private_observation_b15.api")
        store_module = importlib.import_module("private_observation_b15.store")
        baseline_module = importlib.import_module("private_observation_b15.baselines")
        baselines = baseline_module.verify_baselines(release_root)
        store = store_module.ObservationStore(data_root, allowed_project_root=allowed_project_root)
        return api_module.PrivateObservationApp(
            store,
            baselines=baselines,
            clock=lambda: datetime.now(timezone.utc),
            allowed_origins=allowed_origins,
        )
    finally:
        if sys.path and sys.path[0] == str(service_root):
            sys.path.pop(0)


def create_b16_wsgi(service_root: Path, data_root: Path, allowed_project_root: Path, release_root: Path, allowed_origins: tuple[str, ...]):
    batch_root = service_root / "private_batch_import_b16"
    observation_root = service_root / "private_observation_b15"
    sys.path[:0] = [str(batch_root), str(observation_root)]
    try:
        api_module = importlib.import_module("private_batch_import_b16.api")
        store_module = importlib.import_module("private_batch_import_b16.store")
        baseline_module = importlib.import_module("private_batch_import_b16.baselines")
        baselines = baseline_module.verify_baselines(release_root)
        store = store_module.BatchObservationStore(data_root, allowed_project_root=allowed_project_root)
        return api_module.BatchImportApp(
            store,
            baselines=baselines,
            clock=lambda: datetime.now(timezone.utc),
            allowed_origins=allowed_origins,
        )
    finally:
        for item in (str(batch_root), str(observation_root)):
            if item in sys.path:
                sys.path.remove(item)


class QuietWSGIServer(WSGIServer):
    allow_reuse_address = False


class PreviewHandler(BaseHTTPRequestHandler):
    server_version = "CDH-A11-LocalPreview/1"

    @property
    def app(self):
        return self.server  # type: ignore[return-value]

    def log_message(self, message: str, *args: object) -> None:
        print(json.dumps({"at": utc_now(), "kind": "http", "client": self.client_address[0], "message": message % args}, ensure_ascii=False), flush=True)

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host", "")
        return host in {f"127.0.0.1:{self.app.server_port}", f"localhost:{self.app.server_port}"}

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://127.0.0.1:{self.app.server_port}", f"http://localhost:{self.app.server_port}"}

    def _headers(self, status: int, content_type: str, length: int, *, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        if self.command != "HEAD":
            self.wfile.write(body)

    def _policy(self) -> bool:
        if not self._host_allowed():
            self._json(400, {"error": "HOST_NOT_ALLOWED"})
            return False
        if not self._origin_allowed():
            self._json(403, {"error": "ORIGIN_NOT_ALLOWED"})
            return False
        return True

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if not self._policy():
            return
        parsed = urlsplit(self.path)
        if parsed.path == "/__cdh/health":
            self._json(200, {"status": "READY", "instance_id": self.app.instance_id, "schema_version": "CDH-A17-LOCAL-TRIAL-1", "runtime_bundle_manifest_sha256": self.app.bundle_manifest_sha256, "b11_sha256": B11_SHA256, "b15_rev2_sha256": B15_SHA256, "b16_r12_sha256": B16_SHA256, "b16_revision": "REV3", "b16_api_schema": "CDH-B16-PRIVATE-BATCH-API-1", "b15_loopback_port": self.app.b15_port})
            return
        if parsed.path.startswith("/cdh-coupon-v4/"):
            self._proxy_b11(parsed.path[len("/cdh-coupon-v4"):], parsed.query)
            return
        if parsed.path.startswith("/cdh-private-observations/"):
            self._proxy_b15("GET", parsed.path[len("/cdh-private-observations"):], parsed.query)
            return
        self._static(parsed.path)

    def do_POST(self) -> None:
        if not self._policy():
            return
        parsed = urlsplit(self.path)
        if parsed.path.startswith("/cdh-private-observations/"):
            self._proxy_b15("POST", parsed.path[len("/cdh-private-observations"):], parsed.query)
            return
        if parsed.path != "/__cdh/shutdown":
            self._json(405, {"error": "METHOD_NOT_ALLOWED"})
            return
        token = self.headers.get("X-CDH-Control-Token", "")
        if not secrets.compare_digest(token, self.app.control_token):
            self._json(403, {"error": "CONTROL_TOKEN_INVALID"})
            return
        self._json(202, {"status": "STOPPING", "instance_id": self.app.instance_id})
        threading.Thread(target=self.app.shutdown, daemon=True).start()

    def _proxy_b11(self, path: str, query: str) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.app.b11_port, timeout=8)
        headers = {"Host": "127.0.0.1"}
        if self.headers.get("If-None-Match"):
            headers["If-None-Match"] = self.headers["If-None-Match"]
        try:
            connection.request("GET", path + (f"?{query}" if query else ""), headers=headers)
            response = connection.getresponse()
            body = response.read(1_000_001)
            if len(body) > 1_000_000:
                self._json(502, {"error": "UPSTREAM_RESPONSE_LIMIT_EXCEEDED"})
                return
            forwarded = {key: value for key, value in response.getheaders() if key.lower() in {"etag", "x-cdh-schema-version"}}
            self._headers(response.status, response.getheader("Content-Type", "application/json; charset=utf-8"), len(body), extra=forwarded)
            if self.command != "HEAD":
                self.wfile.write(body)
        except (OSError, http.client.HTTPException) as exc:
            self._json(502, {"error": "B11_UPSTREAM_UNAVAILABLE", "detail": str(exc)})
        finally:
            connection.close()

    def _proxy_b15(self, method: str, path: str, query: str) -> None:
        if method not in {"GET", "POST"} or not path.startswith("/api/private-observations/v1/"):
            self._json(404, {"error": "B15_ROUTE_NOT_ALLOWED"})
            return
        headers = {"Host": "127.0.0.1", "Accept": "application/json"}
        for source, destination in (("Content-Type", "Content-Type"), ("X-CDH-CSRF-Token", "X-CDH-CSRF-Token"), ("If-None-Match", "If-None-Match")):
            if self.headers.get(source):
                headers[destination] = self.headers[source]
        origin = self.headers.get("Origin")
        if origin:
            headers["Origin"] = origin
        body = None
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(400, {"error": "CONTENT_LENGTH_INVALID"})
                return
            request_limit = 1_500_000 if path == "/api/private-observations/v1/batch-preview" else 16 * 1024 if path == "/api/private-observations/v1/batch-confirm" else 128 * 1024
            if length < 0 or length > request_limit:
                self._json(413, {"error": "REQUEST_BODY_TOO_LARGE"})
                return
            body = self.rfile.read(length)
            headers["Content-Length"] = str(len(body))
        connection = http.client.HTTPConnection("127.0.0.1", self.app.b15_port, timeout=8)
        try:
            connection.request(method, path + (f"?{query}" if query else ""), body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read(1_000_001)
            if len(payload) > 1_000_000:
                self._json(502, {"error": "UPSTREAM_RESPONSE_LIMIT_EXCEEDED"})
                return
            forwarded = {key: value for key, value in response.getheaders() if key.lower() in {"etag", "x-cdh-schema-version"}}
            self._headers(response.status, response.getheader("Content-Type", "application/json; charset=utf-8"), len(payload), extra=forwarded)
            self.wfile.write(payload)
        except (OSError, http.client.HTTPException) as exc:
            self._json(502, {"error": "B15_UPSTREAM_UNAVAILABLE", "detail": str(exc)})
        finally:
            connection.close()

    def _static(self, raw_path: str) -> None:
        path = raw_path or "/"
        if "\x00" in path or "\\" in path:
            self._json(400, {"error": "INVALID_PATH"})
            return
        relative = PurePosixPath(path.lstrip("/"))
        if path == "/" or not relative.parts:
            relative = PurePosixPath("index.html")
        elif any(part in {"", ".", ".."} for part in relative.parts):
            self._json(400, {"error": "INVALID_PATH"})
            return
        target = self.app.dist / Path(*relative.parts)
        try:
            resolved = target.resolve(strict=True)
            resolved.relative_to(self.app.dist)
        except (FileNotFoundError, ValueError):
            resolved = self.app.dist / "index.html"
        if not resolved.is_file():
            self._json(404, {"error": "STATIC_FILE_NOT_FOUND"})
            return
        body = resolved.read_bytes()
        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self._headers(200, content_type, len(body))
        if self.command != "HEAD":
            self.wfile.write(body)


class PreviewHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, address, handler, *, dist: Path, b11_port: int, b15_port: int, instance_id: str, control_token: str, bundle_manifest_sha256: str):
        super().__init__(address, handler)
        self.dist = dist.resolve()
        self.b11_port = b11_port
        self.b15_port = b15_port
        self.instance_id = instance_id
        self.control_token = control_token
        self.bundle_manifest_sha256 = bundle_manifest_sha256


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CDH A11 loopback-only synthetic local preview")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4174)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--private-data-root", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.project_root.resolve()
    if not 1 <= args.port <= 65535:
        raise PreviewError("PORT_OUT_OF_RANGE")
    bundle = args.bundle_root.resolve(strict=True)
    try:
        bundle.relative_to(root)
    except ValueError as exc:
        raise PreviewError("A17_BUNDLE_OUTSIDE_PROJECT_ROOT") from exc
    bundle_evidence = verify_bundle(bundle)
    dist = (bundle / "vendor" / "frontend" / "dist").resolve()
    if not (dist / "index.html").is_file():
        raise PreviewError(f"FRONTEND_DIST_MISSING: {dist}")
    verify_dist(dist)
    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise PreviewError("CONTROL_TOKEN_INVALID")
    service = (bundle / "vendor" / "b11").resolve()
    wsgi_app = create_b11_wsgi(service)
    b11_server = make_server("127.0.0.1", 0, wsgi_app, server_class=QuietWSGIServer)
    b11_thread = threading.Thread(target=b11_server.serve_forever, daemon=True, name="cdh-b11-wsgi")
    b11_thread.start()
    b15_service = (bundle / "vendor" / "b16").resolve()
    allowed_origins = (f"http://127.0.0.1:{args.port}", f"http://localhost:{args.port}")
    baseline_root = (bundle / "vendor" / "baselines").resolve()
    b15_app = create_b16_wsgi(b15_service, args.private_data_root.resolve(), root, baseline_root, allowed_origins)
    b15_server = make_server("127.0.0.1", 0, b15_app, server_class=QuietWSGIServer)
    b15_thread = threading.Thread(target=b15_server.serve_forever, daemon=True, name="cdh-b15-wsgi")
    b15_thread.start()
    try:
        with PreviewHTTPServer(("127.0.0.1", args.port), PreviewHandler, dist=dist, b11_port=b11_server.server_port, b15_port=b15_server.server_port, instance_id=args.instance_id, control_token=token, bundle_manifest_sha256=str(bundle_evidence["manifest_sha256"])) as server:
            print(json.dumps({"status": "READY", "url": f"http://127.0.0.1:{args.port}/?mode=synthetic&contract=v4", "instance_id": args.instance_id, "runtime_bundle_manifest_sha256": bundle_evidence["manifest_sha256"], "b11_port": b11_server.server_port, "b15_port": b15_server.server_port, "at": utc_now()}), flush=True)
            server.serve_forever()
    finally:
        b15_server.shutdown()
        b15_server.server_close()
        b15_thread.join(timeout=3)
        b11_server.shutdown()
        b11_server.server_close()
        b11_thread.join(timeout=3)
        print(json.dumps({"status": "STOPPED", "instance_id": args.instance_id, "at": utc_now()}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreviewError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc), "at": utc_now()}), file=sys.stderr, flush=True)
        raise SystemExit(2)
