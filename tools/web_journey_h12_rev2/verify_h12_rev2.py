from __future__ import annotations

import json
import socket
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H12 = ROOT / "review" / "H12_REV2"
OUT = H12 / "FINAL_VERIFICATION.json"
sys.path.insert(0, str(ROOT))


def main() -> None:
    browser = json.loads((H12 / "evidence" / "ACTUAL_H12_REV2_BROWSER_HTTP.json").read_text(encoding="utf-8"))
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.web.journey_h12_rev2.test_h12_rev2")
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        port_closed = probe.connect_ex(("127.0.0.1", 12337)) != 0
    active_absent = not (H12 / "runtime" / "project" / "data" / "local_mvp" / "state" / "active.json").exists()
    failed_gates = [name for name, passed in browser["gates"].items() if not passed]
    existing = json.loads(OUT.read_text(encoding="utf-8"))
    existing.update({
        "portable_evidence_test_pass_count": result.testsRun - len(result.failures) - len(result.errors),
        "portable_evidence_test_count": result.testsRun,
        "portable_evidence_test_status": "PASS" if result.wasSuccessful() else "FAIL",
        "failed_product_gates": failed_gates,
        "server_port_closed_after_test": port_closed,
        "active_receipt_absent_after_test": active_absent,
    })
    OUT.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    valid = (
        result.wasSuccessful()
        and browser["status"] == "FAIL"
        and browser["browser_test_exit_code"] == 1
        and browser["chrome_process_exit_code"] == 0
        and failed_gates == ["first_use_controls_and_classification"]
        and port_closed
        and active_absent
    )
    print(json.dumps({"status": "PASS" if valid else "FAIL", "evidence_tests": result.testsRun, "product_status": browser["status"], "failed_product_gates": failed_gates, "port_closed": port_closed}))
    raise SystemExit(0 if valid else 1)


if __name__ == "__main__":
    main()
