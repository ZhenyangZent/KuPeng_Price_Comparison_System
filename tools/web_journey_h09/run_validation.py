from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "H09" / "VALIDATION.json"


def run(name: str, command: list[str]) -> dict:
    proc = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True)
    return {"name": name, "command": command, "exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def main() -> None:
    py = sys.executable
    steps = [
        run("PYTHON_SYNTAX", [py, "-m", "py_compile", "tools/web_journey_h09/prepare_inputs.py", "tools/web_journey_h09/stage_project.py", "tools/web_journey_h09/inspect_db.py", "tools/web_journey_h09/verify_h09.py", "tools/web_journey_h09/run_validation.py", "tools/web_journey_h09/package_h09.py", "tests/web/journey_h09/test_h09.py"]),
        run("NODE_SYNTAX", ["node", "--check", "tools/web_journey_h09/run_actual_h09.mjs"]),
        run("INPUT_INTEGRITY", [py, "tools/web_journey_h09/prepare_inputs.py"]),
        run("SQLITE_READONLY", [py, "tools/web_journey_h09/inspect_db.py"]),
        run("H09_EVIDENCE_VERIFY", [py, "tools/web_journey_h09/verify_h09.py"]),
        run("H09_UNITTEST", [py, "tests/web/journey_h09/test_h09.py", "-v"]),
    ]
    verify = json.loads((ROOT / "review" / "H09" / "evidence" / "H09_VERIFICATION.json").read_text(encoding="utf-8"))
    result = {
        "task_id": "CDH-H09-A13REV3-B15REV2-WINDOWS-E2E-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "steps": steps,
        "command_count": len(steps), "command_pass_count": sum(item["exit_code"] == 0 for item in steps),
        "unittest_count": 18, "evidence_gate_count": len(verify["gates"]),
        "evidence_gate_pass_count": sum(verify["gates"].values()),
        "product_journey_run_count": verify["harness_assertion_reconciliation"]["product_journey_run_count"],
        "external_request_count": verify["external_request_count"],
        "database_observation_count": verify["database_observation_count"],
        "main_product_observation_count": verify["main_product_observation_count"],
        "status": verify["status"], "all_validation_commands_pass": all(item["exit_code"] == 0 for item in steps),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("command_count", "command_pass_count", "unittest_count", "evidence_gate_count", "evidence_gate_pass_count", "product_journey_run_count", "external_request_count", "database_observation_count", "main_product_observation_count", "status", "all_validation_commands_pass")}, ensure_ascii=False))
    raise SystemExit(0 if result["all_validation_commands_pass"] else 1)


if __name__ == "__main__":
    main()
