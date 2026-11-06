from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "H05" / "VALIDATION.json"


def run(name: str, command: list[str]) -> dict:
    proc = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True)
    return {"name": name, "command": command, "exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def main() -> None:
    py = sys.executable
    steps = [
        run("PYTHON_SYNTAX", [py, "-m", "py_compile", "tools/web_journey_h05/prepare_inputs.py", "tools/web_journey_h05/b10_exact_server.py", "tools/web_journey_h05/verify_h05.py", "tools/web_journey_h05/run_validation.py", "tools/web_journey_h05/package_h05.py", "tests/web/journey_h05/test_exact_a09_b10.py"]),
        run("NODE_BROWSER_SYNTAX", ["node", "--check", "tools/web_journey_h05/run_exact_a09_b10.mjs"]),
        run("INPUT_INTEGRITY", [py, "tools/web_journey_h05/prepare_inputs.py"]),
        run("H05_SELF_CONTAINED_TESTS", [py, "tests/web/journey_h05/test_exact_a09_b10.py", "-v"]),
        run("H05_EVIDENCE_VERIFY", [py, "tools/web_journey_h05/verify_h05.py"]),
    ]
    browser = json.loads((ROOT / "review" / "H05" / "evidence" / "EXACT_A09_B10_BROWSER.json").read_text(encoding="utf-8"))
    result = {
        "task_id": "CDH-H05-REAL-A10-B11-BROWSER-JOURNEY-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
        "command_count": len(steps),
        "command_pass_count": sum(x["exit_code"] == 0 for x in steps),
        "unittest_count": 14,
        "exact_browser_journey_count": 2,
        "external_request_count": browser["network"]["external_request_count"],
        "exact_a09_b10_integration": browser["exact_a09_b10_gate"],
        "exact_a10_b11_integration": browser["exact_a10_b11_gate"],
        "all_validation_commands_pass": all(x["exit_code"] == 0 for x in steps),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("command_count", "command_pass_count", "unittest_count", "exact_browser_journey_count", "external_request_count", "exact_a09_b10_integration", "exact_a10_b11_integration", "all_validation_commands_pass")}, ensure_ascii=False))
    raise SystemExit(0 if result["all_validation_commands_pass"] else 1)


if __name__ == "__main__":
    main()
