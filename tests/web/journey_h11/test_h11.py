from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
H11 = ROOT / "review" / "H11"


class H11EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.failed = json.loads((H11 / "evidence" / "ACTUAL_H11_BROWSER_HTTP.json").read_text(encoding="utf-8"))
        cls.actual = json.loads((H11 / "attempt2" / "evidence" / "ACTUAL_H11_BROWSER_HTTP.json").read_text(encoding="utf-8"))
        cls.receipt = json.loads((H11 / "attempt2" / "evidence" / "BROWSER_PROCESS_RECEIPT.json").read_text(encoding="utf-8"))
        cls.sqlite = json.loads((H11 / "attempt2" / "evidence" / "SQLITE_READONLY_EVIDENCE.json").read_text(encoding="utf-8"))
        cls.daily = json.loads((H11 / "attempt2" / "evidence" / "DAILY_DOM_RECONCILIATION.json").read_text(encoding="utf-8"))
        cls.inputs = json.loads((H11 / "INPUT_READBACK.json").read_text(encoding="utf-8"))

    def test_attempt1_failure_is_preserved(self) -> None:
        self.assertEqual(self.failed["status"], "FAIL")
        self.assertIn("Timed out waiting for PROD-B16-EXAMPLE detail", self.failed["error"])

    def test_attempt2_browser_and_chrome_exit_zero(self) -> None:
        self.assertEqual(self.receipt["exit_code"], 0)
        self.assertEqual(self.actual["browser_test_exit_code"], 0)
        self.assertEqual(self.actual["chrome_process_exit_code"], 0)
        self.assertEqual(self.actual["status"], "PASS")

    def test_all_15_product_gates_pass(self) -> None:
        self.assertEqual(len(self.actual["gates"]), 15)
        self.assertTrue(all(self.actual["gates"].values()))

    def test_http_outcomes(self) -> None:
        statuses = [(item["path"].rsplit("/", 1)[-1], item["status"]) for item in self.actual["batch_http"]]
        self.assertIn(("batch-preview", 422), statuses)
        self.assertEqual(statuses.count(("batch-confirm", 201)), 2)
        self.assertEqual(statuses.count(("batch-confirm", 200)), 1)

    def test_preview_and_duplicate_semantics(self) -> None:
        self.assertEqual(self.actual["rows_after_csv"], 2)
        self.assertEqual(self.actual["rows_after_json"], 4)
        self.assertEqual(self.actual["rows_after_replay"], 4)
        self.assertIn("HTTP 200", self.actual["replay_commit"])

    def test_read_after_restart_is_immutable(self) -> None:
        self.assertEqual(self.actual["browser_post_after_restart_count"], 0)
        self.assertEqual(self.actual["rows_before_read"], self.actual["rows_after_read"])
        self.assertEqual(self.actual["database_sha256_before_read"], self.actual["database_sha256_after_read"])

    def test_raw_tracks_are_exact_and_unverified(self) -> None:
        for detail in (self.actual["csv_detail"], self.actual["json_detail"]):
            self.assertEqual([row["price"] for row in detail["before_raw"]], [1000, 950])
            self.assertEqual([row["price"] for row in detail["reported_raw"]], [900])
            self.assertEqual(detail["confirmed_raw"], [])
            self.assertTrue(detail["confirmed_empty"] and detail["not_verified"] and detail["cta_disabled"])

    def test_daily_dom_dates_samples_and_prices_are_exact(self) -> None:
        self.assertEqual(self.daily["status"], "PASS")
        self.assertTrue(all(self.daily["gates"].values()))

    def test_sqlite_contains_only_four_synthetic_unverified_rows(self) -> None:
        self.assertEqual(self.sqlite["row_counts"]["observations"], 4)
        self.assertTrue(self.sqlite["read_only_hash_unchanged"] and self.sqlite["evidence_database_copy_matches"])
        self.assertTrue(all(row["confirmed_after_coupon_price_twd"] is None and row["platform_verified"] == 0 for row in self.sqlite["observations"]))

    def test_exact_inputs_and_no_external_requests(self) -> None:
        self.assertEqual(self.inputs["inputs"]["A15"]["sha256"], "5cc44dedd910ff9b2055cfc2772ad0c3d6db627ffc818794f81fd3d9b5552d4b")
        self.assertEqual(self.inputs["inputs"]["B16_REV2"]["sha256"], "6904b7ab2ffd6daac0325be75a119cd906c67c7c479a4607760ce24739444ed6")
        self.assertEqual(self.inputs["api_compatibility_claim"]["route_or_request_schema_change_count"], 0)
        self.assertEqual(self.actual["external_request_count"], 0)


if __name__ == "__main__":
    unittest.main()
