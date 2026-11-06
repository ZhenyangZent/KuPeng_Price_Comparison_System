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
B16 = ROOT / "review" / "D13" / "002" / "input" / "CDH_B_R12_002_REVIEW"
sys.path.insert(0, str(B16 / "services" / "private_batch_import_b16"))
sys.path.insert(0, str(B16 / "services" / "private_observation_b15"))
from private_batch_import_b16.api import BatchImportApp  # noqa: E402
from private_batch_import_b16.store import BatchObservationStore  # noqa: E402


NOW = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):  # noqa: A003
        return


def send(port, method, path, *, body=None, headers=None, skip_host=False):
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
    data = response.read()
    result = {"status": response.status, "headers": {key.casefold(): value for key, value in response.getheaders()}, "body": json.loads(data) if data else None}
    connection.close()
    return result


def main() -> int:
    work = ROOT / "review" / "D13" / "002" / "http_probe"
    if work.exists():
        if not work.resolve().is_relative_to((ROOT / "review" / "D13" / "002").resolve()):
            raise RuntimeError("unsafe cleanup target")
        shutil.rmtree(work)
    work.mkdir(parents=True)
    store = BatchObservationStore(work / "private-data", allowed_project_root=work, clock=lambda: NOW)
    app = BatchImportApp(store, baselines={}, clock=lambda: NOW, csrf_token="csrf-d13-r2-http", allowed_origins=("http://127.0.0.1:4173",))
    server = make_server("127.0.0.1", 0, app, handler_class=QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        session = send(port, "GET", "/api/private-observations/v1/session")
        row = {"schema_version": "CDH-B15-MANUAL-OBSERVATION-1", "submission_id": "SUB-D13-R2-HTTP", "title": "D13 REV2 HTTP", "identity": {"platform": "COUPANG_TW", "product_id": "PROD-D13-R2-HTTP", "sku_id": "SKU-D13-R2", "seller_id": "SELLER-D13", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD"}, "observed_at": "2026-11-03T12:00:00+08:00", "quantity": 1, "before_coupon_price_twd": 1000, "user_reported_coupon": {"status": "USER_REPORTED", "price_twd": 900, "eligibility": "USER_ASSERTED_ELIGIBLE", "evidence_level": "USER_DESCRIPTION", "evidence_note": "D13 REV2 HTTP", "valid_from": None, "valid_until": None}, "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None}, "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "D13 REV2 HTTP"}}
        content = json.dumps({"schema_version": "CDH-B16-BATCH-FILE-1", "observations": [row]}, separators=(",", ":")).encode("utf-8")
        preview_request = {"schema_version": "CDH-B16-BATCH-PREVIEW-REQUEST-1", "filename": "http.json", "media_type": "application/json", "content_base64": base64.b64encode(content).decode("ascii")}
        authorized = {"X-CDH-CSRF-Token": session["body"]["csrf_token"], "Origin": "http://127.0.0.1:4173"}
        preview = send(port, "POST", "/api/private-observations/v1/batch-preview", body=preview_request, headers=authorized)
        count_after_preview = store.observation_count()
        confirm_request = {"schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": preview["body"]["preview_id"], "confirm_token": preview["body"]["confirm_token"], "explicit_confirm": True}
        confirm = send(port, "POST", "/api/private-observations/v1/batch-confirm", body=confirm_request, headers=authorized)
        count_after_confirm = store.observation_count()
        missing_csrf = send(port, "POST", "/api/private-observations/v1/batch-preview", body=preview_request)
        hostile_origin = send(port, "POST", "/api/private-observations/v1/batch-preview", body=preview_request, headers={"X-CDH-CSRF-Token": session["body"]["csrf_token"], "Origin": "https://evil.invalid"})
        result = {"schema_version": "CDH-D13-B16-REV2-LOOPBACK-HTTP-1", "bind_host": "127.0.0.1", "external_request_count": 0, "session_status": session["status"], "preview_status": preview["status"], "database_count_after_preview": count_after_preview, "confirm_status": confirm["status"], "database_count_after_confirm": count_after_confirm, "missing_csrf_status": missing_csrf["status"], "missing_csrf_code": missing_csrf["body"]["error"]["code"], "hostile_origin_status": hostile_origin["status"], "hostile_origin_code": hostile_origin["body"]["error"]["code"], "host_gate": "COVERED_BY_DIRECT_WSGI_TARGETED_SUITE", "security_headers_present": all(key in confirm["headers"] for key in ("cache-control", "content-security-policy", "x-content-type-options", "x-frame-options"))}
        evidence = ROOT / "review" / "D13" / "002" / "evidence" / "ACTUAL_LOOPBACK_HTTP.json"
        evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, sort_keys=True))
        expected = (200, 200, 0, 201, 1, 403, "CSRF_TOKEN_INVALID", 403, "ORIGIN_NOT_ALLOWED", True)
        actual = (result["session_status"], result["preview_status"], result["database_count_after_preview"], result["confirm_status"], result["database_count_after_confirm"], result["missing_csrf_status"], result["missing_csrf_code"], result["hostile_origin_status"], result["hostile_origin_code"], result["security_headers_present"])
        return 0 if actual == expected else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
