from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[4]
FRONTEND = ROOT / "apps" / "price-web" / "frontend"
PREVIEW = ROOT / "apps" / "price-web" / "local-preview-a11"
REPORT = ROOT / "reports" / "A15_REV2"
LOGS = REPORT / "logs"
EVIDENCE = REPORT / "evidence"
B16_EXTRACTED = ROOT / "input" / "crossline" / "A15" / "R12" / "B16_REV3" / "CDH_B_R12_003_REVIEW"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_release(name: str, expected: str, *, manifest: bool = False) -> dict[str, object]:
    path = ROOT / "review" / "releases" / name
    actual = sha256(path) if path.is_file() else None
    result: dict[str, object] = {"path": path.relative_to(ROOT).as_posix(), "expected_sha256": expected, "actual_sha256": actual, "crc": "NOT_RUN", "safe_paths": "NOT_RUN", "duplicates": "NOT_RUN", "manifest": "N/A", "pass": False}
    if not path.is_file() or actual != expected:
        return result
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        unsafe = [entry for entry in names if PurePosixPath(entry.replace("\\", "/")).is_absolute() or ".." in PurePosixPath(entry.replace("\\", "/")).parts or "\\" in entry]
        duplicates = len(names) - len(set(names)) + len(names) - len({item.casefold() for item in names})
        result.update({"crc": "PASS" if archive.testzip() is None else "FAIL", "safe_paths": "PASS" if not unsafe else "FAIL", "duplicates": duplicates})
        manifest_pass = True
        if manifest:
            manifest_name = "CDH_B_R12_003_REVIEW/REVIEW_MANIFEST.json"
            declaration = json.loads(archive.read(manifest_name))
            declared = {item["path"]: item for item in declaration["payloads"]}
            actual_names = set(names) - {manifest_name}
            manifest_pass = set(declared) == actual_names and all(len(archive.read(item)) == declaration_item["bytes"] and hashlib.sha256(archive.read(item)).hexdigest() == declaration_item["sha256"] for item, declaration_item in declared.items())
            result["manifest"] = "PASS" if manifest_pass else "FAIL"
            result["manifest_sha256"] = hashlib.sha256(archive.read(manifest_name)).hexdigest()
        result["pass"] = result["crc"] == "PASS" and result["safe_paths"] == "PASS" and duplicates == 0 and manifest_pass
    return result


def execute(name: str, command: list[str], cwd: Path, *, env_extra: dict[str, str] | None = None, timeout: int = 360) -> dict[str, object]:
    temp = REPORT / "test_temp" / name
    temp.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "TEMP": str(temp), "TMP": str(temp), **(env_extra or {})}
    completed = subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    record = {"name": name, "command": command, "cwd": str(cwd), "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "pass": completed.returncode == 0}
    (LOGS / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(f"{name} failed: {(completed.stdout + completed.stderr)[-5000:]}")
    return record


def count(record: dict[str, object]) -> int | None:
    output = str(record["stdout"]) + str(record["stderr"])
    match = re.search(r"Tests\s+(\d+) passed", output) or re.search(r"Ran (\d+) tests", output)
    return int(match.group(1)) if match else None


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True); EVIDENCE.mkdir(parents=True, exist_ok=True)
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("npm unavailable")
    dependencies = {
        "a15_original": verify_release("CDH_A_R12_001_REVIEW.zip", "5cc44dedd910ff9b2055cfc2772ad0c3d6db627ffc818794f81fd3d9b5552d4b"),
        "b16_rev3": verify_release("CDH_B_R12_003_REVIEW.zip", "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7", manifest=True),
        "a14": verify_release("CDH_A_R11_004_REVIEW.zip", "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160"),
        "b15_rev2": verify_release("CDH_B_R11_002_REVIEW.zip", "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe"),
    }
    if not all(bool(item["pass"]) for item in dependencies.values()):
        raise RuntimeError(f"dependency identity failure: {dependencies}")
    baseline_env = {"CDH_B16_BASELINE_ROOT": str(ROOT / "review" / "releases"), "CDH_B15_BASELINE_ROOT": str(ROOT / "review" / "releases")}
    stages: list[dict[str, object]] = []
    stages.append(execute("PY_COMPILE", [sys.executable, "-m", "py_compile", str(PREVIEW / "preview_server.py"), str(PREVIEW / "control.py"), str(PREVIEW / "scripts" / "run_final_validation_a15.py")], ROOT))
    preview = execute("LOCAL_PREVIEW_UNIT", [sys.executable, "-m", "unittest", "discover", "-s", str(PREVIEW / "tests"), "-v"], ROOT); stages.append(preview)
    b16 = execute("B16_PRODUCT_TESTS", [sys.executable, "-m", "unittest", "discover", "-s", "tests/private_batch_import_b16", "-v"], B16_EXTRACTED, env_extra=baseline_env); stages.append(b16)
    b15 = execute("B15_REV2_REGRESSION", [sys.executable, "-m", "unittest", "discover", "-s", "tests/private_observation_b15", "-v"], B16_EXTRACTED, env_extra=baseline_env); stages.append(b15)
    browser = execute("A15_ACTUAL_CHROME_E2E", [npm, "run", "e2e:a15"], FRONTEND, timeout=300); stages.append(browser)
    browser_evidence = json.loads((EVIDENCE / "BROWSER_E2E_A15.json").read_text(encoding="utf-8"))
    summary = {
        "schema_version": "CDH-A15-REV2-FINAL-VALIDATION-1", "task_id": "CDH-A15-BATCH-IMPORT-UI-001", "revision": "REV2", "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "authority": "OFFLINE_LOCAL_ISOLATED_A_LINE_INCREMENT_ONLY", "dependencies": dependencies,
        "frontend_tests": "NOT_RUN_UNCHANGED", "frontend_dist_rebuilt": False, "local_preview_tests": count(preview), "b16_product_tests": count(b16), "b15_regression_tests": count(b15),
        "browser_all_pass": browser_evidence.get("all_pass"), "actual_integration": browser_evidence.get("integration"), "chrome_exit_code": browser_evidence.get("chrome_exit_code"),
        "website_restart_count": browser_evidence.get("website_restart_count"), "rows_after_create": browser_evidence.get("rows_after_create"), "rows_after_replay": browser_evidence.get("rows_after_replay"),
        "rows_before_read": browser_evidence.get("rows_before_read"), "rows_after_read": browser_evidence.get("rows_after_read"), "database_unchanged_by_read": browser_evidence.get("database_unchanged_by_read"),
        "external_request_count": browser_evidence.get("external_request_count"), "formal_database_write_count": browser_evidence.get("formal_database_write_count"), "registry_action_count": browser_evidence.get("registry_action_count"), "firefox_action_count": browser_evidence.get("firefox_action_count"),
        "stages": [{"name": item["name"], "exit_code": item["exit_code"], "pass": item["pass"]} for item in stages],
    }
    summary["all_available_scope_pass"] = all(bool(item["pass"]) for item in dependencies.values()) and all(bool(item["pass"]) for item in stages) and summary["browser_all_pass"] is True and summary["chrome_exit_code"] == 0 and summary["database_unchanged_by_read"] is True and summary["rows_after_create"] == summary["rows_after_replay"] == summary["rows_before_read"] == summary["rows_after_read"] == 2 and summary["external_request_count"] == 0
    (EVIDENCE / "FINAL_VALIDATION.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS" if summary["all_available_scope_pass"] else "FAIL", "frontend_tests": summary["frontend_tests"], "local_preview_tests": summary["local_preview_tests"], "b16_product_tests": summary["b16_product_tests"], "b15_regression_tests": summary["b15_regression_tests"], "browser_all_pass": summary["browser_all_pass"], "chrome_exit_code": summary["chrome_exit_code"]}, sort_keys=True))
    return 0 if summary["all_available_scope_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
