from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CONTROL = Path(__file__).resolve().parents[1] / "control.py"
A12 = "--a12" in sys.argv
REPORT = ROOT / "reports" / ("A12" if A12 else "A11") / "evidence"
PORT = 4196 if A12 else 4193


def run_control(action: str, *, state: Path, port: int = PORT, expect: int = 0) -> dict[str, object]:
    command = [sys.executable, str(CONTROL), action, "--project-root", str(ROOT), "--port", str(port), "--state-dir", str(state), "--runtime-root", str(REPORT / "runtime"), "--log-dir", str(REPORT / "server_logs"), "--timeout", "20"]
    environment = {**os.environ, "PYTHONUTF8": "1"}
    result = subprocess.run(command, cwd=CONTROL.parent, env=environment, capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=30)
    if result.returncode != expect:
        raise AssertionError(f"control {action} exit={result.returncode}, expected={expect}, stdout={result.stdout}, stderr={result.stderr}")
    text = result.stdout.strip() if expect == 0 else result.stderr.strip()
    return json.loads(text.splitlines()[-1])


def request(method: str, path: str, *, port: int = PORT, host: str | None = None, origin: str | None = None, token: str | None = None) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Host": host or f"127.0.0.1:{port}"}
    if origin:
        headers["Origin"] = origin
    if token:
        headers["X-CDH-Control-Token"] = token
    try:
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        return response.status, {key.lower(): value for key, value in response.getheaders()}, response.read()
    finally:
        connection.close()


def body_json(body: bytes) -> dict[str, object]:
    return json.loads(body.decode("utf-8"))


def check(condition: bool, name: str, observations: dict[str, object], value: object) -> None:
    observations[name] = value
    if not condition:
        raise AssertionError(f"{name}: {value}")


def main() -> int:
    REPORT.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    state = REPORT / f"integration-state-{run_id}"
    observations: dict[str, object] = {"task_id": "CDH-A12-LOCAL-PRICE-DAILY-DOM-AND-SAFE-IMPORT-PREVIEW-001" if A12 else "CDH-A11-WINDOWS-LOCAL-WEB-PREVIEW-001", "run_id": run_id, "port": PORT}
    started = False
    try:
        start = run_control("start", state=state); started = True
        check(start.get("status") == "READY", "start_status", observations, start)
        status, headers, body = request("GET", "/__cdh/health")
        check(status == 200 and body_json(body).get("status") == "READY", "health", observations, {"status": status, "body": body_json(body)})
        status, headers, body = request("GET", "/?mode=synthetic&contract=v4")
        check(status == 200 and b'<div id="root"></div>' in body and "connect-src 'self'" in headers.get("content-security-policy", ""), "static_shell", observations, {"status": status, "content_type": headers.get("content-type"), "csp": headers.get("content-security-policy")})
        status, headers, body = request("GET", "/cdh-coupon-v4/api/v4/products?q=confirmed&page=1&limit=100")
        search = body_json(body)
        check(status == 200 and search.get("schema_version") == "CDH-COUPON-PRICE-V4" and search.get("total") == 1, "actual_b11_search", observations, {"status": status, "total": search.get("total"), "schema": search.get("schema_version"), "etag": headers.get("etag")})
        series_key = search["items"][0]["series_key"]
        status, _, body = request("GET", f"/cdh-coupon-v4/api/v4/products/{series_key}")
        detail = body_json(body)
        check(status == 200 and detail["product"]["display_basis"] == "CONFIRMED_COUPON" and detail["product"]["required_total_twd"] is None and len(detail["history_quality"]["before_coupon"]["daily_representatives"]) > 0, "actual_b11_detail", observations, {"status": status, "series_key": series_key, "display_basis": detail["product"]["display_basis"], "display_price_twd": detail["product"]["display_price_twd"], "required_total_twd": detail["product"]["required_total_twd"], "daily_before_count": len(detail["history_quality"]["before_coupon"]["daily_representatives"])})
        status, _, body = request("GET", "/cdh-coupon-v4/api/v4/products?q=no-such-item&page=1&limit=100")
        empty = body_json(body)
        check(status == 200 and empty.get("total") == 0 and empty.get("items") == [], "empty_search", observations, {"status": status, "total": empty.get("total")})
        status, _, body = request("GET", "/__cdh/health", host="attacker.invalid")
        check(status == 400 and body_json(body).get("error") == "HOST_NOT_ALLOWED", "host_rejection", observations, {"status": status, "body": body_json(body)})
        status, _, body = request("GET", "/__cdh/health", origin="http://attacker.invalid")
        check(status == 403 and body_json(body).get("error") == "ORIGIN_NOT_ALLOWED", "origin_rejection", observations, {"status": status, "body": body_json(body)})
        status, _, body = request("POST", "/__cdh/shutdown", token="wrong-control-token")
        check(status == 403 and body_json(body).get("error") == "CONTROL_TOKEN_INVALID", "wrong_token_rejection", observations, {"status": status, "body": body_json(body)})
        stop = run_control("stop", state=state); started = False
        check(stop.get("status") == "STOPPED", "first_stop", observations, stop)
        restart = run_control("start", state=state); started = True
        check(restart.get("status") == "READY" and restart.get("url") == start.get("url"), "restart_same_port", observations, restart)
        second_stop = run_control("stop", state=state); started = False
        check(second_stop.get("status") == "STOPPED", "second_stop", observations, second_stop)

        conflict_state = REPORT / f"conflict-state-{run_id}"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
            blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            blocker.bind(("127.0.0.1", 0)); blocker.listen(1)
            conflict_port = blocker.getsockname()[1]
            conflict = run_control("start", state=conflict_state, port=conflict_port, expect=2)
        check(conflict.get("status") == "FAILED" and "PORT_IN_USE" in str(conflict.get("error")), "port_conflict", observations, conflict)
        observations["all_pass"] = True
    except Exception as exc:
        observations["all_pass"] = False
        observations["failure"] = repr(exc)
        raise
    finally:
        if started:
            try:
                observations["emergency_stop"] = run_control("stop", state=state)
            except Exception as exc:
                observations["emergency_stop_failure"] = repr(exc)
        result = REPORT / "LOCAL_PREVIEW_INTEGRATION.json"
        result.write_text(json.dumps(observations, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"result": str(result), "all_pass": observations.get("all_pass")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
