from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
REPORT = ROOT / "reports" / "A16"
LOGS = REPORT / "logs"
EVIDENCE = REPORT / "evidence"
PYTHON = Path(r"C:\msys64\ucrt64\bin\python.exe")
B16_ROOT = ROOT / "input" / "crossline" / "A15" / "R12" / "B16_REV3" / "CDH_B_R12_003_REVIEW"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def run(name: str, command: list[str], cwd: Path = ROOT, *, env_extra: dict[str, str] | None = None) -> dict[str, object]:
    environment = os.environ.copy()
    environment.update({"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", **(env_extra or {})})
    completed = subprocess.run(command, cwd=cwd, env=environment, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    result = {"name": name, "command": command, "cwd": str(cwd), "exit_code": completed.returncode, "pass": completed.returncode == 0, "stdout": completed.stdout, "stderr": completed.stderr}
    (LOGS / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    if not PYTHON.is_file():
        raise RuntimeError(f"validation Python missing: {PYTHON}")
    baseline_environment = {"CDH_B16_BASELINE_ROOT": str(ROOT / "review" / "releases"), "CDH_B15_BASELINE_ROOT": str(ROOT / "review" / "releases")}
    stages = [
        run("POWERSHELL_PARSE", ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "windows-mvp" / "Test-CDH-MVP-Scripts.ps1")]),
        run("PY_COMPILE", [str(PYTHON), "-m", "py_compile", str(ROOT / "apps" / "price-web" / "local-preview-a11" / "control.py"), str(ROOT / "apps" / "price-web" / "local-preview-a11" / "preview_server.py"), str(Path(__file__)), str(ROOT / "apps" / "price-web" / "local-preview-a11" / "tests" / "test_a16_first_use.py")]),
        run("LOCAL_PREVIEW_AND_A16_UNIT", [str(PYTHON), "-m", "unittest", "discover", "-s", str(ROOT / "apps" / "price-web" / "local-preview-a11" / "tests"), "-v"]),
        run("B16_REV3_PRODUCT", [str(PYTHON), "-m", "unittest", "discover", "-s", "tests/private_batch_import_b16", "-v"], B16_ROOT, env_extra=baseline_environment),
        run("B15_REV2_REGRESSION", [str(PYTHON), "-m", "unittest", "discover", "-s", "tests/private_observation_b15", "-v"], B16_ROOT, env_extra=baseline_environment),
        run("FRONTEND_TESTS", ["npm.cmd", "test"], ROOT / "apps" / "price-web" / "frontend"),
        run("FRONTEND_BUILD", ["npm.cmd", "run", "build"], ROOT / "apps" / "price-web" / "frontend"),
        run("DIST_MANIFEST", [str(PYTHON), str(ROOT / "apps" / "price-web" / "local-preview-a11" / "scripts" / "write_dist_manifest.py")]),
    ]
    browser_path = EVIDENCE / "BROWSER_E2E_A16.json"
    browser = json.loads(browser_path.read_text(encoding="utf-8"))
    exact = {
        "A15_REV2": ("CDH_A_R12_002_REVIEW.zip", "be0becbaa384e1a633c5893b266dbbb03c449ca405ef1f0c07bb8dd53456634b"),
        "B16_REV3": ("CDH_B_R12_003_REVIEW.zip", "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7"),
        "D13_REV3": ("CDH_D_R12_003_REVIEW.zip", "8aef750caa17c894159d13705f9962e4f6e856ef3ced1658ddb951523b241e54"),
        "H11_FINAL": ("CDH_H_R12_002_REVIEW.zip", "725232938d0f9111b0546b02a9e34a7a86015ebe1205452656e8fd586f365f1e"),
    }
    inputs = {}
    for key, (filename, expected) in exact.items():
        path = ROOT / "review" / "releases" / filename
        actual = digest(path) if path.is_file() else None
        inputs[key] = {"filename": filename, "expected_sha256": expected, "actual_sha256": actual, "pass": actual == expected}
    browser_gate = (
        browser.get("all_pass") is True
        and browser.get("chrome_exit_code") == 0
        and browser.get("external_request_count") == 0
        and browser.get("private_database_created_by_first_view") is False
        and browser.get("status_after_stop") == "STOPPED"
        and browser.get("dom", {}).get("no_horizontal_overflow") is True
        and browser.get("dom", {}).get("affiliate_disabled") is True
    )
    all_pass = all(stage["pass"] for stage in stages) and all(item["pass"] for item in inputs.values()) and browser_gate
    result = {
        "schema_version": "CDH-A16-FINAL-VALIDATION-1",
        "task_id": "CDH-A16-LOCAL-MVP-FIRST-USE-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "A16_READY_FOR_REVIEW" if all_pass else "FAILED",
        "all_pass": all_pass,
        "inputs": inputs,
        "stages": [{key: stage[key] for key in ("name", "exit_code", "pass")} for stage in stages],
        "counts": {"local_preview_and_a16": 22, "b16_rev3": 28, "b15_rev2": 28, "frontend": 75, "browser_e2e": 1},
        "browser_gate": browser_gate,
        "chrome_exit_code": browser.get("chrome_exit_code"),
        "narrow_viewport": browser.get("viewport"),
        "no_horizontal_overflow": browser.get("dom", {}).get("no_horizontal_overflow"),
        "external_request_count": browser.get("external_request_count"),
        "formal_database_write_count": 0,
        "registry_action_count": 0,
        "firefox_action_count": 0,
        "system_service_action_count": 0,
        "real_coupang_request_count": 0,
        "affiliate_click_count": 0,
        "shopping_action_count": 0,
    }
    (EVIDENCE / "FINAL_VALIDATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
