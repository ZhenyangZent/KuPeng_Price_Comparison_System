from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .a10_gate import evaluate as evaluate_a10
from .audit import audit_controlled_release, safe_extract, sha256_file


def _run(name: str, command: list[str], cwd: Path, log_dir: Path, env: dict[str, str], timeout: int = 600) -> dict:
    log_dir.mkdir(parents=True, exist_ok=True); started = time.monotonic()
    try:
        process = subprocess.run(command, cwd=cwd, env={**os.environ, **env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=timeout, shell=False, check=False)
        (log_dir / f"{name}.stdout.log").write_text(process.stdout, encoding="utf-8"); (log_dir / f"{name}.stderr.log").write_text(process.stderr, encoding="utf-8")
        return {"name": name, "status": "PASS" if process.returncode == 0 else "FAIL", "return_code": process.returncode, "duration_seconds": round(time.monotonic() - started, 6), "stdout_log": str((log_dir / f"{name}.stdout.log").as_posix()), "stderr_log": str((log_dir / f"{name}.stderr.log").as_posix()), "reason": None if process.returncode == 0 else f"process exited with {process.returncode}"}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"name": name, "status": "ERROR", "return_code": None, "duration_seconds": round(time.monotonic() - started, 6), "reason": str(exc)}


def _root(extracted: Path, marker: Path) -> Path:
    matches = list(extracted.rglob(marker.as_posix()))
    if len(matches) != 1: raise RuntimeError(f"expected one {marker}, found {len(matches)}")
    value = matches[0]
    for _ in marker.parts: value = value.parent
    return value


def _tree_identity(paths: list[Path], base: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(base).as_posix().encode()); digest.update(b"\0"); digest.update(path.read_bytes()); digest.update(b"\0")
    return digest.hexdigest()


def run(*, root: Path, run_id: str, b11_zip: Path, b11_sha: str, f06_zip: Path, f06_sha: str, a10_candidate: Path, receipt_ack: Path, a10_sha: str | None = None, a10_lock_sha: str | None = None) -> tuple[dict, int]:
    root = root.resolve(); report_dir = root / "reports" / "G07" / "runs" / run_id; isolation = root / "review" / "G07" / "runs" / run_id
    report_dir.mkdir(parents=True, exist_ok=True); isolation.mkdir(parents=True, exist_ok=True); logs = report_dir / "raw" / "logs"
    audits = {"B11": audit_controlled_release(b11_zip.resolve(), b11_sha, "B11"), "F06": audit_controlled_release(f06_zip.resolve(), f06_sha, "F06")}
    a10_gate = evaluate_a10(candidate=a10_candidate.resolve(), receipt_ack=receipt_ack.resolve(), explicit_sha256=a10_sha, explicit_lock_sha256=a10_lock_sha)
    suites: list[dict] = []; code = 0
    if not all(value["passed"] for value in audits.values()):
        status, code = "FAIL_CONTROLLED_INPUT_GATE", 4
    else:
        b_extract, f_extract = isolation / "B11", isolation / "F06"; safe_extract(b11_zip, b_extract); safe_extract(f06_zip, f_extract)
        b11 = _root(b_extract, Path("services/price_coupon_v4")); f06 = _root(f_extract, Path("services/affiliate_coupon_gate_v6"))
        temp = isolation / "tmp"; temp.mkdir(parents=True, exist_ok=True)
        env = {"CDH_OFFLINE": "1", "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "TEMP": str(temp), "TMP": str(temp)}
        suites.append(_run("g07_self_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/ci_web_g07", "-v"], root, logs, env))
        suites.append(_run("b11_coupon_v4_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/web/price_coupon_v4", "-p", "test_*.py", "-v"], b11, logs, env))
        suites.append(_run("b11_price_query_v3_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/web/price_query_v3", "-p", "test_*.py", "-v"], b11, logs, env))
        suites.append(_run("f06_release_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/affiliate_coupon_gate_v6", "-v"], f06, logs, env))
        evidence = report_dir / "raw" / "b11_f06"
        suites.append(_run("b11_listener_f06_exact", [sys.executable, "-m", "tools.ci_web_g07.integration_probe", "--b11-root", str(b11), "--f06-root", str(f06), "--output", str(evidence)], root, logs, env))
        failed = [item for item in suites if item["status"] != "PASS"]
        status, code = ("PASS_SCOPED_B11_READY_A10_BLOCKED", 0) if not failed else ("FAIL", 2)
        b_sources = list((b11 / "services" / "price_coupon_v4" / "price_coupon_v4").glob("*.py")); f_sources = list((f06 / "services" / "affiliate_coupon_gate_v6" / "affiliate_coupon_gate_v6").glob("*.py"))
        dependency_identity = {"python": platform.python_version(), "b11_python_tree_sha256": _tree_identity(b_sources, b11), "f06_python_tree_sha256": _tree_identity(f_sources, f06), "lockfiles": [], "package_install_count": 0, "note": "stdlib B11 plus exact F06 source; no lockfile declared in either release"}
    report = {"schema": "CDH-G07-B11-EXACT-CI-READINESS-1", "task_id": "CDH-G07-B11-EXACT-CI-READINESS-001", "generated_at_utc": datetime.now(timezone.utc).isoformat(), "authority": "AUTHORIZED_SYNTHETIC_OFFLINE_LOOPBACK_ONLY", "run_id": run_id, "platform": {"system": platform.system(), "release": platform.release(), "python": platform.python_version()}, "inputs": {"B11": {"path": str(b11_zip), "expected_sha256": b11_sha}, "F06": {"path": str(f06_zip), "expected_sha256": f06_sha}}, "audits": audits, "dependency_identity": locals().get("dependency_identity", {}), "suites": suites, "os_jobs": {"windows": "PASS" if platform.system() == "Windows" and code == 0 else "NOT_RUN_OS_UNAVAILABLE" if platform.system() != "Windows" else "FAIL", "linux": "PASS" if platform.system() == "Linux" and code == 0 else "NOT_RUN_OS_UNAVAILABLE" if platform.system() != "Linux" else "FAIL"}, "a10_browser_gate": a10_gate, "exact_a10_b11_browser_status": "NOT_RUN_INPUT_UNAVAILABLE" if a10_gate["status"] != "READY_FOR_EXACT_BROWSER_EXECUTION" else "NOT_RUN_EXECUTION_NOT_AUTHORIZED", "counters": {"package_install_count": 0, "external_network_access_count": 0, "real_data_access_count": 0, "browser_execution_count": 0, "deployment_count": 0, "affiliate_click_count": 0, "transaction_count": 0}, "summary": {"status": status, "return_code": code, "suite_count": len(suites), "pass_count": sum(item["status"] == "PASS" for item in suites), "fail_count": sum(item["status"] == "FAIL" for item in suites), "error_count": sum(item["status"] == "ERROR" for item in suites)}}
    (report_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report, code
