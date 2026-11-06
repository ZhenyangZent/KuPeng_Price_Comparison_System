from __future__ import annotations

import unittest

from tests.web.security_d09.helpers import baseline_result, exact_result


class B11F06ExactSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = exact_result()

    def test_http_host_origin_method_limits_and_statuses(self):
        self.assertEqual(self.result["statuses"], {"search": 200, "detail": 200, "hostile_host": 400, "hostile_origin": 403, "post": 405, "oversized": 400, "not_found": 404, "not_modified": 304, "options": 204})

    def test_cors_is_exact_and_never_wildcard(self):
        self.assertTrue(self.result["cors"]["allowed_exact"])
        self.assertTrue(self.result["cors"]["wildcard_absent"])

    def test_database_is_read_only_and_responses_have_no_secret_fields(self):
        self.assertTrue(self.result["read_only"]["unchanged"])
        self.assertTrue(self.result["secrets"]["passed"])
        self.assertEqual(self.result["secrets"]["forbidden_keys"], [])

    def test_static_boundaries_and_no_external_request(self):
        self.assertTrue(all(self.result["static"].values()))
        self.assertEqual(self.result["runtime_external_request_count"], 0)

    def test_f06_consumes_actual_b11_search_and_detail(self):
        integration = self.result["f06_integration"]
        self.assertGreaterEqual(integration["search_count"], 1)
        self.assertEqual(integration["detail_series_key"], "confirmed")
        self.assertEqual(integration["prices"], [99, 99, 49])
        self.assertEqual(integration["history_counts"], [1, 1])


class D08PortableBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = baseline_result()

    def test_exact_a09_b10_f05_gate_replays_with_same_findings(self):
        self.assertEqual(self.result["audit_execution"], "PASS")
        self.assertEqual(self.result["priority_counts"], {"P0": 0, "P1": 3, "P2": 1})
        self.assertEqual(self.result["unexpected_failures"], [])

    def test_legacy_target_is_now_portably_verified(self):
        a09 = self.result["targets"][0]
        self.assertTrue(a09["safe_paths"])
        self.assertEqual((a09["manifest_missing_count"], a09["manifest_mismatch_count"], a09["manifest_undeclared_count"]), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
