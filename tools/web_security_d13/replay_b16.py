from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
B16 = ROOT / "review" / "D13" / "001" / "input" / "CDH_B_R12_001_REVIEW"
EVIDENCE = ROOT / "review" / "D13" / "001" / "evidence"


def main() -> int:
    environment = os.environ.copy()
    environment["CDH_B16_BASELINE_ROOT"] = str(ROOT / "review" / "releases")
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/private_batch_import_b16", "-v"],
        cwd=B16,
        env=environment,
        text=True,
        capture_output=True,
        timeout=240,
    )
    log = completed.stdout + completed.stderr
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "B16_UPSTREAM_REPLAY.log").write_text(log, encoding="utf-8")
    passed = completed.returncode == 0 and "Ran 23 tests" in log and "OK" in log
    result = {
        "schema_version": "CDH-D13-B16-UPSTREAM-REPLAY-1",
        "expected_tests": 23,
        "returncode": completed.returncode,
        "gate": "PASS" if passed else "FAIL",
    }
    (EVIDENCE / "B16_UPSTREAM_REPLAY_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(log, end="")
    print(json.dumps(result, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
