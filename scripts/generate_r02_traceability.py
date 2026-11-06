from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
OUTPUT = ROOT / "reports" / "R02" / "REQUIREMENT_TRACEABILITY.csv"


def flatten(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def mapping(test_id: str) -> tuple[str, str]:
    if "test_orchestrator_r01_new_regressions" in test_id:
        finding = {
            "R02_01": "F03_HISTORY_FRESHNESS",
            "R02_02": "F01_MONOTONIC_STATE",
            "R02_03": "F05_AVAILABILITY_EPOCH",
            "R02_04": "F04_STABLE_NOTIFICATION_IDENTITY",
            "R02_05": "F06_BASELINE_TRUST",
            "R02_06": "F02_INCLUDED_COUPON_VALIDATION",
            "R02_07": "F02_INCLUDED_ADJUSTMENT_BINDING",
            "R02_08": "F01_REVOCATION_MONOTONICITY",
            "R02_09": "F05_RULE_EPOCH",
        }
        requirement = next(value for key, value in finding.items() if key in test_id)
        return "ORCHESTRATOR_9_VERBATIM", requirement
    if "test_r02_positive_regressions" in test_id:
        return "R02_POSITIVE", "R02_POSITIVE_AND_MIGRATION_COVERAGE"
    return "R01_ORIGINAL_96", "R01_REGRESSION_PRESERVATION"


def main() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    suite = unittest.defaultTestLoader.discover(str(TESTS), pattern="test_*.py")
    test_ids = sorted(test.id() for test in flatten(suite))
    if len(test_ids) != 112 or len(set(test_ids)) != 112:
        raise SystemExit(f"expected 112 unique tests, found {len(test_ids)} / {len(set(test_ids))} unique")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("TEST_INDEX", "TEST_ID", "ORIGIN", "REQUIREMENT", "EVIDENCE_LOG", "EXPECTED_RESULT"))
        for index, test_id in enumerate(test_ids, 1):
            origin, requirement = mapping(test_id)
            writer.writerow(
                (index, test_id, origin, requirement, "logs/after_full_112_stdout.log", "PASS")
            )
    print(f"TRACEABILITY_ROWS={len(test_ids)}")
    print(f"OUTPUT={OUTPUT}")


if __name__ == "__main__":
    main()
