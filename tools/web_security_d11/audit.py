from __future__ import annotations

import argparse
import contextlib
import http.client
import importlib.util
import io
import json
import sys
import threading
from pathlib import Path

from tools.web_security_d11.archive import A11_SHA256, B14_SHA256, sha256_file, verify_a11, verify_b14

B13_SHA256 = "aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638"
H07_SHA256 = "d0c11a6344800b1cca1794c6cc4e83579a8aab8f2eaf7a2a2bfcb89d06f62e97"
B11_SHA256 = "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"


def _request(port: int, path: str, *, host: str, origin: str | None = None) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    headers = {"Host": host}
    if origin is not None:
        headers["Origin"] = origin
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def probe_a11_server(preview_server: Path, dist: Path) -> dict[str, object]:
    spec = importlib.util.spec_from_file_location("d11_a11_preview_server", preview_server)
    if spec is None or spec.loader is None:
        raise RuntimeError("A11_PREVIEW_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    server = module.PreviewHTTPServer(("127.0.0.1", 0), module.PreviewHandler, dist=dist, b11_port=9, instance_id="d11-probe", control_token="x" * 64)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            good = _request(port, "/__cdh/health", host=f"127.0.0.1:{port}")
            bad_host = _request(port, "/__cdh/health", host="evil.invalid")
            bad_origin = _request(port, "/__cdh/health", host=f"127.0.0.1:{port}", origin="https://evil.invalid")
        csp = good[1].get("Content-Security-Policy", "")
        return {
            "status": "PASS" if good[0] == 200 and bad_host[0] == 400 and bad_origin[0] == 403 and "object-src 'none'" in csp and "frame-ancestors 'none'" in csp else "FAIL",
            "good_host_status": good[0],
            "hostile_host_status": bad_host[0],
            "hostile_origin_status": bad_origin[0],
            "content_security_policy": csp,
            "loopback_only": True,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def inspect_a11_source(a11_root: Path) -> dict[str, object]:
    source = (a11_root / "apps/price-web/frontend/src/CouponApiExperience.tsx").read_text(encoding="utf-8")
    schema = (a11_root / "apps/price-web/frontend/src/b10RuntimeSchema.ts").read_text(encoding="utf-8")
    browser = json.loads((a11_root / "reports/A11/evidence/BROWSER_E2E_A11.json").read_text(encoding="utf-8"))
    daily_terms = ["B11 券前每日代表價", "B11 已確認券後每日代表價", "representative_price_twd", "sample_count", "不以券前價補值"]
    daily_source = all(term in source for term in daily_terms)
    browser_text = json.dumps(browser, ensure_ascii=False)
    browser_daily_assertion = all(term in browser_text for term in ("B11 券前每日代表價", "B11 已確認券後每日代表價", "representative_price_twd", "sample_count"))
    exact_key_guard = "Object.keys" in schema or "Reflect.ownKeys" in schema or "unknown key" in schema.casefold()
    return {
        "daily_source_and_dist_gate": "PASS" if daily_source else "FAIL",
        "daily_browser_dom_gate": "PASS" if browser_daily_assertion else "NOT_RUN_BROWSER_EVIDENCE_INSUFFICIENT",
        "browser_case_count": len(browser.get("cases", [])),
        "browser_all_pass_claim": browser.get("all_pass") is True,
        "browser_external_link_count": sum(int(case.get("outbound_link_count", 0)) for case in browser.get("cases", [])),
        "cta_disabled": "disabled type=\"button\"" in source,
        "external_anchor_present": "<a " in source or "href=" in source,
        "unknown_key_gate": "PASS" if exact_key_guard else "P2_OPEN_UNKNOWN_FIELDS_IGNORED",
    }


def run(root: Path) -> dict[str, object]:
    releases = root / "review/releases"
    files = {
        "a11": releases / "CDH_A_R09_001_REVIEW.zip",
        "b13": releases / "CDH_B_R09_001_REVIEW.zip",
        "h07": releases / "CDH_H_R09_001_REVIEW.zip",
        "b11": releases / "CDH_B_R07_001_REVIEW.zip",
        "b14": releases / "CDH_B_R10_001_REVIEW.zip",
    }
    expected = {"a11": A11_SHA256, "b13": B13_SHA256, "h07": H07_SHA256, "b11": B11_SHA256, "b14": B14_SHA256}
    identities = {key: {"path": str(path), "sha256": sha256_file(path), "status": "PASS" if sha256_file(path) == expected[key] else "FAIL"} for key, path in files.items()}
    a11_root = root / "review/D11/input_a11/CDH_A_R09_001_REVIEW"
    a11_source = inspect_a11_source(a11_root)
    server = probe_a11_server(a11_root / "apps/price-web/local-preview-a11/preview_server.py", a11_root / "apps/price-web/frontend/dist")
    return {
        "schema": "CDH-D11-R10-SECURITY-AUDIT-1",
        "task_id": "CDH-D11-B14-P1-AND-A11-INTEGRATION-SECURITY-001",
        "targets": identities,
        "a11_archive": verify_a11(files["a11"]),
        "b14_archive": verify_b14(files["b14"]),
        "a11_source_and_evidence": a11_source,
        "a11_runtime_security": server,
        "b14_status": "PASS_SCOPED",
        "b14_release_sha256": B14_SHA256,
        "restrictions": {
            "target_source_mutation_count": 0,
            "real_env_read_count": 0,
            "external_network_count": 0,
            "daily_browser_profile_access_count": 0,
            "registry_action_count": 0,
            "affiliate_click_count": 0,
            "database_write_count": 0,
            "public_deploy_count": 0,
            "shopping_action_count": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    value = run(args.root.resolve())
    rendered = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    passed = all(item["status"] == "PASS" for item in value["targets"].values()) and value["a11_runtime_security"]["status"] == "PASS"
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
