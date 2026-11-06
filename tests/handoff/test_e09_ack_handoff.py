from __future__ import annotations

import json
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "CDH_B_R07_001_REVIEW.zip": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
    "CDH_C_R07_001_REVIEW.zip": "78a9a946cf7569fef77d8baf3a2c7dfe7bdfdc0c98e0ecf14606f2c720571123",
    "CDH_D_R07_001_REVIEW.zip": "d87db68a632609abe35046bbf327d7631c0ff492a317c7b0eadc65cef2d22181",
    "CDH_E_R07_002_REVIEW.zip": "2bdd849d249782af2f16cd487e258d787e6f29576f5021cf0054062bcc94903e",
    "CDH_F_R07_001_REVIEW.zip": "c2db9aa981cbc935b52944516d5b4259829ffa5af892ac3dc7d28fc6b022ac89",
    "CDH_G_R07_001_REVIEW.zip": "e35883c4cbddaeb5b7dce4c7fff39e6a26788a1235dfe92cd6c7b79afac73b60",
    "CDH_H_R07_001_REVIEW.zip": "f4fcb0f73f9a59362f15f93025cb8ab489664a061916291d3c8d3077b79d4b9d",
}


class E09AckHandoffTests(unittest.TestCase):
    def test_checked_in_ack_authority_matches_r08_exact_values(self) -> None:
        payload = json.loads((PROJECT_ROOT / "review/E09/R08_EXACT_ACKS.json").read_text(encoding="utf-8"))
        observed = {record["filename"]: record["sha256"] for record in payload["acks"]}
        self.assertEqual(payload["schema"], "CDH-EXACT-ACK-1")
        self.assertEqual(observed, EXPECTED)
        self.assertFalse(payload["functional_pass_inferred"])

    def test_semantic_ledger_preserves_d_rework_and_a_not_received(self) -> None:
        ledger = json.loads((PROJECT_ROOT / "docs/HANDOFF/R07_RECEIPT_STATUS_LEDGER.json").read_text(encoding="utf-8"))
        records = {record["workline"]: record for record in ledger["records"]}
        self.assertEqual(ledger["record_count"], 7)
        self.assertEqual(ledger["not_received"], ["A10"])
        self.assertEqual(records["D"]["handoff_status"], "RECEIVED_REWORK_REQUIRED")
        self.assertFalse(ledger["functional_pass_inferred_from_receipt"])


if __name__ == "__main__":
    unittest.main()
