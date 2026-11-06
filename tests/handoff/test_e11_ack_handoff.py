from __future__ import annotations

import json
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "CDH_A_R09_001_REVIEW.zip": "40e54a65a7c2bfe808bcaa528e75058ab96c98c4f68d9cfa09259b7e5b97a0cd",
    "CDH_B_R09_001_REVIEW.zip": "aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638",
    "CDH_C_R09_001_REVIEW.zip": "28c77026e93720a01719a6c3bfc3b4250de2194ba15f288776d8a54f9eb18865",
    "CDH_D_R09_001_REVIEW.zip": "450eed4716dba938a06237025f20624d16c59373b09d553de4c1e06ac2549293",
    "CDH_E_R09_001_REVIEW.zip": "d0401e584393ab1f064c988f03186788d5e03c4eb0f3f53cffb19b326c39904b",
    "CDH_F_R09_001_REVIEW.zip": "75600bf4a2d8397abea93164af75e1ff99a4bab99f0082feaad859f1486ea688",
    "CDH_G_R09_001_REVIEW.zip": "488ede603f2daae285d33ab99eeb9add4120b48a8e808d2290fd3fecac7d4d62",
    "CDH_H_R09_001_REVIEW.zip": "d0c11a6344800b1cca1794c6cc4e83579a8aab8f2eaf7a2a2bfcb89d06f62e97",
}


class E11AckHandoffTests(unittest.TestCase):
    def test_checked_in_ack_authority_matches_r10_exact_values(self) -> None:
        payload = json.loads((PROJECT_ROOT / "review/E11/R10_EXACT_ACKS.json").read_text(encoding="utf-8"))
        observed = {record["filename"]: record["sha256"] for record in payload["acks"]}
        self.assertEqual(payload["schema"], "CDH-EXACT-ACK-1")
        self.assertEqual(observed, EXPECTED)
        self.assertFalse(payload["functional_pass_inferred"])

    def test_r09_semantics_preserve_p1_and_product_failure(self) -> None:
        ledger = json.loads((PROJECT_ROOT / "docs/HANDOFF/R09_RECEIPT_STATUS_LEDGER.json").read_text(encoding="utf-8"))
        records = {record["workline"]: record for record in ledger["records"]}
        self.assertEqual(ledger["record_count"], 8)
        self.assertEqual(records["B"]["functional_status"], "REWORK_P1_DUPLICATE_JSON_KEY")
        self.assertEqual(records["H"]["evidence_status"], "EVIDENCE_PASS")
        self.assertEqual(records["H"]["functional_status"], "PRODUCT_INTEGRATION_FAIL_DAILY_HISTORY_NOT_RENDERED")
        self.assertFalse(ledger["functional_pass_inferred_from_receipt"])


if __name__ == "__main__":
    unittest.main()
