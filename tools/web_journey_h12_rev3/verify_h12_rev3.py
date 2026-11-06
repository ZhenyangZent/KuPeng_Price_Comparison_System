from __future__ import annotations

import hashlib
import json
import socket
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H12 = ROOT / "review" / "H12_REV3"
PROJECT = H12 / "runtime" / "project"
OUT = H12 / "FINAL_VERIFICATION.json"
sys.path.insert(0, str(ROOT))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    targeted = json.loads((H12 / "evidence" / "TARGETED_AFFILIATE_GATE.json").read_text(encoding="utf-8"))
    combined = json.loads((H12 / "evidence" / "COMBINED_GATE_EVIDENCE.json").read_text(encoding="utf-8"))
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.web.journey_h12_rev3.test_h12_rev3")
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        port_closed = probe.connect_ex(("127.0.0.1", 12340)) != 0
    active_absent = not (PROJECT / "data" / "local_mvp" / "state" / "active.json").exists()
    db_absent = not (PROJECT / "data" / "private_user_observations_b15" / "private_user_observations.sqlite3").exists()
    rev2_hash = sha256(ROOT / "review" / "releases" / "CDH_H_R12_004_REVIEW.zip")
    existing = json.loads(OUT.read_text(encoding="utf-8"))
    existing.update({
        "portable_evidence_test_pass_count": result.testsRun - len(result.failures) - len(result.errors),
        "portable_evidence_test_count": result.testsRun,
        "portable_evidence_test_status": "PASS" if result.wasSuccessful() else "FAIL",
        "server_port_closed_after_test": port_closed,
        "active_receipt_absent_after_test": active_absent,
        "private_database_absent_after_test": db_absent,
        "h12_rev2_sha256_readback": rev2_hash,
    })
    OUT.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    valid = (
        result.wasSuccessful()
        and targeted["status"] == "PASS"
        and targeted["targeted_browser_test_exit_code"] == 0
        and targeted["chrome_process_exit_code"] == 0
        and targeted["targeted_gate_pass_count"] == targeted["targeted_gate_count"] == 9
        and not targeted["single_run_full_17_gate_claimed"]
        and combined["status"] == "PASS_SCOPED_COMPOSITE_EVIDENCE"
        and combined["composite_product_gate_pass_count"] == combined["composite_product_gate_count"] == 17
        and rev2_hash == "df490f54ff4315e2c4171248464040e02ce2eef58265d1e5c3f88e4854294b80"
        and port_closed and active_absent and db_absent
    )
    print(json.dumps({"status": "PASS" if valid else "FAIL", "evidence_tests": result.testsRun, "targeted": targeted["status"], "composite": combined["status"], "port_closed": port_closed, "database_absent": db_absent}))
    raise SystemExit(0 if valid else 1)


if __name__ == "__main__":
    main()
