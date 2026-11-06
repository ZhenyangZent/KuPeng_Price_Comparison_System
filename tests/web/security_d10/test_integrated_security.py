from __future__ import annotations

import unittest

from tests.web.security_d10.helpers import result
from tools.web_security_d10.targets import C09_EXTRAS, HASHES


class ExactIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = result()

    def test_all_five_exact_shas_are_bound(self):
        self.assertEqual({role: value["sha256"] for role, value in self.gate["targets"].items()}, HASHES)

    def test_strict_targets_have_no_manifest_gap(self):
        for role in ("A10", "B11", "B12", "F07"):
            with self.subTest(role=role):
                value = self.gate["targets"][role]
                self.assertEqual((value["manifest_missing_count"], value["manifest_mismatch_count"], value["manifest_undeclared_count"]), (0, 0, 0))

    def test_c09_exception_is_exact_not_general(self):
        self.assertEqual(self.gate["targets"]["C09"]["manifest_undeclared"], C09_EXTRAS)


class B11AndF07Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = result()["runtime"]

    def test_host_origin_query_path_and_method_fail_closed(self):
        self.assertEqual(self.runtime["b11"]["statuses"], {"search": 200, "detail": 200, "hostile_host": 400, "hostile_origin": 403, "allowed_origin": 200, "long_query": 400, "path_traversal": 400, "post": 405})

    def test_b11_database_is_read_only(self):
        self.assertTrue(self.runtime["b11"]["read_only"])
        self.assertEqual(self.runtime["b11"]["database_before"], self.runtime["b11"]["database_after"])

    def test_all_nine_coupon_cases_keep_cta_disabled(self):
        self.assertEqual(self.runtime["f07"]["decision_count"], 9)
        self.assertTrue(self.runtime["f07"]["all_cta_disabled"])
        self.assertEqual(self.runtime["f07"]["decisions"]["zero"]["display_price_twd"], 0)
        self.assertIsNone(self.runtime["f07"]["decisions"]["unavailable"]["display_price_twd"])

    def test_url_smuggling_is_rejected_by_f07(self):
        self.assertTrue(self.runtime["f07"]["strict_extra_rejected"])
        self.assertEqual(self.runtime["f07"]["strict_extra_code"], "FORBIDDEN_SECRET_OR_URL_FIELD")


class A10StaticBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a10 = result()["runtime"]["a10"]

    def test_csp_is_same_origin_and_no_unsafe_inline(self):
        self.assertTrue(all(self.a10["csp"].values()))

    def test_fetch_url_and_xss_sinks_are_hardened(self):
        checks = self.a10["static"]
        for key in ("credentials_omit", "redirect_error", "query_encoded", "series_encoded", "same_origin_base", "no_dangerous_html", "cta_disabled"):
            with self.subTest(key=key):
                self.assertTrue(checks[key])

    def test_missing_exact_extra_field_gate_is_recorded_not_hidden(self):
        self.assertFalse(self.a10["static"]["strict_extra_fields"])


class ImportSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = result()["runtime"]

    def test_b12_path_traversal_is_rejected_and_no_db_write_occurs(self):
        self.assertTrue(self.runtime["b12"]["path_traversal_rejected"])
        self.assertEqual(self.runtime["b12"]["database_write_count"], 0)

    def test_b12_duplicate_json_key_finding_is_reproduced(self):
        self.assertTrue(self.runtime["b12"]["duplicate_json_accepted"])
        self.assertEqual(self.runtime["b12"]["duplicate_json_dry_run_status"], "DENIED_PROVENANCE")

    def test_csv_formula_prefix_is_inert_but_recorded(self):
        self.assertTrue(self.runtime["b12"]["csv_formula_text_accepted"])

    def test_c09_strict_json_rejects_duplicate_keys(self):
        self.assertTrue(self.runtime["c09"]["duplicate_json_denied"])
        self.assertEqual(self.runtime["c09"]["duplicate_json_issues"][0]["code"], "DUPLICATE_JSON_KEY")


class GateStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = result()

    def test_harness_passes_with_precise_findings(self):
        self.assertEqual(self.gate["audit_execution"], "PASS")
        self.assertEqual(self.gate["review_status"], "READY_FOR_REVIEW_WITH_P1_FINDING")
        self.assertEqual(self.gate["priority_counts"], {"P0": 0, "P1": 1, "P2": 3})

    def test_browser_claim_is_never_invented(self):
        self.assertIn(self.gate["browser_integration"], {"NOT_RUN_ENV_BLOCKED", "NOT_RUN_D10_HAS_NO_BROWSER_AUTHORITY"})

    def test_prohibited_actions_remain_zero(self):
        restrictions = self.gate["restrictions"]
        self.assertEqual(restrictions["external_network_count"], 0)
        self.assertEqual(restrictions["real_env_read_count"], 0)
        self.assertEqual(restrictions["affiliate_click_count"], 0)
        self.assertEqual(restrictions["database_write_count"], 0)


if __name__ == "__main__":
    unittest.main()
