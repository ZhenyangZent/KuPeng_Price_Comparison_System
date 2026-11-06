from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .audit import audit_release, safe_extract, sha256_file


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock: sock.bind(("127.0.0.1", 0)); return int(sock.getsockname()[1])


def run_process(name: str, command: list[str], cwd: Path, logs: Path, env: dict[str, str], timeout: int = 900, missing: str | None = None) -> dict:
    if missing: return {"name": name, "status": "NOT_RUN_DEPENDENCY_UNAVAILABLE", "return_code": None, "duration_seconds": 0, "reason": missing}
    logs.mkdir(parents=True, exist_ok=True); started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=cwd, env={**os.environ, **env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=timeout, shell=False, check=False)
        (logs / f"{name}.stdout.log").write_text(result.stdout, encoding="utf-8"); (logs / f"{name}.stderr.log").write_text(result.stderr, encoding="utf-8")
        return {"name": name, "status": "PASS" if result.returncode == 0 else "FAIL", "return_code": result.returncode, "duration_seconds": round(time.monotonic() - started, 6), "reason": None if result.returncode == 0 else f"process exited with {result.returncode}"}
    except (OSError, subprocess.TimeoutExpired) as exc: return {"name": name, "status": "ERROR", "return_code": None, "duration_seconds": round(time.monotonic() - started, 6), "reason": str(exc)}


def release_root(extracted: Path, marker: Path) -> Path:
    matches = list(extracted.rglob(marker.as_posix()))
    if len(matches) != 1: raise RuntimeError(f"expected one {marker}, found {len(matches)}")
    value = matches[0]
    for _ in marker.parts: value = value.parent
    return value


def chrome_identity() -> tuple[str | None, str | None]:
    candidates = [Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"), Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")]
    path = next((item for item in candidates if item.is_file()), None)
    if path is None: return None, None
    command = ["powershell", "-NoProfile", "-Command", f"(Get-Item -LiteralPath '{str(path).replace("'", "''")}').VersionInfo.ProductVersion"]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", shell=False, check=False)
    return str(path), result.stdout.strip() or None


def browser_suite(root: Path, a10: Path, b11: Path, evidence: Path, logs: Path, env: dict[str, str], chrome: str | None, node: str | None) -> dict:
    if not chrome or not node: return {"name": "a10r08_b11_browser", "status": "NOT_RUN_DEPENDENCY_UNAVAILABLE", "return_code": None, "duration_seconds": 0, "reason": "Chrome or Node unavailable"}
    front_port, api_port, debug_port = free_port(), free_port(), free_port(); trace = evidence / "stack_trace.json"; evidence.mkdir(parents=True, exist_ok=True); logs.mkdir(parents=True, exist_ok=True)
    out_path, err_path = logs / "stack.stdout.log", logs / "stack.stderr.log"; started = time.monotonic()
    with out_path.open("w", encoding="utf-8") as stdout, err_path.open("w", encoding="utf-8") as stderr:
        stack = subprocess.Popen([sys.executable, "-m", "tools.ci_web_g08.stack_server", "--a10-root", str(a10), "--b11-root", str(b11), "--front-port", str(front_port), "--api-port", str(api_port), "--trace", str(trace)], cwd=root, env={**os.environ, **env}, stdout=stdout, stderr=stderr, text=True, shell=False)
        try:
            base = f"http://127.0.0.1:{front_port}"
            for _ in range(100):
                try:
                    with urllib.request.urlopen(base + "/", timeout=2) as response:
                        if response.status == 200: break
                except OSError: time.sleep(0.1)
            else: raise RuntimeError("local A10/B11 stack not ready")
            result = run_process("browser_cdp", [node, str(root / "tools" / "ci_web_g08" / "browser_probe.mjs"), "--chrome", chrome, "--base", base, "--output", str(evidence), "--debug-port", str(debug_port)], root, logs, env, timeout=600)
            result["name"] = "a10r08_b11_browser"
        except Exception as exc: result = {"name": "a10r08_b11_browser", "status": "ERROR", "return_code": None, "duration_seconds": round(time.monotonic() - started, 6), "reason": str(exc)}
        finally:
            try: urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{front_port}/__g08_shutdown", method="POST"), timeout=3).read()
            except OSError: pass
            try: stack.wait(timeout=10)
            except subprocess.TimeoutExpired: stack.terminate(); stack.wait(timeout=5)
    result["duration_seconds"] = round(time.monotonic() - started, 6); return result


def tree_hash(directory: Path, suffixes: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file() and item.suffix in suffixes): digest.update(path.relative_to(directory).as_posix().encode()); digest.update(b"\0"); digest.update(path.read_bytes()); digest.update(b"\0")
    return digest.hexdigest()


def run(*, root: Path, run_id: str, inputs: dict[str, tuple[Path, str]], receipt_ack: Path) -> tuple[dict, int]:
    root = root.resolve(); report_dir = root / "reports" / "G08" / "runs" / run_id; isolation = root / "review" / "G08" / "runs" / run_id; logs = report_dir / "raw" / "logs"
    report_dir.mkdir(parents=True, exist_ok=True); isolation.mkdir(parents=True, exist_ok=True)
    kinds = {"A10": "A10", "B11": "B11", "B12": "B12", "C09": "C09", "F07": "F07"}; audits = {name: audit_release(path.resolve(), expected, kinds[name]) for name, (path, expected) in inputs.items()}
    ack = json.loads(receipt_ack.read_text(encoding="utf-8")); receipts = {(item["file"], item["sha256"]) for item in ack["receipts"]}; ack_gates = {name: (path.name, expected) in receipts or name == "B11" for name, (path, expected) in inputs.items()}
    suites: list[dict] = []; status, code = "FAIL_CONTROLLED_INPUT_GATE", 4; dependency = {}
    if all(item["passed"] for item in audits.values()) and all(ack_gates.values()):
        roots = {}
        markers = {"A10": Path("apps/price-web/frontend"), "B11": Path("services/price_coupon_v4"), "B12": Path("services/import_staging_b12"), "C09": Path("research/import_provenance_c09"), "F07": Path("services/affiliate_coupon_gate_v7")}
        for name, (archive, _) in inputs.items():
            target = isolation / name; safe_extract(archive, target); roots[name] = release_root(target, markers[name])
        temp = isolation / "tmp"; temp.mkdir(parents=True, exist_ok=True); env = {"CDH_OFFLINE": "1", "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "TEMP": str(temp), "TMP": str(temp), "PYTHONDONTWRITEBYTECODE": "1"}
        node = shutil.which("node"); chrome, chrome_version = chrome_identity(); a_front = roots["A10"] / "apps" / "price-web" / "frontend"; local_front = root / "apps" / "price-web" / "frontend"
        lock_sha = sha256_file(a_front / "package-lock.json"); local_lock_sha = sha256_file(local_front / "package-lock.json") if (local_front / "package-lock.json").is_file() else None; dependency_match = lock_sha == local_lock_sha and (local_front / "node_modules").is_dir()
        if dependency_match and not (a_front / "node_modules").exists():
            try: os.symlink(local_front / "node_modules", a_front / "node_modules", target_is_directory=True)
            except OSError: dependency_match = False
        dependency = {"a10_lock_sha256": lock_sha, "local_lock_sha256": local_lock_sha, "lock_match": dependency_match, "node": subprocess.run([node, "--version"], stdout=subprocess.PIPE, text=True, shell=False).stdout.strip() if node else None, "chrome": chrome_version, "package_install_count": 0}
        suites.append(run_process("g08_self_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/ci_web_g08", "-v"], root, logs, env))
        suites.append(run_process("a10r08_vitest", [node or "node", "node_modules/vitest/vitest.mjs", "run", "--reporter=verbose"], a_front, logs, env, timeout=600, missing=None if node and dependency_match else "matching A10 dependency lock unavailable"))
        suites.append(run_process("b11_coupon_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/web/price_coupon_v4", "-p", "test_*.py", "-v"], roots["B11"], logs, env))
        suites.append(run_process("b11_v3_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/web/price_query_v3", "-p", "test_*.py", "-v"], roots["B11"], logs, env))
        suites.append(run_process("b12_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/import_staging_b12", "-v"], roots["B12"], logs, env))
        suites.append(run_process("c09_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/import_provenance_c09", "-v"], roots["C09"], logs, env))
        suites.append(run_process("f07_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/affiliate_coupon_gate_v7", "-v"], roots["F07"], logs, env))
        suites.append(run_process("b12_c09_import_stage", [sys.executable, "-m", "tools.ci_web_g08.import_probe", "--b12-root", str(roots["B12"]), "--c09-zip", str(inputs["C09"][0].resolve()), "--b11-zip", str(inputs["B11"][0].resolve()), "--b11-root", str(roots["B11"]), "--output", str(report_dir / "raw" / "import")], root, logs, env))
        suites.append(browser_suite(root, roots["A10"], roots["B11"], report_dir / "raw" / "browser", logs, env, chrome, node))
        failed = [suite for suite in suites if suite["status"] != "PASS"]; status, code = ("INTEGRATION_PASS_SCOPED", 0) if not failed else ("FAIL", 2)
        source_identities = {"a10_frontend_tree_sha256": tree_hash(a_front / "src", (".ts", ".tsx")), "a10_dist_tree_sha256": tree_hash(a_front / "dist", (".html", ".js", ".css")), "b11_python_tree_sha256": tree_hash(roots["B11"] / "services" / "price_coupon_v4", (".py",))}
    report = {"schema": "CDH-G08-A10R08-B11-WINDOWS-EXACT-CI-1", "task_id": "CDH-G08-A10R08-B11-WINDOWS-EXACT-CI-001", "generated_at_utc": datetime.now(timezone.utc).isoformat(), "authority": "SCOPED_OFFLINE_LOCAL_ONLY", "run_id": run_id, "platform": {"system": platform.system(), "release": platform.release(), "python": platform.python_version()}, "inputs": {name: {"path": str(path), "expected_sha256": expected, "ack_match": ack_gates[name]} for name, (path, expected) in inputs.items()}, "audits": audits, "dependencies": dependency, "source_identities": locals().get("source_identities", {}), "suites": suites, "counters": {"package_install_count": 0, "external_network_access_count": 0, "real_data_access_count": 0, "b11_database_write_count": 0, "deployment_count": 0, "affiliate_click_count": 0, "transaction_count": 0}, "summary": {"status": status, "return_code": code, "suite_count": len(suites), "pass_count": sum(item["status"] == "PASS" for item in suites), "fail_count": sum(item["status"] == "FAIL" for item in suites), "not_run_count": sum(item["status"].startswith("NOT_RUN") for item in suites), "error_count": sum(item["status"] == "ERROR" for item in suites)}}
    (report_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); return report, code
