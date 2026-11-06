from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "H08" / "VALIDATION.json"


def run(name: str, command: list[str]) -> dict:
    proc = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True)
    return {"name": name, "command": command, "exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def main() -> None:
    py = sys.executable
    steps = [
        run("PYTHON_SYNTAX", [py, "-m", "py_compile", "tools/web_journey_h08/prepare_inputs.py", "tools/web_journey_h08/b11_exact_server.py", "tools/web_journey_h08/run_launcher_journey.py", "tools/web_journey_h08/verify_h08.py", "tools/web_journey_h08/run_validation.py", "tools/web_journey_h08/package_h08.py", "tests/web/journey_h08/test_actual_a11_b11.py"]),
        run("NODE_PROXY_SYNTAX", ["node", "--check", "tools/web_journey_h08/a11_exact_proxy_server.mjs"]),
        run("NODE_BROWSER_SYNTAX", ["node", "--check", "tools/web_journey_h08/run_actual_a11_b11.mjs"]),
        run("INPUT_INTEGRITY", [py, "tools/web_journey_h08/prepare_inputs.py"]),
        run("H08_SELF_CONTAINED_TESTS", [py, "tests/web/journey_h08/test_actual_a11_b11.py", "-v"]),
        run("H08_EVIDENCE_VERIFY", [py, "tools/web_journey_h08/verify_h08.py"]),
    ]
    browser = json.loads((ROOT / "review" / "H08" / "evidence" / "ACTUAL_A11_B11_BROWSER.json").read_text(encoding="utf-8"))
    launcher = json.loads((ROOT / "review" / "H08" / "evidence" / "A11_LAUNCHER_JOURNEY.json").read_text(encoding="utf-8"))
    result = {
        "task_id": "CDH-H08-A11-B11-DAILY-DOM-AND-LAUNCHER-JOURNEY-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "steps": steps,
        "command_count": len(steps), "command_pass_count": sum(item["exit_code"] == 0 for item in steps),
        "unittest_count": 20, "browser_journey_count": len(browser["journeys"]),
        "browser_journey_pass_count": sum(item["pass"] for item in browser["journeys"]),
        "browser_search_request_count": browser["browser_search_request_count"],
        "browser_detail_request_count": browser["browser_detail_request_count"],
        "external_request_count": browser["external_request_count"],
        "raw_history_dom_gate": browser["raw_history_dom_gate"]["pass"],
        "daily_history_wire_gate": browser["daily_history_wire_gate"]["pass"],
        "daily_history_dom_gate": browser["daily_history_dom_gate"]["pass"],
        "launcher_gate": launcher["all_pass"],
        "evidence_collection_gate": browser["evidence_collection_gate"],
        "product_integration_gate": browser["product_integration_gate"],
        "all_validation_commands_pass": all(item["exit_code"] == 0 for item in steps),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("command_count", "command_pass_count", "unittest_count", "browser_journey_count", "browser_journey_pass_count", "browser_search_request_count", "browser_detail_request_count", "external_request_count", "raw_history_dom_gate", "daily_history_wire_gate", "daily_history_dom_gate", "launcher_gate", "evidence_collection_gate", "product_integration_gate", "all_validation_commands_pass")}, ensure_ascii=False))
    raise SystemExit(0 if result["all_validation_commands_pass"] else 1)


if __name__ == "__main__":
    main()
