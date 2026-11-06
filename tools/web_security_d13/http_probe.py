from __future__ import annotations

import base64
import http.client
import json
import shutil
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server


ROOT = Path(__file__).resolve().parents[2]
B16 = ROOT / "review" / "D13" / "001" / "input" / "CDH_B_R12_001_REVIEW"
sys.path.insert(0, str(B16 / "services" / "private_batch_import_b16"))
sys.path.insert(0, str(B16 / "services" / "private_observation_b15"))

from private_batch_import_b16.api import BatchImportApp  # noqa: E402
from private_batch_import_b16.store import BatchObservationStore  # noqa: E402


NOW = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)
OUT = ROOT / "review" / "D13" / "001" / "evidence" / "ACTUAL_LOOPBACK_HTTP.json"
DATA = ROOT / "review" / "D13" / "001" / "http_probe"
BASELINES = {"b15_rev2": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe"}


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):  # noqa: A003
        return


def send(port: int, method: str, path: str, *, body: dict[str, object] | None = None, headers: dict[str, str] | None = None, skip_host: bool = False):
    raw = b"" if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    supplied_host = any(key.casefold() == "host" for key in (headers or {}))
    connection.putrequest(method, path, skip_host=skip_host or supplied_host)
    for key, value in (headers or {}).items():
        connection.putheader(key, value)
    if body is not None:
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(len(raw)))
    connection.endheaders(raw if body is not None else None)
    response = connection.getresponse()
    payload = response.read()
    result = {
        "status": response.status,
        "headers": {key.casefold(): value for key, value in response.getheaders()},
        "body": json.loads(payload) if payload else None,
    }
    connection.close()
    return result


def main() -> int:
    if DATA.exists():
        resolved = DATA.resolve()
        expected = (ROOT / "review" / "D13" / "001").resolve()
        if not resolved.is_relative_to(expected):
            raise RuntimeError("unsafe cleanup target")
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)
    store = BatchObservationStore(DATA / "private-data", allowed_project_root=DATA, clock=lambda: NOW)
    app = BatchImportApp(
        store,
        baselines=BASELINES,
        clock=lambda: NOW,
        csrf_token="csrf-d13-http",
        allowed_origins=("http://127.0.0.1:4173",),
    )
    server = make_server("127.0.0.1", 0, app, handler_class=QuietHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        session = send(port, "GET", "/api/private-observations/v1/session")
        observation = {
            "schema_version": "CDH-B15-MANUAL-OBSERVATION-1",
            "submission_id": "SUB-D13-HTTP-0001",
            "title": "D13 HTTP synthetic",
            "identity": {"platform": "COUPANG_TW", "product_id": "PROD-D13-HTTP", "sku_id": "SKU-D13-HTTP", "seller_id": "SELLER-D13", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD"},
            "observed_at": "2026-11-03T12:00:00+08:00",
            "quantity": 1,
            "before_coupon_price_twd": 1000,
            "user_reported_coupon": {"status": "USER_REPORTED", "price_twd": 900, "eligibility": "USER_ASSERTED_ELIGIBLE", "evidence_level": "USER_DESCRIPTION", "evidence_note": "D13 HTTP synthetic", "valid_from": None, "valid_until": None},
            "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None},
            "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "D13 HTTP synthetic"},
        }
        content = json.dumps({"schema_version": "CDH-B16-BATCH-FILE-1", "observations": [observation]}, separators=(",", ":")).encode("utf-8")
        preview_request = {
            "schema_version": "CDH-B16-BATCH-PREVIEW-REQUEST-1",
            "filename": "d13.json",
            "media_type": "application/json",
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
        authorized = {"X-CDH-CSRF-Token": session["body"]["csrf_token"], "Origin": "http://127.0.0.1:4173"}
        preview = send(port, "POST", "/api/private-observations/v1/batch-preview", body=preview_request, headers=authorized)
        count_after_preview = store.observation_count()
        confirm_request = {
            "schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1",
            "preview_id": preview["body"]["preview_id"],
            "confirm_token": preview["body"]["confirm_token"],
            "explicit_confirm": True,
        }
        confirm = send(port, "POST", "/api/private-observations/v1/batch-confirm", body=confirm_request, headers=authorized)
        count_after_confirm = store.observation_count()
        hostile_origin = send(port, "POST", "/api/private-observations/v1/batch-preview", body=preview_request, headers={"X-CDH-CSRF-Token": session["body"]["csrf_token"], "Origin": "https://evil.invalid"})
        bad_host = send(port, "POST", "/api/private-observations/v1/batch-preview", body=preview_request, headers={"Host": "evil.invalid", "X-CDH-CSRF-Token": session["body"]["csrf_token"]})
        missing_host = send(port, "POST", "/api/private-observations/v1/batch-preview", body=preview_request, headers={"X-CDH-CSRF-Token": session["body"]["csrf_token"]}, skip_host=True)
        bad_method = send(port, "PUT", "/api/private-observations/v1/batch-preview", body=preview_request, headers=authorized)
        result = {
            "schema_version": "CDH-D13-ACTUAL-LOOPBACK-HTTP-1",
            "bind_host": "127.0.0.1",
            "external_request_count": 0,
            "session_status": session["status"],
            "preview_status": preview["status"],
            "database_count_after_preview": count_after_preview,
            "confirm_status": confirm["status"],
            "database_count_after_confirm": count_after_confirm,
            "hostile_origin_status": hostile_origin["status"],
            "hostile_origin_code": hostile_origin["body"]["error"]["code"],
            "bad_host_status": bad_host["status"],
            "bad_host_code": bad_host["body"]["error"]["code"],
            "missing_host_status": missing_host["status"],
            "missing_host_code": missing_host["body"]["error"]["code"],
            "bad_method_status": bad_method["status"],
            "bad_method_code": bad_method["body"]["error"]["code"],
            "security_headers_present": all(
                key in confirm["headers"]
                for key in ("cache-control", "content-security-policy", "x-content-type-options", "x-frame-options")
            ),
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        passed = result == {
            **result,
            "session_status": 200,
            "preview_status": 200,
            "database_count_after_preview": 0,
            "confirm_status": 201,
            "database_count_after_confirm": 1,
            "hostile_origin_status": 403,
            "hostile_origin_code": "ORIGIN_NOT_ALLOWED",
            "bad_host_status": 400,
            "bad_host_code": "HOST_NOT_ALLOWED",
            "missing_host_status": 400,
            "missing_host_code": "HOST_REQUIRED",
            "bad_method_status": 405,
            "bad_method_code": "METHOD_NOT_ALLOWED",
            "security_headers_present": True,
        }
        print(json.dumps(result, sort_keys=True))
        return 0 if passed else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
