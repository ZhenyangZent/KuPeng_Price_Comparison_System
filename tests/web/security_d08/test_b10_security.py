from __future__ import annotations

import unittest

from tests.web.security_d08.helpers import gate_result


class B10SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = gate_result()

    def test_real_wsgi_search_detail_and_error_codes(self) -> None:
        protocol = self.result["b10_http"]["protocol_gate"]
        for name in ("search_200", "detail_200", "etag_304_empty", "not_found_404", "post_405", "options_405"):
            self.assertTrue(protocol[name], name)

    def test_security_headers_cover_success_304_and_errors(self) -> None:
        self.assertTrue(self.result["b10_http"]["protocol_gate"]["headers_all_paths"])
        self.assertTrue(all(item["passed"] for item in self.result["b10_http"]["headers"].values()))

    def test_cors_wildcard_and_sessions_are_absent(self) -> None:
        protocol = self.result["b10_http"]["protocol_gate"]
        self.assertTrue(protocol["cors_wildcard_absent"])
        self.assertTrue(protocol["session_cookie_absent"])

    def test_untrusted_host_and_origin_are_reproduced_as_p2(self) -> None:
        value = self.result["b10_http"]["host_origin"]
        self.assertEqual((value["hostile_host_status"], value["hostile_origin_status"]), (200, 200))
        self.assertFalse(value["host_rejected"])
        self.assertFalse(value["origin_rejected"])

    def test_double_discount_fails_closed(self) -> None:
        self.assertTrue(self.result["coupon_security"]["checks"]["double_discount_falls_back"])

    def test_wrong_sku_fails_closed(self) -> None:
        self.assertTrue(self.result["coupon_security"]["checks"]["wrong_sku_falls_back"])

    def test_order_quantity_and_minimum_spend_are_preserved(self) -> None:
        self.assertTrue(self.result["coupon_security"]["checks"]["order_quantity_preserved"])

    def test_private_and_expired_coupon_semantics_are_preserved(self) -> None:
        checks = self.result["coupon_security"]["checks"]
        self.assertTrue(checks["private_profile_preserved"])
        self.assertTrue(checks["expired_not_current_but_historical"])

    def test_zero_unknown_shipping_is_not_free_checkout(self) -> None:
        self.assertTrue(self.result["coupon_security"]["checks"]["zero_unknown_shipping"])

    def test_invalid_timestamp_and_revoked_source_are_unavailable(self) -> None:
        checks = self.result["coupon_security"]["checks"]
        self.assertTrue(checks["invalid_timestamp_unavailable"])
        self.assertTrue(checks["revoked_source_unavailable"])

    def test_no_click_secret_or_external_io(self) -> None:
        value = self.result["leak_and_external_io"]
        self.assertTrue(value["response_key_gate"])
        self.assertTrue(value["external_client_static_gate"])
        self.assertEqual(value["runtime_external_request_count"], 0)


if __name__ == "__main__":
    unittest.main()
