from __future__ import annotations

import concurrent.futures
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cdh_core.models import (
    BaselineSnapshot,
    EligibilityState,
    Evidence,
    EvidenceBasis,
    EventStatus,
    MoneyValue,
    Observation,
    OfferIdentity,
    PurchaseScenario,
    ValueState,
)
from cdh_core.persistence import (
    CurrentState,
    CurrentStateConflict,
    DecisionBindingError,
    EventStore,
    IdempotencyConflict,
    MockSink,
    ObservationConflict,
    StaleCurrentState,
)
from cdh_core.policy import PolicyContext, decide
from cdh_core.pricing import CouponTerms, PricingInput, calculate_total, parse_minor


NOW = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)
TEST_TEMP_ROOT = Path(__file__).parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)
OFFER = OfferIdentity("TEST", "prod1", "sku1", "seller1", "NEW", "1x", "LOCAL")
OTHER = OfferIdentity("TEST", "prod2", "sku2", "seller2", "NEW", "1x", "LOCAL")


def scenario(
    offer: OfferIdentity = OFFER,
    *,
    membership: str = "WOW",
    context_id: str = "ctx-1",
    coupon: str | None = None,
    channel: str = "WEB",
    payment: str = "TEST_CARD",
) -> PurchaseScenario:
    return PurchaseScenario(
        offer,
        context_id,
        1,
        membership,
        coupon_plan_id=coupon,
        eligibility_profile_version="profile-v1",
        price_basis="CURRENT_TOTAL",
        purchase_channel=channel,
        payment_method=payment,
    )


def pricing_cost(
    target: PurchaseScenario,
    subtotal: int = 500,
    shipping: int = 0,
    *,
    coupon: CouponTerms | None = None,
):
    return calculate_total(
        target,
        PricingInput(
            MoneyValue.known(subtotal),
            MoneyValue.known(shipping),
            (),
            MoneyValue.known(0),
            1,
            True,
            coupon=coupon,
            evaluated_at=NOW,
            evidence_expires_at=NOW + timedelta(minutes=10),
            quote_evidence_id="audit-regression-quote",
        ),
    )


def verified_context(target: PurchaseScenario | None = None) -> PolicyContext:
    bound = target or scenario()
    return PolicyContext.synthetic_verified(NOW, bound, expires_at=NOW + timedelta(minutes=10))


def notifying_bundle(target: PurchaseScenario, subtotal: int = 500):
    calculated = pricing_cost(target, subtotal)
    decision = decide(target, calculated, None, verified_context(target))
    if not decision.notify:
        raise AssertionError(f"test setup expected a notifying decision: {decision.primary_reason}")
    state = CurrentState.verified_from(
        target,
        calculated,
        now=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    return calculated, decision, state


class AuditCounterexampleRegressionTests(unittest.TestCase):
    def test_aud_01_membership_is_part_of_evidence_scope(self) -> None:
        wow = scenario(membership="WOW")
        non_wow = scenario(membership="NO_WOW")
        evidence = Evidence(
            "e1",
            "shipping",
            0,
            EvidenceBasis.OBSERVED,
            wow.offer.key,
            wow.context_id,
            wow.scope_key,
            NOW - timedelta(minutes=1),
            NOW + timedelta(minutes=5),
            "rules-v1",
            membership_context=wow.membership_context,
        )
        compatible, reason = evidence.compatibility(non_wow, NOW)
        self.assertFalse(compatible)
        self.assertEqual(reason, "EVIDENCE_SCENARIO_MISMATCH")

    def test_aud_02_offer_identity_delimiter_collision_removed(self) -> None:
        first = OfferIdentity("P|X", "Y", "SKU", "SELL", "NEW", "1x", "LOCAL")
        second = OfferIdentity("P", "X|Y", "SKU", "SELL", "NEW", "1x", "LOCAL")
        self.assertNotEqual(first, second)
        self.assertNotEqual(first.key, second.key)

    def test_aud_03_unbound_cross_sku_baseline_cannot_authorize_o2(self) -> None:
        target = scenario(OTHER)
        calculated = pricing_cost(target, 5_000, 6_000)
        unbound = BaselineSnapshot(
            100_000,
            3,
            7,
            21,
            NOW - timedelta(days=1),
            True,
            "BASELINE_READY",
            event_time=NOW,
        )
        decision = decide(target, calculated, unbound, verified_context(target))
        self.assertFalse(decision.notify)
        self.assertEqual(decision.primary_reason, "PAID_SHIPPING_REQUIRES_BASELINE")

    def test_aud_04_default_policy_context_is_fail_closed(self) -> None:
        target = scenario()
        decision = decide(target, pricing_cost(target, 0), None)
        self.assertFalse(decision.notify)
        self.assertEqual(decision.primary_reason, "POLICY_CONTEXT_UNVERIFIED")

    def test_aud_05_semantic_dedupe_ignores_caller_key_variation(self) -> None:
        target = scenario()
        calculated, decision, state = notifying_bundle(target)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "audit-05.sqlite3")
            store.set_current_state(state, now=NOW)
            first, created_first = store.enqueue(
                target,
                decision,
                request_id="req-1",
                dedupe_key="caller-key-one",
                expected_fingerprint=calculated.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5),
                now=NOW,
            )
            second, created_second = store.enqueue(
                target,
                decision,
                request_id="req-2",
                dedupe_key="caller-key-two",
                expected_fingerprint=calculated.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5),
                now=NOW,
            )
            self.assertEqual(first, second)
            self.assertTrue(created_first)
            self.assertFalse(created_second)
            self.assertEqual(store.counts(), {"events": 1, "outbox": 1})

    def test_aud_06_divergent_request_id_reuse_is_conflict(self) -> None:
        original = scenario()
        other = scenario(OTHER)
        cost_a, decision_a, state_a = notifying_bundle(original)
        cost_b, decision_b, state_b = notifying_bundle(other)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "audit-06.sqlite3")
            store.set_current_state(state_a, now=NOW)
            store.enqueue(
                original,
                decision_a,
                request_id="same-request",
                dedupe_key="one",
                expected_fingerprint=cost_a.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5),
                now=NOW,
            )
            store.set_current_state(state_b, now=NOW)
            with self.assertRaises(IdempotencyConflict):
                store.enqueue(
                    other,
                    decision_b,
                    request_id="same-request",
                    dedupe_key="two",
                    expected_fingerprint=cost_b.quote_fingerprint or "",
                    expires_at=NOW + timedelta(minutes=5),
                    now=NOW,
                )

    def test_aud_07_observation_source_clocks_round_trip(self) -> None:
        target = scenario()
        published = NOW - timedelta(days=7)
        received = NOW - timedelta(seconds=1)
        observation = Observation(
            target.offer.key,
            target.context_id,
            1,
            target.price_basis,
            500,
            NOW - timedelta(minutes=2),
            source_published_at=published,
            received_at=received,
            source_id="offline-source",
            membership_context=target.membership_context,
            eligibility_profile_version=target.eligibility_profile_version,
            coupon_plan_id=target.coupon_plan_id,
            purchase_channel=target.purchase_channel,
            payment_method=target.payment_method,
        )
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "audit-07.sqlite3")
            self.assertTrue(store.record_observation("obs-1", observation))
            record = store.observation_record("obs-1")
            self.assertEqual(record["source_published_at"], published.isoformat())
            self.assertEqual(record["received_at"], received.isoformat())
            self.assertEqual(record["payload_fingerprint"], observation.payload_fingerprint)

    def test_aud_08_exact_expiry_is_invalid(self) -> None:
        target = scenario()
        evidence = Evidence(
            "expiry",
            "shipping",
            0,
            EvidenceBasis.OBSERVED,
            target.offer.key,
            target.context_id,
            target.scope_key,
            NOW - timedelta(minutes=1),
            NOW + timedelta(minutes=5),
            "rules-v1",
        )
        self.assertEqual(evidence.compatibility(target, evidence.expires_at), (False, "EVIDENCE_EXPIRED"))

    def test_aud_09_app_and_payment_coupon_requires_matching_context(self) -> None:
        target = scenario(coupon="app-coupon", channel="WEB", payment="TEST_CARD")
        terms = CouponTerms(
            "app-coupon",
            MoneyValue.known(5_000),
            0,
            True,
            True,
            claimed=True,
            remaining_uses=1,
            requires_app=True,
            allowed_payment_method="APP_ONLY_PAYMENT",
            rule_version="test-coupon-v1",
        )
        calculated = pricing_cost(target, 5_000, coupon=terms)
        self.assertFalse(calculated.complete)
        self.assertIsNone(calculated.total_minor)
        self.assertIn("COUPON_APP_CHANNEL_MISMATCH", calculated.reason_codes)
        self.assertIn("COUPON_PAYMENT_METHOD_MISMATCH", calculated.reason_codes)

    def test_aud_10_current_state_key_binds_coupon_and_price_basis(self) -> None:
        def coupon_bundle(coupon_id: str):
            target = scenario(coupon=coupon_id)
            terms = CouponTerms(
                coupon_id,
                MoneyValue.known(100),
                0,
                True,
                True,
                claimed=True,
                remaining_uses=1,
                rule_version="test-coupon-v1",
                expiry_policy="PERPETUAL",
                offer_scope_policy="ALL",
                seller_scope_policy="ALL",
                threshold_policy="NONE",
                terms_evidence_id="audit-coupon-terms",
                terms_context_id=target.context_id,
                terms_membership_context=target.membership_context,
                terms_eligibility_profile_version=target.eligibility_profile_version,
                terms_evidence_basis=EvidenceBasis.OBSERVED,
                terms_source_record_sha256="c" * 64,
            )
            calculated = pricing_cost(target, 500, coupon=terms)
            return target, CurrentState.verified_from(
                target, calculated, now=NOW, expires_at=NOW + timedelta(minutes=10)
            )

        scenario_a, state_a = coupon_bundle("A")
        scenario_b, state_b = coupon_bundle("B")
        self.assertNotEqual(scenario_a.scope_key, scenario_b.scope_key)
        self.assertEqual(state_a.scenario_key, scenario_a.scope_key)
        self.assertEqual(state_b.scenario_key, scenario_b.scope_key)
        self.assertNotEqual(state_a.scenario_key, state_b.scenario_key)

    def test_aud_11_stale_current_state_cannot_be_delivered(self) -> None:
        target = scenario()
        calculated, decision, state = notifying_bundle(target)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "audit-11.sqlite3")
            store.set_current_state(state, now=NOW)
            event_id, _ = store.enqueue(
                target,
                decision,
                request_id="stale-state",
                dedupe_key="stale-state",
                expected_fingerprint=calculated.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5),
                now=NOW,
            )
            stale = replace(
                state,
                observed_at=NOW - timedelta(days=2),
                received_at=NOW - timedelta(days=2),
                expires_at=NOW - timedelta(days=1),
            )
            with self.assertRaises(StaleCurrentState):
                store.set_current_state(stale, now=NOW)
            self.assertEqual(store.deliver(event_id, MockSink(), now=NOW), EventStatus.DELIVERED)

    def test_aud_12_not_applicable_subtotal_cannot_become_false_zero(self) -> None:
        target = scenario()
        calculated = calculate_total(
            target,
            PricingInput(
                MoneyValue.unavailable(ValueState.NOT_APPLICABLE, evidence_id="absence-evidence"),
                MoneyValue.known(0),
                (),
                MoneyValue.known(0),
                1,
                True,
                evaluated_at=NOW,
            ),
        )
        decision = decide(target, calculated, None, verified_context(target))
        self.assertFalse(calculated.complete)
        self.assertIsNone(calculated.total_minor)
        self.assertFalse(decision.notify)
        self.assertNotEqual(decision.primary_reason, "S0")

    def test_aud_13_future_evidence_is_not_yet_valid(self) -> None:
        target = scenario()
        future = Evidence(
            "future",
            "shipping",
            0,
            EvidenceBasis.OBSERVED,
            target.offer.key,
            target.context_id,
            target.scope_key,
            NOW + timedelta(minutes=3),
            NOW + timedelta(minutes=8),
            "rules-v1",
        )
        self.assertEqual(future.compatibility(target, NOW), (False, "EVIDENCE_NOT_YET_VALID"))

    def test_aud_14_coupon_terms_must_match_selected_plan(self) -> None:
        target = scenario(coupon="coupon-A")
        wrong = CouponTerms(
            "coupon-B",
            MoneyValue.known(5_000),
            0,
            True,
            True,
            claimed=True,
            remaining_uses=1,
            rule_version="test-coupon-v1",
        )
        calculated = pricing_cost(target, 5_000, coupon=wrong)
        self.assertFalse(calculated.complete)
        self.assertIsNone(calculated.total_minor)
        self.assertNotIn("coupon-B", calculated.applied_adjustment_ids)
        self.assertIn("COUPON_PLAN_MISMATCH", calculated.reason_codes)

    def test_aud_15_decision_cannot_be_enqueued_for_another_product(self) -> None:
        original = scenario()
        wrong = scenario(OTHER)
        calculated, decision, _ = notifying_bundle(original, 0)
        wrong_cost, _, wrong_state = notifying_bundle(wrong, 0)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "audit-15.sqlite3")
            store.set_current_state(wrong_state, now=NOW)
            with self.assertRaises(DecisionBindingError):
                store.enqueue(
                    wrong,
                    decision,
                    request_id="mismatched",
                    dedupe_key="mismatched",
                    expected_fingerprint=wrong_cost.quote_fingerprint or calculated.quote_fingerprint or "",
                    expires_at=NOW + timedelta(minutes=5),
                    now=NOW,
                )

    def test_aud_16_lower_price_creates_new_semantic_event(self) -> None:
        target = scenario()
        cost_100, decision_100, state_100 = notifying_bundle(target, 100)
        cost_50, decision_50, state_50 = notifying_bundle(target, 50)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "audit-16.sqlite3")
            store.set_current_state(state_100, now=NOW)
            first, first_created = store.enqueue(
                target,
                decision_100,
                request_id="r-100",
                dedupe_key="stable-product-key",
                expected_fingerprint=cost_100.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5),
                now=NOW,
            )
            changed_at = NOW + timedelta(seconds=1)
            state_50 = replace(state_50, observed_at=changed_at, received_at=changed_at)
            store.set_current_state(state_50, now=changed_at)
            second, second_created = store.enqueue(
                target,
                decision_50,
                request_id="r-50",
                dedupe_key="stable-product-key",
                expected_fingerprint=cost_50.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5),
                now=changed_at,
            )
            self.assertTrue(first_created)
            self.assertTrue(second_created)
            self.assertNotEqual(first, second)
            self.assertEqual(store.counts(), {"events": 2, "outbox": 2})

    def test_aud_17_observation_id_conflict_is_explicit(self) -> None:
        target = scenario()

        def observation(amount: int) -> Observation:
            return Observation(
                target.offer.key,
                target.context_id,
                1,
                target.price_basis,
                amount,
                NOW,
                membership_context=target.membership_context,
                eligibility_profile_version=target.eligibility_profile_version,
                purchase_channel=target.purchase_channel,
                payment_method=target.payment_method,
            )

        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "audit-17.sqlite3")
            self.assertTrue(store.record_observation("same-id", observation(500)))
            with self.assertRaises(ObservationConflict):
                store.record_observation("same-id", observation(2_000))


class _NeverCalledSink:
    def deliver(self, payload: dict[str, object]) -> None:
        raise AssertionError("superseded event must not call sink")


class _BlockingSink:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def deliver(self, payload: dict[str, object]) -> None:
        self.started.set()
        if not self.release.wait(3):
            raise RuntimeError("test sink timed out")


class PersistenceHardeningTests(unittest.TestCase):
    def test_schema_v1_migration_preserves_archives_and_starts_v2_empty(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            database = Path(directory) / "migration.sqlite3"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
                connection.execute("INSERT INTO schema_version VALUES (1, 'before')")
                connection.execute("CREATE TABLE current_state(legacy_value TEXT)")
                connection.execute("INSERT INTO current_state VALUES ('preserve-me')")
                connection.execute("CREATE TABLE deal_events(legacy_value TEXT)")
                connection.execute("INSERT INTO deal_events VALUES ('preserve-event')")
                connection.commit()
            store = EventStore(database)
            self.assertEqual(store.schema_version(), 5)
            self.assertEqual(
                store.archived_v1_tables(),
                ("current_state_v1_archive", "deal_events_v1_archive"),
            )
            self.assertEqual(store.counts(), {"events": 0, "outbox": 0})
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT legacy_value FROM current_state_v1_archive").fetchone()[0], "preserve-me")
                self.assertEqual(connection.execute("SELECT legacy_value FROM deal_events_v1_archive").fetchone()[0], "preserve-event")

    def test_sink_callback_does_not_hold_writer_lock_and_postcheck_is_safe(self) -> None:
        target = scenario()
        calculated, decision, state = notifying_bundle(target)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "slow-sink.sqlite3")
            store.set_current_state(state, now=NOW)
            event_id, _ = store.enqueue(
                target,
                decision,
                request_id="slow-sink",
                dedupe_key="slow-sink",
                expected_fingerprint=calculated.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5),
                now=NOW,
            )
            sink = _BlockingSink()
            changed_at = NOW + timedelta(seconds=1)
            changed = replace(
                state,
                quote_fingerprint="changed-during-callback",
                semantic_fingerprint="semantic-changed-during-callback",
                total_minor=1_500,
                observed_at=changed_at,
                received_at=changed_at,
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                delivery_future = executor.submit(store.deliver, event_id, sink, now=NOW)
                self.assertTrue(sink.started.wait(2), "sink callback did not start")
                write_future = executor.submit(store.set_current_state, changed, now=changed_at)
                try:
                    write_future.result(timeout=1)
                finally:
                    sink.release.set()
                status = delivery_future.result(timeout=2)
            self.assertEqual(status, EventStatus.DELIVERY_UNKNOWN)

    def test_same_semantic_state_after_24_hours_does_not_force_resend(self) -> None:
        target = scenario()
        calculated = calculate_total(
            target,
            PricingInput(
                MoneyValue.known(500),
                MoneyValue.known(0),
                (),
                MoneyValue.known(0),
                1,
                True,
                evaluated_at=NOW,
                evidence_expires_at=NOW + timedelta(hours=30),
                quote_evidence_id="long-lived-test-quote",
            ),
        )
        long_context = PolicyContext.synthetic_verified(NOW, target, expires_at=NOW + timedelta(hours=30))
        decision = decide(target, calculated, None, long_context)
        state = CurrentState.verified_from(
            target,
            calculated,
            now=NOW,
            expires_at=NOW + timedelta(hours=30),
        )
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "dedupe-window.sqlite3")
            store.set_current_state(state, now=NOW)
            first, _ = store.enqueue(
                target,
                decision,
                request_id="window-1",
                dedupe_key="same-caller-key",
                expected_fingerprint=calculated.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5),
                now=NOW,
            )
            later = NOW + timedelta(hours=25)
            second, created = store.enqueue(
                target,
                decision,
                request_id="window-2",
                dedupe_key="same-caller-key",
                expected_fingerprint=calculated.quote_fingerprint or "",
                expires_at=later + timedelta(minutes=5),
                now=later,
            )
            self.assertFalse(created)
            self.assertEqual(first, second)

    def test_severity_flicker_with_same_verified_price_is_deduplicated(self) -> None:
        target = scenario()
        calculated = pricing_cost(target, 60_000)
        history = BaselineSnapshot(
            100_000,
            3,
            7,
            21,
            NOW - timedelta(days=1),
            True,
            "BASELINE_READY",
            event_time=NOW,
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
        ordinary = decide(target, calculated, history, verified_context(target))
        new_low_context = replace(verified_context(target), historical_new_low=True)
        escalated = decide(target, calculated, history, new_low_context)
        self.assertEqual((ordinary.primary_reason, escalated.primary_reason), ("S3", "S2"))
        state = CurrentState.verified_from(
            target, calculated, now=NOW, expires_at=NOW + timedelta(minutes=10)
        )
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "severity-flicker.sqlite3")
            store.set_current_state(state, now=NOW)
            first, _ = store.enqueue(
                target,
                ordinary,
                request_id="severity-s3",
                dedupe_key="caller-s3",
                expected_fingerprint=calculated.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5),
                now=NOW,
            )
            second, created = store.enqueue(
                target,
                escalated,
                request_id="severity-s2",
                dedupe_key="caller-s2",
                expected_fingerprint=calculated.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=5),
                now=NOW,
            )
            self.assertFalse(created)
            self.assertEqual(first, second)


class PropertyAndBindingTests(unittest.TestCase):
    def test_coupon_threshold_requires_separate_no_coupon_scenario(self) -> None:
        selected = scenario(coupon="coupon-60")
        terms = CouponTerms(
            "coupon-60",
            MoneyValue.known(6_000),
            50_000,
            True,
            True,
            claimed=True,
            remaining_uses=1,
            threshold_evidence_id="threshold-evidence",
            rule_version="test-coupon-v1",
        )
        selected_cost = pricing_cost(selected, 4_900, coupon=terms)
        without_coupon = scenario(coupon=None)
        no_coupon_cost = pricing_cost(without_coupon, 4_900)
        self.assertFalse(selected_cost.complete)
        self.assertIn("COUPON_THRESHOLD_NOT_MET", selected_cost.reason_codes)
        self.assertTrue(no_coupon_cost.complete)
        self.assertEqual(no_coupon_cost.total_minor, 4_900)
        self.assertNotEqual(selected.scope_key, without_coupon.scope_key)

    def test_property_raising_known_cost_does_not_create_a_new_free_shipping_alert(self) -> None:
        target = scenario()
        context = verified_context(target)
        for amount in range(901, 2_001, 37):
            with self.subTest(amount=amount):
                decision = decide(target, pricing_cost(target, amount), None, context)
                self.assertFalse(decision.notify)

    def test_property_price_string_or_rounding_cannot_turn_901_into_900(self) -> None:
        for raw in ("901", "9.01", 9.01, 900.999, True):
            with self.subTest(raw=raw):
                self.assertEqual(parse_minor(raw).state, ValueState.PARSE_ERROR)
        self.assertEqual(parse_minor(901).minor, 901)

    def test_property_irrelevant_target_does_not_change_verified_price(self) -> None:
        normal = scenario()
        with_target = replace(normal, target_total_minor=10_000)
        normal_cost = pricing_cost(normal, 5_000, 600)
        target_cost = pricing_cost(with_target, 5_000, 600)
        self.assertEqual(normal.scope_key, with_target.scope_key)
        self.assertEqual(normal_cost.total_minor, target_cost.total_minor)
        self.assertEqual(normal_cost.quote_fingerprint, target_cost.quote_fingerprint)

    def test_property_all_non_numeric_subtotals_suppress_s0(self) -> None:
        target = scenario()
        for state in (ValueState.UNKNOWN, ValueState.NOT_APPLICABLE, ValueState.CONFLICT, ValueState.PARSE_ERROR):
            with self.subTest(state=state):
                calculated = calculate_total(
                    target,
                    PricingInput(
                        MoneyValue.unavailable(state, evidence_id=f"evidence:{state}"),
                        MoneyValue.known(0),
                        (),
                        MoneyValue.known(0),
                        1,
                        True,
                        evaluated_at=NOW,
                        evidence_expires_at=NOW + timedelta(minutes=10),
                        quote_evidence_id="property-quote",
                    ),
                )
                decision = decide(target, calculated, None, verified_context(target))
                self.assertFalse(calculated.complete)
                self.assertFalse(decision.notify)
                self.assertNotEqual(decision.primary_reason, "S0")

    def test_baseline_rejects_stale_future_and_mixed_price_basis(self) -> None:
        target = scenario()
        calculated = pricing_cost(target, 5_000, 6_000)
        valid = BaselineSnapshot(
            100_000,
            3,
            7,
            21,
            NOW - timedelta(days=1),
            True,
            "BASELINE_READY",
            event_time=NOW,
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
        variants = (
            replace(valid, last_observed_at=NOW - timedelta(days=8)),
            replace(valid, event_time=NOW + timedelta(minutes=1), last_observed_at=NOW),
            replace(valid, price_basis="UNIT_PRICE"),
        )
        for history in variants:
            with self.subTest(reason=history.compatibility(target, NOW)[1]):
                decision = decide(target, calculated, history, verified_context(target))
                self.assertFalse(decision.notify)
                self.assertNotEqual(decision.primary_reason, "O2")


if __name__ == "__main__":
    unittest.main()
