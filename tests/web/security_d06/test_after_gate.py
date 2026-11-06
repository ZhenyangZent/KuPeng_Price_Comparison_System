from __future__ import annotations

import unittest

from tools.web_security_d06.gate import run_gate
from tests.web.security_d06.helpers import A08, A08_SHA, B09, B09_SHA


class AfterGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = run_gate(A08, B09, frontend_sha256=A08_SHA, backend_sha256=B09_SHA, mode="after")
        cls.checks = {item["check_id"]: item for item in cls.report["checks"]}
        cls.findings = {item["finding_id"]: item for item in cls.report["findings"]}

    def test_after_acceptance_has_no_p0_or_p1(self) -> None:
        self.assertEqual(self.report["integration_acceptance"], "PASS")
        self.assertEqual(self.report["blocking_finding_count"], 0)
        self.assertEqual(self.report["priority_counts"], {"P0": 0, "P1": 0, "P2": 2})

    def test_all_nine_crossline_parser_calls_pass(self) -> None:
        results = self.report["evidence"]["parser_results"]
        self.assertEqual(len(results), 9)
        self.assertTrue(all(item["success"] for item in results), results)

    def test_unavailable_null_is_renderable(self) -> None:
        self.assertTrue(self.checks["UNAVAILABLE_NULL_RENDERABLE"]["passed"])
        item = self.report["evidence"]["unavailable"]
        self.assertIsNone(item["last_observed_price_twd"])
        self.assertEqual(item["price_basis"], "UNAVAILABLE")

    def test_v2_raw_min_and_v3_daily_median_are_separate(self) -> None:
        self.assertTrue(self.checks["V2_RAW_MINIMUM_SEPARATE_FROM_V3_DAILY_MEDIAN"]["passed"])
        value = self.report["evidence"]["raw_minimum"]
        self.assertEqual(value["v2_observation_period_min_twd"], 10)
        self.assertEqual(value["v3_daily_median_period_low_twd"], 20)

    def test_null_zero_stale_expired_and_wrong_sku_gates_pass(self) -> None:
        for check in ("NULL_ZERO_UNAVAILABLE_SEPARATION", "STALE_AND_EXPIRED_SOURCE_FAIL_CLOSED", "SAME_PRODUCT_WRONG_SKU_SELLER_PARTITION"):
            with self.subTest(check=check):
                self.assertTrue(self.checks[check]["passed"])

    def test_schema_downgrade_is_rejected(self) -> None:
        self.assertTrue(self.checks["API_SCHEMA_DOWNGRADE_REFUSED"]["passed"])
        self.assertEqual(self.report["evidence"]["downgrade"]["code"], "VERSION_MISMATCH")

    def test_current_affiliate_authority_and_host_attacks_fail_closed(self) -> None:
        self.assertTrue(self.checks["AFFILIATE_HOST_URL_IDENTITY_AND_AUTHORITY"]["passed"])
        values = {item["name"]: item["value"] for item in self.report["evidence"]["affiliate"]}
        self.assertIsNone(values["current_no_authority"])
        for name in ("wrong_host", "http", "userinfo", "javascript", "wrong_sku", "expired"):
            self.assertIsNone(values[name])

    def test_loopback_no_raw_html_and_env_boundary_pass(self) -> None:
        self.assertTrue(self.checks["FRONTEND_STATIC_SECURITY_BOUNDARIES"]["passed"])
        self.assertTrue(self.checks["FRONTEND_ENV_PLACEHOLDER_ONLY"]["passed"])

    def test_remaining_findings_are_only_defense_in_depth_p2(self) -> None:
        self.assertEqual(set(self.findings), {"D06-P2-002", "D06-P2-003"})
        self.assertFalse(self.checks["FRONTEND_CSP"]["passed"])
        self.assertFalse(self.checks["BACKEND_HEADERS_AND_NO_CORS"]["passed"])


if __name__ == "__main__":
    unittest.main()
