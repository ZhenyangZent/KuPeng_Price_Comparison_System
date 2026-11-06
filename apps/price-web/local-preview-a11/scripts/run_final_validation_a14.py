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
REPORT = ROOT / "reports" / "A14"
LOGS = REPORT / "logs"
EVIDENCE = REPORT / "evidence"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_release(name: str, expected: str) -> dict[str, object]:
    path = ROOT / "review" / "releases" / name
    actual = sha256(path) if path.is_file() else None
    crc_bad = None
    unsafe: list[str] = []
    duplicates = None
    if path.is_file():
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            crc_bad = archive.testzip()
            duplicates = len(names) - len(set(names))
            unsafe = [entry for entry in names if PurePosixPath(entry.replace("\\", "/")).is_absolute() or ".." in PurePosixPath(entry.replace("\\", "/")).parts]
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "expected_sha256": expected, "actual_sha256": actual, "crc_bad": crc_bad, "duplicates": duplicates, "unsafe": unsafe, "pass": actual == expected and crc_bad is None and duplicates == 0 and not unsafe}


def execute(name: str, command: list[str], cwd: Path, timeout: int = 300) -> dict[str, object]:
    temp = REPORT / "test_temp" / name
    temp.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "TEMP": str(temp), "TMP": str(temp)}
    if name == "B15_REV2_PRODUCT_TESTS":
        environment["CDH_B15_BASELINE_ROOT"] = str(ROOT / "review" / "releases")
    result = subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    record = {"name": name, "command": command, "cwd": str(cwd), "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr, "pass": result.returncode == 0}
    (LOGS / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"{name} failed with {result.returncode}: {(result.stderr + result.stdout)[-4000:]}")
    return record


def count_tests(record: dict[str, object]) -> int | None:
    output = str(record["stdout"]) + str(record["stderr"])
    match = re.search(r"Tests\s+(\d+) passed", output) or re.search(r"Ran (\d+) tests", output)
    return int(match.group(1)) if match else None


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("npm unavailable")
    dependencies = {
        "a13_rev3": verify_release("CDH_A_R11_003_REVIEW.zip", "d1b8814f0ae54f5fa5fae77c873620fe70da979fcbfe689a333096fab897b274"),
        "b15_rev2": verify_release("CDH_B_R11_002_REVIEW.zip", "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe"),
        "b11_r07": verify_release("CDH_B_R07_001_REVIEW.zip", "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"),
    }
    if not all(item["pass"] for item in dependencies.values()):
        raise RuntimeError(f"dependency identity failure: {dependencies}")
    b15_source = ROOT / "input" / "crossline" / "A13" / "R11" / "B15_REV2" / "CDH_B_R11_002_REVIEW"
    stages: list[dict[str, object]] = []
    stages.append(execute("PY_COMPILE", [sys.executable, "-m", "py_compile", str(PREVIEW / "preview_server.py"), str(PREVIEW / "control.py"), str(PREVIEW / "scripts" / "run_final_validation_a14.py"), str(PREVIEW / "scripts" / "package_review.py")], ROOT))
    stages.append(execute("FRONTEND_BUILD", [npm, "run", "build"], FRONTEND))
    frontend = execute("FRONTEND_TESTS", [npm, "test"], FRONTEND); stages.append(frontend)
    stages.append(execute("A14_DIST_MANIFEST", [sys.executable, str(PREVIEW / "scripts" / "write_dist_manifest.py")], ROOT))
    preview_tests = execute("LOCAL_PREVIEW_UNIT", [sys.executable, "-m", "unittest", "discover", "-s", str(PREVIEW / "tests"), "-v"], ROOT); stages.append(preview_tests)
    b15_tests = execute("B15_REV2_PRODUCT_TESTS", [sys.executable, "-m", "unittest", "discover", "-s", str(b15_source / "tests" / "private_observation_b15"), "-v"], b15_source); stages.append(b15_tests)
    browser = execute("A14_RESTART_READONLY_BROWSER", [npm, "run", "e2e:a14"], FRONTEND); stages.append(browser)
    browser_evidence = json.loads((EVIDENCE / "BROWSER_E2E_A14.json").read_text(encoding="utf-8"))
    summary = {
        "schema_version": "CDH-A14-FINAL-VALIDATION-1",
        "task_id": "CDH-A14-PRIVATE-HISTORY-BROWSE-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "authority": "OFFLINE_LOCAL_ISOLATED_A_LINE_INCREMENT_ONLY",
        "dependencies": dependencies,
        "frontend_tests": count_tests(frontend),
        "local_preview_tests": count_tests(preview_tests),
        "b15_rev2_product_tests": count_tests(b15_tests),
        "browser_case_count": 1,
        "browser_all_pass": browser_evidence.get("all_pass"),
        "actual_integration": browser_evidence.get("integration"),
        "website_restart_count": browser_evidence.get("website_restart_count"),
        "rows_before_read": browser_evidence.get("rows_before_read"),
        "rows_after_read": browser_evidence.get("rows_after_read"),
        "database_unchanged_by_read": browser_evidence.get("database_unchanged_by_read"),
        "private_post_after_restart_count": browser_evidence.get("private_post_after_restart_count"),
        "formal_database_write_count": browser_evidence.get("formal_database_write_count"),
        "registry_action_count": browser_evidence.get("registry_action_count"),
        "firefox_action_count": browser_evidence.get("firefox_action_count"),
        "stages": [{"name": item["name"], "exit_code": item["exit_code"], "pass": item["pass"]} for item in stages],
    }
    summary["all_available_scope_pass"] = all(item["pass"] for item in dependencies.values()) and all(item["pass"] for item in stages) and summary["browser_all_pass"] is True and summary["database_unchanged_by_read"] is True and summary["private_post_after_restart_count"] == 0 and summary["rows_before_read"] == summary["rows_after_read"] == 2
    (EVIDENCE / "FINAL_VALIDATION.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS" if summary["all_available_scope_pass"] else "FAIL", "frontend_tests": summary["frontend_tests"], "local_preview_tests": summary["local_preview_tests"], "b15_rev2_product_tests": summary["b15_rev2_product_tests"], "browser_all_pass": summary["browser_all_pass"], "database_unchanged_by_read": summary["database_unchanged_by_read"]}, ensure_ascii=True))
    return 0 if summary["all_available_scope_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
