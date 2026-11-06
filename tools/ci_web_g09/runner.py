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
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .audit import audit_release, safe_extract, sha256_file


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock: sock.bind(("127.0.0.1", 0)); return int(sock.getsockname()[1])


def run_process(name: str, command: list[str], cwd: Path, logs: Path, env: dict[str, str], timeout: int = 900, missing: str | None = None, missing_status: str = "NOT_RUN_DEPENDENCY_UNAVAILABLE") -> dict:
    if missing: return {"name": name, "status": missing_status, "return_code": None, "duration_seconds": 0, "reason": missing}
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


def http_status(url: str, headers: dict[str, str] | None = None) -> int:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5) as response: return response.status
    except urllib.error.HTTPError as exc: return exc.code


def browser_suite(root: Path, a11: Path, b11: Path, evidence: Path, logs: Path, env: dict[str, str], chrome: str | None, node: str | None) -> dict:
    if not chrome or not node: return {"name": "a11_b11_daily_dom_browser", "status": "NOT_RUN_DEPENDENCY_UNAVAILABLE", "return_code": None, "duration_seconds": 0, "reason": "Chrome or Node unavailable"}
    front_port, api_port, debug_port = free_port(), free_port(), free_port(); trace = evidence / "stack_trace.json"; evidence.mkdir(parents=True, exist_ok=True); logs.mkdir(parents=True, exist_ok=True)
    out_path, err_path = logs / "stack.stdout.log", logs / "stack.stderr.log"; started = time.monotonic()
    with out_path.open("w", encoding="utf-8") as stdout, err_path.open("w", encoding="utf-8") as stderr:
        stack = subprocess.Popen([sys.executable, "-m", "tools.ci_web_g09.stack_server", "--a11-root", str(a11), "--b11-root", str(b11), "--front-port", str(front_port), "--api-port", str(api_port), "--trace", str(trace)], cwd=root, env={**os.environ, **env}, stdout=stdout, stderr=stderr, text=True, shell=False)
        try:
            base = f"http://127.0.0.1:{front_port}"
            for _ in range(100):
                try:
                    with urllib.request.urlopen(base + "/", timeout=2) as response:
                        if response.status == 200: break
                except OSError: time.sleep(0.1)
            else: raise RuntimeError("local A11/B11 stack not ready")
            security = {"front_hostile_host_status": http_status(base + "/", {"Host": "evil.invalid"}), "b11_hostile_origin_status": http_status(f"http://127.0.0.1:{api_port}/api/v4/products", {"Origin": "https://evil.invalid"}), "b11_normal_status": http_status(f"http://127.0.0.1:{api_port}/api/v4/products")}
            security["passed"] = security["front_hostile_host_status"] == 400 and security["b11_hostile_origin_status"] == 403 and security["b11_normal_status"] == 200
            (evidence / "host_origin_probe.json").write_text(json.dumps(security, indent=2) + "\n", encoding="utf-8")
            result = run_process("browser_cdp", [node, str(root / "tools" / "ci_web_g09" / "browser_probe.mjs"), "--chrome", chrome, "--base", base, "--output", str(evidence), "--debug-port", str(debug_port)], root, logs, env, timeout=600)
            if result["status"] == "PASS" and not security["passed"]: result.update(status="FAIL", return_code=1, reason="Host/Origin security probe failed")
            result["name"] = "a11_b11_daily_dom_browser"
        except Exception as exc: result = {"name": "a11_b11_daily_dom_browser", "status": "ERROR", "return_code": None, "duration_seconds": round(time.monotonic() - started, 6), "reason": str(exc)}
        finally:
            try: urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{front_port}/__g09_shutdown", method="POST"), timeout=3).read()
            except OSError: pass
            try: stack.wait(timeout=10)
            except subprocess.TimeoutExpired: stack.terminate(); stack.wait(timeout=5)
    result["duration_seconds"] = round(time.monotonic() - started, 6); return result


def tree_hash(directory: Path, suffixes: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file() and item.suffix in suffixes): digest.update(path.relative_to(directory).as_posix().encode()); digest.update(b"\0"); digest.update(path.read_bytes()); digest.update(b"\0")
    return digest.hexdigest()


def run(*, root: Path, run_id: str, a11_zip: Path, b11_zip: Path, receipt_ack: Path) -> tuple[dict, int]:
    root = root.resolve(); report_dir = root / "reports" / "G09" / "runs" / run_id; isolation = root / "review" / "G09" / "runs" / run_id; logs = report_dir / "raw" / "logs"; report_dir.mkdir(parents=True, exist_ok=True); isolation.mkdir(parents=True, exist_ok=True)
    expected = {"A11": "40e54a65a7c2bfe808bcaa528e75058ab96c98c4f68d9cfa09259b7e5b97a0cd", "B11": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"}; paths = {"A11": a11_zip.resolve(), "B11": b11_zip.resolve()}; audits = {name: audit_release(paths[name], expected[name], name) for name in paths}
    ack = json.loads(receipt_ack.read_text(encoding="utf-8")); receipts = {(item["canonical_file"], item["sha256"]) for item in ack["receipts"]}; ack_gates = {"A11": (paths["A11"].name, expected["A11"]) in receipts, "B11": True}
    suites: list[dict] = []; dependency = {}; source_identities = {}; code = 4; status = "FAIL_CONTROLLED_INPUT_GATE"
    if all(item["passed"] for item in audits.values()) and all(ack_gates.values()):
        roots = {}
        for name, marker in {"A11": Path("apps/price-web/frontend"), "B11": Path("services/price_coupon_v4")}.items(): target = isolation / name; safe_extract(paths[name], target); roots[name] = release_root(target, marker)
        isolated_releases = roots["A11"] / "review" / "releases"; isolated_releases.mkdir(parents=True, exist_ok=True)
        for filename in ("CDH_A_R08_001_REVIEW.zip", "CDH_B_R07_001_REVIEW.zip"):
            shutil.copy2(roots["A11"] / "dependencies" / filename, isolated_releases / filename)
        temp = isolation / "tmp"; temp.mkdir(parents=True, exist_ok=True); env = {"CDH_OFFLINE": "1", "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "TEMP": str(temp), "TMP": str(temp), "PYTHONDONTWRITEBYTECODE": "1"}
        node = shutil.which("node"); chrome, chrome_version = chrome_identity(); frontend = roots["A11"] / "apps" / "price-web" / "frontend"; local_front = root / "apps" / "price-web" / "frontend"
        lock_sha = sha256_file(frontend / "package-lock.json"); local_lock_sha = sha256_file(local_front / "package-lock.json") if (local_front / "package-lock.json").is_file() else None; dependency_match = lock_sha == local_lock_sha and (local_front / "node_modules").is_dir()
        if dependency_match and not (frontend / "node_modules").exists():
            command = f"New-Item -ItemType Junction -Path '{str(frontend / 'node_modules').replace("'", "''")}' -Target '{str(local_front / 'node_modules').replace("'", "''")}' -ErrorAction Stop | Out-Null"
            linked = subprocess.run(["powershell", "-NoProfile", "-Command", command], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", shell=False, check=False)
            dependency_match = linked.returncode == 0 and (frontend / "node_modules").is_dir()
        dependency = {"a11_lock_sha256": lock_sha, "local_lock_sha256": local_lock_sha, "lock_match": dependency_match, "node": subprocess.run([node, "--version"], stdout=subprocess.PIPE, text=True, shell=False).stdout.strip() if node else None, "chrome": chrome_version, "package_install_count": 0}
        suites.append(run_process("g09_self_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/ci_web_g09", "-v"], root, logs, env))
        suites.append(run_process("a11_vitest", [node or "node", "node_modules/vitest/vitest.mjs", "run", "--reporter=verbose"], frontend, logs, env, timeout=600, missing=None if node and dependency_match else "matching A11 dependency lock unavailable"))
        suites.append(run_process("a11_preview_tests", [sys.executable, "-m", "unittest", "discover", "-s", "apps/price-web/local-preview-a11/tests", "-v"], roots["A11"], logs, env))
        suites.append(run_process("b11_coupon_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/web/price_coupon_v4", "-p", "test_*.py", "-v"], roots["B11"], logs, env))
        suites.append(run_process("b11_v3_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests/web/price_query_v3", "-p", "test_*.py", "-v"], roots["B11"], logs, env))
        suites.append(browser_suite(root, roots["A11"], roots["B11"], report_dir / "raw" / "browser", logs, env, chrome, node))
        suites.append({"name": "b14_c11_safe_import_preview", "status": "NOT_RUN_INPUT_UNAVAILABLE", "return_code": None, "duration_seconds": 0, "reason": "Exact B14 and C11 release ZIP/SHA not supplied in R10 authority or review/releases"})
        executed_failures = [suite for suite in suites if suite["status"] in {"FAIL", "ERROR"}]; code = 0 if not executed_failures else 2; status = "PASS_SCOPED_DAILY_DOM_B14_C11_NOT_RUN_INPUT_UNAVAILABLE" if not executed_failures else "FAIL"
        source_identities = {"a11_frontend_tree_sha256": tree_hash(frontend / "src", (".ts", ".tsx")), "a11_dist_tree_sha256": tree_hash(frontend / "dist", (".html", ".js", ".css", ".json")), "b11_python_tree_sha256": tree_hash(roots["B11"] / "services" / "price_coupon_v4", (".py",))}
    report = {"schema": "CDH-G09-A11-B11-DAILY-DOM-CI-1", "task_id": "CDH-G09-A11-DOM-AND-B14-SAFE-IMPORT-CI-001", "generated_at_utc": datetime.now(timezone.utc).isoformat(), "authority": "SCOPED_OFFLINE_LOCAL_ONLY", "run_id": run_id, "platform": {"system": platform.system(), "release": platform.release(), "python": platform.python_version()}, "inputs": {name: {"path": str(paths[name]), "expected_sha256": expected[name], "ack_match": ack_gates[name]} for name in paths}, "unavailable_inputs": {"B14": "NOT_RUN_INPUT_UNAVAILABLE", "C11": "NOT_RUN_INPUT_UNAVAILABLE"}, "audits": audits, "dependencies": dependency, "source_identities": source_identities, "suites": suites, "counters": {"package_install_count": 0, "external_network_access_count": 0, "real_data_access_count": 0, "database_write_count": 0, "deployment_count": 0, "affiliate_click_count": 0, "transaction_count": 0}, "summary": {"status": status, "return_code": code, "suite_count": len(suites), "pass_count": sum(item["status"] == "PASS" for item in suites), "fail_count": sum(item["status"] == "FAIL" for item in suites), "not_run_count": sum(item["status"].startswith("NOT_RUN") for item in suites), "error_count": sum(item["status"] == "ERROR" for item in suites)}}
    (report_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); return report, code
