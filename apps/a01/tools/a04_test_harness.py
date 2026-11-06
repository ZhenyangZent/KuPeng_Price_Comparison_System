from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    temporary = ROOT / "experiments/A04/test_tmp"; temporary.mkdir(parents=True, exist_ok=True)
    crossline = ROOT / "input/orchestrator_bundles/I02/extracted/03_INDEPENDENT_CROSSLINE_12_CASES.py"
    suites = [
        ("A01", [sys.executable, "-m", "unittest", "discover", "-s", "tests/a01", "-v"]),
        ("A02", [sys.executable, "-m", "unittest", "discover", "-s", "tests/a02", "-v"]),
        ("I02", [sys.executable, "-m", "unittest", "discover", "-s", "tests/i02", "-v"]),
        ("A03", [sys.executable, "-m", "unittest", "discover", "-s", "tests/a03", "-v"]),
        ("A04", [sys.executable, "-m", "unittest", "discover", "-s", "tests/a04", "-v"]),
        ("D01", [sys.executable, "-m", "unittest", "discover", "-s", "tests/d01", "-v"]),
        ("D02", [sys.executable, "-m", "unittest", "discover", "-s", "tests/d02", "-v"]),
        ("D03", [sys.executable, "-m", "unittest", "discover", "-s", "tests/d03", "-v"]),
        ("CROSSLINE_12", [sys.executable, str(crossline)]),
    ]
    env = dict(os.environ)
    env.update({"QT_QPA_PLATFORM": "offscreen", "CDH_PROJECT_ROOT": str(ROOT), "CDH_TEST_TMP_ROOT": str(temporary), "TEMP": str(temporary), "TMP": str(temporary)})
    results = []
    for name, command in suites:
        started = datetime.now(timezone.utc)
        completed = subprocess.run(command, cwd=ROOT, env=env, shell=False, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        ended = datetime.now(timezone.utc)
        log = f"COMMAND: {json.dumps(command, ensure_ascii=False)}\nEXIT_CODE: {completed.returncode}\nSTARTED_UTC: {started.isoformat()}\nENDED_UTC: {ended.isoformat()}\n\nSTDOUT\n{completed.stdout}\nSTDERR\n{completed.stderr}"
        (output / f"{name}.log").write_text(log, encoding="utf-8")
        matches = re.findall(r"Ran (\d+) tests?", completed.stdout + completed.stderr)
        count = int(matches[-1]) if matches else None
        results.append({"suite": name, "exit_code": completed.returncode, "tests": count, "started_utc": started.isoformat(), "ended_utc": ended.isoformat(), "log": f"{name}.log"})
    summary = {"task_id": "CDH-A04-WINDOWS-DAILY-APP-001", "python": sys.version, "platform": sys.platform, "results": results, "total_tests": sum(item["tests"] or 0 for item in results), "all_pass": all(item["exit_code"] == 0 for item in results)}
    (output / "TEST_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
