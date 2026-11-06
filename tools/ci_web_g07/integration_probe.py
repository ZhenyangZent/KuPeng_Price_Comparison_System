from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0)); return int(sock.getsockname()[1])


def request(port: int, path: str, headers: dict[str, str] | None = None) -> dict:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", path, headers=headers or {})
    response = connection.getresponse(); raw = response.read(); connection.close()
    return {"method": "GET", "path": path, "request_headers": headers or {}, "status": response.status, "response_headers": dict(response.getheaders()), "body": json.loads(raw) if raw else None}


def wait_ready(port: int) -> dict:
    last = None
    for _ in range(50):
        try: return request(port, "/api/v4/products?page=1&limit=20")
        except (ConnectionError, OSError) as exc: last = exc; time.sleep(0.1)
    raise RuntimeError(f"B11 listener not ready: {last}")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--b11-root", type=Path, required=True); parser.add_argument("--f06-root", type=Path, required=True); parser.add_argument("--output", type=Path, required=True); args = parser.parse_args()
    b11 = args.b11_root.resolve(); f06 = args.f06_root.resolve(); output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    active = b11 / "services" / "price_coupon_v4" / "fixtures" / "b11_suite" / "active"
    database, authority = active / "coupon.sqlite3", active / "coupon.authority.json"
    before = {"database": digest(database), "authority": digest(authority)}; port = free_port()
    env = {**os.environ, "PYTHONPATH": str(b11 / "services" / "price_coupon_v4"), "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "CDH_OFFLINE": "1"}
    command = [sys.executable, "-m", "price_coupon_v4.server", "--database-copy", str(database), "--authority-file", str(authority), "--fixture-root", str(active), "--host", "127.0.0.1", "--port", str(port)]
    stdout_path, stderr_path = output / "b11_listener.stdout.log", output / "b11_listener.stderr.log"
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=b11, env=env, stdout=stdout, stderr=stderr, text=True, shell=False)
        try:
            normal = wait_ready(port)
            detail = request(port, "/api/v4/products/confirmed", {"Host": f"127.0.0.1:{port}"})
            hostile_host = request(port, "/api/v4/products", {"Host": "evil.invalid"})
            hostile_origin = request(port, "/api/v4/products", {"Host": f"127.0.0.1:{port}", "Origin": "https://evil.invalid"})
        finally:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
    public = subprocess.run([sys.executable, "-m", "price_coupon_v4.server", "--database-copy", str(database), "--authority-file", str(authority), "--fixture-root", str(active), "--host", "0.0.0.0", "--port", str(free_port()), "--check"], cwd=b11, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", shell=False, check=False)
    after = {"database": digest(database), "authority": digest(authority)}

    sys.path.insert(0, str(f06 / "services" / "affiliate_coupon_gate_v6"))
    from affiliate_coupon_gate_v6 import AffiliateCouponGateV6, AffiliateTrustInput, GateRequest, RuntimeCeiling, adapt_detail_envelope, adapt_search_envelope
    search_items = adapt_search_envelope(normal["body"]); snapshot = adapt_detail_envelope(detail["body"])
    decision = AffiliateCouponGateV6().evaluate(snapshot=snapshot, request=GateRequest(snapshot.series_identity, snapshot.coupon.eligibility_profile, True), affiliate=AffiliateTrustInput("DISABLED", False, None, False, None, ("SOURCE_BLOCKED",)), ceiling=RuntimeCeiling("SOURCE_AUTHORIZATION_REQUIRED", True, False, False, False, None, frozenset(), frozenset()), now=datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc))
    normal_headers = {key.casefold(): value for key, value in normal["response_headers"].items()}
    assertions = {
        "listener_loopback_only": command[command.index("--host") + 1] == "127.0.0.1",
        "real_search_http_200": normal["status"] == 200 and len(normal["body"].get("items", [])) == 9,
        "real_detail_http_200": detail["status"] == 200,
        "f06_parsed_all_search_items": len(search_items) == 9,
        "f06_parsed_detail_identity": snapshot.series_key == "confirmed",
        "coupon_49_before_99": decision.display_price_twd == 49 and decision.before_coupon_price_twd == 99,
        "dual_history": decision.before_coupon_history_count >= 1 and decision.confirmed_after_coupon_history_count >= 1,
        "cta_disabled": decision.cta_enabled is False and decision.click_url is None,
        "hostile_host_rejected": hostile_host["status"] == 400,
        "hostile_origin_rejected": hostile_origin["status"] == 403,
        "no_wildcard_cors": normal_headers.get("access-control-allow-origin") != "*",
        "public_bind_rejected": public.returncode != 0 and "0.0.0.0" in public.stderr,
        "snapshot_read_only": before == after,
    }
    trace = {"schema": "CDH-G07-B11-F06-HTTP-TRACE-1", "listener": {"bind": "127.0.0.1", "port": "<EPHEMERAL>", "command": ["<PYTHON>", "-m", "price_coupon_v4.server", "...", "--host", "127.0.0.1", "--port", "<EPHEMERAL>"]}, "requests": {"normal_search": normal, "detail": detail, "hostile_host": hostile_host, "hostile_origin": hostile_origin}, "public_bind_probe": {"return_code": public.returncode, "stderr": public.stderr}, "read_only_hashes": {"before": before, "after": after}}
    result = {"schema": "CDH-G07-B11-F06-EXACT-1", "assertions": assertions, "decision": {"display_price_twd": decision.display_price_twd, "before_coupon_price_twd": decision.before_coupon_price_twd, "display_basis": decision.display_basis, "cta_enabled": decision.cta_enabled, "click_url": decision.click_url, "reason_codes": list(decision.reason_codes)}, "passed": all(assertions.values())}
    (output / "http_trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "integration_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True)); return 0 if result["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
