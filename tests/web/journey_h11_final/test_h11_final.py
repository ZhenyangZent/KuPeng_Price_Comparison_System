from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FINAL = ROOT / "review" / "H11_FINAL"


class H11FinalEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.actual = json.loads((FINAL / "evidence" / "ACTUAL_H11_BROWSER_HTTP.json").read_text(encoding="utf-8"))
        cls.receipt = json.loads((FINAL / "evidence" / "BROWSER_PROCESS_RECEIPT.json").read_text(encoding="utf-8"))
        cls.sqlite = json.loads((FINAL / "evidence" / "SQLITE_READONLY_EVIDENCE.json").read_text(encoding="utf-8"))
        cls.daily = json.loads((FINAL / "evidence" / "DAILY_DOM_RECONCILIATION.json").read_text(encoding="utf-8"))
        cls.inputs = json.loads((FINAL / "INPUT_READBACK.json").read_text(encoding="utf-8"))
        cls.staged = json.loads((FINAL / "STAGED_PROJECT.json").read_text(encoding="utf-8"))

    def test_exact_inputs_and_integrity(self) -> None:
        self.assertEqual(self.inputs["status"], "PASS")
        self.assertEqual(self.inputs["inputs"]["A15_REV2"]["sha256"], "be0becbaa384e1a633c5893b266dbbb03c449ca405ef1f0c07bb8dd53456634b")
        self.assertEqual(self.inputs["inputs"]["B16_REV3"]["sha256"], "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7")
        self.assertEqual(self.inputs["inputs"]["D13_REV3"]["sha256"], "8aef750caa17c894159d13705f9962e4f6e856ef3ced1658ddb951523b241e54")

    def test_official_launcher_without_h_loader(self) -> None:
        self.assertTrue(self.staged["official_binding_gate"])
        self.assertEqual(self.staged["h_test_loader_file_count"], 0)
        self.assertFalse(self.actual["h_test_loader_used"])

    def test_health_reports_b16_rev3(self) -> None:
        self.assertEqual(self.actual["health"]["b16_revision"], "REV3")
        self.assertEqual(self.actual["health"]["b16_r12_sha256"], "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7")
        self.assertEqual(self.actual["health"]["b16_api_schema"], "CDH-B16-PRIVATE-BATCH-API-1")

    def test_real_browser_processes_exit_zero(self) -> None:
        self.assertEqual(self.receipt["exit_code"], 0)
        self.assertEqual(self.actual["browser_test_exit_code"], 0)
        self.assertEqual(self.actual["chrome_process_exit_code"], 0)

    def test_product_gates_15_of_15(self) -> None:
        self.assertEqual(len(self.actual["gates"]), 15)
        self.assertTrue(all(self.actual["gates"].values()))

    def test_preview_and_confirm_http_contract(self) -> None:
        self.assertEqual([item["status"] for item in self.actual["batch_http"]], [422, 200, 201, 200, 201, 200, 200])
        self.assertTrue(self.actual["csv_preview"]["database_write_zero"])
        self.assertTrue(self.actual["json_preview"]["database_write_zero"])

    def test_duplicate_confirm_is_idempotent(self) -> None:
        self.assertEqual(self.actual["rows_after_json"], 4)
        self.assertEqual(self.actual["rows_after_replay"], 4)

    def test_restart_then_read_is_non_mutating(self) -> None:
        self.assertNotEqual(self.actual["first_instance_id"], self.actual["second_instance_id"])
        self.assertEqual(self.actual["browser_post_after_restart_count"], 0)
        self.assertEqual(self.actual["database_sha256_before_read"], self.actual["database_sha256_after_read"])

    def test_raw_tracks_and_unverified_classification(self) -> None:
        for detail in (self.actual["csv_detail"], self.actual["json_detail"]):
            self.assertEqual([item["price"] for item in detail["before_raw"]], [1000, 950])
            self.assertEqual([item["price"] for item in detail["reported_raw"]], [900])
            self.assertEqual(detail["confirmed_raw"], [])
            self.assertTrue(detail["not_verified"])
            self.assertTrue(detail["cta_disabled"])

    def test_daily_dom_strict_twd_reconciliation(self) -> None:
        self.assertEqual(len(self.daily["gates"]), 6)
        self.assertTrue(all(self.daily["gates"].values()))
        self.assertEqual(self.daily["parser"], "STRICT_ANCHORED_TWD_FULLMATCH")

    def test_sqlite_contains_only_four_synthetic_private_rows(self) -> None:
        self.assertEqual(self.sqlite["row_counts"]["observations"], 4)
        self.assertEqual({row["product_id"] for row in self.sqlite["observations"]}, {"PROD-B16-CSV", "PROD-B16-EXAMPLE"})
        self.assertTrue(all(row["confirmed_after_coupon_price_twd"] is None and row["platform_verified"] == 0 for row in self.sqlite["observations"]))
        self.assertTrue(all(row["source_class"] == "USER_ENTERED" and row["visibility"] == "PRIVATE_LOCAL" for row in self.sqlite["observations"]))

    def test_sqlite_read_only_copy_matches(self) -> None:
        self.assertTrue(self.sqlite["read_only_hash_unchanged"])
        self.assertTrue(self.sqlite["evidence_database_copy_matches"])

    def test_no_external_network_or_console_errors(self) -> None:
        self.assertEqual(self.actual["external_request_count"], 0)
        self.assertEqual(self.actual["console_events"], [])

    def test_capture_set_complete(self) -> None:
        self.assertEqual(len(self.actual["captures"]), 12)
        for item in self.actual["captures"]:
            self.assertTrue((ROOT / item["screenshot"]).is_file())
            self.assertTrue((ROOT / item["dom"]).is_file())


if __name__ == "__main__":
    unittest.main()
