from __future__ import annotations

import io
import json
import sys
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import security_suite  # noqa: E402


def main() -> int:
    evidence = ROOT / "review" / "D13" / "001" / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(security_suite.D13SecurityTests)
    started = time.perf_counter()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    elapsed = time.perf_counter() - started
    log = stream.getvalue()
    (evidence / "D13_SECURITY_TEST.log").write_text(log, encoding="utf-8")
    payload = {
        "schema_version": "CDH-D13-SECURITY-TEST-RESULT-1",
        "tests_run": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "elapsed_seconds": round(elapsed, 6),
        "successful": result.wasSuccessful(),
        "failure_tests": [str(test) for test, _trace in result.failures],
        "error_tests": [str(test) for test, _trace in result.errors],
    }
    (evidence / "D13_SECURITY_TEST_RESULT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(log, end="")
    print(json.dumps(payload, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
