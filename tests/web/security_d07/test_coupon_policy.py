from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime, timezone

from tools.web_security_d07.coupon_policy import CouponContractError, evaluate_coupon_v4
from tools.web_security_d07.gate import run_coupon_cases
from tools.web_security_d07.synthetic_cases import IDENTITY, confirmed_payload, history_point, unconfirmed_payload


NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)


def evaluate(payload, **kwargs):
    return evaluate_coupon_v4(payload, now=NOW, expected_identity=IDENTITY, **kwargs)


class CouponPolicyTests(unittest.TestCase):
    def test_contract_case_matrix_passes(self) -> None:
        results = run_coupon_cases()
        self.assertGreaterEqual(len(results), 18)
        self.assertEqual([item["name"] for item in results if not item["passed"]], [])

    def test_confirmed_coupon_is_primary_and_base_is_preserved(self) -> None:
        value = evaluate(confirmed_payload(), eligibility_profile="SYN-ELIGIBLE-PROFILE")
        self.assertEqual(value["display_price_twd"], 49)
        self.assertEqual(value["base_price_twd"], 99)
        self.assertEqual(value["display_basis"], "CONFIRMED_COUPON")

    def test_unverified_possible_price_never_becomes_primary(self) -> None:
        value = evaluate(unconfirmed_payload("UNVERIFIED"))
        self.assertEqual(value["display_price_twd"], 99)
        self.assertEqual(value["possible_coupon_price_twd"], 49)
        self.assertIsNone(value["confirmed_coupon_price_twd"])

    def test_expired_status_never_becomes_primary(self) -> None:
        value = evaluate(unconfirmed_payload("EXPIRED"))
        self.assertFalse(value["coupon_applied"])
        self.assertEqual(value["display_price_twd"], 99)

    def test_out_of_time_confirmation_falls_back(self) -> None:
        payload = confirmed_payload()
        payload["coupon"]["valid_until"] = "2026-11-05T03:59:59Z"
        payload["display_price_twd"] = 99
        payload["display_basis"] = "BASE_PRICE"
        value = evaluate(payload, eligibility_profile="SYN-ELIGIBLE-PROFILE")
        self.assertFalse(value["coupon_applied"])
        self.assertIn("COUPON_OUTSIDE_VALIDITY", value["reasons"])

    def test_already_included_does_not_double_discount(self) -> None:
        payload = confirmed_payload()
        payload["base_price_twd"] = 49
        payload["coupon"]["already_included_in_base"] = True
        payload["confirmed_coupon_price_twd"] = 49
        payload["display_price_twd"] = 49
        value = evaluate(payload, eligibility_profile="SYN-ELIGIBLE-PROFILE")
        self.assertEqual(value["display_price_twd"], 49)

    def test_declared_discount_mismatch_is_rejected(self) -> None:
        payload = confirmed_payload()
        payload["confirmed_coupon_price_twd"] = 48
        payload["display_price_twd"] = 48
        with self.assertRaisesRegex(CouponContractError, "does not match"):
            evaluate(payload, eligibility_profile="SYN-ELIGIBLE-PROFILE")

    def test_discount_above_base_is_not_clamped_to_zero(self) -> None:
        payload = confirmed_payload()
        payload["coupon"]["discount_twd"] = 100
        payload["confirmed_coupon_price_twd"] = 0
        payload["display_price_twd"] = 0
        with self.assertRaises(CouponContractError) as caught:
            evaluate(payload, eligibility_profile="SYN-ELIGIBLE-PROFILE")
        self.assertEqual(caught.exception.code, "DISCOUNT_EXCEEDS_PRICE")

    def test_genuine_zero_remains_distinct_from_null(self) -> None:
        payload = confirmed_payload()
        payload["base_price_twd"] = 50
        payload["confirmed_coupon_price_twd"] = 0
        payload["display_price_twd"] = 0
        payload["shipping_status"] = "FREE"
        payload["required_total_twd"] = 0
        value = evaluate(payload, eligibility_profile="SYN-ELIGIBLE-PROFILE")
        self.assertEqual(value["display_price_twd"], 0)

    def test_boolean_is_not_accepted_as_zero_or_one_price(self) -> None:
        payload = confirmed_payload()
        payload["base_price_twd"] = False
        with self.assertRaises(CouponContractError) as caught:
            evaluate(payload)
        self.assertEqual(caught.exception.code, "INVALID_PRICE")

    def test_unknown_shipping_keeps_required_total_null(self) -> None:
        value = evaluate(confirmed_payload(), eligibility_profile="SYN-ELIGIBLE-PROFILE")
        self.assertIsNone(value["required_total_twd"])
        self.assertEqual(value["display_price_twd"], 49)

    def test_order_coupon_keeps_unit_and_required_total_separate(self) -> None:
        payload = confirmed_payload()
        payload["base_price_twd"] = 100
        payload["confirmed_coupon_price_twd"] = 75
        payload["display_price_twd"] = 75
        payload["shipping_status"] = "FREE"
        payload["required_total_twd"] = 150
        value = evaluate(payload, eligibility_profile="SYN-ELIGIBLE-PROFILE", minimum_purchase_quantity=2, discount_scope="ORDER")
        self.assertEqual(value["display_price_twd"], 75)
        self.assertEqual(value["required_total_twd"], 150)

    def test_different_seller_is_rejected(self) -> None:
        payload = confirmed_payload()
        expected = deepcopy(IDENTITY)
        expected["seller_id"] = "SYN-OTHER-SELLER"
        with self.assertRaises(CouponContractError) as caught:
            evaluate_coupon_v4(payload, now=NOW, expected_identity=expected)
        self.assertEqual(caught.exception.code, "REQUEST_IDENTITY_MISMATCH")

    def test_history_branches_do_not_merge(self) -> None:
        payload = confirmed_payload()
        payload["history"]["before_coupon"] = [history_point(price=99)]
        payload["history"]["confirmed_after_coupon"] = [history_point(price=59, after=True)]
        value = evaluate(payload, eligibility_profile="SYN-ELIGIBLE-PROFILE")
        self.assertEqual([item["price_twd"] for item in value["history"]["before_coupon"]], [99])
        self.assertEqual([item["price_twd"] for item in value["history"]["confirmed_after_coupon"]], [59])

    def test_history_wrong_sku_is_rejected(self) -> None:
        payload = confirmed_payload()
        point = history_point(price=99)
        point["series_identity"]["sku_id"] = "SYN-WRONG"
        payload["history"]["before_coupon"] = [point]
        with self.assertRaises(CouponContractError) as caught:
            evaluate(payload)
        self.assertEqual(caught.exception.code, "HISTORY_IDENTITY_MISMATCH")

    def test_csv_formula_and_markup_are_rejected(self) -> None:
        for attack in ("=WEBSERVICE(unsafe)", "+cmd", "<script>alert(1)</script>"):
            payload = confirmed_payload()
            payload["coupon"]["scope_evidence"] = attack
            with self.subTest(attack=attack), self.assertRaises(CouponContractError) as caught:
                evaluate(payload)
            self.assertEqual(caught.exception.code, "TEXT_INJECTION")

    def test_json_unknown_redirect_field_is_rejected(self) -> None:
        payload = confirmed_payload()
        payload["redirect_url"] = "https://example.invalid/?token=secret"
        with self.assertRaises(CouponContractError) as caught:
            evaluate(payload)
        self.assertEqual(caught.exception.code, "INVALID_FIELDS")

    def test_cta_is_always_disabled_even_for_confirmed_coupon(self) -> None:
        value = evaluate(confirmed_payload(), eligibility_profile="SYN-ELIGIBLE-PROFILE")
        self.assertFalse(value["cta_enabled"])
        self.assertIsNone(value["cta_url"])


if __name__ == "__main__":
    unittest.main()
