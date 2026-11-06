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


A07_SHA = "390499b3c99b2d3b551530be357f2810d6299db7c8cbd8ab182cf8ca2e19db90"
B08_SHA = "a6d5ffb65860fcb33504baefd3c5288c1c75aac0494af248bb3e4c5624cd69bd"
A07_ALLOWED_METADATA = ("CDH_A07_001_REVIEW/input_contract/MANIFEST.json",)


def _redact(text: str, root: Path) -> str:
    variants = {str(root), str(root).replace("\\", "/"), str(Path.home()), str(Path.home()).replace("\\", "/")}
    result = text
    for value in sorted(variants, key=len, reverse=True):
        if value:
            result = result.replace(value, "<PROJECT_ROOT>" if value.casefold().startswith(str(root).casefold()) else "<USER_HOME>")
    return result


def _run(name: str, command: list[str], cwd: Path, log_dir: Path, root: Path, *, env: dict[str, str] | None = None, missing: str | None = None, timeout: int = 420) -> dict:
    result = {"name": name, "command": [_redact(str(value), root) for value in command], "cwd": str(cwd.relative_to(root)) if cwd.is_relative_to(root) else "<ISOLATED_PATH>", "status": None, "return_code": None, "duration_seconds": 0.0, "reason": None}
    if missing:
        result.update(status="NOT_RUN_DEPENDENCY", reason=missing)
        return result
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path, stderr_path = log_dir / f"{name}.stdout.log", log_dir / f"{name}.stderr.log"
    run_env = os.environ.copy(); run_env.update(env or {})
    started = time.monotonic()
    try:
        completed = subprocess.run(command, cwd=cwd, env=run_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=timeout, shell=False, check=False)
        stdout_path.write_text(_redact(completed.stdout, root), encoding="utf-8")
        stderr_path.write_text(_redact(completed.stderr, root), encoding="utf-8")
        result.update(status="PASS" if completed.returncode == 0 else "FAIL", return_code=completed.returncode, duration_seconds=round(time.monotonic() - started, 6), stdout_log=str(stdout_path.relative_to(root)), stderr_log=str(stderr_path.relative_to(root)))
        if completed.returncode: result["reason"] = f"process exited with {completed.returncode}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        result.update(status="ERROR", duration_seconds=round(time.monotonic() - started, 6), reason=_redact(str(exc), root))
    return result


def _find_root(extracted: Path, marker: Path) -> Path:
    matches = [path.parent.parent.parent for path in extracted.rglob(marker.as_posix())]
    if len(matches) != 1:
        raise RuntimeError(f"expected one release root for {marker}, found {len(matches)}")
    # marker apps/price-web/frontend -> rglob returns frontend; climb marker part count.
    current = next(extracted.rglob(marker.as_posix()))
    for _ in marker.parts: current = current.parent
    return current


def _exit_code(suites: list[dict], audits: list[dict]) -> int:
    if not all(item.get("passed") for item in audits): return 4
    states = [item["status"] for item in suites]
    if "ERROR" in states: return 6
    if "FAIL" in states: return 2
    if "NOT_RUN_DEPENDENCY" in states: return 3
    return 0


def _write_junit(path: Path, suites: list[dict], audits: list[dict]) -> None:
    cases = list(suites) + [{"name": f"archive_{index}", "status": "PASS" if item["passed"] else "FAIL", "duration_seconds": 0, "reason": None if item["passed"] else "archive gate failed"} for index, item in enumerate(audits, 1)]
    root = ET.Element("testsuite", name="cdh-g04", tests=str(len(cases)), failures=str(sum(c["status"] == "FAIL" for c in cases)), errors=str(sum(c["status"] == "ERROR" for c in cases)), skipped=str(sum(c["status"] == "NOT_RUN_DEPENDENCY" for c in cases)))
    for case in cases:
        node = ET.SubElement(root, "testcase", classname="tools.ci_web_g04", name=case["name"], time=str(case.get("duration_seconds", 0)))
        if case["status"] == "FAIL": ET.SubElement(node, "failure", message=case.get("reason") or "failure")
        elif case["status"] == "ERROR": ET.SubElement(node, "error", message=case.get("reason") or "error")
        elif case["status"] == "NOT_RUN_DEPENDENCY": ET.SubElement(node, "skipped", message=case.get("reason") or "dependency missing")
    ET.indent(root, space="  "); ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _write_html(path: Path, report: dict) -> None:
    rows = "".join(f"<tr><td>{html.escape(s['name'])}</td><td>{html.escape(s['status'])}</td><td>{html.escape(str(s.get('return_code')))}</td><td>{html.escape(s.get('reason') or '')}</td></tr>" for s in report["suites"])
    cross = report.get("crossline") or {}
    path.write_text("<!doctype html><meta charset='utf-8'><title>CDH G04 preflight</title><style>body{font:15px system-ui;margin:2rem;color:#172033}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd;padding:.5rem;text-align:left}th{background:#eef3f8}</style><h1>CDH G04 current-release preflight</h1><p>Profile: " + html.escape(report["profile"]) + "</p><p>Crossline: " + html.escape(json.dumps(cross.get("summary", {}))) + "</p><table><tr><th>Suite</th><th>Status</th><th>RC</th><th>Reason</th></tr>" + rows + "</table>", encoding="utf-8")


def run(*, root: Path, run_id: str, frontend_zip: Path, frontend_sha: str, backend_zip: Path, backend_sha: str, profile: str, include_headless: bool) -> tuple[dict, int]:
    root = root.resolve(); frontend_zip = frontend_zip.resolve(); backend_zip = backend_zip.resolve()
    report_dir = root / "reports" / "G04" / "runs" / run_id
    isolation = root / "review" / "G04" / "runs" / run_id
    report_dir.mkdir(parents=True, exist_ok=True); isolation.mkdir(parents=True, exist_ok=True)
    allowed = A07_ALLOWED_METADATA if frontend_sha.casefold() == A07_SHA else ()
    audits = [audit_zip(frontend_zip, frontend_sha, allowed_undeclared_metadata=allowed), audit_zip(backend_zip, backend_sha)]
    for item in audits: item["path"] = str(Path(item["path"]).relative_to(root)) if Path(item["path"]).is_relative_to(root) else "<EXTERNAL_INPUT>"
    if not all(item["passed"] for item in audits):
        report = {"schema": "CDH-G04-PREFLIGHT-1", "profile": profile, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "audits": audits, "suites": [], "summary": {"status": "SECURITY_FAILURE", "return_code": 4}}
        (report_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report, 4
    front_extract, back_extract = isolation / "frontend_release", isolation / "backend_release"
    safe_extract(frontend_zip, front_extract); safe_extract(backend_zip, back_extract)
    front_root = _find_root(front_extract, Path("apps/price-web/frontend"))
    back_root = _find_root(back_extract, Path("services/price_query_v3"))
    frontend = front_root / "apps" / "price-web" / "frontend"
    local_frontend = root / "apps" / "price-web" / "frontend"
    local_modules = local_frontend / "node_modules"; local_lock = local_frontend / "package-lock.json"
    node_ok = local_modules.is_dir() and local_lock.is_file() and sha256_file(local_lock) == sha256_file(frontend / "package-lock.json")
    if node_ok:
        target = frontend / "node_modules"
        if not target.exists(): os.symlink(local_modules, target, target_is_directory=True)
    node, npm = shutil.which("node"), shutil.which("npm") or shutil.which("npm.cmd")
    typescript_js = local_modules / "typescript" / "lib" / "typescript.js"
    chrome_candidates = [Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"), Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium"), Path("/usr/bin/chromium-browser")]
    chrome = next((str(path) for path in chrome_candidates if path.is_file()), None)
    temp = isolation / "tmp"; temp.mkdir(parents=True, exist_ok=True)
    env = {"CDH_OFFLINE": "1", "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "TEMP": str(temp), "TMP": str(temp), "CDH_CHROME_PATH": chrome or ""}
    logs = report_dir / "logs"
    fixture_path = isolation / "crossline_fixtures.json"; crossline_path = report_dir / "crossline.json"
    suites = [
        _run("g04_self_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/ci_web_g04", "-v"], root, logs, root, env=env),
        _run("backend_release_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/web/price_query_v3", "-p", "test_*.py", "-v"], back_root, logs, root, env=env),
        _run("build_crossline_fixtures", [sys.executable, "-m", "tools.ci_web_g04.fixture_builder", "--backend-root", str(back_root), "--output", str(fixture_path), "--temp-root", str(isolation / "fixture_tmp")], root, logs, root, env=env),
    ]
    eval_missing = None if node and node_ok and typescript_js.is_file() and suites[-1]["status"] == "PASS" else "matching Node/TypeScript dependency tree or generated fixture unavailable"
    suites.append(_run("evaluate_crossline_contract", [node or "node", str(root / "tools" / "ci_web_g04" / "evaluate_contract.cjs"), str(typescript_js), str(frontend), str(fixture_path), str(crossline_path), profile, str(isolation / "compiled")], root, logs, root, env=env, missing=eval_missing))
    node_missing = None if node and npm and node_ok else "matching immutable frontend dependency tree unavailable; do not install automatically"
    suites.extend([
        _run("frontend_vitest", [node or "node", "node_modules/vitest/vitest.mjs", "run", "--reporter=verbose"], frontend, logs, root, env=env, missing=node_missing),
        _run("frontend_role_tests", [npm or "npm", "run", "test:role"], frontend, logs, root, env=env, missing=node_missing),
        _run("frontend_build", [npm or "npm", "run", "build"], frontend, logs, root, env=env, missing=node_missing),
    ])
    if include_headless:
        suites.append(_run("frontend_headless", [node or "node", "scripts/headless-e2e.mjs"], frontend, logs, root, env=env, missing=None if node_missing is None and chrome else "Chrome/Chromium or matching frontend dependencies unavailable", timeout=480))
    crossline = json.loads(crossline_path.read_text(encoding="utf-8")) if crossline_path.is_file() else None
    code = _exit_code(suites, audits)
    report = {
        "schema": "CDH-G04-PREFLIGHT-1", "task_id": "CDH-G04-CURRENT-RELEASES-CI-PREFLIGHT-001", "authority": "AUTHORIZED_SYNTHETIC_OFFLINE_ONLY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "run_id": run_id, "profile": profile,
        "platform": {"system": platform.system(), "release": platform.release(), "python": platform.python_version(), "node": bool(node), "npm": bool(npm), "chrome": bool(chrome)},
        "inputs": {"frontend": {"zip": str(frontend_zip.relative_to(root)), "sha256": frontend_sha}, "backend": {"zip": str(backend_zip.relative_to(root)), "sha256": backend_sha}},
        "audits": audits, "dependency_lock_match": node_ok, "suites": suites, "crossline": crossline,
        "counters": {"package_install_count": 0, "external_network_access_count": 0, "real_data_access_count": 0, "deployment_count": 0, "real_affiliate_click_count": 0},
        "summary": {"status": ("BASELINE_DEFECTS_REPRODUCED" if profile == "baseline-defects" else "PASS") if code == 0 else "FAIL", "return_code": code, "suite_count": len(suites), "pass_count": sum(item["status"] == "PASS" for item in suites), "fail_count": sum(item["status"] == "FAIL" for item in suites), "not_run_dependency_count": sum(item["status"] == "NOT_RUN_DEPENDENCY" for item in suites), "error_count": sum(item["status"] == "ERROR" for item in suites)},
    }
    (report_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_junit(report_dir / "result.junit.xml", suites, audits); _write_html(report_dir / "result.html", report)
    return report, code
