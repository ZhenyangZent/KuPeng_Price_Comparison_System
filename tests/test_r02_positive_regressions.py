from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cdh_core.history import is_historical_new_low
from cdh_core.models import EvidenceBasis, EventStatus, MoneyValue, Observation, OfferIdentity, PurchaseScenario
from cdh_core.persistence import CurrentState, CurrentStateConflict, EventStore, MockSink
from cdh_core.policy import PolicyContext, decide
from cdh_core.pricing import CouponTerms, PricingInput, calculate_total


NOW = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)
TEST_TEMP_ROOT = Path(__file__).parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)
OFFER = OfferIdentity("SYNTHETIC", "positive", "sku-positive", "seller", "NEW", "1x", "LOCAL")


def scenario(*, coupon: str | None = None) -> PurchaseScenario:
    return PurchaseScenario(
        OFFER,
        "ctx-positive",
        1,
        "WOW",
        coupon_plan_id=coupon,
        eligibility_profile_version="profile-v1",
        price_basis="CURRENT_TOTAL",
        purchase_channel="WEB",
        payment_method="TEST_CARD",
    )


def cost_for(
    target: PurchaseScenario,
    subtotal: int,
    *,
    when: datetime = NOW,
    evidence_id: str = "positive-quote",
    coupon: CouponTerms | None = None,
    included: frozenset[str] = frozenset(),
    lifetime: timedelta = timedelta(minutes=10),
):
    return calculate_total(
        target,
        PricingInput(
            MoneyValue.known(subtotal),
            MoneyValue.known(0),
            (),
            MoneyValue.known(0),
            1,
            True,
            coupon=coupon,
            included_adjustment_ids=included,
            evaluated_at=when,
            evidence_expires_at=when + lifetime,
            quote_evidence_id=evidence_id,
        ),
    )


def context(target: PurchaseScenario, *, now: datetime = NOW, lifetime: timedelta = timedelta(minutes=10)):
    return PolicyContext.synthetic_verified(now, target, expires_at=now + lifetime)


class R02PositiveRegressionTests(unittest.TestCase):
    def test_valid_already_included_coupon_is_complete_without_double_discount(self) -> None:
        target = scenario(coupon="coupon-valid")
        terms = CouponTerms(
            "coupon-valid",
            MoneyValue.known(500),
            0,
            True,
            True,
            expires_at=NOW + timedelta(hours=1),
            applicable_offer_keys=frozenset({target.offer.key}),
            applicable_seller_ids=frozenset({target.offer.seller_id}),
            claimed=True,
            remaining_uses=1,
            rule_version="coupon-validated-v2",
            expiry_policy="FIXED",
            offer_scope_policy="LISTED",
            seller_scope_policy="LISTED",
            threshold_policy="NONE",
            terms_evidence_id="positive-coupon-terms",
            terms_context_id=target.context_id,
            terms_membership_context=target.membership_context,
            terms_eligibility_profile_version=target.eligibility_profile_version,
            terms_evidence_basis=EvidenceBasis.OBSERVED,
            terms_source_record_sha256="b" * 64,
        )
        calculated = cost_for(target, 0, coupon=terms, included=frozenset({"coupon-valid"}))
        decision = decide(target, calculated, None, context(target))
        self.assertTrue(calculated.complete)
        self.assertEqual(calculated.total_minor, 0)
        self.assertEqual(calculated.discount_minor, 0)
        self.assertIn("COUPON_ALREADY_INCLUDED", calculated.reason_codes)
        self.assertEqual(decision.primary_reason, "S0")

    def test_verified_completed_day_history_detects_true_new_low(self) -> None:
        target = scenario()
        observations = [
            Observation(
                target.offer.key,
                target.context_id,
                target.quantity,
                target.price_basis,
                10_000 + day,
                NOW - timedelta(days=day),
                membership_context=target.membership_context,
                eligibility_profile_version=target.eligibility_profile_version,
                coupon_plan_id=target.coupon_plan_id,
                purchase_channel=target.purchase_channel,
                payment_method=target.payment_method,
            )
            for day in range(1, 8)
        ]
        self.assertTrue(is_historical_new_low(500, observations, NOW, target))
        self.assertFalse(is_historical_new_low(20_000, observations, NOW, target))

    def test_confirmed_new_availability_epoch_allows_re_evaluated_notification(self) -> None:
        target = scenario()
        calculated = cost_for(target, 500)
        decision = decide(target, calculated, None, context(target))
        original = CurrentState.verified_from(
            target, calculated, now=NOW, expires_at=NOW + timedelta(minutes=10), availability_version="stock-1"
        )
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "restock.sqlite3")
            store.set_current_state(original, now=NOW)
            first, created_first = store.enqueue(
                target, decision, request_id="stock-1", dedupe_key="same", expected_fingerprint=calculated.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5), now=NOW,
            )
            restocked_at = NOW + timedelta(minutes=1)
            restocked = replace(
                original,
                observed_at=restocked_at,
                received_at=restocked_at,
                availability_version="stock-2",
            )
            store.set_current_state(restocked, now=restocked_at)
            self.assertEqual(store.deliver(first, MockSink(), now=restocked_at), EventStatus.SUPERSEDED)
            second, created_second = store.enqueue(
                target, decision, request_id="stock-2", dedupe_key="same", expected_fingerprint=calculated.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5), now=restocked_at,
            )
            self.assertTrue(created_first)
            self.assertTrue(created_second)
            self.assertNotEqual(first, second)
            self.assertEqual(store.deliver(second, MockSink(), now=restocked_at), EventStatus.DELIVERED)

    def test_same_price_deduplicates_after_24_hours_and_database_restart(self) -> None:
        target = scenario()
        first_cost = cost_for(target, 500, lifetime=timedelta(hours=30), evidence_id="load-1")
        first_decision = decide(target, first_cost, None, context(target, lifetime=timedelta(hours=30)))
        first_state = CurrentState.verified_from(
            target, first_cost, now=NOW, expires_at=NOW + timedelta(hours=30)
        )
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            database = Path(directory) / "restart.sqlite3"
            store = EventStore(database)
            store.set_current_state(first_state, now=NOW)
            first, _ = store.enqueue(
                target, first_decision, request_id="load-1", dedupe_key="same", expected_fingerprint=first_cost.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5), now=NOW,
            )
            later = NOW + timedelta(hours=25)
            second_cost = cost_for(target, 500, when=later, lifetime=timedelta(hours=5), evidence_id="load-2")
            second_decision = decide(target, second_cost, None, context(target, now=later, lifetime=timedelta(hours=5)))
            second_state = CurrentState.verified_from(
                target, second_cost, now=later, expires_at=later + timedelta(hours=5)
            )
            restarted = EventStore(database)
            restarted.set_current_state(second_state, now=later)
            second, created = restarted.enqueue(
                target, second_decision, request_id="load-2", dedupe_key="same", expected_fingerprint=second_cost.quote_fingerprint or "",
                expires_at=later + timedelta(minutes=5), now=later,
            )
            self.assertFalse(created)
            self.assertEqual(first, second)
            self.assertEqual(restarted.counts(), {"events": 1, "outbox": 1})

    def test_newer_source_disable_then_reenable_with_policy_revision_is_monotonic(self) -> None:
        target = scenario()
        calculated = cost_for(target, 500)
        decision = decide(target, calculated, None, context(target))
        enabled = CurrentState.verified_from(target, calculated, now=NOW, expires_at=NOW + timedelta(minutes=10))
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "source-transition.sqlite3")
            store.set_current_state(enabled, now=NOW)
            first, _ = store.enqueue(
                target, decision, request_id="enabled-v1", dedupe_key="source", expected_fingerprint=calculated.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5), now=NOW,
            )
            disabled_at = NOW + timedelta(minutes=1)
            disabled = replace(enabled, source_enabled=False, observed_at=disabled_at, received_at=disabled_at)
            store.set_current_state(disabled, now=disabled_at)
            self.assertEqual(store.deliver(first, MockSink(), now=disabled_at), EventStatus.SUPERSEDED)
            enabled_at = NOW + timedelta(minutes=2)
            reenabled = replace(
                enabled,
                observed_at=enabled_at,
                received_at=enabled_at,
                rule_version="source-policy-v2",
            )
            store.set_current_state(reenabled, now=enabled_at)
            second, created = store.enqueue(
                target, decision, request_id="enabled-v2", dedupe_key="source", expected_fingerprint=calculated.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5), now=enabled_at,
            )
            self.assertTrue(created)
            self.assertNotEqual(first, second)
            self.assertEqual(store.deliver(second, MockSink(), now=enabled_at), EventStatus.DELIVERED)

    def test_equal_timestamp_conflict_is_explicit_and_identical_retry_is_idempotent(self) -> None:
        target = scenario()
        calculated = cost_for(target, 500)
        state = CurrentState.verified_from(target, calculated, now=NOW, expires_at=NOW + timedelta(minutes=10))
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "equal-time.sqlite3")
            self.assertTrue(store.set_current_state(state, now=NOW))
            self.assertFalse(store.set_current_state(state, now=NOW + timedelta(seconds=1)))
            conflict = replace(state, source_enabled=False)
            with self.assertRaises(CurrentStateConflict):
                store.set_current_state(conflict, now=NOW + timedelta(seconds=1))

    def test_schema_v2_rows_are_archived_and_old_outbox_is_not_activated(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            database = Path(directory) / "v2.sqlite3"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
                connection.execute("INSERT INTO schema_version VALUES (2, '2026-11-01T00:00:00+00:00')")
                connection.execute("CREATE TABLE current_state(legacy_value TEXT)")
                connection.execute("INSERT INTO current_state VALUES ('legacy-state')")
                connection.execute("CREATE TABLE deal_events(legacy_value TEXT)")
                connection.execute("INSERT INTO deal_events VALUES ('legacy-queued-event')")
                connection.execute("CREATE TABLE notification_outbox(legacy_value TEXT)")
                connection.execute("INSERT INTO notification_outbox VALUES ('legacy-outbox')")
                connection.commit()
            store = EventStore(database)
            self.assertEqual(store.schema_version(), 5)
            self.assertEqual(
                store.archived_v2_tables(),
                ("current_state_v2_archive", "deal_events_v2_archive", "notification_outbox_v2_archive"),
            )
            self.assertEqual(store.counts(), {"events": 0, "outbox": 0})


if __name__ == "__main__":
    unittest.main()
