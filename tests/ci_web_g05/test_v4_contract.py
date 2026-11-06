from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tools.ci_web_g05.v4_contract import ContractError, CouponHistoryStore, base_payload, resolve


NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)


class CouponContractTests(unittest.TestCase):
    def case(self): return copy.deepcopy(base_payload())

    def test_t01_confirmed_coupon_is_primary_and_base_is_preserved(self):
        value = resolve(self.case(), now=NOW)
        self.assertEqual((value.display_price_twd, value.base_price_twd, value.display_basis), (49, 99, "CONFIRMED_COUPON"))

    def test_t02_unclaimed_ineligible_expired_and_unknown_never_become_primary(self):
        for status in ("CLAIM_REQUIRED", "UNVERIFIED", "INELIGIBLE", "EXPIRED", "UNKNOWN", "NONE"):
            payload = self.case(); payload["coupon"]["status"] = status; payload["confirmed_coupon_price_twd"] = None
            payload["possible_coupon_price_twd"] = 49; payload["display_price_twd"] = 99; payload["display_basis"] = "BASE"
            value = resolve(payload, now=NOW)
            self.assertEqual((value.display_price_twd, value.possible_coupon_price_twd), (99, 49), status)

    def test_t03_already_included_coupon_is_not_subtracted_twice(self):
        payload = self.case(); payload["base_price_twd"] = 49; payload["coupon"]["already_included_in_base"] = True
        payload["confirmed_coupon_price_twd"] = 49; payload["display_price_twd"] = 49
        value = resolve(payload, now=NOW)
        self.assertEqual(value.confirmed_coupon_price_twd, 49); self.assertFalse(value.coupon_applied)

    def test_t04_order_coupon_and_quantity_produce_unit_75_total_150(self):
        payload = self.case(); payload["base_price_twd"] = 100; payload["quantity"] = 2; payload["coupon"]["discount_scope"] = "ORDER"
        payload["confirmed_coupon_price_twd"] = 75; payload["display_price_twd"] = 75; payload["shipping_status"] = "FREE"; payload["required_total_twd"] = 150
        value = resolve(payload, now=NOW)
        self.assertEqual((value.display_price_twd, value.required_total_twd), (75, 150))

    def test_t05_different_sku_or_seller_coupon_is_refused(self):
        for field in ("sku_id", "seller_id"):
            payload = self.case(); payload["coupon"]["series_identity"][field] = "OTHER"
            payload["confirmed_coupon_price_twd"] = None; payload["display_price_twd"] = 99; payload["display_basis"] = "BASE"
            self.assertFalse(resolve(payload, now=NOW).coupon_applied)

    def test_t06_expired_or_other_period_coupon_is_not_current(self):
        payload = self.case(); payload["coupon"]["valid_until"] = "2026-11-04T00:00:00Z"
        payload["confirmed_coupon_price_twd"] = None; payload["display_price_twd"] = 99; payload["display_basis"] = "BASE"
        self.assertEqual(resolve(payload, now=NOW).reason, "BASE_PRICE")

    def test_t07_unknown_shipping_keeps_product_price_but_total_null(self):
        value = resolve(self.case(), now=NOW)
        self.assertEqual(value.display_price_twd, 49); self.assertIsNone(value.required_total_twd)

    def test_t08_private_or_first_purchase_price_requires_confirmed_eligibility(self):
        payload = self.case(); payload["coupon"]["status"] = "UNVERIFIED"; payload["coupon"]["eligibility_profile"] = "FIRST_PURCHASE_SELF_REPORTED"
        payload["confirmed_coupon_price_twd"] = None; payload["display_price_twd"] = 99; payload["display_basis"] = "BASE"
        self.assertEqual(resolve(payload, now=NOW).display_price_twd, 99)

    def test_t09_synthetic_fixture_is_test_only(self):
        with self.assertRaisesRegex(ContractError, "TEST_ONLY"): resolve(self.case(), now=NOW, mode="PRODUCTION")

    def test_t10_zero_is_valid_but_null_is_unknown(self):
        zero = self.case(); zero["base_price_twd"] = 50; zero["confirmed_coupon_price_twd"] = 0; zero["display_price_twd"] = 0
        self.assertEqual(resolve(zero, now=NOW).display_price_twd, 0)
        unknown = self.case(); unknown["base_price_twd"] = None; unknown["coupon"]["status"] = "NONE"; unknown["coupon"]["discount_twd"] = None
        unknown["confirmed_coupon_price_twd"] = None; unknown["display_price_twd"] = None; unknown["display_basis"] = "UNKNOWN"
        self.assertIsNone(resolve(unknown, now=NOW).display_price_twd)

    def test_overdiscount_does_not_fabricate_zero(self):
        payload = self.case(); payload["base_price_twd"] = 40
        with self.assertRaisesRegex(ContractError, "zero"): resolve(payload, now=NOW)

    def test_declared_price_must_equal_evidence_derived_price(self):
        payload = self.case(); payload["confirmed_coupon_price_twd"] = 48; payload["display_price_twd"] = 48
        with self.assertRaisesRegex(ContractError, "declared confirmed"): resolve(payload, now=NOW)

    def test_dual_history_is_stored_as_separate_series_with_evidence(self):
        parent = Path("reports/G05/test_tmp").resolve(); parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            store = CouponHistoryStore(Path(directory) / "history.sqlite3"); payload = self.case(); value = resolve(payload, now=NOW); store.record(payload, value)
            before, after = store.read("BEFORE_COUPON"), store.read("CONFIRMED_AFTER_COUPON")
            self.assertEqual((before[0]["price_twd"], after[0]["price_twd"]), (99, 49))
            self.assertIsNone(before[0]["coupon_json"]); self.assertIn("SYN-COUPON-1", after[0]["coupon_json"])

    def test_history_does_not_treat_past_coupon_as_current_authority(self):
        payload = self.case(); value = resolve(payload, now=NOW)
        self.assertEqual(value.display_price_twd, 49)
        with self.assertRaisesRegex(ContractError, "declared confirmed"):
            resolve({**payload, "confirmed_coupon_price_twd": 49, "display_price_twd": 49, "coupon": {**payload["coupon"], "status": "EXPIRED"}}, now=NOW)


if __name__ == "__main__": unittest.main()
