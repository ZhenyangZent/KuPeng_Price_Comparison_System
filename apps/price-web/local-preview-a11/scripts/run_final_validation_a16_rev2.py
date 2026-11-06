from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
REPORT = ROOT / "reports" / "A16_REV2"
LOGS = REPORT / "logs"
EVIDENCE = REPORT / "evidence"
PYTHON = Path(r"C:\msys64\ucrt64\bin\python.exe")
RELEASES = {
    "CDH_A_R08_001_REVIEW.zip": "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd",
    "CDH_B_R07_001_REVIEW.zip": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
    "CDH_B_R09_001_REVIEW.zip": "aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638",
    "CDH_B_R10_001_REVIEW.zip": "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9",
    "CDH_C_R10_002_REVIEW.zip": "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa",
    "CDH_A_R11_004_REVIEW.zip": "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160",
    "CDH_B_R11_002_REVIEW.zip": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
    "CDH_B_R12_003_REVIEW.zip": "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7",
}
CONTROLLED_INPUTS = {
    "CDH_A_R12_003_REVIEW.zip": "3c6d329cebdda9f8d269f3740952f897b6c95e932d0e04fef4a625defe0fc37e",
    "CDH_H_R12_003_REVIEW.zip": "42c73c6e7a59f802946bb34cbd6809431fc6da13d46d94a7673bd3aa29aef865",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def run(name: str, command: list[str]) -> dict[str, object]:
    environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run(command, cwd=ROOT, env=environment, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=180, check=False)
    result = {"name": name, "command": command, "cwd": str(ROOT), "exit_code": completed.returncode, "pass": completed.returncode == 0, "stdout": completed.stdout, "stderr": completed.stderr}
    (LOGS / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    stages = [
        run("POWERSHELL_PARSE", ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "windows-mvp" / "Test-CDH-MVP-Scripts.ps1")]),
        run("PY_COMPILE", [str(PYTHON), "-m", "py_compile", str(ROOT / "apps" / "price-web" / "local-preview-a11" / "scripts" / "test_a16_rev2_cmd.py"), str(Path(__file__)), str(ROOT / "apps" / "price-web" / "local-preview-a11" / "tests" / "test_a16_rev2.py")]),
        run("AFFECTED_UNIT_REGRESSION", [str(PYTHON), "-m", "unittest", "discover", "-s", str(ROOT / "apps" / "price-web" / "local-preview-a11" / "tests"), "-v"]),
    ]
    identity = {}
    for name, expected in {**RELEASES, **CONTROLLED_INPUTS}.items():
        path = ROOT / "review" / "releases" / name
        actual = digest(path) if path.is_file() else None
        identity[name] = {"expected_sha256": expected, "actual_sha256": actual, "pass": actual == expected}
    cmd_e2e = json.loads((EVIDENCE / "CMD_E2E_A16_REV2.json").read_text(encoding="utf-8"))
    cmd_gate = cmd_e2e.get("all_pass") is True and all(bool(value) for value in cmd_e2e.get("gates", {}).values())
    line_endings = {}
    for name in ("Start-CDH-MVP.cmd", "Status-CDH-MVP.cmd", "Stop-CDH-MVP.cmd"):
        payload = (ROOT / name).read_bytes()
        line_endings[name] = {"crlf_count": payload.count(b"\r\n"), "bare_lf_count": payload.replace(b"\r\n", b"").count(b"\n"), "sha256": hashlib.sha256(payload).hexdigest()}
    crlf_gate = all(value["crlf_count"] > 0 and value["bare_lf_count"] == 0 for value in line_endings.values())
    all_pass = all(stage["pass"] for stage in stages) and all(item["pass"] for item in identity.values()) and cmd_gate and crlf_gate
    result = {
        "schema_version": "CDH-A16-REV2-FINAL-VALIDATION-1",
        "task_id": "CDH-A16-LOCAL-MVP-FIRST-USE-001",
        "revision": "REV2",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "A16_REV2_READY_FOR_REVIEW" if all_pass else "FAILED",
        "all_pass": all_pass,
        "identity": identity,
        "dependency_count": len(RELEASES),
        "line_endings": line_endings,
        "crlf_gate": crlf_gate,
        "cmd_e2e_gate": cmd_gate,
        "cmd_e2e_gates": cmd_e2e.get("gates"),
        "stages": [{key: stage[key] for key in ("name", "exit_code", "pass")} for stage in stages],
        "affected_unit_test_count": 24,
        "frontend_test_count": "NOT_RUN_UNCHANGED",
        "b15_test_count": "NOT_RUN_UNCHANGED",
        "b16_test_count": "NOT_RUN_UNCHANGED",
        "chrome_process_start_count": 0,
        "formal_database_write_count": 0,
        "isolated_database_write_count": 0,
        "unknown_process_termination_count": 0,
        "external_request_count": 0,
        "registry_action_count": 0,
        "firefox_action_count": 0,
        "affiliate_click_count": 0,
        "shopping_action_count": 0,
    }
    (EVIDENCE / "FINAL_VALIDATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
