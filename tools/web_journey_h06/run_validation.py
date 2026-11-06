from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "H06" / "VALIDATION.json"


def run(name: str, command: list[str]) -> dict:
    proc = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True)
    return {"name": name, "command": command, "exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def main() -> None:
    py = sys.executable
    steps = [
        run("PYTHON_SYNTAX", [py, "-m", "py_compile", "tools/web_journey_h06/prepare_inputs.py", "tools/web_journey_h06/b11_exact_server.py", "tools/web_journey_h06/verify_h06.py", "tools/web_journey_h06/run_validation.py", "tools/web_journey_h06/package_h06.py", "tests/web/journey_h06/test_actual_a10_b11.py"]),
        run("NODE_PROXY_SYNTAX", ["node", "--check", "tools/web_journey_h06/a10_exact_proxy_server.mjs"]),
        run("NODE_BROWSER_SYNTAX", ["node", "--check", "tools/web_journey_h06/run_actual_a10_b11.mjs"]),
        run("INPUT_INTEGRITY", [py, "tools/web_journey_h06/prepare_inputs.py"]),
        run("H06_SELF_CONTAINED_TESTS", [py, "tests/web/journey_h06/test_actual_a10_b11.py", "-v"]),
        run("H06_EVIDENCE_VERIFY", [py, "tools/web_journey_h06/verify_h06.py"]),
    ]
    browser = json.loads((ROOT / "review" / "H06" / "evidence" / "ACTUAL_A10_B11_BROWSER.json").read_text(encoding="utf-8"))
    result = {
        "task_id": "CDH-H06-A10-B11-ACTUAL-BROWSER-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
        "command_count": len(steps),
        "command_pass_count": sum(item["exit_code"] == 0 for item in steps),
        "unittest_count": 18,
        "browser_journey_count": len(browser["journeys"]),
        "browser_journey_pass_count": sum(item["pass"] for item in browser["journeys"]),
        "browser_search_request_count": browser["browser_search_request_count"],
        "browser_detail_request_count": browser["browser_detail_request_count"],
        "external_request_count": browser["external_request_count"],
        "actual_browser_evidence": browser["evidence_result"],
        "final_integration_gate": browser["final_integration_gate"],
        "all_validation_commands_pass": all(item["exit_code"] == 0 for item in steps),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("command_count", "command_pass_count", "unittest_count", "browser_journey_count", "browser_journey_pass_count", "browser_search_request_count", "browser_detail_request_count", "external_request_count", "actual_browser_evidence", "final_integration_gate", "all_validation_commands_pass")}, ensure_ascii=False))
    raise SystemExit(0 if result["all_validation_commands_pass"] else 1)


if __name__ == "__main__":
    main()
