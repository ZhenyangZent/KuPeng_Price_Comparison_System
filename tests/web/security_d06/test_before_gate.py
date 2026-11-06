from __future__ import annotations

import unittest

from tools.web_security_d06.gate import run_gate
from tests.web.security_d06.helpers import A07, A07_SHA, B08, B08_SHA


class BeforeGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = run_gate(A07, B08, frontend_sha256=A07_SHA, backend_sha256=B08_SHA, mode="before")
        cls.checks = {item["check_id"]: item for item in cls.report["checks"]}
        cls.findings = {item["finding_id"]: item for item in cls.report["findings"]}

    def test_central_nine_call_counterexample_is_reproduced_six_three(self) -> None:
        results = self.report["evidence"]["parser_results"]
        self.assertEqual(len(results), 9)
        self.assertEqual(sum(item["success"] for item in results), 6)
        self.assertEqual(sum(not item["success"] for item in results), 3)

    def test_valid_search_detail_affiliate_all_pass(self) -> None:
        self.assertTrue(self.checks["VALID_V2_SEARCH_DETAIL_AFFILIATE"]["passed"])

    def test_unavailable_null_failure_is_precisely_classified(self) -> None:
        self.assertFalse(self.checks["UNAVAILABLE_NULL_RENDERABLE"]["passed"])
        self.assertEqual(self.findings["D06-P1-001"]["owner"], "A")
        self.assertIn("runtimeSchema.ts:25", self.findings["D06-P1-001"]["location"])

    def test_v2_raw_min_and_v3_daily_median_mismatch_is_precise(self) -> None:
        value = self.report["evidence"]["raw_minimum"]
        self.assertEqual(value["history_prices"], [10, 20, 30])
        self.assertEqual(value["raw_min"], 10)
        self.assertEqual(value["v2_observation_period_min_twd"], 20)
        self.assertEqual(value["v3_daily_median_period_low_twd"], 20)
        self.assertEqual(self.findings["D06-P1-002"]["owner"], "B")

    def test_null_zero_and_unavailable_are_not_conflated(self) -> None:
        self.assertTrue(self.checks["NULL_ZERO_UNAVAILABLE_SEPARATION"]["passed"])
        self.assertIsNone(self.report["evidence"]["unavailable"]["last_observed_price_twd"])
        self.assertEqual(self.report["evidence"]["zero"]["last_observed_price_twd"], 0)

    def test_stale_and_expired_sources_cannot_claim_new_low(self) -> None:
        self.assertTrue(self.checks["STALE_AND_EXPIRED_SOURCE_FAIL_CLOSED"]["passed"])
        self.assertFalse(self.report["evidence"]["stale"]["quality"]["new_low_valid"])
        self.assertIsNone(self.report["evidence"]["expired"]["item"]["last_observed_price_twd"])

    def test_wrong_sku_and_seller_stay_partitioned(self) -> None:
        self.assertTrue(self.checks["SAME_PRODUCT_WRONG_SKU_SELLER_PARTITION"]["passed"])
        self.assertEqual(self.report["evidence"]["wrong_sku_identities"], [["same-product", "sku-a", "seller-a"], ["same-product", "sku-b", "seller-b"]])

    def test_v1_schema_downgrade_is_rejected(self) -> None:
        self.assertTrue(self.checks["API_SCHEMA_DOWNGRADE_REFUSED"]["passed"])
        self.assertEqual(self.report["evidence"]["downgrade"]["code"], "VERSION_MISMATCH")

    def test_affiliate_host_url_identity_expiry_and_authority_fail_closed(self) -> None:
        self.assertTrue(self.checks["AFFILIATE_HOST_URL_IDENTITY_AND_AUTHORITY"]["passed"])
        values = {item["name"]: item["value"] for item in self.report["evidence"]["affiliate"]}
        self.assertIsNone(values["current_no_authority"])
        self.assertIsNotNone(values["synthetic_exact"])
        for name in ("wrong_host", "http", "userinfo", "javascript", "wrong_sku", "expired"):
            self.assertIsNone(values[name])

    def test_loopback_v2_no_raw_html_and_empty_production_affiliate_policy(self) -> None:
        self.assertTrue(self.checks["FRONTEND_STATIC_SECURITY_BOUNDARIES"]["passed"])

    def test_env_boundary_is_archive_only_and_placeholder_safe(self) -> None:
        self.assertTrue(self.checks["FRONTEND_ENV_PLACEHOLDER_ONLY"]["passed"])

    def test_csp_headers_and_manifest_are_p2_not_hidden(self) -> None:
        self.assertEqual(self.report["priority_counts"], {"P0": 0, "P1": 2, "P2": 3})
        self.assertEqual(set(self.findings), {"D06-P2-001", "D06-P1-001", "D06-P1-002", "D06-P2-002", "D06-P2-003"})

    def test_before_mode_never_claims_after_acceptance(self) -> None:
        self.assertEqual(self.report["integration_acceptance"], "PRECHECK_REPRODUCED_NOT_AFTER_ACCEPTANCE")
        self.assertEqual(self.report["blocking_finding_count"], 2)


if __name__ == "__main__":
    unittest.main()
