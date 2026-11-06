from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
B16 = ROOT / "review" / "D13" / "002" / "input" / "CDH_B_R12_002_REVIEW"
EVIDENCE = ROOT / "review" / "D13" / "002" / "evidence"


def main() -> int:
    environment = os.environ.copy()
    environment["CDH_B16_BASELINE_ROOT"] = str(ROOT / "review" / "releases")
    environment["CDH_B15_BASELINE_ROOT"] = str(ROOT / "review" / "releases")
    suites = (("B16_REV2", "tests/private_batch_import_b16", 26), ("B15", "tests/private_observation_b15", 28))
    results = []
    passed = True
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    for name, path, expected in suites:
        completed = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", path, "-v"], cwd=B16, env=environment, text=True, capture_output=True, timeout=240)
        log = completed.stdout + completed.stderr
        (EVIDENCE / f"{name}_UPSTREAM_REPLAY.log").write_text(log, encoding="utf-8")
        gate = completed.returncode == 0 and f"Ran {expected} tests" in log and "OK" in log
        passed = passed and gate
        results.append({"suite": name, "expected": expected, "returncode": completed.returncode, "gate": "PASS" if gate else "FAIL"})
    payload = {"schema_version": "CDH-D13-B16-REV2-UPSTREAM-REPLAY-1", "gate": "PASS" if passed else "FAIL", "total_tests": 54, "suites": results}
    (EVIDENCE / "UPSTREAM_REPLAY_RESULT.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
