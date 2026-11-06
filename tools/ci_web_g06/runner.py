from __future__ import annotations

import html
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from .audit import audit_zip, safe_extract, sha256_file


def _redact(text: str, root: Path) -> str:
    values = {str(root.resolve()), str(root.resolve()).replace("\\", "/"), str(Path.home()), str(Path.home()).replace("\\", "/")}
    for value in sorted(values, key=len, reverse=True):
        if value: text = text.replace(value, "<PROJECT_ROOT>" if value.casefold().startswith(str(root.resolve()).casefold()) else "<USER_HOME>")
    return text


def _execute(name: str, command: list[str], cwd: Path, log_dir: Path, root: Path, *, env: dict[str, str] | None = None, missing_reason: str | None = None, timeout: int = 300) -> dict:
    record = {"name": name, "command": [_redact(str(value), root) for value in command], "cwd": str(cwd.relative_to(root)) if cwd.is_relative_to(root) else "<ISOLATED>", "status": None, "return_code": None, "duration_seconds": 0.0, "reason": missing_reason}
    if missing_reason:
        record["status"] = "NOT_RUN_DEPENDENCY_UNAVAILABLE"; return record
    log_dir.mkdir(parents=True, exist_ok=True); started = time.monotonic()
    try:
        process = subprocess.run(command, cwd=cwd, env={**os.environ, **(env or {})}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=timeout, shell=False, check=False)
        (log_dir / f"{name}.stdout.log").write_text(_redact(process.stdout, root), encoding="utf-8")
        (log_dir / f"{name}.stderr.log").write_text(_redact(process.stderr, root), encoding="utf-8")
        record.update(status="PASS" if process.returncode == 0 else "FAIL", return_code=process.returncode, duration_seconds=round(time.monotonic() - started, 6), stdout_log=str((log_dir / f"{name}.stdout.log").relative_to(root)), stderr_log=str((log_dir / f"{name}.stderr.log").relative_to(root)), reason=None if process.returncode == 0 else f"process exited with {process.returncode}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        record.update(status="ERROR", duration_seconds=round(time.monotonic() - started, 6), reason=_redact(str(exc), root))
    return record


def _release_root(extracted: Path, marker: Path) -> Path:
    matches = list(extracted.rglob(marker.as_posix()))
    if len(matches) != 1: raise RuntimeError(f"expected one {marker}; found {len(matches)}")
    current = matches[0]
    for _ in marker.parts: current = current.parent
    return current


def _version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=10, shell=False, check=False)
        return result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired): return None


def _chrome() -> tuple[str | None, str | None]:
    candidates = [Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"), Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"), Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"), Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium")]
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None: return None, None
    version = None
    if os.name == "nt":
        try:
            script = f"(Get-Item -LiteralPath '{str(executable).replace("'", "''")}').VersionInfo.ProductVersion"
            version = _version(["powershell", "-NoProfile", "-Command", script])
        except OSError: pass
    return str(executable), version or _version([str(executable), "--version"])


def _write_junit(path: Path, suites: list[dict], audits: list[dict]) -> None:
    cases = list(suites) + [{"name": f"archive_{index}", "status": "PASS" if item["passed"] else "FAIL", "reason": None if item["passed"] else item.get("error", "archive gate failed"), "duration_seconds": 0} for index, item in enumerate(audits, 1)]
    root = ET.Element("testsuite", name="cdh-g06", tests=str(len(cases)), failures=str(sum(case["status"] == "FAIL" for case in cases)), errors=str(sum(case["status"] == "ERROR" for case in cases)), skipped=str(sum(case["status"].startswith("NOT_RUN") for case in cases)))
    for case in cases:
        node = ET.SubElement(root, "testcase", classname="tools.ci_web_g06", name=case["name"], time=str(case.get("duration_seconds", 0)))
        if case["status"] == "FAIL": ET.SubElement(node, "failure", message=case.get("reason") or "failure")
        elif case["status"] == "ERROR": ET.SubElement(node, "error", message=case.get("reason") or "error")
        elif case["status"].startswith("NOT_RUN"): ET.SubElement(node, "skipped", message=case.get("reason") or "not run")
    ET.indent(root, space=" "); ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _write_html(path: Path, report: dict) -> None:
    rows = "".join(f"<tr><td>{html.escape(case['name'])}</td><td>{html.escape(case['status'])}</td><td>{html.escape(str(case.get('return_code')))}</td><td>{html.escape(case.get('reason') or '')}</td></tr>" for case in report["suites"])
    path.write_text("<!doctype html><meta charset='utf-8'><title>CDH G06</title><style>body{font:15px system-ui;margin:2rem;color:#182131}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd;padding:.5rem;text-align:left}th{background:#eef3f8}</style><h1>G06 exact-release V4 verification</h1><p>Profile: " + html.escape(report["profile"]) + "</p><p>Status: " + html.escape(report["summary"]["status"]) + "</p><table><tr><th>Suite</th><th>Status</th><th>RC</th><th>Reason</th></tr>" + rows + "</table>", encoding="utf-8")


def run(*, root: Path, run_id: str, frontend_zip: Path, frontend_sha: str, backend_zip: Path, backend_sha: str, profile: str) -> tuple[dict, int]:
    root = root.resolve(); frontend_zip = frontend_zip.resolve(); backend_zip = backend_zip.resolve()
    report_dir = root / "reports" / "G06" / "runs" / run_id; isolate = root / "review" / "G06" / "runs" / run_id
    report_dir.mkdir(parents=True, exist_ok=True); isolate.mkdir(parents=True, exist_ok=True)
    node = shutil.which("node"); chrome, chrome_version = _chrome()
    platform_info = {"system": platform.system(), "release": platform.release(), "python": platform.python_version(), "node": _version([node, "--version"]) if node else None, "chrome": chrome_version}
    inputs_missing = not frontend_zip.is_file() or not backend_zip.is_file()
    audits = [audit_zip(frontend_zip, frontend_sha), audit_zip(backend_zip, backend_sha)]
    for audit in audits:
        path = Path(audit["path"]); audit["path"] = str(path.relative_to(root)) if path.is_relative_to(root) else "<EXTERNAL_INPUT>"
    suites: list[dict] = []
    base = {"schema": "CDH-G06-EXACT-RELEASE-V4-E2E-1", "task_id": "CDH-G06-EXACT-RELEASE-V4-E2E-CI-001", "authority": "AUTHORIZED_SYNTHETIC_OFFLINE_LOOPBACK_ONLY", "generated_at_utc": datetime.now(timezone.utc).isoformat(), "run_id": run_id, "profile": profile, "platform": platform_info, "inputs": {"frontend": {"zip": str(frontend_zip.relative_to(root)) if frontend_zip.is_relative_to(root) else "<EXTERNAL_INPUT>", "sha256": frontend_sha}, "backend": {"zip": str(backend_zip.relative_to(root)) if backend_zip.is_relative_to(root) else "<EXTERNAL_INPUT>", "sha256": backend_sha}}, "audits": audits, "suites": suites, "counters": {"package_install_count": 0, "external_network_access_count": 0, "real_data_access_count": 0, "real_affiliate_click_count": 0, "deployment_count": 0, "transaction_count": 0}}
    if inputs_missing:
        status, code = "NOT_RUN_INPUT_UNAVAILABLE", 3
    elif not all(audit["passed"] for audit in audits):
        status, code = "FAIL_ARCHIVE_OR_SECRET_GATE", 4
    else:
        front_extract, back_extract = isolate / "frontend_release", isolate / "backend_release"
        safe_extract(frontend_zip, front_extract); safe_extract(backend_zip, back_extract)
        try:
            frontend_root = _release_root(front_extract, Path("apps/price-web/frontend")); backend_root = _release_root(back_extract, Path("services/price_coupon_v4"))
        except RuntimeError as exc:
            suites.append({"name": "release_layout", "status": "FAIL", "return_code": None, "duration_seconds": 0, "reason": str(exc)})
            status, code = "FAIL_RELEASE_LAYOUT", 2
        else:
            frontend = frontend_root / "apps" / "price-web" / "frontend"; logs = report_dir / "logs"
            env = {"CDH_OFFLINE": "1", "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "CDH_CHROME_PATH": chrome or ""}
            suites.append(_execute("g06_self_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/ci_web_g06", "-v"], root, logs, root, env=env))
            suites.append(_execute("backend_release_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/web/price_coupon_v4", "-p", "test_*.py", "-v"], backend_root, logs, root, env=env))
            probe_dir = report_dir / "evidence" / "real_wsgi"
            suites.append(_execute("real_wsgi_search_detail", [sys.executable, "-m", "tools.ci_web_g06.wsgi_probe", "--backend-root", str(backend_root), "--output", str(probe_dir)], root, logs, root, env=env))
            if profile == "a09-b10-expected-fail":
                local_modules = root / "apps" / "price-web" / "frontend" / "node_modules"; lock = root / "apps" / "price-web" / "frontend" / "package-lock.json"
                exact_lock = frontend / "package-lock.json"; lock_match = lock.is_file() and exact_lock.is_file() and sha256_file(lock) == sha256_file(exact_lock)
                tsc = local_modules / "typescript" / "lib" / "tsc.js"; compiled = isolate / "compiled_a09"; compiled.mkdir(parents=True, exist_ok=True)
                dependency_reason = None if node and tsc.is_file() and lock_match else "matching immutable Node/TypeScript dependency tree unavailable"
                suites.append(_execute("compile_exact_a09_parser", [node or "node", str(tsc), "--target", "ES2022", "--module", "commonjs", "--moduleResolution", "node", "--skipLibCheck", "--outDir", str(compiled), str(frontend / "src" / "couponTypes.ts"), str(frontend / "src" / "couponRuntimeSchema.ts")], root, logs, root, env=env, missing_reason=dependency_reason))
                (compiled / "package.json").write_text('{"type":"commonjs"}\n', encoding="utf-8")
                parser_missing = None if suites[-1]["status"] == "PASS" and suites[-2]["status"] == "PASS" else "compiled exact A09 parser or real B10 HTTP evidence unavailable"
                suites.append(_execute("expected_wire_failure", [node or "node", str(root / "tools" / "ci_web_g06" / "parser_probe.cjs"), str(compiled / "couponRuntimeSchema.js"), str(probe_dir / "api_responses.json"), str(report_dir / "evidence" / "a09_b10_parser_failure.json")], root, logs, root, env=env, missing_reason=parser_missing))
                failed = any(case["status"] in {"FAIL", "ERROR"} for case in suites); skipped = any(case["status"].startswith("NOT_RUN") for case in suites)
                status, code = ("EXPECTED_WIRE_FAILURE_REPRODUCED", 0) if not failed and not skipped else (("NOT_RUN_DEPENDENCY_UNAVAILABLE", 3) if skipped and not failed else ("FAIL", 2))
            else:
                # The exact gate is deliberately release-owned: no G-side stub, frozen HTML, or fixture can stand in for A10/B11.
                entry = frontend / "scripts" / "g06-exact-e2e.mjs"
                reason = "exact A10/B11 release E2E entrypoint scripts/g06-exact-e2e.mjs unavailable" if not entry.is_file() else "B11 continuous WSGI/browser orchestration adapter requires received contract discovery"
                suites.append({"name": "exact_browser_search_detail_dom", "status": "NOT_RUN_DEPENDENCY_UNAVAILABLE", "return_code": None, "duration_seconds": 0, "reason": reason})
                status, code = "NOT_RUN_DEPENDENCY_UNAVAILABLE", 3
    probe_path = report_dir / "evidence" / "real_wsgi" / "wsgi_probe.json"
    base["backend_semantic_gates"] = json.loads(probe_path.read_text(encoding="utf-8"))["assertions"] if probe_path.is_file() else {}
    exact_reason = "NOT_RUN_INPUT_UNAVAILABLE" if inputs_missing else ("NOT_RUN_DEPENDENCY_UNAVAILABLE" if profile != "a10-b11-exact" or code == 3 else "UNKNOWN")
    base["exact_a10_b11_gates"] = {
        "real_b11_wsgi_browser_search_detail": exact_reason,
        "dom_coupon_49_and_base_99": exact_reason,
        "dom_dual_history": exact_reason,
        "dom_price_unknown": exact_reason,
        "dom_zero_unknown_shipping": exact_reason,
        "dom_quantity_over_one": exact_reason,
        "dom_expired_coupon": exact_reason,
        "dom_revoked_source": exact_reason,
        "dom_cta_disabled": exact_reason,
        "screenshots": exact_reason,
        "har_or_equivalent_network_trace": exact_reason,
    }
    base["summary"] = {"status": status, "return_code": code, "suite_count": len(suites), "pass_count": sum(case["status"] == "PASS" for case in suites), "fail_count": sum(case["status"] == "FAIL" for case in suites), "error_count": sum(case["status"] == "ERROR" for case in suites), "not_run_count": sum(case["status"].startswith("NOT_RUN") for case in suites)}
    (report_dir / "result.json").write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_junit(report_dir / "result.junit.xml", suites, audits); _write_html(report_dir / "result.html", base)
    return base, code
