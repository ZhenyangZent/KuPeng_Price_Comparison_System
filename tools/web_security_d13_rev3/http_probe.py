from __future__ import annotations

import http.client
import json
import shutil
import sys
import threading
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from targeted_suite import NOW, BatchImportApp, BatchObservationStore, file_body, observation  # noqa: E402


class Quiet(WSGIRequestHandler):
    def log_message(self, format, *args):  # noqa: A003
        return


def send(port, method, path, *, body=None, headers=None):
    raw = b"" if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.putrequest(method, path)
    for key, value in (headers or {}).items():
        connection.putheader(key, value)
    if body is not None:
        connection.putheader("Content-Type", "application/json"); connection.putheader("Content-Length", str(len(raw)))
    connection.endheaders(raw if body is not None else None)
    response = connection.getresponse(); data = response.read()
    result = {"status": response.status, "headers": {key.casefold(): value for key, value in response.getheaders()}, "body": json.loads(data) if data else None}
    connection.close(); return result


def main() -> int:
    work = ROOT / "review/D13/003/http_probe"
    if work.exists():
        if not work.resolve().is_relative_to((ROOT / "review/D13/003").resolve()):
            raise RuntimeError("unsafe cleanup")
        shutil.rmtree(work)
    work.mkdir(parents=True)
    store = BatchObservationStore(work / "private-data", allowed_project_root=work, clock=lambda: NOW)
    app = BatchImportApp(store, baselines={}, clock=lambda: NOW, csrf_token="csrf-d13-r3-http", allowed_origins=("http://127.0.0.1:4173",))
    server = make_server("127.0.0.1", 0, app, handler_class=Quiet); thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        port = server.server_port
        session = send(port, "GET", "/api/private-observations/v1/session")
        body = file_body([observation("SUB-D13-R3-HTTP")])
        headers = {"X-CDH-CSRF-Token": session["body"]["csrf_token"], "Origin": "http://127.0.0.1:4173"}
        preview = send(port, "POST", "/api/private-observations/v1/batch-preview", body=body, headers=headers)
        preview_count = store.observation_count()
        confirm_body = {"schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": preview["body"]["preview_id"], "confirm_token": preview["body"]["confirm_token"], "explicit_confirm": True}
        confirmed = send(port, "POST", "/api/private-observations/v1/batch-confirm", body=confirm_body, headers=headers)
        missing_csrf = send(port, "POST", "/api/private-observations/v1/batch-preview", body=body)
        hostile = send(port, "POST", "/api/private-observations/v1/batch-preview", body=body, headers={"X-CDH-CSRF-Token": session["body"]["csrf_token"], "Origin": "https://evil.invalid"})
        result = {"schema_version": "CDH-D13-B16-REV3-LOOPBACK-HTTP-1", "bind_host": "127.0.0.1", "external_request_count": 0, "session_status": session["status"], "preview_status": preview["status"], "database_count_after_preview": preview_count, "confirm_status": confirmed["status"], "database_count_after_confirm": store.observation_count(), "missing_csrf_status": missing_csrf["status"], "missing_csrf_code": missing_csrf["body"]["error"]["code"], "hostile_origin_status": hostile["status"], "hostile_origin_code": hostile["body"]["error"]["code"], "security_headers_present": all(key in confirmed["headers"] for key in ("cache-control", "content-security-policy", "x-content-type-options", "x-frame-options"))}
        expected = (200, 200, 0, 201, 1, 403, "CSRF_TOKEN_INVALID", 403, "ORIGIN_NOT_ALLOWED", True)
        actual = (result["session_status"], result["preview_status"], result["database_count_after_preview"], result["confirm_status"], result["database_count_after_confirm"], result["missing_csrf_status"], result["missing_csrf_code"], result["hostile_origin_status"], result["hostile_origin_code"], result["security_headers_present"])
        result["gate"] = "PASS" if actual == expected else "FAIL"
        output = ROOT / "review/D13/003/evidence/ACTUAL_LOOPBACK_HTTP.json"; output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, sort_keys=True)); return 0 if result["gate"] == "PASS" else 1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
