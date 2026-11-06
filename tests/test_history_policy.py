from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from cdh_core.history import build_baseline, is_historical_new_low
from cdh_core.models import (
    BaselineSnapshot,
    EligibilityState,
    MoneyValue,
    Observation,
    OfferIdentity,
    PurchaseScenario,
    StockState,
)
from cdh_core.policy import PolicyContext, decide as core_decide
from cdh_core.pricing import FeeComponent, PricingInput, calculate_total


AS_OF = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)


def obs(days_ago: int, value: int, *, hour: int = 1, sku: str = "sku") -> Observation:
    when = AS_OF - timedelta(days=days_ago)
    when = when.replace(hour=hour, minute=0)
    target = make_scenario(sku=sku)
    return Observation(
        target.offer.key,
        target.context_id,
        target.quantity,
        target.price_basis,
        value,
        when,
        membership_context=target.membership_context,
        eligibility_profile_version=target.eligibility_profile_version,
        coupon_plan_id=target.coupon_plan_id,
        purchase_channel=target.purchase_channel,
        payment_method=target.payment_method,
    )


def make_scenario(quantity: int = 1, target: int | None = None, sku: str = "sku") -> PurchaseScenario:
    identity = OfferIdentity("TEST", "p", sku, "seller", "NEW", "1x", "TEST")
    return PurchaseScenario(
        identity,
        "ctx",
        quantity,
        "WOW_USER_DECLARED",
        target_total_minor=target,
        eligibility_profile_version="test-profile-v1",
        purchase_channel="WEB",
        payment_method="TEST_CARD",
    )


def cost(subtotal: int, shipping: int = 0, *, quantity: int = 1):
    return calculate_total(
        make_scenario(quantity),
        PricingInput(
            MoneyValue.known(subtotal),
            MoneyValue.known(shipping),
            (),
            MoneyValue.known(0),
            quantity,
            True,
            evaluated_at=AS_OF,
            evidence_expires_at=AS_OF + timedelta(minutes=5),
            quote_evidence_id="test-quote",
        ),
    )


def baseline(
    item_minor: int, *, reliable: bool = True, scenario: PurchaseScenario | None = None
) -> BaselineSnapshot:
    target = scenario or make_scenario()
    last_observed_at = AS_OF - timedelta(days=1)
    return BaselineSnapshot(
        item_minor,
        3,
        7,
        7,
        last_observed_at,
        reliable,
        "BASELINE_READY",
        event_time=AS_OF,
        series_key=target.history_series_key,
        scenario_scope=target.scope_key,
        offer_key=target.offer.key,
        context_id=target.context_id,
        membership_context=target.membership_context,
        eligibility_profile_version=target.eligibility_profile_version,
        coupon_plan_id=target.coupon_plan_id,
        quantity=target.quantity,
        price_basis=target.price_basis,
        contributing_observation_count=7,
        last_eligible_history_day="2026-10-31",
    )


def verified_context(target: PurchaseScenario | None = None) -> PolicyContext:
    return PolicyContext.synthetic_verified(
        AS_OF,
        target or make_scenario(),
        expires_at=AS_OF + timedelta(minutes=5),
    )


def decide(
    scenario: PurchaseScenario,
    calculated,
    history: BaselineSnapshot | None,
    context: PolicyContext | None = None,
):
    return core_decide(scenario, calculated, history, context or verified_context(scenario))


class HistoryTests(unittest.TestCase):
    def test_m30_requires_seven_valid_days(self) -> None:
        result = build_baseline([obs(day, 10_000) for day in range(1, 7)], AS_OF, make_scenario())
        self.assertFalse(result.reliable)
        self.assertEqual(result.reason, "INSUFFICIENT_HISTORY")

    def test_seven_days_and_fresh_sample_enable_baseline(self) -> None:
        result = build_baseline([obs(day, 10_000 + day) for day in range(1, 8)], AS_OF, make_scenario())
        self.assertTrue(result.reliable)
        self.assertEqual(result.sample_days_m30, 7)

    def test_latest_older_than_seven_days_is_stale(self) -> None:
        result = build_baseline([obs(day, 10_000) for day in range(8, 15)], AS_OF, make_scenario())
        self.assertFalse(result.reliable)
        self.assertEqual(result.reason, "STALE_HISTORY")

    def test_same_utc_hour_only_first_affects_daily_median(self) -> None:
        rows = [obs(day, 10_000) for day in range(1, 8)]
        first = obs(1, 10_000, hour=2)
        later_same_hour = replace(first, unit_minor=1, observed_at=first.observed_at + timedelta(minutes=30))
        result = build_baseline(rows + [first, later_same_hour], AS_OF, make_scenario())
        self.assertTrue(result.reliable)
        self.assertGreater(result.item_minor or 0, 1)

    def test_taipei_current_day_excluded_from_own_baseline(self) -> None:
        rows = [obs(day, 10_000) for day in range(1, 8)]
        current = replace(rows[0], unit_minor=1, observed_at=AS_OF - timedelta(minutes=1))
        result = build_baseline(rows + [current], AS_OF, make_scenario())
        self.assertGreater(result.item_minor or 0, 1)

    def test_mixed_sku_history_rejected(self) -> None:
        rows = [obs(day, 10_000) for day in range(1, 8)] + [obs(1, 1, sku="other")]
        self.assertEqual(build_baseline(rows, AS_OF, make_scenario()).reason, "MIXED_HISTORY_SERIES")

    def test_first_observation_is_not_new_low(self) -> None:
        self.assertFalse(is_historical_new_low(1, [], AS_OF, make_scenario()))

    def test_event_before_snapshot_detects_real_new_low(self) -> None:
        rows = [obs(day, 10_000 + day) for day in range(1, 8)]
        self.assertTrue(is_historical_new_low(5_000, rows, AS_OF, make_scenario()))


class PolicyTests(unittest.TestCase):
    def test_s0_zero_total_free_shipping(self) -> None:
        self.assertEqual(decide(make_scenario(), cost(0), None).primary_reason, "S0")

    def test_zero_product_plus_shipping_without_baseline_is_silent(self) -> None:
        decision = decide(make_scenario(), cost(0, 6000), None)
        self.assertFalse(decision.notify)
        self.assertEqual(decision.primary_reason, "PAID_SHIPPING_REQUIRES_BASELINE")

    def test_s1_without_history_is_candidate(self) -> None:
        decision = decide(make_scenario(), cost(500), None)
        self.assertEqual(decision.primary_reason, "S1")
        self.assertIn("LOW_PRICE_CANDIDATE", decision.labels)

    def test_same_five_dollar_baseline_is_not_sale(self) -> None:
        decision = decide(make_scenario(), cost(500), baseline(500))
        self.assertFalse(decision.notify)

    def test_nine_point_zero_one_display_rounding_does_not_become_s1(self) -> None:
        decision = decide(make_scenario(), cost(901), None)
        self.assertFalse(decision.notify)
        self.assertNotEqual(decision.primary_reason, "S1")

    def test_minimum_100_one_dollar_each_not_s1(self) -> None:
        decision = decide(make_scenario(100), cost(10_000, quantity=100), None)
        self.assertNotEqual(decision.primary_reason, "S1")

    def test_four_dollar_two_units_is_s1(self) -> None:
        decision = decide(make_scenario(2), cost(800, quantity=2), None)
        self.assertEqual(decision.primary_reason, "S1")

    def test_o1(self) -> None:
        decision = decide(make_scenario(), cost(0, 3000), baseline(20_000))
        self.assertEqual(decision.primary_reason, "O1")

    def test_o1_exact_boundary_and_fraction_guard(self) -> None:
        self.assertEqual(decide(make_scenario(), cost(0, 3900), baseline(15_000)).primary_reason, "O1")
        self.assertNotEqual(decide(make_scenario(), cost(0, 3901), baseline(15_000)).primary_reason, "O1")
        self.assertNotEqual(decide(make_scenario(), cost(0, 3900), baseline(14_999)).primary_reason, "O1")

    def test_o2(self) -> None:
        decision = decide(make_scenario(), cost(5000, 6000), baseline(100_000))
        self.assertEqual(decision.primary_reason, "O2")

    def test_paid_shipping_target_does_not_bypass_exception(self) -> None:
        scenario = make_scenario(target=10_000)
        decision = decide(scenario, cost(5000, 6000), baseline(20_000))
        self.assertFalse(decision.notify)

    def test_target_reached_at_twenty_percent_drop(self) -> None:
        scenario = make_scenario(target=80_000)
        decision = decide(scenario, cost(80_000), baseline(100_000))
        self.assertEqual(decision.primary_reason, "TARGET_REACHED")

    def test_target_without_history(self) -> None:
        decision = decide(make_scenario(target=80_000), cost(80_000), None)
        self.assertEqual(decision.primary_reason, "TARGET_REACHED")

    def test_s2_and_s3(self) -> None:
        self.assertEqual(decide(make_scenario(), cost(30_000), baseline(100_000)).primary_reason, "S2")
        self.assertEqual(decide(make_scenario(), cost(60_000), baseline(100_000)).primary_reason, "S3")

    def test_q2_exact_s3_example(self) -> None:
        scenario = make_scenario(2)
        decision = decide(scenario, cost(18_000, quantity=2), baseline(15_000, scenario=scenario))
        self.assertEqual(decision.primary_reason, "S3")
        self.assertEqual(decision.total_minor, 18_000)
        self.assertEqual(decision.baseline_total_minor, 30_000)
        self.assertEqual(decision.savings_minor, 12_000)

    def test_zero_product_with_required_service_fee_is_not_s0(self) -> None:
        scenario = make_scenario()
        calculated = calculate_total(
            scenario,
            PricingInput(
                MoneyValue.known(0),
                MoneyValue.known(0),
                (FeeComponent("required-service", MoneyValue.known(2000)),),
                MoneyValue.known(0),
                1,
                True,
                evaluated_at=AS_OF,
                evidence_expires_at=AS_OF + timedelta(minutes=5),
                quote_evidence_id="test-service-fee-quote",
            ),
        )
        decision = decide(scenario, calculated, None)
        self.assertFalse(decision.notify)
        self.assertNotEqual(decision.primary_reason, "S0")

    def test_zero_baseline_does_not_divide(self) -> None:
        decision = decide(make_scenario(), cost(100), baseline(0))
        self.assertIsNone(decision.drop_basis_points)

    def test_each_hard_gate_fails_closed(self) -> None:
        cases = {
            "user_enabled": "USER_DISABLED",
            "notifications_enabled": "NOTIFICATIONS_DISABLED",
            "source_allowed": "SOURCE_NOT_ALLOWED",
            "evidence_valid": "EVIDENCE_INVALID",
        }
        for field, reason in cases.items():
            with self.subTest(field=field):
                values = {field: False}
                self.assertEqual(
                    decide(make_scenario(), cost(0), None, replace(verified_context(), **values)).primary_reason,
                    reason,
                )

    def test_eligibility_unknown_ineligible_and_conflict_are_distinct(self) -> None:
        expected = {
            EligibilityState.UNKNOWN: "ELIGIBILITY_UNKNOWN",
            EligibilityState.INELIGIBLE: "INELIGIBLE",
            EligibilityState.CONFLICT: "ELIGIBILITY_CONFLICT",
        }
        for state, reason in expected.items():
            with self.subTest(state=state):
                decision = decide(make_scenario(), cost(0), None, replace(verified_context(), eligibility=state))
                self.assertFalse(decision.notify)
                self.assertEqual(decision.primary_reason, reason)

    def test_out_of_stock_and_subscription_fail_closed(self) -> None:
        self.assertEqual(
            decide(make_scenario(), cost(0), None, replace(verified_context(), stock=StockState.OUT_OF_STOCK)).primary_reason,
            "NOT_IN_STOCK",
        )
        self.assertEqual(
            decide(make_scenario(), cost(0), None, replace(verified_context(), subscription_or_deposit=True)).primary_reason,
            "SUBSCRIPTION_OR_DEPOSIT",
        )


if __name__ == "__main__":
    unittest.main()

