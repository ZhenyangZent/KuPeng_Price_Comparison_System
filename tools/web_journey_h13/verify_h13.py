from __future__ import annotations

import hashlib
import json
import socket
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H13 = ROOT / "review" / "H13"
PROJECT = H13 / "runtime" / "project"
OUT = H13 / "FINAL_VERIFICATION.json"
sys.path.insert(0, str(ROOT))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    browser = json.loads((H13 / "evidence" / "ACTUAL_H13_BROWSER_HTTP.json").read_text(encoding="utf-8"))
    reconciliation = json.loads((H13 / "evidence" / "FAILURE_RECONCILIATION.json").read_text(encoding="utf-8"))
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.web.journey_h13.test_h13")
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2); port_closed = probe.connect_ex(("127.0.0.1", 12341)) != 0
    active_absent = not (PROJECT / "data" / "A17_trial" / "state" / "active.json").exists()
    a17_hash = sha256(ROOT / "review" / "releases" / "CDH_A_R13_001_REVIEW.zip")
    existing = json.loads(OUT.read_text(encoding="utf-8"))
    existing.update({
        "portable_evidence_test_pass_count": result.testsRun - len(result.failures) - len(result.errors),
        "portable_evidence_test_count": result.testsRun,
        "portable_evidence_test_status": "PASS" if result.wasSuccessful() else "FAIL",
        "server_port_closed_after_test": port_closed,
        "active_receipt_absent_after_test": active_absent,
        "a17_sha256_readback": a17_hash,
    })
    OUT.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    valid = (
        result.wasSuccessful()
        and browser["status"] == "FAIL" and browser["browser_test_exit_code"] == 1
        and reconciliation["status"] == "FAIL_H_TEST_STALE_RESULT_RACE"
        and reconciliation["stale_manual_detail_hash_observed"]
        and not reconciliation["csv_detail_request_observed"]
        and a17_hash == "5de6b85e72767e8135b7ff0e6e3acb534965d5f636f61eea918cb082b02a8237"
        and port_closed and active_absent
    )
    print(json.dumps({"status": "PASS" if valid else "FAIL", "evidence_tests": result.testsRun, "product_status": browser["status"], "failure": reconciliation["status"], "port_closed": port_closed}))
    raise SystemExit(0 if valid else 1)


if __name__ == "__main__":
    main()
