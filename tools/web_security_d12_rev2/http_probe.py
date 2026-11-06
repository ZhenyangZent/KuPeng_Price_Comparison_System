from __future__ import annotations

import argparse
import http.client
import json
import socket
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

NOW = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)


class QuietHandler(WSGIRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


def observation() -> dict[str, object]:
    return {
        "schema_version": "CDH-B15-MANUAL-OBSERVATION-1",
        "submission_id": "SUB-D12-REV2-HTTP-0001",
        "title": "D12 REV2 HTTP synthetic product",
        "identity": {"platform": "COUPANG_TW", "product_id": "PROD-D12-REV2", "sku_id": "SKU-D12-REV2", "seller_id": "SELLER-D12", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD"},
        "observed_at": "2026-11-05T15:00:00+08:00",
        "quantity": 1,
        "before_coupon_price_twd": 1200,
        "user_reported_coupon": {"status": "USER_REPORTED", "price_twd": 1000, "eligibility": "USER_ASSERTED_ELIGIBLE", "evidence_level": "USER_DESCRIPTION", "evidence_note": "D12 isolated synthetic evidence", "valid_from": "2026-11-01T00:00:00+08:00", "valid_until": "2026-11-30T23:59:59+08:00"},
        "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None},
        "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "D12 isolated loopback probe"},
    }


def call(port: int, method: str, path: str, *, body: bytes = b"", headers: dict[str, str] | None = None) -> dict[str, object]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    try:
        connection.request(method, path, body=body, headers=dict(headers or {}))
        response = connection.getresponse()
        raw = response.read()
        return {"method": method, "path": path, "status": response.status, "body": json.loads(raw) if raw else None}
    finally:
        connection.close()


def call_without_host(port: int) -> dict[str, object]:
    request = b"GET /api/private-observations/v1/session HTTP/1.0\r\nConnection: close\r\n\r\n"
    with socket.create_connection(("127.0.0.1", port), timeout=4) as stream:
        stream.sendall(request)
        chunks = []
        while True:
            chunk = stream.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n", 1)[0].split()[1])
    return {"method": "GET", "path": "/api/private-observations/v1/session", "host_header": "OMITTED", "status": status, "body": json.loads(body) if body else None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b15-root", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.b15_root.resolve() / "services/private_observation_b15"))
    from private_observation_b15.api import PrivateObservationApp
    from private_observation_b15.store import ObservationStore

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.json_out.parent.resolve()) as directory:
        isolated = Path(directory)
        store = ObservationStore(isolated / "private-data", allowed_project_root=isolated, clock=lambda: NOW)
        app = PrivateObservationApp(store, baselines={"B15_REV2": "D12_EXACT_INPUT"}, clock=lambda: NOW, csrf_token="d12-rev2-http-csrf", allowed_origins=("http://127.0.0.1:4173",))
        server = make_server("127.0.0.1", 0, app, handler_class=QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_port
        requests: list[dict[str, object]] = []
        try:
            requests.append(call_without_host(port))
            requests.append(call(port, "GET", "/api/private-observations/v1/session", headers={"Host": f"127.0.0.1:{port}", "Origin": "https://evil.invalid"}))
            duplicate = b'{"identity":{"sku_id":"A","sku_\\u0069d":"B"}}'
            requests.append(call(port, "POST", "/api/private-observations/v1/preview", body=duplicate, headers={"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", "X-CDH-CSRF-Token": "d12-rev2-http-csrf"}))
            payload = json.dumps(observation(), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
            requests.append(call(port, "POST", "/api/private-observations/v1/preview", body=payload, headers={"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"}))
            preview = call(port, "POST", "/api/private-observations/v1/preview", body=payload, headers={"Host": f"127.0.0.1:{port}", "Origin": "http://127.0.0.1:4173", "Content-Type": "application/json", "X-CDH-CSRF-Token": "d12-rev2-http-csrf"})
            requests.append(preview)
            confirm = json.dumps({"preview_id": preview["body"]["preview_id"], "confirm_token": preview["body"]["confirm_token"], "explicit_confirm": True}, separators=(",", ":")).encode("utf-8")
            requests.append(call(port, "POST", "/api/private-observations/v1/confirm", body=confirm, headers={"Host": f"127.0.0.1:{port}", "Origin": "http://127.0.0.1:4173", "Content-Type": "application/json", "X-CDH-CSRF-Token": "d12-rev2-http-csrf"}))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        statuses = [item["status"] for item in requests]
        expected = [400, 403, 400, 403, 200, 201]
        public = []
        for item in requests:
            body = item.get("body")
            if item["path"].endswith("/preview") and item["status"] == 200 and isinstance(body, dict):
                body = {**body, "preview_id": "[REDACTED]", "confirm_token": "[REDACTED]"}
            public.append({**item, "body": body})
        result = {
            "schema": "CDH-D12-B15-REV2-ACTUAL-HTTP-PROBE-1",
            "loopback_only": True,
            "external_request_count": 0,
            "request_count": len(requests),
            "statuses": statuses,
            "expected_statuses": expected,
            "status_gate": "PASS" if statuses == expected else "FAIL",
            "observation_count": store.observation_count(),
            "requests": public,
        }
    args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("schema", "statuses", "status_gate", "external_request_count", "observation_count")}, sort_keys=True))
    return 0 if result["status_gate"] == "PASS" and result["observation_count"] == 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
