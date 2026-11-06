from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cdh_core.models import EventStatus, POLICY_VERSION
from cdh_core.persistence import MockSink
from cdh_integration.adapter import IntegrationValidationError, QualificationFixture, SyntheticObservation
from cdh_integration.pipeline import SyntheticIntegrationPipeline


NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
TMP_ROOT = Path("review/I01/001/tmp/tests")


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def observation(
    *,
    sku: str = "SYNTH-I01-0001",
    price_minor: int = 0,
    observed_at: datetime | None = None,
    title: str = "I01 合成商品",
) -> dict[str, object]:
    stamp = observed_at or (NOW - timedelta(minutes=1))
    return {
        "source_class": "SYNTHETIC_TEST_PAGE",
        "sku": sku,
        "product_url": f"https://synthetic.invalid/products/{sku.lower()}",
        "price_minor": price_minor,
        "currency": "TWD",
        "observed_at": iso(stamp),
        "title": title,
    }


def reliable_history(unit_minor: int, *, now: datetime = NOW) -> list[dict[str, object]]:
    return [
        {"observed_at": iso(now - timedelta(days=day, hours=1)), "unit_minor": unit_minor}
        for day in range(1, 8)
    ]


def fixture(
    raw: dict[str, object],
    *,
    now: datetime = NOW,
    seller_id: str = "SYNTH-SELLER-1",
    package_signature: str = "SYNTH-PACK-1",
    quantity: int = 1,
    minimum_quantity: int = 1,
    shipping_minor: int = 0,
    fees: list[dict[str, object]] | None = None,
    tax_minor: int = 0,
    stock_state: str = "IN_STOCK",
    eligibility_state: str = "ELIGIBLE",
    user_enabled: bool = True,
    notifications_enabled: bool = True,
    source_allowed: bool = True,
    independently_purchasable: bool = True,
    requires_additional_items: bool = False,
    subscription_or_deposit: bool = False,
    membership_context: str = "WOW_SYNTHETIC",
    eligibility_profile_version: str = "ELIGIBILITY-SYNTH-v1",
    target_total_minor: int | None = None,
    coupon: dict[str, object] | None = None,
    history: list[dict[str, object]] | None = None,
    availability_version: str = "availability-v1",
    total_quote_evidence_id: str | None = None,
) -> dict[str, object]:
    parsed = SyntheticObservation.parse(raw)
    result: dict[str, object] = {
        "fixture_class": "SYNTHETIC_QUALIFICATION_FIXTURE",
        "fixture_id": f"FIXTURE-{parsed.sku}-{parsed.source_payload_sha256[:8]}",
        "source_payload_sha256": parsed.source_payload_sha256,
        "sku": parsed.sku,
        "product_url": parsed.product_url,
        "seller_id": seller_id,
        "condition": "NEW_SYNTHETIC",
        "package_signature": package_signature,
        "delivery_type": "SYNTHETIC_DELIVERY",
        "price_minor": parsed.price_minor,
        "price_scenario_id": QualificationFixture.expected_price_scenario_id(
            parsed,
            seller_id=seller_id,
            package_signature=package_signature,
            quantity=quantity,
        ),
        "observation_observed_at": iso(parsed.observed_at),
        "context_id": "I01-SYNTHETIC-CONTEXT",
        "membership_context": membership_context,
        "eligibility_profile_version": eligibility_profile_version,
        "policy_version": POLICY_VERSION,
        "source_permission_version": "OFFLINE-SYNTHETIC-v1",
        "fixture_observed_at": iso(parsed.observed_at - timedelta(minutes=1)),
        "fixture_expires_at": iso(now + timedelta(minutes=10)),
        "quantity": quantity,
        "minimum_quantity": minimum_quantity,
        "stock_state": stock_state,
        "eligibility_state": eligibility_state,
        "independently_purchasable": independently_purchasable,
        "requires_additional_items": requires_additional_items,
        "shipping_minor": shipping_minor,
        "fees": [] if fees is None else fees,
        "tax_minor": tax_minor,
        "subscription_or_deposit": subscription_or_deposit,
        "user_enabled": user_enabled,
        "notifications_enabled": notifications_enabled,
        "source_allowed": source_allowed,
        "coupon_plan_id": None if coupon is None else coupon["coupon_id"],
        "coupon": coupon,
        "target_total_minor": target_total_minor,
        "purchase_channel": "WEB_SYNTHETIC",
        "payment_method": "NONE_SYNTHETIC",
        "availability_version": availability_version,
        "history": [] if history is None else history,
    }
    if quantity == 1 or total_quote_evidence_id is not None:
        result.update(
            {
                "price_basis": "TOTAL_FOR_QUANTITY",
                "quoted_quantity": quantity,
                "total_quote_evidence_id": total_quote_evidence_id or "I01-Q1-QUOTE-EVIDENCE",
            }
        )
    return result


def valid_coupon(*, expires_at: datetime = NOW + timedelta(minutes=5)) -> dict[str, object]:
    return {
        "coupon_id": "SYNTH-COUPON-1",
        "discount_minor": 5_000,
        "minimum_subtotal_minor": 5_000,
        "expires_at": iso(expires_at),
        "claimed": True,
        "remaining_uses": 1,
        "eligibility": True,
        "restrictions_satisfied": True,
        "cap_behavior_confirmed": True,
        "requires_app": False,
        "allowed_payment_method": None,
        "threshold_policy": "FIXED",
        "rule_version": "i01-coupon-rule-v1",
        "terms_evidence_id": "I01-COUPON-TERMS-1",
    }


class I01TestCase(unittest.TestCase):
    def setUp(self) -> None:
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=TMP_ROOT)
        self.directory = Path(self.temporary.name)
        self.clock = MutableClock()
        self.pipeline = SyntheticIntegrationPipeline(
            candidate_database=self.directory / "candidates.sqlite3",
            event_database=self.directory / "events.sqlite3",
            clock=self.clock,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()


class ObservationValidationTests(I01TestCase):
    def test_01_valid_observation_has_stable_source_sha(self) -> None:
        raw = observation()
        first = SyntheticObservation.parse(raw)
        second = SyntheticObservation.parse(copy.deepcopy(raw))
        self.assertEqual(first.source_payload_sha256, second.source_payload_sha256)
        self.assertEqual(len(first.source_payload_sha256), 64)

    def test_02_non_synthetic_source_is_rejected(self) -> None:
        raw = observation()
        raw["source_class"] = "PUBLIC_PAGE"
        with self.assertRaisesRegex(IntegrationValidationError, "not authorized"):
            SyntheticObservation.parse(raw)

    def test_03_real_commerce_url_is_rejected(self) -> None:
        raw = observation()
        raw["product_url"] = "https://not-synthetic.example/products/rejected"
        with self.assertRaises(IntegrationValidationError) as caught:
            SyntheticObservation.parse(raw)
        self.assertEqual(caught.exception.code, "URL_NOT_SYNTHETIC")

    def test_04_lookalike_synthetic_host_is_rejected(self) -> None:
        raw = observation()
        raw["product_url"] = "https://synthetic.invalid.evil.example/products/x"
        with self.assertRaises(IntegrationValidationError):
            SyntheticObservation.parse(raw)

    def test_05_unknown_observation_field_is_rejected(self) -> None:
        raw = observation()
        raw["wow"] = True
        with self.assertRaises(IntegrationValidationError) as caught:
            SyntheticObservation.parse(raw)
        self.assertEqual(caught.exception.code, "INVALID_OBSERVATION_FIELDS")

    def test_06_missing_observation_field_is_rejected(self) -> None:
        raw = observation()
        del raw["title"]
        with self.assertRaises(IntegrationValidationError):
            SyntheticObservation.parse(raw)

    def test_07_boolean_price_is_rejected(self) -> None:
        raw = observation()
        raw["price_minor"] = True
        self.assertEqual(self.pipeline.process(raw).status, "REJECTED")

    def test_08_negative_price_is_rejected(self) -> None:
        raw = observation()
        raw["price_minor"] = -1
        self.assertEqual(self.pipeline.process(raw).reasons, ("INVALID_PRICE_MINOR",))

    def test_09_float_price_is_rejected(self) -> None:
        raw = observation()
        raw["price_minor"] = 0.0
        self.assertEqual(self.pipeline.process(raw).status, "REJECTED")

    def test_10_non_twd_currency_is_rejected(self) -> None:
        raw = observation()
        raw["currency"] = "USD"
        self.assertEqual(self.pipeline.process(raw).reasons, ("INVALID_CURRENCY",))

    def test_11_non_utc_observed_time_is_rejected(self) -> None:
        raw = observation()
        raw["observed_at"] = "2026-11-02T19:59:00+08:00"
        self.assertEqual(self.pipeline.process(raw).reasons, ("INVALID_OBSERVED_AT",))

    def test_12_blank_title_is_rejected(self) -> None:
        raw = observation(title=" ")
        self.assertEqual(self.pipeline.process(raw).reasons, ("INVALID_TITLE",))


class QualificationAndDecisionTests(I01TestCase):
    def test_13_zero_without_fixture_waits_and_never_enters_outbox(self) -> None:
        result = self.pipeline.process(observation(price_minor=0))
        self.assertEqual(result.status, "WAITING_EVIDENCE")
        self.assertEqual(self.pipeline.events.counts(), {"events": 0, "outbox": 0})
        self.assertEqual(self.pipeline.ledger.get(result.source_payload_sha256)["status"], "WAITING_EVIDENCE")

    def test_14_fully_qualified_zero_queues_s0_and_mock_delivers(self) -> None:
        raw = observation(price_minor=0)
        result = self.pipeline.process(raw, fixture(raw))
        self.assertEqual((result.status, result.decision.primary_reason), ("QUEUED", "S0"))
        sink = MockSink()
        self.assertEqual(self.pipeline.deliver(result.event_id, sink, now=NOW), EventStatus.DELIVERED)
        self.assertEqual(len(sink.deliveries), 1)
        self.assertEqual(sink.deliveries[0]["delivery_kind"], "MOCK_ONLY")

    def test_15_fully_qualified_five_dollars_without_history_is_s1(self) -> None:
        raw = observation(price_minor=500)
        result = self.pipeline.process(raw, fixture(raw))
        self.assertEqual(result.decision.primary_reason, "S1")

    def test_16_normal_five_dollars_with_equal_baseline_is_filtered(self) -> None:
        raw = observation(price_minor=500)
        result = self.pipeline.process(raw, fixture(raw, history=reliable_history(500)))
        self.assertEqual((result.status, result.decision.primary_reason), ("FILTERED", "NO_FREE_SHIPPING_POLICY_MATCH"))

    def test_17_explicit_target_can_trigger_at_equal_normal_price(self) -> None:
        raw = observation(price_minor=500)
        result = self.pipeline.process(
            raw,
            fixture(raw, history=reliable_history(500), target_total_minor=500),
        )
        self.assertEqual(result.decision.primary_reason, "TARGET_REACHED")

    def test_18_paid_shipping_without_baseline_is_filtered(self) -> None:
        raw = observation(price_minor=0)
        result = self.pipeline.process(raw, fixture(raw, shipping_minor=3_000))
        self.assertEqual(result.decision.primary_reason, "PAID_SHIPPING_REQUIRES_BASELINE")

    def test_19_paid_shipping_o2_with_reliable_history_is_queued(self) -> None:
        raw = observation(price_minor=5_000)
        result = self.pipeline.process(
            raw,
            fixture(raw, shipping_minor=6_000, history=reliable_history(100_000)),
        )
        self.assertEqual((result.status, result.decision.primary_reason), ("QUEUED", "O2"))

    def test_20_fixture_sku_mismatch_is_blocked(self) -> None:
        raw = observation()
        qualified = fixture(raw)
        qualified["sku"] = "OTHER-SKU"
        result = self.pipeline.process(raw, qualified)
        self.assertEqual(result.reasons, ("FIXTURE_SKU_MISMATCH",))

    def test_21_fixture_seller_tamper_breaks_price_scenario_binding(self) -> None:
        raw = observation()
        qualified = fixture(raw)
        qualified["seller_id"] = "OTHER-SELLER"
        result = self.pipeline.process(raw, qualified)
        self.assertEqual(result.reasons, ("FIXTURE_PRICE_SCENARIO_MISMATCH",))

    def test_22_fixture_source_hash_mismatch_is_blocked(self) -> None:
        raw = observation()
        qualified = fixture(raw)
        qualified["source_payload_sha256"] = "0" * 64
        self.assertEqual(self.pipeline.process(raw, qualified).reasons, ("FIXTURE_SOURCE_HASH_MISMATCH",))

    def test_23_fixture_observation_time_mismatch_is_blocked(self) -> None:
        raw = observation()
        qualified = fixture(raw)
        qualified["observation_observed_at"] = iso(NOW - timedelta(minutes=2))
        self.assertEqual(self.pipeline.process(raw, qualified).reasons, ("FIXTURE_OBSERVATION_TIME_MISMATCH",))

    def test_24_wrong_core_policy_version_is_blocked(self) -> None:
        raw = observation()
        qualified = fixture(raw)
        qualified["policy_version"] = "other-policy"
        self.assertEqual(self.pipeline.process(raw, qualified).reasons, ("FIXTURE_POLICY_VERSION_MISMATCH",))

    def test_25_unknown_stock_is_filtered(self) -> None:
        raw = observation()
        result = self.pipeline.process(raw, fixture(raw, stock_state="UNKNOWN"))
        self.assertEqual(result.decision.primary_reason, "NOT_IN_STOCK")

    def test_26_unknown_eligibility_is_filtered(self) -> None:
        raw = observation()
        result = self.pipeline.process(raw, fixture(raw, eligibility_state="UNKNOWN"))
        self.assertEqual(result.decision.primary_reason, "ELIGIBILITY_UNKNOWN")

    def test_27_explicit_quantity_two_is_not_defaulted(self) -> None:
        raw = observation(price_minor=800)
        result = self.pipeline.process(
            raw,
            fixture(
                raw,
                quantity=2,
                minimum_quantity=2,
                total_quote_evidence_id="I01-Q2-FULL-QUOTE-EVIDENCE",
            ),
        )
        self.assertEqual(result.scenario.quantity, 2)
        self.assertEqual(result.decision.primary_reason, "S1")

    def test_28_minimum_quantity_mismatch_blocks_cost(self) -> None:
        raw = observation(price_minor=800)
        result = self.pipeline.process(raw, fixture(raw, quantity=1, minimum_quantity=2))
        self.assertIn("MINIMUM_QUANTITY_NOT_MET", result.reasons)

    def test_29_additional_items_requirement_is_blocked(self) -> None:
        raw = observation(price_minor=0)
        result = self.pipeline.process(raw, fixture(raw, requires_additional_items=True))
        self.assertIn("REQUIRES_BUNDLE", result.reasons)

    def test_30_service_fee_prevents_false_s0(self) -> None:
        raw = observation(price_minor=0)
        result = self.pipeline.process(
            raw,
            fixture(raw, fees=[{"component_id": "service-fee", "amount_minor": 2_000}]),
        )
        self.assertNotEqual(result.decision.primary_reason, "S0")
        self.assertEqual(result.decision.total_minor, 2_000)

    def test_31_tax_prevents_false_s0(self) -> None:
        raw = observation(price_minor=0)
        result = self.pipeline.process(raw, fixture(raw, tax_minor=2_000))
        self.assertNotEqual(result.decision.primary_reason, "S0")

    def test_32_subscription_or_deposit_is_filtered(self) -> None:
        raw = observation(price_minor=0)
        result = self.pipeline.process(raw, fixture(raw, subscription_or_deposit=True))
        self.assertEqual(result.decision.primary_reason, "SUBSCRIPTION_OR_DEPOSIT")

    def test_33_valid_coupon_can_produce_zero_only_through_core_pricing(self) -> None:
        raw = observation(price_minor=5_000)
        result = self.pipeline.process(raw, fixture(raw, coupon=valid_coupon()))
        self.assertEqual(result.decision.primary_reason, "S0")

    def test_34_coupon_unknown_threshold_is_rejected_before_core(self) -> None:
        raw = observation(price_minor=5_000)
        coupon = valid_coupon()
        coupon["threshold_policy"] = "UNKNOWN"
        result = self.pipeline.process(raw, fixture(raw, coupon=coupon))
        self.assertEqual(result.reasons, ("COUPON_THRESHOLD_UNVERIFIED",))


class PersistenceAndRevocationTests(I01TestCase):
    def test_35_exact_replay_is_idempotent_for_observation_and_event(self) -> None:
        raw = observation()
        qualified = fixture(raw)
        first = self.pipeline.process(raw, qualified)
        second = self.pipeline.process(raw, qualified)
        self.assertTrue(first.event_created)
        self.assertFalse(second.event_created)
        self.assertFalse(second.observation_created)
        self.assertEqual(first.event_id, second.event_id)
        self.assertEqual(self.pipeline.events.counts(), {"events": 1, "outbox": 1})

    def test_36_reopened_store_replay_remains_idempotent(self) -> None:
        raw = observation()
        qualified = fixture(raw)
        first = self.pipeline.process(raw, qualified)
        reopened = SyntheticIntegrationPipeline(
            candidate_database=self.directory / "candidates.sqlite3",
            event_database=self.directory / "events.sqlite3",
            clock=self.clock,
        )
        second = reopened.process(raw, qualified)
        self.assertEqual(first.event_id, second.event_id)
        self.assertFalse(second.event_created)

    def test_37_out_of_order_old_observation_cannot_roll_back_state(self) -> None:
        newer_time = NOW - timedelta(seconds=30)
        newer = observation(price_minor=0, observed_at=newer_time)
        self.pipeline.process(newer, fixture(newer))
        older = observation(price_minor=0, observed_at=NOW - timedelta(minutes=2))
        result = self.pipeline.process(older, fixture(older))
        self.assertEqual(result.reasons, ("STALE_SOURCE_OBSERVATION",))
        self.assertEqual(self.pipeline.events.counts()["events"], 1)

    def test_38_price_rise_invalidates_old_queued_event_before_delivery(self) -> None:
        low = observation(price_minor=0, observed_at=NOW - timedelta(minutes=1))
        low_result = self.pipeline.process(low, fixture(low))
        self.clock.value = NOW + timedelta(minutes=1)
        high = observation(price_minor=5_000, observed_at=NOW + timedelta(seconds=30))
        high_result = self.pipeline.process(high, fixture(high, now=self.clock.value))
        self.assertEqual(high_result.status, "FILTERED")
        sink = MockSink()
        status = self.pipeline.deliver(low_result.event_id, sink, now=self.clock.value)
        self.assertEqual(status, EventStatus.SUPERSEDED)
        self.assertEqual(sink.deliveries, [])

    def test_39_notification_disable_supersedes_queued_event(self) -> None:
        raw = observation()
        result = self.pipeline.process(raw, fixture(raw))
        changed = NOW + timedelta(seconds=1)
        self.pipeline.revoke_user_policy(
            result.scenario,
            notifications_enabled=False,
            source_allowed=True,
            membership_context=result.scenario.membership_context,
            eligibility_profile_version=result.scenario.eligibility_profile_version,
            revision_id="disable-notifications-v2",
            now=changed,
        )
        self.assertEqual(self.pipeline.events.event_status(result.event_id), EventStatus.SUPERSEDED)

    def test_40_source_permission_revoke_supersedes_queued_event(self) -> None:
        raw = observation()
        result = self.pipeline.process(raw, fixture(raw))
        changed = NOW + timedelta(seconds=1)
        self.pipeline.revoke_user_policy(
            result.scenario,
            notifications_enabled=True,
            source_allowed=False,
            membership_context=result.scenario.membership_context,
            eligibility_profile_version=result.scenario.eligibility_profile_version,
            revision_id="source-revoked-v2",
            now=changed,
        )
        self.assertEqual(self.pipeline.events.event_status(result.event_id), EventStatus.SUPERSEDED)

    def test_41_wow_profile_change_supersedes_queued_event(self) -> None:
        raw = observation()
        result = self.pipeline.process(raw, fixture(raw))
        changed = NOW + timedelta(seconds=1)
        self.pipeline.revoke_user_policy(
            result.scenario,
            notifications_enabled=True,
            source_allowed=True,
            membership_context="NON_WOW_SYNTHETIC",
            eligibility_profile_version="ELIGIBILITY-SYNTH-v2",
            revision_id="membership-switch-v2",
            now=changed,
        )
        self.assertEqual(self.pipeline.events.event_status(result.event_id), EventStatus.SUPERSEDED)

    def test_42_coupon_expiry_expires_event_before_mock_delivery(self) -> None:
        raw = observation(price_minor=5_000)
        expiry = NOW + timedelta(seconds=30)
        result = self.pipeline.process(raw, fixture(raw, coupon=valid_coupon(expires_at=expiry)))
        sink = MockSink()
        status = self.pipeline.deliver(result.event_id, sink, now=NOW + timedelta(minutes=1))
        self.assertEqual(status, EventStatus.EXPIRED)
        self.assertEqual(sink.deliveries, [])

    def test_43_mock_sink_is_the_only_delivery_kind(self) -> None:
        raw = observation()
        result = self.pipeline.process(raw, fixture(raw))
        sink = MockSink()
        self.pipeline.deliver(result.event_id, sink, now=NOW)
        self.assertEqual({item["delivery_kind"] for item in sink.deliveries}, {"MOCK_ONLY"})

    def test_44_candidate_ledger_preserves_traceability_fields(self) -> None:
        raw = observation()
        result = self.pipeline.process(raw, fixture(raw))
        record = self.pipeline.ledger.get(result.source_payload_sha256)
        self.assertEqual(record["fixture_sha256"], result.fixture_sha256)
        self.assertEqual(record["scenario_scope"], result.scenario.scope_key)
        self.assertEqual(record["event_id"], result.event_id)
        self.assertEqual(json.loads(record["reason_codes_json"]), ["S0"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
