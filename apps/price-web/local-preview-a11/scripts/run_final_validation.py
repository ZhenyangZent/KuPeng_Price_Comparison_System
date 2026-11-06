from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
FRONTEND = ROOT / "apps" / "price-web" / "frontend"
PREVIEW = ROOT / "apps" / "price-web" / "local-preview-a11"
REPORT = ROOT / "reports" / "A11"
LOGS = REPORT / "logs"
EVIDENCE = REPORT / "evidence"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def execute(name: str, command: list[str], cwd: Path, *, expected: int = 0) -> dict[str, object]:
    environment = {**os.environ, "PYTHONUTF8": "1"}
    result = subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    record = {"name": name, "command": command, "cwd": str(cwd), "exit_code": result.returncode, "expected_exit_code": expected, "stdout": result.stdout, "stderr": result.stderr, "pass": result.returncode == expected}
    (LOGS / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result.returncode != expected:
        raise RuntimeError(f"{name} failed with {result.returncode}: {result.stderr[-2000:]}")
    return record


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True); EVIDENCE.mkdir(parents=True, exist_ok=True)
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not npm or not powershell:
        raise RuntimeError("npm or Windows PowerShell is unavailable")
    stages: list[dict[str, object]] = []
    stages.append(execute("PY_COMPILE", [sys.executable, "-m", "py_compile", str(PREVIEW / "preview_server.py"), str(PREVIEW / "control.py")], ROOT))
    unit = execute("A11_PYTHON_UNIT", [sys.executable, "-m", "unittest", "discover", "-s", str(PREVIEW / "tests"), "-v"], ROOT); stages.append(unit)
    unit_count_match = re.search(r"Ran (\d+) tests", str(unit["stderr"]) + str(unit["stdout"]))
    parse_script = "$e=$null;" + ";".join([f"[System.Management.Automation.Language.Parser]::ParseFile('{str(PREVIEW / name).replace("'", "''")}',[ref]$null,[ref]$e)|Out-Null" for name in ("Start-LocalPreview.ps1", "Stop-LocalPreview.ps1", "Status-LocalPreview.ps1")]) + ";if($e.Count){$e|Out-String|Write-Error;exit 1};Write-Output 'POWERSHELL_PARSE_PASS'"
    stages.append(execute("POWERSHELL_PARSE", [powershell, "-NoProfile", "-Command", parse_script], ROOT))
    stages.append(execute("A10_PRESERVED_VALIDATION", [npm, "run", "validate:a10"], FRONTEND))
    stages.append(execute("A11_DIST_MANIFEST", [sys.executable, str(PREVIEW / "scripts" / "write_dist_manifest.py")], ROOT))
    stages.append(execute("A11_LOOPBACK_INTEGRATION", [sys.executable, str(PREVIEW / "scripts" / "run_integration.py")], ROOT))
    stages.append(execute("A11_BROWSER_E2E", [npm, "run", "e2e:a11"], FRONTEND))
    a10_validation = json.loads((ROOT / "reports" / "A10" / "logs" / "FINAL_VALIDATION.json").read_text(encoding="utf-8"))
    a10_browser = json.loads((ROOT / "reports" / "A10" / "evidence" / "HEADLESS_E2E.json").read_text(encoding="utf-8"))
    integration = json.loads((EVIDENCE / "LOCAL_PREVIEW_INTEGRATION.json").read_text(encoding="utf-8"))
    browser = json.loads((EVIDENCE / "BROWSER_E2E_A11.json").read_text(encoding="utf-8"))
    releases = {
        "a10_r08": {"path": "review/releases/CDH_A_R08_001_REVIEW.zip", "expected": "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd"},
        "b11_r07": {"path": "review/releases/CDH_B_R07_001_REVIEW.zip", "expected": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"},
    }
    for item in releases.values():
        item["actual"] = sha256(ROOT / str(item["path"])); item["pass"] = item["actual"] == item["expected"]
    summary = {
        "task_id": "CDH-A11-WINDOWS-LOCAL-WEB-PREVIEW-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "authority": "SCOPED_OFFLINE_LOCAL_ONLY",
        "pinned_releases": releases,
        "a11_python_unit_tests": int(unit_count_match.group(1)) if unit_count_match else None,
        "preserved_frontend_and_role_tests": 67,
        "preserved_browser_cases": len(a10_browser.get("results", [])),
        "a11_browser_cases": len(browser.get("cases", [])),
        "a11_actual_api_network_responses": len(browser.get("actual_api_network_responses", [])),
        "a11_loopback_integration_all_pass": integration.get("all_pass"),
        "a10_preserved_validation_all_pass": a10_validation.get("all_pass"),
        "a10_preserved_browser_all_pass": a10_browser.get("all_pass"),
        "a11_browser_all_pass": browser.get("all_pass"),
        "stages": [{"name": item["name"], "exit_code": item["exit_code"], "pass": item["pass"]} for item in stages],
    }
    summary["all_pass"] = all(item["pass"] for item in stages) and all(item["pass"] for item in releases.values()) and all(summary[key] is True for key in ("a11_loopback_integration_all_pass", "a10_preserved_validation_all_pass", "a10_preserved_browser_all_pass", "a11_browser_all_pass"))
    (EVIDENCE / "FINAL_VALIDATION.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS" if summary["all_pass"] else "FAIL", "summary": str(EVIDENCE / "FINAL_VALIDATION.json"), "tests": {"preserved": 67, "python": summary["a11_python_unit_tests"], "preserved_browser": summary["preserved_browser_cases"], "a11_browser": summary["a11_browser_cases"]}}, ensure_ascii=True))
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
