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


INPUTS = {
    "A06": ("CDH_A06_001_REVIEW.zip", "d9fce75d876b86d5cbb28f77e8ff9354e9d38a5c9389abe10d2a2ddc46adefb5"),
    "B06": ("CDH_B06_001_REVIEW.zip", "d99284c7e6d422b16255b51d29aacb5034a1d43b254c4aca6fa389cef6caf3ae"),
    "B07": ("CDH_B07_001_REVIEW.zip", "f0a597f225233cd635e53c8646ce58ab20422250a8cb357650434eb59d342ee4"),
    "F02": ("CDH_F02_001_REVIEW.zip", "89b4c21f9f28516052f0298b71d71c6d6f82f48daea5d91db81bcbb5815afd73"),
}


def _copy_tree(source: Path, destination: Path, conflicts: list[dict]) -> None:
    for item in sorted(source.rglob("*")):
        if not item.is_file():
            continue
        relative = item.relative_to(source)
        target = destination / relative
        if target.exists():
            before, after = sha256_file(target), sha256_file(item)
            if before != after:
                conflicts.append({"path": relative.as_posix(), "existing_sha256": before, "incoming_sha256": after})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def _run(name: str, command: list[str], cwd: Path, log_dir: Path, env: dict[str, str] | None = None, missing: str | None = None, timeout: int = 360) -> dict:
    result = {"name": name, "command": command, "cwd": str(cwd), "status": None, "return_code": None, "duration_seconds": 0.0, "reason": None}
    if missing:
        result.update(status="NOT_EXECUTED_DEPENDENCY", reason=missing)
        return result
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = log_dir / f"{name}.stdout.log"
    stderr = log_dir / f"{name}.stderr.log"
    run_env = os.environ.copy()
    run_env.update(env or {})
    started = time.monotonic()
    try:
        completed = subprocess.run(command, cwd=cwd, env=run_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=timeout, shell=False, check=False)
        stdout.write_text(completed.stdout, encoding="utf-8")
        stderr.write_text(completed.stderr, encoding="utf-8")
        result.update(status="PASS" if completed.returncode == 0 else "FAIL", return_code=completed.returncode, duration_seconds=round(time.monotonic() - started, 6), stdout_log=str(stdout), stderr_log=str(stderr))
        if completed.returncode:
            result["reason"] = f"process exited with {completed.returncode}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        result.update(status="ERROR", duration_seconds=round(time.monotonic() - started, 6), reason=str(exc))
    return result


def _write_junit(path: Path, suites: list[dict], audits: list[dict]) -> None:
    cases = suites + [{"name": f"archive_{Path(a['path']).stem}", "status": "PASS" if a["passed"] else "FAIL", "duration_seconds": 0, "reason": None if a["passed"] else "archive gate failed"} for a in audits]
    root = ET.Element("testsuite", name="cdh-g03", tests=str(len(cases)), failures=str(sum(c["status"] == "FAIL" for c in cases)), errors=str(sum(c["status"] == "ERROR" for c in cases)), skipped=str(sum(c["status"].startswith("NOT_EXECUTED") for c in cases)))
    for case in cases:
        node = ET.SubElement(root, "testcase", classname="tools.ci_web_g03", name=case["name"], time=str(case.get("duration_seconds", 0)))
        if case["status"] == "FAIL": ET.SubElement(node, "failure", message=case.get("reason") or "failed")
        elif case["status"] == "ERROR": ET.SubElement(node, "error", message=case.get("reason") or "error")
        elif case["status"].startswith("NOT_EXECUTED"): ET.SubElement(node, "skipped", message=case.get("reason") or case["status"])
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _write_html(path: Path, report: dict) -> None:
    rows = "".join(f"<tr><td>{html.escape(s['name'])}</td><td>{html.escape(s['status'])}</td><td>{html.escape(str(s.get('return_code')))}</td><td>{html.escape(s.get('reason') or '')}</td></tr>" for s in report["suites"])
    path.write_text("<!doctype html><meta charset='utf-8'><title>CDH G03 Offline CI</title><style>body{font:15px system-ui;margin:2rem;color:#172033}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd;padding:.5rem;text-align:left}th{background:#eef3f8}.PASS{color:#176b38}</style><h1>CDH G03 Offline CI</h1><p>Generated: " + html.escape(report["generated_at_utc"]) + "</p><table><thead><tr><th>Suite</th><th>Status</th><th>RC</th><th>Reason</th></tr></thead><tbody>" + rows + "</tbody></table>", encoding="utf-8")


def run(root: Path, run_id: str) -> tuple[dict, int]:
    root = root.resolve()
    report_dir = root / "reports" / "G03" / "runs" / run_id
    isolation = root / "review" / "G03" / "runs" / run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    isolation.mkdir(parents=True, exist_ok=True)
    audits = []
    for _, (name, expected) in INPUTS.items():
        audits.append(audit_zip(root / "review" / "releases" / name, expected))
    if not all(a["passed"] for a in audits):
        report = {"schema": "CDH-G03-CI-1", "generated_at_utc": datetime.now(timezone.utc).isoformat(), "audits": audits, "suites": [], "summary": {"status": "SECURITY_FAILURE", "return_code": 4}}
        (report_dir / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report, 4
    inputs_dir, workspace = isolation / "inputs", isolation / "workspace"
    conflicts: list[dict] = []
    for key, (name, _) in INPUTS.items():
        safe_extract(root / "review" / "releases" / name, inputs_dir / key)
    _copy_tree(inputs_dir / "A06" / "apps" / "price-web" / "frontend", workspace / "apps" / "price-web" / "frontend", conflicts)
    _copy_tree(inputs_dir / "A06" / "tests" / "web" / "frontend", workspace / "tests" / "web" / "frontend", conflicts)
    for key, service, tests in (("B06", "price_query", "price_query"), ("B07", "price_quality", "price_quality")):
        _copy_tree(inputs_dir / key / "services" / service, workspace / "services" / service, conflicts)
        _copy_tree(inputs_dir / key / "tests" / "web" / tests, workspace / "tests" / "web" / tests, conflicts)
    froot = inputs_dir / "F02" / "CDH_F02_001_REVIEW"
    for rel in ("services/affiliate_binding_v2", "tests/web/affiliate_binding_v2", "evidence/controlled_inputs"):
        _copy_tree(froot / rel, workspace / rel, conflicts)
    if conflicts:
        (report_dir / "conflicts.json").write_text(json.dumps(conflicts, indent=2) + "\n", encoding="utf-8")
    frontend = workspace / "apps" / "price-web" / "frontend"
    local_modules = root / "apps" / "price-web" / "frontend" / "node_modules"
    local_lock = root / "apps" / "price-web" / "frontend" / "package-lock.json"
    node_ok = local_modules.is_dir() and local_lock.is_file() and sha256_file(local_lock) == sha256_file(frontend / "package-lock.json")
    if node_ok:
        target = frontend / "node_modules"
        if not target.exists():
            os.symlink(local_modules, target, target_is_directory=True)
    node = shutil.which("node")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    python = sys.executable
    chrome_candidates = [Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"), Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium"), Path("/usr/bin/chromium-browser")]
    chrome = next((str(p) for p in chrome_candidates if p.is_file()), None)
    env = {"CDH_OFFLINE": "1", "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "TEMP": str(isolation / "tmp"), "TMP": str(isolation / "tmp")}
    Path(env["TEMP"]).mkdir(parents=True, exist_ok=True)
    suites = [
        _run("g03_self_tests", [python, "-m", "unittest", "discover", "-s", "tests/ci_web_g03", "-v"], root, report_dir / "logs", env),
        _run("b06_price_query", [python, "-m", "unittest", "discover", "-s", "tests/web/price_query", "-p", "test_*.py", "-v"], workspace, report_dir / "logs", env),
        _run("b07_price_quality", [python, "-m", "unittest", "discover", "-s", "tests/web/price_quality", "-p", "test_*.py", "-v"], workspace, report_dir / "logs", env),
        _run("f02_affiliate_binding", [python, "-m", "unittest", "discover", "-s", "tests/web/affiliate_binding_v2", "-p", "test_*.py", "-v"], workspace, report_dir / "logs", env),
        _run("a06_vitest", [node or "node", "node_modules/vitest/vitest.mjs", "run", "--reporter=verbose"], frontend, report_dir / "logs", env, None if npm and node and node_ok else "matching local Node/npm dependencies unavailable"),
        _run("a06_role_tests", [npm or "npm", "run", "test:role"], frontend, report_dir / "logs", env, None if npm and node and node_ok else "matching local Node/npm dependencies unavailable"),
        _run("a06_build", [npm or "npm", "run", "build"], frontend, report_dir / "logs", env, None if npm and node and node_ok else "matching local Node/npm dependencies unavailable"),
        _run("a06_headless", [node or "node", "scripts/headless-e2e.mjs"], frontend, report_dir / "logs", {**env, "CDH_CHROME_PATH": chrome or ""}, None if node and node_ok and chrome else "headless Chrome or matching local Node dependencies unavailable"),
    ]
    # A06 currently pins Windows Chrome. Patch only the isolated adapter copy when needed.
    if suites[-1]["status"] == "FAIL" and chrome:
        script = frontend / "scripts" / "headless-e2e.mjs"
        original = script.read_text(encoding="utf-8")
        needle = "const chromePath = 'C:\\\\Program Files\\\\Google\\\\Chrome\\\\Application\\\\chrome.exe';"
        replacement = "const chromePath = process.env.CDH_CHROME_PATH || 'C:\\\\Program Files\\\\Google\\\\Chrome\\\\Application\\\\chrome.exe';"
        if needle in original:
            script.write_text(original.replace(needle, replacement), encoding="utf-8")
            suites[-1] = _run("a06_headless", [node or "node", "scripts/headless-e2e.mjs"], frontend, report_dir / "logs", {**env, "CDH_CHROME_PATH": chrome}, None, 420)
            suites[-1]["isolated_adapter"] = {"reason": "cross-platform Chrome path injection", "source_archive_unchanged": True}
    statuses = [s["status"] for s in suites]
    code = 5 if conflicts else 6 if "ERROR" in statuses else 2 if "FAIL" in statuses else 3 if any(s.startswith("NOT_EXECUTED") for s in statuses) else 0
    contract_evidence = {
        "SOURCE_BLOCKED": suites[3]["status"] == "PASS",
        "CLICK_DISABLED": suites[4]["status"] == "PASS" and suites[-1]["status"] == "PASS",
        "UNKNOWN_SHIPPING": suites[4]["status"] == "PASS" and suites[-1]["status"] == "PASS",
        "VIEWPORTS": ["1440x1100", "390x844", "1024x900"] if suites[-1]["status"] == "PASS" else [],
        "FRONTEND_BACKEND_CONTRACT": suites[1]["status"] == "PASS" and suites[4]["status"] == "PASS",
    }
    report = {
        "schema": "CDH-G03-CI-1", "generated_at_utc": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
        "platform": {"system": platform.system(), "release": platform.release(), "python": platform.python_version(), "node": node, "npm": npm, "chrome": chrome},
        "authority": "OFFLINE_LOCAL_CI_ONLY", "network_access_count": 0, "package_install_count": 0,
        "audits": audits, "workspace": {"path": str(workspace), "conflicts": conflicts, "node_modules_source": str(local_modules) if node_ok else None, "package_lock_match": node_ok},
        "suites": suites, "contract_evidence": contract_evidence,
        "summary": {"suite_count": len(suites), "pass_count": statuses.count("PASS"), "fail_count": statuses.count("FAIL"), "error_count": statuses.count("ERROR"), "not_executed_dependency_count": statuses.count("NOT_EXECUTED_DEPENDENCY"), "return_code": code, "status": "PASS" if code == 0 else "FAIL"},
    }
    (report_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_junit(report_dir / "result.junit.xml", suites, audits)
    _write_html(report_dir / "result.html", report)
    return report, code
