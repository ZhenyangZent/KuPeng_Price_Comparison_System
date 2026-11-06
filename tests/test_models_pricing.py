from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta, timezone
from fractions import Fraction

from cdh_core.models import (
    Evidence,
    EvidenceBasis,
    MoneyValue,
    OfferIdentity,
    PurchaseScenario,
    ValueState,
)
from cdh_core.pricing import (
    CostComponentEvidence,
    CouponTerms,
    FeeComponent,
    PricingInput,
    calculate_total,
    parse_minor,
)


NOW = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)


def offer(sku: str = "sku-a") -> OfferIdentity:
    return OfferIdentity("TEST", "p1", sku, "seller", "NEW", "1x", "TEST_DELIVERY")


def scenario(
    *, sku: str = "sku-a", context: str = "ctx-wow", quantity: int = 1, coupon: str | None = None
) -> PurchaseScenario:
    return PurchaseScenario(
        offer(sku),
        context,
        quantity,
        "WOW_USER_DECLARED",
        coupon_plan_id=coupon,
        eligibility_profile_version="test-profile-v1",
        purchase_channel="WEB",
        payment_method="TEST_CARD",
    )


def base_pricing(**changes: object) -> PricingInput:
    values: dict[str, object] = {
        "subtotal": MoneyValue.known(1000),
        "shipping": MoneyValue.known(0),
        "fees": (),
        "tax": MoneyValue.known(0),
        "minimum_quantity": 1,
        "independently_purchasable": True,
        "evaluated_at": NOW,
        "evidence_expires_at": NOW + timedelta(minutes=5),
        "quote_evidence_id": "test-quote",
    }
    values.update(changes)
    return PricingInput(**values)


def coupon_proof(*, expiry_policy: str = "PERPETUAL", threshold_policy: str = "NONE") -> dict[str, object]:
    return {
        "expiry_policy": expiry_policy,
        "offer_scope_policy": "ALL",
        "seller_scope_policy": "ALL",
        "threshold_policy": threshold_policy,
        "terms_evidence_id": "synthetic-coupon-terms",
        "terms_context_id": "ctx-wow",
        "terms_membership_context": "WOW_USER_DECLARED",
        "terms_eligibility_profile_version": "test-profile-v1",
        "terms_evidence_basis": EvidenceBasis.OBSERVED,
        "terms_source_record_sha256": "a" * 64,
    }


class MoneyModelTests(unittest.TestCase):
    def test_known_zero_is_explicit(self) -> None:
        value = MoneyValue.known(0)
        self.assertEqual(value.state, ValueState.KNOWN_ZERO)
        self.assertEqual(value.resolved_minor(), 0)

    def test_unknown_is_not_zero(self) -> None:
        value = MoneyValue.unavailable(ValueState.UNKNOWN)
        self.assertFalse(value.is_usable)
        with self.assertRaises(ValueError):
            value.resolved_minor()

    def test_non_numeric_states_are_distinct(self) -> None:
        states = {ValueState.UNKNOWN, ValueState.NOT_APPLICABLE, ValueState.CONFLICT, ValueState.PARSE_ERROR}
        self.assertEqual(len({MoneyValue.unavailable(state).state for state in states}), 4)

    def test_bool_float_nan_infinity_and_null_rejected(self) -> None:
        for value in (True, False, 1.0, math.nan, math.inf, None, ""):
            with self.subTest(value=value):
                self.assertNotIn(parse_minor(value).state, (ValueState.KNOWN, ValueState.KNOWN_ZERO))

    def test_negative_rejected(self) -> None:
        self.assertEqual(parse_minor(-1).state, ValueState.PARSE_ERROR)

    def test_currency_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_minor(100, currency="USD")

    def test_boolean_quantity_rejected(self) -> None:
        with self.assertRaises(TypeError):
            scenario(quantity=True)  # type: ignore[arg-type]

    def test_fractional_unit_cost_is_exact(self) -> None:
        result = calculate_total(scenario(quantity=3), base_pricing(subtotal=MoneyValue.known(1000)))
        self.assertEqual(result.unit_minor, Fraction(1000, 3))


class EvidenceScopeTests(unittest.TestCase):
    def make_evidence(self, target: PurchaseScenario) -> Evidence:
        return Evidence(
            "ev1",
            "shipping",
            0,
            EvidenceBasis.OBSERVED,
            target.offer.key,
            target.context_id,
            target.scope_key,
            NOW,
            NOW + timedelta(minutes=5),
            "rule-1",
        )

    def test_same_scenario_evidence_is_compatible(self) -> None:
        target = scenario()
        self.assertEqual(self.make_evidence(target).compatibility(target, NOW), (True, "EVIDENCE_COMPATIBLE"))

    def test_different_sku_is_rejected(self) -> None:
        original = scenario()
        ok, reason = self.make_evidence(original).compatibility(scenario(sku="sku-b"), NOW)
        self.assertFalse(ok)
        self.assertEqual(reason, "EVIDENCE_OFFER_MISMATCH")

    def test_different_context_is_rejected(self) -> None:
        original = scenario()
        ok, reason = self.make_evidence(original).compatibility(scenario(context="ctx-non-wow"), NOW)
        self.assertFalse(ok)
        self.assertEqual(reason, "EVIDENCE_CONTEXT_MISMATCH")

    def test_expired_evidence_is_rejected(self) -> None:
        target = scenario()
        ok, reason = self.make_evidence(target).compatibility(target, NOW + timedelta(minutes=6))
        self.assertFalse(ok)
        self.assertEqual(reason, "EVIDENCE_EXPIRED")


class PricingTests(unittest.TestCase):
    def test_complete_required_cost_formula(self) -> None:
        pricing = base_pricing(
            subtotal=MoneyValue.known(10_000),
            shipping=MoneyValue.known(600),
            fees=(FeeComponent("service", MoneyValue.known(200)),),
            tax=MoneyValue.known(100),
            coupon=CouponTerms(
                "c1", MoneyValue.known(1000), 5000, True, True,
                claimed=True, remaining_uses=1, threshold_evidence_id="threshold-1",
                rule_version="test-coupon-v1",
                **coupon_proof(threshold_policy="FIXED"),
            ),
        )
        result = calculate_total(scenario(coupon="c1"), pricing)
        self.assertTrue(result.complete)
        self.assertEqual(result.total_minor, 9900)

    def test_unknown_shipping_blocks(self) -> None:
        result = calculate_total(scenario(), base_pricing(shipping=MoneyValue.unavailable(ValueState.UNKNOWN)))
        self.assertFalse(result.complete)
        self.assertIn("SHIPPING_UNKNOWN", result.reason_codes)

    def test_unknown_tax_blocks_even_with_free_shipping(self) -> None:
        result = calculate_total(scenario(), base_pricing(tax=MoneyValue.unavailable(ValueState.UNKNOWN)))
        self.assertFalse(result.complete)
        self.assertIn("TAX_UNKNOWN", result.reason_codes)

    def test_coupon_not_double_deducted(self) -> None:
        pricing = base_pricing(
            subtotal=MoneyValue.known(4900),
            coupon=CouponTerms(
                "coupon-50", MoneyValue.known(5000), 0, True, True,
                claimed=True, remaining_uses=1, rule_version="test-coupon-v1",
                **coupon_proof(),
            ),
            included_adjustment_ids=frozenset({"coupon-50"}),
        )
        result = calculate_total(scenario(coupon="coupon-50"), pricing)
        self.assertEqual(result.total_minor, 4900)
        self.assertIn("COUPON_ALREADY_INCLUDED", result.reason_codes)

    def test_coupon_threshold_not_met(self) -> None:
        pricing = base_pricing(
            subtotal=MoneyValue.known(4900),
            coupon=CouponTerms(
                "coupon-60", MoneyValue.known(6000), 50_000, True, True,
                claimed=True, remaining_uses=1, threshold_evidence_id="threshold-60",
                rule_version="test-coupon-v1",
                **coupon_proof(threshold_policy="FIXED"),
            ),
        )
        result = calculate_total(scenario(coupon="coupon-60"), pricing)
        self.assertFalse(result.complete)
        self.assertIsNone(result.total_minor)
        self.assertIn("COUPON_THRESHOLD_NOT_MET", result.reason_codes)

    def test_expired_coupon_is_not_applied(self) -> None:
        pricing = base_pricing(
            subtotal=MoneyValue.known(5000),
            coupon=CouponTerms(
                "expired",
                MoneyValue.known(1000),
                0,
                True,
                True,
                expires_at=NOW - timedelta(seconds=1),
                claimed=True,
                remaining_uses=1,
                rule_version="test-coupon-v1",
                **coupon_proof(expiry_policy="FIXED"),
            ),
            evaluated_at=NOW,
        )
        result = calculate_total(scenario(coupon="expired"), pricing)
        self.assertFalse(result.complete)
        self.assertIsNone(result.total_minor)
        self.assertIn("COUPON_EXPIRED", result.reason_codes)

    def test_app_or_payment_restriction_not_satisfied(self) -> None:
        pricing = base_pricing(
            subtotal=MoneyValue.known(5000),
            coupon=CouponTerms(
                "app-only",
                MoneyValue.known(1000),
                0,
                True,
                True,
                claimed=True,
                remaining_uses=1,
                requires_app=True,
                allowed_payment_method="TEST_CARD",
                rule_version="test-coupon-v1",
                **coupon_proof(),
            ),
        )
        result = calculate_total(scenario(coupon="app-only"), pricing)
        self.assertFalse(result.complete)
        self.assertIsNone(result.total_minor)
        self.assertIn("COUPON_APP_CHANNEL_MISMATCH", result.reason_codes)

    def test_coupon_unknown_eligibility_blocks_coupon_scenario(self) -> None:
        result = calculate_total(
            scenario(coupon="first-buy"),
            base_pricing(
                coupon=CouponTerms(
                    "first-buy", MoneyValue.known(900), 0, None, True, claimed=True, remaining_uses=1,
                    rule_version="test-coupon-v1",
                    **coupon_proof(),
                )
            ),
        )
        self.assertFalse(result.complete)
        self.assertIn("COUPON_ELIGIBILITY_UNKNOWN_OR_FALSE", result.reason_codes)

    def test_oversized_coupon_without_cap_rule_blocks(self) -> None:
        result = calculate_total(
            scenario(coupon="too-large"),
            base_pricing(
                subtotal=MoneyValue.known(1000),
                coupon=CouponTerms(
                    "too-large", MoneyValue.known(2000), 0, True, True, claimed=True, remaining_uses=1,
                    rule_version="test-coupon-v1",
                    **coupon_proof(),
                ),
            ),
        )
        self.assertFalse(result.complete)
        self.assertIn("COUPON_EXCEEDS_SUBTOTAL_UNCONFIRMED", result.reason_codes)

    def test_explicit_coupon_cap_can_make_zero(self) -> None:
        result = calculate_total(
            scenario(coupon="capped"),
            base_pricing(
                subtotal=MoneyValue.known(1000),
                coupon=CouponTerms(
                    "capped", MoneyValue.known(2000), 0, True, True, True,
                    claimed=True, remaining_uses=1, rule_version="test-coupon-v1",
                    **coupon_proof(),
                ),
            ),
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.total_minor, 0)

    def test_minimum_quantity_blocks(self) -> None:
        result = calculate_total(scenario(quantity=1), base_pricing(minimum_quantity=2))
        self.assertFalse(result.complete)
        self.assertIn("MINIMUM_QUANTITY_NOT_MET", result.reason_codes)

    def test_additional_item_bundle_blocks(self) -> None:
        result = calculate_total(scenario(), base_pricing(requires_additional_items=True))
        self.assertFalse(result.complete)
        self.assertIn("REQUIRES_BUNDLE", result.reason_codes)

    def test_included_tax_not_added_again(self) -> None:
        target = scenario()
        pricing = base_pricing(
            subtotal=MoneyValue.known(10_000),
            tax=MoneyValue.unavailable(ValueState.NOT_APPLICABLE, evidence_id="tax-included"),
            component_evidence=(
                CostComponentEvidence(
                    "TAX",
                    "tax",
                    "INCLUDED_IN_SUBTOTAL",
                    target.scope_key,
                    "test-quote",
                    10_000,
                    500,
                    "tax-included",
                    "synthetic-tax-rule-v1",
                    NOW,
                    NOW + timedelta(minutes=5),
                    EvidenceBasis.OBSERVED,
                    "b" * 64,
                ),
            ),
        )
        self.assertEqual(calculate_total(target, pricing).total_minor, 10_000)

    def test_duplicate_fee_id_blocks(self) -> None:
        fees = (FeeComponent("service", MoneyValue.known(100)), FeeComponent("service", MoneyValue.known(100)))
        result = calculate_total(scenario(), base_pricing(fees=fees))
        self.assertFalse(result.complete)
        self.assertIn("DUPLICATE_FEE_ID", result.reason_codes)


if __name__ == "__main__":
    unittest.main()

