from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
REPORT = PROJECT / "reports" / "H03" / "VALIDATION.json"


def run(name: str, command: list[str]) -> dict[str, object]:
    completed = subprocess.run(command, cwd=PROJECT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    return {"name": name, "command": command, "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def main() -> None:
    node = "node"
    python = sys.executable
    steps = [
        run("PYTHON_SYNTAX", [python, "-m", "py_compile", "tools/web_journey_h03/prepare_baselines.py", "tools/web_journey_h03/generate_b08_cases.py", "tools/web_journey_h03/verify_h03.py", "tools/web_journey_h03/verify_r05_input.py", "tests/web/journey_h03/test_contract_reproduction.py", "tests/web/journey_h03/test_fixed_integration.py"]),
        run("NODE_CONTRACT_SYNTAX", [node, "--check", "tools/web_journey_h03/run_a07_b08_contract.mjs"]),
        run("NODE_BROWSER_SYNTAX", [node, "--check", "tools/web_journey_h03/run_browser_journey.mjs"]),
        run("NODE_REPORT_SYNTAX", [node, "--check", "tools/web_journey_h03/render_integration_report.mjs"]),
        run("BASELINE_INTEGRITY", [python, "tools/web_journey_h03/prepare_baselines.py"]),
        run("R05_INPUT_INTEGRITY", [python, "tools/web_journey_h03/verify_r05_input.py"]),
        run("GENERATE_B08_CASES", [python, "tools/web_journey_h03/generate_b08_cases.py"]),
        run("A07_B08_REPRODUCTION", [node, "tools/web_journey_h03/run_a07_b08_contract.mjs"]),
        run("A07_B08_TESTS", [python, "tests/web/journey_h03/test_contract_reproduction.py", "-v"]),
        run("GENERATE_B09_CASES", [python, "tools/web_journey_h03/generate_b08_cases.py", "--backend=B09"]),
        run("A08_B09_CONTRACT", [node, "tools/web_journey_h03/run_a07_b08_contract.mjs", "--frontend=A08", "--backend=B09"]),
        run("A08_B09_TESTS", [python, "tests/web/journey_h03/test_fixed_integration.py", "-v"]),
        run("H03_EVIDENCE_VERIFY", [python, "tools/web_journey_h03/verify_h03.py"]),
    ]
    browser = json.loads((PROJECT / "review" / "H03" / "evidence" / "BROWSER_JOURNEY_A08_B09.json").read_text(encoding="utf-8"))
    summary = {
        "task_id": "CDH-H03-A07-B08-INTEGRATION-JOURNEY-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
        "command_count": len(steps),
        "command_pass_count": sum(item["exit_code"] == 0 for item in steps),
        "python_unittest_count": 9,
        "browser_journey_count": len(browser["results"]),
        "browser_journey_pass_count": sum(item["pass"] for item in browser["results"]),
        "external_request_count": browser["network"]["external_request_count"],
        "all_pass": all(item["exit_code"] == 0 for item in steps) and browser["all_journeys_pass"],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("command_count", "command_pass_count", "python_unittest_count", "browser_journey_count", "browser_journey_pass_count", "external_request_count", "all_pass")}, ensure_ascii=False))
    if not summary["all_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
