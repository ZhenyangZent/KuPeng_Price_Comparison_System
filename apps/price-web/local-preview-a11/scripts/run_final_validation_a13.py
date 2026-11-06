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
REPORT = ROOT / "reports" / "A13_REV3"
LOGS = REPORT / "logs"
EVIDENCE = REPORT / "evidence"
R11 = ROOT / "input" / "orchestrator_bundles" / "R11_FAST_TRACK_DELTA_20261105"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def execute(name: str, command: list[str], cwd: Path, timeout: int = 300) -> dict[str, object]:
    test_temp = REPORT / "test_temp" / name
    test_temp.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "TEMP": str(test_temp), "TMP": str(test_temp)}
    if name == "B15_EXACT_PRODUCT_TESTS":
        environment["CDH_B15_BASELINE_ROOT"] = str(ROOT / "review" / "releases")
    result = subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    record = {"name": name, "command": command, "cwd": str(cwd), "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr, "pass": result.returncode == 0}
    (LOGS / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"{name} failed with {result.returncode}: {(result.stderr + result.stdout)[-4000:]}")
    return record


def verify_r11() -> dict[str, object]:
    archive_path = R11 / "CDH_R11_FAST_TRACK_DELTA_20261105.zip"
    extracted = R11 / "extracted"
    expected_zip = "8c1f71375dcf08df93f6c50cab35f7e196c641a70ca0f5b8184af3fd448b9bcb"
    manifest_path = extracted / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = manifest["files"]
    actual = {item.relative_to(extracted).as_posix(): sha256(item) for item in extracted.rglob("*") if item.is_file() and item != manifest_path}
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        archive_files = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in names if not name.endswith("/") and name != "MANIFEST.json"}
        unsafe = [name for name in names if PurePosixPath(name.replace("\\", "/")).is_absolute() or ".." in PurePosixPath(name.replace("\\", "/")).parts]
        crc_bad = archive.testzip()
    result = {"zip_sha256": sha256(archive_path), "expected_zip_sha256": expected_zip, "manifest_sha256": sha256(manifest_path), "manifest_schema": manifest.get("schema"), "declared": len(declared), "archive": len(archive_files), "extracted": len(actual), "missing": sorted(set(declared) - set(actual)), "undeclared": sorted(set(actual) - set(declared)), "mismatch": sorted(key for key in set(declared) & set(actual) if declared[key] != actual[key]), "crc_bad": crc_bad, "duplicates": len(names) - len(set(names)), "case_collisions": len(names) - len({name.casefold() for name in names}), "unsafe": unsafe}
    result["pass"] = result["zip_sha256"] == expected_zip and manifest.get("schema") == "CDH-R11-DELTA-MANIFEST-1" and len(declared) == 10 and declared == archive_files == actual and crc_bad is None and result["duplicates"] == result["case_collisions"] == 0 and unsafe == []
    return result


def verify_b15_rev2() -> dict[str, object]:
    archive_path = ROOT / "review" / "releases" / "CDH_B_R11_002_REVIEW.zip"
    extract_base = ROOT / "input" / "crossline" / "A13" / "R11" / "B15_REV2"
    manifest_path = extract_base / "CDH_B_R11_002_REVIEW" / "REVIEW_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = {entry["path"]: (entry["bytes"], entry["sha256"]) for entry in manifest["payloads"]}
    actual = {item.relative_to(extract_base).as_posix(): (item.stat().st_size, sha256(item)) for item in extract_base.rglob("*") if item.is_file() and item != manifest_path and "__pycache__" not in item.parts and item.suffix != ".pyc"}
    with zipfile.ZipFile(archive_path) as archive:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
        archive_payloads = {info.filename: (info.file_size, hashlib.sha256(archive.read(info)).hexdigest()) for info in archive.infolist() if not info.is_dir() and info.filename != "CDH_B_R11_002_REVIEW/REVIEW_MANIFEST.json"}
        unsafe = [name for name in names if PurePosixPath(name.replace("\\", "/")).is_absolute() or ".." in PurePosixPath(name.replace("\\", "/")).parts]
        crc_bad = archive.testzip()
    result = {"zip_sha256": sha256(archive_path), "manifest_sha256": sha256(manifest_path), "manifest_schema": manifest.get("schema_version"), "declared": len(declared), "archive": len(archive_payloads), "extracted": len(actual), "missing": sorted(set(declared) - set(actual)), "undeclared": sorted(set(actual) - set(declared)), "mismatch": sorted(key for key in set(declared) & set(actual) if declared[key] != actual[key]), "crc_bad": crc_bad, "duplicates": len(names) - len(set(names)), "case_collisions": len(names) - len({name.casefold() for name in names}), "unsafe": unsafe}
    result["pass"] = result["zip_sha256"] == "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe" and manifest.get("schema_version") == "CDH-B15-REV2-REVIEW-MANIFEST-1" and declared == archive_payloads == actual and crc_bad is None and result["duplicates"] == result["case_collisions"] == 0 and unsafe == []
    return result


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True); EVIDENCE.mkdir(parents=True, exist_ok=True)
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not npm or not powershell:
        raise RuntimeError("npm or Windows PowerShell unavailable")
    r11 = verify_r11()
    if not r11["pass"]:
        raise RuntimeError(f"R11 input integrity failed: {r11}")
    b15_rev2_input = verify_b15_rev2()
    if not b15_rev2_input["pass"]:
        raise RuntimeError(f"B15 REV2 input integrity failed: {b15_rev2_input}")
    pinned = {
        "a12_r10": {"path": "review/releases/CDH_A_R10_001_REVIEW.zip", "expected": "7a361572ee88c8fe7bd85ae7e8578a635939c9b939725e1c4c4e2da58d0c1fb9"},
        "b11_r07": {"path": "review/releases/CDH_B_R07_001_REVIEW.zip", "expected": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"},
        "c11_rev2_r10": {"path": "review/releases/CDH_C_R10_002_REVIEW.zip", "expected": "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa"},
        "a13_r11_rev2": {"path": "review/releases/CDH_A_R11_002_REVIEW.zip", "expected": "c4a5e36f868c77682d1a4b40ad00b78611afd3d164216f8ad89827415e732405"},
        "b15_r11_rev2": {"path": "review/releases/CDH_B_R11_002_REVIEW.zip", "expected": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe"},
    }
    for item in pinned.values():
        path = ROOT / item["path"]; item["actual"] = sha256(path) if path.is_file() else None; item["pass"] = item["actual"] == item["expected"]
    if not all(item["pass"] for item in pinned.values()):
        raise RuntimeError(f"pinned release mismatch: {pinned}")
    stages = []
    stages.append(execute("PY_COMPILE", [sys.executable, "-m", "py_compile", str(PREVIEW / "preview_server.py"), str(PREVIEW / "control.py"), str(PREVIEW / "scripts" / "run_final_validation_a13.py"), str(PREVIEW / "scripts" / "package_review.py")], ROOT))
    stages.append(execute("FRONTEND_BUILD", [npm, "run", "build"], FRONTEND))
    stages.append(execute("FRONTEND_TESTS", [npm, "test"], FRONTEND))
    for name, script in (("A07_ROLE_TESTS", "test:role"), ("A09_ROLE_TESTS", "test:a09-role"), ("A10_ROLE_TESTS", "test:a10-role")):
        stages.append(execute(name, [npm, "run", script], FRONTEND))
    stages.append(execute("A13_DIST_MANIFEST", [sys.executable, str(PREVIEW / "scripts" / "write_dist_manifest.py")], ROOT))
    python_unit = execute("A11_A13_PYTHON_UNIT", [sys.executable, "-m", "unittest", "discover", "-s", str(PREVIEW / "tests"), "-v"], ROOT); stages.append(python_unit)
    parse_script = "$e=$null;" + ";".join([f"[System.Management.Automation.Language.Parser]::ParseFile('{str(PREVIEW / name).replace("'", "''")}',[ref]$null,[ref]$e)|Out-Null" for name in ("Start-LocalPreview.ps1", "Stop-LocalPreview.ps1", "Status-LocalPreview.ps1")]) + ";if($e.Count){$e|Out-String|Write-Error;exit 1};Write-Output 'POWERSHELL_PARSE_PASS'"
    stages.append(execute("POWERSHELL_PARSE", [powershell, "-NoProfile", "-Command", parse_script], ROOT))
    stages.append(execute("A12_LOOPBACK_REGRESSION", [sys.executable, str(PREVIEW / "scripts" / "run_integration.py"), "--a12"], ROOT))
    stages.append(execute("A12_BROWSER_REGRESSION", [npm, "run", "e2e:a12"], FRONTEND))
    b15_source = ROOT / "input" / "crossline" / "A13" / "R11" / "B15_REV2" / "CDH_B_R11_002_REVIEW"
    stages.append(execute("B15_EXACT_PRODUCT_TESTS", [sys.executable, "-m", "unittest", "discover", "-s", str(b15_source / "tests" / "private_observation_b15"), "-v"], b15_source))
    stages.append(execute("A13_REV3_ACTUAL_B15_REV2_BROWSER", [npm, "run", "e2e:a13"], FRONTEND))
    frontend_log = next(item for item in stages if item["name"] == "FRONTEND_TESTS")
    test_match = re.search(r"Tests\s+(\d+) passed", str(frontend_log["stdout"]) + str(frontend_log["stderr"]))
    unit_match = re.search(r"Ran (\d+) tests", str(python_unit["stderr"]) + str(python_unit["stdout"]))
    browser = json.loads((EVIDENCE / "BROWSER_E2E_A13_REV3.json").read_text(encoding="utf-8"))
    a12_browser = json.loads((ROOT / "reports" / "A12" / "evidence" / "BROWSER_E2E_A12.json").read_text(encoding="utf-8"))
    b15 = {"status": "ACTUAL_LOCAL_API", "exact_release_sha256": pinned["b15_r11_rev2"]["actual"], "actual_preview_confirm_search_detail": browser.get("all_pass") is True, "two_day_observation_e2e": browser.get("dom", {}).get("before") == ["1000", "950"], "negative_case_count": len(browser.get("negatives", [])), "missing_host_code_present": next((item.get("code_present") for item in browser.get("negatives", []) if item.get("name") == "missing_host"), False), "isolated_private_data_root": browser.get("isolated_private_data_root"), "formal_database_write_count": browser.get("formal_database_write_count")}
    summary = {"task_id": "CDH-A13-PRIVATE-MANUAL-PRICE-UI-001", "revision": "REV3", "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "authority": "SCOPED_LOCAL_DEVELOPMENT_WITH_SYNTHETIC_TESTS_ONLY", "r11_input": r11, "b15_rev2_input": b15_rev2_input, "pinned_releases": pinned, "frontend_tests": int(test_match.group(1)) if test_match else None, "python_unit_tests": int(unit_match.group(1)) if unit_match else None, "a12_browser_cases": len(a12_browser.get("cases", [])), "a12_browser_all_pass": a12_browser.get("all_pass"), "a13_browser_positive_observations": 2, "a13_browser_negative_cases": len(browser.get("negatives", [])), "a13_browser_all_pass": browser.get("all_pass"), "b15_integration": b15, "stages": [{"name": item["name"], "exit_code": item["exit_code"], "pass": item["pass"]} for item in stages]}
    summary["all_available_scope_pass"] = r11["pass"] and b15_rev2_input["pass"] and all(item["pass"] for item in pinned.values()) and all(item["pass"] for item in stages) and summary["a12_browser_all_pass"] is True and summary["a13_browser_all_pass"] is True
    (EVIDENCE / "FINAL_VALIDATION.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_REV3" if summary["all_available_scope_pass"] else "FAIL", "frontend_tests": summary["frontend_tests"], "python_tests": summary["python_unit_tests"], "a12_browser": summary["a12_browser_cases"], "a13_positive": summary["a13_browser_positive_observations"], "a13_negative": summary["a13_browser_negative_cases"], "b15_integration": b15["status"]}, ensure_ascii=True))
    return 0 if summary["all_available_scope_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
