from __future__ import annotations

import argparse
import http.client
import importlib.util
import json
import socket
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote
from wsgiref.simple_server import make_server


def record() -> dict[str, object]:
    return {
        "schema_version": "CDH-B15-MANUAL-OBSERVATION-1",
        "submission_id": "SUB-D12-A13-REV3-0001",
        "title": "D12 A13 REV3 boundary product",
        "identity": {"platform": "COUPANG_TW", "product_id": "PROD-D12-A13-REV3", "sku_id": "SKU-D12-A13-REV3", "seller_id": "SELLER-D12", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD"},
        "observed_at": "2026-11-05T15:00:00+08:00",
        "quantity": 1,
        "before_coupon_price_twd": 1200,
        "user_reported_coupon": {"status": "USER_REPORTED", "price_twd": 1000, "eligibility": "USER_ASSERTED_ELIGIBLE", "evidence_level": "USER_DESCRIPTION", "evidence_note": "D12 A13 boundary evidence", "valid_from": "2026-11-01T00:00:00+08:00", "valid_until": "2026-11-30T23:59:59+08:00"},
        "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None},
        "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "D12 isolated A13 boundary"},
    }


def call(port: int, method: str, path: str, *, body: bytes = b"", headers: dict[str, str] | None = None) -> dict[str, object]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=6)
    try:
        connection.request(method, path, body=body, headers=dict(headers or {}))
        response = connection.getresponse()
        raw = response.read()
        return {"method": method, "path": path, "status": response.status, "body": json.loads(raw) if raw else None}
    finally:
        connection.close()


def call_without_host(port: int) -> dict[str, object]:
    request = b"GET /cdh-private-observations/api/private-observations/v1/session HTTP/1.0\r\nConnection: close\r\n\r\n"
    with socket.create_connection(("127.0.0.1", port), timeout=6) as stream:
        stream.sendall(request)
        chunks = []
        while True:
            chunk = stream.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    return {"method": "GET", "path": "/cdh-private-observations/api/private-observations/v1/session", "host_header": "OMITTED", "status": int(head.split(b"\r\n", 1)[0].split()[1]), "body": json.loads(body) if body else None}


def load_preview_server(a13_root: Path):
    path = a13_root / "apps/price-web/local-preview-a11/preview_server.py"
    spec = importlib.util.spec_from_file_location("d12_a13_rev3_preview_server", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("A13_PREVIEW_SERVER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a13-root", type=Path, required=True)
    parser.add_argument("--b15-release", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    a13 = args.a13_root.resolve()
    module = load_preview_server(a13)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.json_out.parent.resolve()) as directory:
        isolated = Path(directory)
        project = isolated / "project"
        runtime = project / "runtime"
        data = project / "private-data"
        project.mkdir()
        service = module.ensure_exact_b15(args.b15_release.resolve(), runtime)
        outside_rejected = False
        try:
            module.create_b15_wsgi(service, isolated / "outside-data", project, args.release_root.resolve(), ("http://127.0.0.1:1",))
        except Exception:
            outside_rejected = True
        b15_app = module.create_b15_wsgi(service, data, project, args.release_root.resolve(), ("http://127.0.0.1:1",))
        b15_server = make_server("127.0.0.1", 0, b15_app, server_class=module.QuietWSGIServer)
        b15_thread = threading.Thread(target=b15_server.serve_forever, daemon=True)
        b15_thread.start()
        preview = module.PreviewHTTPServer(("127.0.0.1", 0), module.PreviewHandler, dist=a13 / "apps/price-web/frontend/dist", b11_port=b15_server.server_port, b15_port=b15_server.server_port, instance_id="d12-a13-rev3", control_token="x" * 40)
        allowed_origin = f"http://127.0.0.1:{preview.server_port}"
        b15_app.allowed_origins = frozenset((allowed_origin, f"http://localhost:{preview.server_port}"))
        preview_thread = threading.Thread(target=preview.serve_forever, daemon=True)
        preview_thread.start()
        host = f"127.0.0.1:{preview.server_port}"
        requests: list[dict[str, object]] = []
        prefix = "/cdh-private-observations/api/private-observations/v1"
        try:
            requests.append(call_without_host(preview.server_port))
            requests.append(call(preview.server_port, "GET", prefix + "/session", headers={"Host": host, "Origin": "https://evil.invalid"}))
            session = call(preview.server_port, "GET", prefix + "/session", headers={"Host": host, "Origin": allowed_origin})
            requests.append(session)
            csrf = session["body"]["csrf_token"]
            payload = json.dumps(record(), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
            requests.append(call(preview.server_port, "POST", prefix + "/preview", body=payload, headers={"Host": host, "Origin": allowed_origin, "Content-Type": "application/json"}))
            duplicate = b'{"identity":{"sku_id":"A","sku_\\u0069d":"B"}}'
            requests.append(call(preview.server_port, "POST", prefix + "/preview", body=duplicate, headers={"Host": host, "Origin": allowed_origin, "Content-Type": "application/json", "X-CDH-CSRF-Token": csrf}))
            response_preview = call(preview.server_port, "POST", prefix + "/preview", body=payload, headers={"Host": host, "Origin": allowed_origin, "Content-Type": "application/json", "X-CDH-CSRF-Token": csrf})
            requests.append(response_preview)
            confirmation = json.dumps({"preview_id": response_preview["body"]["preview_id"], "confirm_token": response_preview["body"]["confirm_token"], "explicit_confirm": True}, separators=(",", ":")).encode("utf-8")
            requests.append(call(preview.server_port, "POST", prefix + "/confirm", body=confirmation, headers={"Host": host, "Origin": allowed_origin, "Content-Type": "application/json", "X-CDH-CSRF-Token": csrf}))
            search = call(preview.server_port, "GET", prefix + "/products?q=PROD-D12-A13-REV3&page=1&limit=20", headers={"Host": host, "Origin": allowed_origin})
            requests.append(search)
            series = search["body"]["items"][0]["series_key"]
            detail = call(preview.server_port, "GET", prefix + "/products/" + quote(series, safe=""), headers={"Host": host, "Origin": allowed_origin})
            requests.append(detail)
        finally:
            preview.shutdown()
            preview.server_close()
            preview_thread.join(timeout=3)
            b15_server.shutdown()
            b15_server.server_close()
            b15_thread.join(timeout=3)
        statuses = [item["status"] for item in requests]
        expected = [400, 403, 200, 403, 400, 200, 201, 200, 200]
        history = requests[-1]["body"]["history"]
        safety = history["confirmed_after_coupon"] == [] and history["user_reported_after_coupon"][0]["price_twd"] == 1000
        outside_sqlite = list((isolated / "outside-data").rglob("*.sqlite3")) if (isolated / "outside-data").exists() else []
        public = []
        for item in requests:
            body = item.get("body")
            if item["path"].endswith("/session") and item["status"] == 200 and isinstance(body, dict):
                body = {**body, "csrf_token": "[REDACTED]"}
            if item["path"].endswith("/preview") and item["status"] == 200 and isinstance(body, dict):
                body = {**body, "preview_id": "[REDACTED]", "confirm_token": "[REDACTED]"}
            public.append({**item, "body": body})
        result = {
            "schema": "CDH-D12-A13-REV3-B15-REV2-BOUNDARY-PROBE-1",
            "a13_rev3_sha256": "d1b8814f0ae54f5fa5fae77c873620fe70da979fcbfe689a333096fab897b274",
            "b15_rev2_sha256": module.B15_SHA256,
            "loopback_only": True,
            "external_request_count": 0,
            "statuses": statuses,
            "expected_statuses": expected,
            "outside_data_root_rejected": outside_rejected,
            "outside_sqlite_created_count": len(outside_sqlite),
            "confirmed_coupon_separation": safety,
            "observation_count": 1,
            "gate": "PASS" if statuses == expected and outside_rejected and not outside_sqlite and safety else "FAIL",
            "requests": public,
        }
    args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("schema", "gate", "statuses", "outside_data_root_rejected", "outside_sqlite_created_count", "confirmed_coupon_separation", "external_request_count")}, sort_keys=True))
    return 0 if result["gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
