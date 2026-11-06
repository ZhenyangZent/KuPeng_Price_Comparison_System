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
REPORT = ROOT / "reports" / "A12"
LOGS = REPORT / "logs"
EVIDENCE = REPORT / "evidence"
R10 = ROOT / "input" / "orchestrator_bundles" / "UNIFIED_CONTINUOUS_20261105_R10"
B14_SHA256 = "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9"
C11_SHA256 = "61fe46e988f9955ecc0db5b719ebec861cb220eef0054eb664288557250bff20"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def execute(name: str, command: list[str], cwd: Path) -> dict[str, object]:
    environment = {**os.environ, "PYTHONUTF8": "1"}
    result = subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
    record = {"name": name, "command": command, "cwd": str(cwd), "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr, "pass": result.returncode == 0}
    (LOGS / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"{name} failed with {result.returncode}: {(result.stderr + result.stdout)[-3000:]}")
    return record


def verify_r10() -> dict[str, object]:
    archive_path = R10 / "CDH_UNIFIED_CONTINUOUS_20261105_R10.zip"
    extracted = R10 / "extracted"
    expected_zip = "0474031243db86ffc7c7b05e7569f701f5705cf84a25b98453b987f1c99b7abc"
    manifest_path = extracted / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = {item["path"]: (item["bytes"], item["sha256"]) for item in manifest["payloads"]}
    actual = {item.relative_to(extracted).as_posix(): (item.stat().st_size, sha256(item)) for item in extracted.rglob("*") if item.is_file() and item != manifest_path}
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        unsafe = [name for name in names if PurePosixPath(name.replace("\\", "/")).is_absolute() or ".." in PurePosixPath(name.replace("\\", "/")).parts]
        crc_bad = archive.testzip()
    result = {"zip_sha256": sha256(archive_path), "expected_zip_sha256": expected_zip, "manifest_sha256": sha256(manifest_path), "manifest_schema": manifest.get("schema"), "declared": len(declared), "actual": len(actual), "missing": sorted(set(declared) - set(actual)), "undeclared": sorted(set(actual) - set(declared)), "mismatch": sorted(key for key in set(declared) & set(actual) if declared[key] != actual[key]), "crc_bad": crc_bad, "duplicates": len(names) - len(set(names)), "unsafe": unsafe}
    result["pass"] = result["zip_sha256"] == expected_zip and result["manifest_schema"] == "CDH-R10-SHARED-TASK-MANIFEST-1" and len(declared) == 19 and declared == actual and crc_bad is None and result["duplicates"] == 0 and unsafe == []
    return result


def verify_crossline_release(path: Path, expected_sha256: str, manifest_name: str, root_prefix: str) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        files = {info.filename: info for info in archive.infolist() if not info.is_dir()}
        manifest_bytes = archive.read(manifest_name)
        manifest = json.loads(manifest_bytes)
        declared: dict[str, tuple[int, str]] = {}
        for item in manifest["payloads"]:
            archive_name = item["path"] if item["path"] in files else root_prefix + item["path"]
            declared[archive_name] = (item["bytes"], item["sha256"])
        actual = {
            name: (files[name].file_size, hashlib.sha256(archive.read(name)).hexdigest())
            for name in files if name != manifest_name
        }
        unsafe = [name for name in names if PurePosixPath(name.replace("\\", "/")).is_absolute() or ".." in PurePosixPath(name.replace("\\", "/")).parts]
        case_collisions = len(names) - len({name.casefold() for name in names})
        crc_bad = archive.testzip()
    result = {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "zip_sha256": sha256(path),
        "expected_zip_sha256": expected_sha256,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest_schema": manifest.get("schema_version") or manifest.get("schema"),
        "declared": len(declared),
        "actual": len(actual),
        "missing": sorted(set(declared) - set(actual)),
        "undeclared": sorted(set(actual) - set(declared)),
        "mismatch": sorted(key for key in set(declared) & set(actual) if declared[key] != actual[key]),
        "crc_bad": crc_bad,
        "duplicates": len(names) - len(set(names)),
        "case_collisions": case_collisions,
        "unsafe": unsafe,
    }
    result["pass"] = (
        result["zip_sha256"] == expected_sha256
        and declared == actual
        and crc_bad is None
        and result["duplicates"] == 0
        and case_collisions == 0
        and unsafe == []
    )
    return result


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True); EVIDENCE.mkdir(parents=True, exist_ok=True)
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not npm or not powershell:
        raise RuntimeError("npm or Windows PowerShell unavailable")
    r10 = verify_r10()
    if not r10["pass"]:
        raise RuntimeError(f"R10 input integrity failed: {r10}")
    crossline = {
        "b14_r10": verify_crossline_release(
            ROOT / "review" / "releases" / "CDH_B_R10_001_REVIEW.zip",
            B14_SHA256,
            "CDH_B_R10_001_REVIEW/REVIEW_MANIFEST.json",
            "CDH_B_R10_001_REVIEW/",
        ),
        "c11_r10": verify_crossline_release(
            ROOT / "review" / "releases" / "CDH_C_R10_001_REVIEW.zip",
            C11_SHA256,
            "CDH_C_R10_001_REVIEW/MANIFEST.json",
            "CDH_C_R10_001_REVIEW/",
        ),
    }
    if not all(item["pass"] for item in crossline.values()):
        raise RuntimeError(f"cross-line input integrity failed: {crossline}")
    stages = []
    stages.append(execute("PY_COMPILE", [sys.executable, "-m", "py_compile", str(PREVIEW / "preview_server.py"), str(PREVIEW / "control.py"), str(PREVIEW / "scripts" / "run_integration.py"), str(PREVIEW / "scripts" / "package_review.py")], ROOT))
    stages.append(execute("A10_A11_PRESERVED_VALIDATION", [npm, "run", "validate:a10"], FRONTEND))
    stages.append(execute("A12_DIST_MANIFEST", [sys.executable, str(PREVIEW / "scripts" / "write_dist_manifest.py")], ROOT))
    python_unit = execute("A11_A12_PYTHON_UNIT", [sys.executable, "-m", "unittest", "discover", "-s", str(PREVIEW / "tests"), "-v"], ROOT); stages.append(python_unit)
    parse_script = "$e=$null;" + ";".join([f"[System.Management.Automation.Language.Parser]::ParseFile('{str(PREVIEW / name).replace("'", "''")}',[ref]$null,[ref]$e)|Out-Null" for name in ("Start-LocalPreview.ps1", "Stop-LocalPreview.ps1", "Status-LocalPreview.ps1")]) + ";if($e.Count){$e|Out-String|Write-Error;exit 1};Write-Output 'POWERSHELL_PARSE_PASS'"
    stages.append(execute("POWERSHELL_PARSE", [powershell, "-NoProfile", "-Command", parse_script], ROOT))
    stages.append(execute("A12_LOOPBACK_INTEGRATION", [sys.executable, str(PREVIEW / "scripts" / "run_integration.py"), "--a12"], ROOT))
    stages.append(execute("A12_BROWSER_E2E", [npm, "run", "e2e:a12"], FRONTEND))
    preserved = json.loads((ROOT / "reports" / "A10" / "logs" / "FINAL_VALIDATION.json").read_text(encoding="utf-8"))
    preserved_browser = json.loads((ROOT / "reports" / "A10" / "evidence" / "HEADLESS_E2E.json").read_text(encoding="utf-8"))
    integration = json.loads((EVIDENCE / "LOCAL_PREVIEW_INTEGRATION.json").read_text(encoding="utf-8"))
    browser = json.loads((EVIDENCE / "BROWSER_E2E_A12.json").read_text(encoding="utf-8"))
    unit_match = re.search(r"Ran (\d+) tests", str(python_unit["stderr"]) + str(python_unit["stdout"]))
    pinned = {
        "a11_r09": {"path": "review/releases/CDH_A_R09_001_REVIEW.zip", "expected": "40e54a65a7c2bfe808bcaa528e75058ab96c98c4f68d9cfa09259b7e5b97a0cd"},
        "b11_r07": {"path": "review/releases/CDH_B_R07_001_REVIEW.zip", "expected": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"},
    }
    for item in pinned.values():
        path = ROOT / item["path"]; item["actual"] = sha256(path) if path.is_file() else None; item["pass"] = item["actual"] == item["expected"]
    summary = {
        "task_id": "CDH-A12-LOCAL-PRICE-DAILY-DOM-AND-SAFE-IMPORT-PREVIEW-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "authority": "SCOPED_OFFLINE_LOCAL_ONLY",
        "r10_input": r10,
        "crossline_inputs": crossline,
        "pinned_releases": pinned,
        "preserved_frontend_and_role_tests": 67,
        "preserved_browser_cases": len(preserved_browser.get("results", [])),
        "python_unit_tests": int(unit_match.group(1)) if unit_match else None,
        "a12_browser_cases": len(browser.get("cases", [])),
        "a12_daily_dom_cases": browser.get("daily_dom_case_count"),
        "a12_actual_browser_api_responses": len(browser.get("actual_api_network_responses", [])),
        "wire_probe_count": len(browser.get("wire_probes", [])),
        "loopback_integration_all_pass": integration.get("all_pass"),
        "preserved_validation_all_pass": preserved.get("all_pass"),
        "preserved_browser_all_pass": preserved_browser.get("all_pass"),
        "a12_browser_all_pass": browser.get("all_pass"),
        "safe_import_preview": {
            "status": "NOT_RUN_UPSTREAM_CONTRACT_NOT_BOUND",
            "b14_release_available_and_integrity_pass": True,
            "c11_release_available_and_integrity_pass": True,
            "blocker": "Exact C11 release explicitly records B14_DUPLICATE_JSON_GATE=NOT_RUN_INPUT_UNAVAILABLE and accepts only a B13/C10 binding. A12 must not fabricate a B14-to-C11 safe DTO.",
            "ui_product_data_displayed": False,
            "formal_import_action_exposed": False,
        },
        "stages": [{"name": item["name"], "exit_code": item["exit_code"], "pass": item["pass"]} for item in stages],
    }
    summary["all_available_scope_pass"] = all(item["pass"] for item in stages) and r10["pass"] and all(item["pass"] for item in crossline.values()) and all(item["pass"] for item in pinned.values()) and all(summary[key] is True for key in ("loopback_integration_all_pass", "preserved_validation_all_pass", "preserved_browser_all_pass", "a12_browser_all_pass"))
    (EVIDENCE / "FINAL_VALIDATION.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_AVAILABLE_SCOPE" if summary["all_available_scope_pass"] else "FAIL", "preserved_tests": 67, "python_tests": summary["python_unit_tests"], "preserved_browser": summary["preserved_browser_cases"], "a12_browser": summary["a12_browser_cases"], "daily_dom_cases": summary["a12_daily_dom_cases"], "safe_import_preview": "NOT_RUN_UPSTREAM_CONTRACT_NOT_BOUND"}, ensure_ascii=True))
    return 0 if summary["all_available_scope_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
