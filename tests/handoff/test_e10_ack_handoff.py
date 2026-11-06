from __future__ import annotations

import json
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "CDH_A_R07_001_REVIEW.zip": "eb4b449972f1bb6bccd9457e8ee88a2b3c69f2a2001b17fc5adfceb23c6a7e08",
    "CDH_A_R08_001_REVIEW.zip": "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd",
    "CDH_B_R08_001_REVIEW.zip": "8e04bcec4e7dd82778858043064dd9676597edade17c496ab16a9042e68bc364",
    "CDH_C_R08_001_REVIEW.zip": "a8367fed73efce99e93941a6475f386def7dfa25de27b0e2889d4fe00b1ed0d7",
    "CDH_D_R08_001_REVIEW.zip": "fa12f642907d77c2e598e6fd6fe251032221ffbf61f056449b449d2dd855b999",
    "CDH_E_R08_001_REVIEW.zip": "da3c1c15a08604901eee5405c99df97c6abb99c456a16eab8fe29b93c3647e6c",
    "CDH_F_R08_001_REVIEW.zip": "705b8cf34a5315e661de443f27346efa3b97670e81f334f59cb6ab9cd2fff2ee",
    "CDH_G_R08_001_REVIEW.zip": "9edd847686b7566889a94ffcc3837bfdcee2294f219aa60d5dde728209e78a4c",
    "CDH_H_R08_001_REVIEW.zip": "64f0d85017e8d2843215f20458899881ddb7bad2c24559fb1ba8c6b705ed2417",
}


class E10AckHandoffTests(unittest.TestCase):
    def test_checked_in_ack_authority_matches_r09_exact_values(self) -> None:
        payload = json.loads((PROJECT_ROOT / "review/E10/R09_EXACT_ACKS.json").read_text(encoding="utf-8"))
        observed = {record["filename"]: record["sha256"] for record in payload["acks"]}
        self.assertEqual(payload["schema"], "CDH-EXACT-ACK-1")
        self.assertEqual(observed, EXPECTED)
        self.assertFalse(payload["functional_pass_inferred"])

    def test_r08_semantics_keep_a_versions_and_scope_separate(self) -> None:
        ledger = json.loads((PROJECT_ROOT / "docs/HANDOFF/R08_RECEIPT_STATUS_LEDGER.json").read_text(encoding="utf-8"))
        a_records = [record for record in ledger["records"] if record["workline"] == "A"]
        self.assertEqual(ledger["record_count"], 9)
        self.assertEqual(len(a_records), 2)
        self.assertEqual(a_records[0]["browser_evidence_scope"], "H06_EXACT_R07_ONLY")
        self.assertEqual(a_records[1]["browser_evidence_scope"], "NEW_VALIDATION_REQUIRED")
        self.assertFalse(ledger["functional_pass_inferred_from_receipt"])


if __name__ == "__main__":
    unittest.main()
