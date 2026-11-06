from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cdh_core.demo import run_demo
from cdh_core.models import Decision, EventStatus, MoneyValue, Observation, OfferIdentity, PurchaseScenario
from cdh_core.persistence import CurrentState, EventStore, MockSink
from cdh_core.policy import PolicyContext, decide
from cdh_core.pricing import PricingInput, calculate_total


NOW = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)
TEST_TEMP_ROOT = Path(__file__).parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)


def make_scenario() -> PurchaseScenario:
    offer = OfferIdentity("TEST", "p", "sku", "seller", "NEW", "1x", "TEST")
    return PurchaseScenario(
        offer,
        "ctx",
        1,
        "WOW_USER_DECLARED",
        eligibility_profile_version="test-profile-v1",
        purchase_channel="WEB",
        payment_method="TEST_CARD",
    )


def make_cost(scenario: PurchaseScenario, total: int = 500):
    return calculate_total(
        scenario,
        PricingInput(
            MoneyValue.known(total),
            MoneyValue.known(0),
            (),
            MoneyValue.known(0),
            1,
            True,
            evaluated_at=NOW,
            evidence_expires_at=NOW + timedelta(minutes=10),
            quote_evidence_id="test-quote",
        ),
    )


def make_decision(scenario: PurchaseScenario, total: int = 500) -> Decision:
    calculated = make_cost(scenario, total)
    context = PolicyContext.synthetic_verified(NOW, scenario, expires_at=NOW + timedelta(minutes=10))
    return decide(scenario, calculated, None, context)


def current(scenario: PurchaseScenario, calculated=None, **changes: object) -> CurrentState:
    state = CurrentState.verified_from(
        scenario,
        calculated or make_cost(scenario),
        now=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    return replace(state, **changes)


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.db = Path(self.temp.name) / "test.sqlite3"
        self.store = EventStore(self.db)
        self.scenario = make_scenario()
        self.cost = make_cost(self.scenario)
        self.decision = make_decision(self.scenario)
        self.store.set_current_state(current(self.scenario, self.cost), now=NOW)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def enqueue(self, *, request: str = "req-1", dedupe: str = "dedupe-1", failure: bool = False) -> tuple[str, bool]:
        return self.store.enqueue(
            self.scenario,
            self.decision,
            request_id=request,
            dedupe_key=dedupe,
            expected_fingerprint=self.cost.quote_fingerprint or "",
            expires_at=NOW + timedelta(minutes=5),
            now=NOW,
            inject_failure=failure,
        )

    def test_schema_migration_version(self) -> None:
        self.assertEqual(self.store.schema_version(), 5)

    def test_event_and_outbox_commit_atomically(self) -> None:
        self.enqueue()
        self.assertEqual(self.store.counts(), {"events": 1, "outbox": 1})

    def test_raw_observations_and_daily_stats_are_separate(self) -> None:
        observation = Observation(
            self.scenario.offer.key,
            self.scenario.context_id,
            1,
            self.scenario.price_basis,
            500,
            NOW,
            source_published_at=NOW - timedelta(seconds=3),
            received_at=NOW + timedelta(seconds=1),
            membership_context=self.scenario.membership_context,
            eligibility_profile_version=self.scenario.eligibility_profile_version,
            coupon_plan_id=self.scenario.coupon_plan_id,
            purchase_channel=self.scenario.purchase_channel,
            payment_method=self.scenario.payment_method,
        )
        self.assertTrue(self.store.record_observation("obs-1", observation))
        self.assertFalse(self.store.record_observation("obs-1", observation))
        self.store.upsert_daily_stat(
            series_key=observation.series_key,
            local_day="2026-11-01",
            median_unit_minor=500,
            sample_count=1,
        )
        self.assertEqual(self.store.history_counts(), {"raw_observations": 1, "daily_stats": 1})

    def test_injected_transaction_failure_rolls_back_both(self) -> None:
        with self.assertRaises(sqlite3.OperationalError):
            self.enqueue(failure=True)
        self.assertEqual(self.store.counts(), {"events": 0, "outbox": 0})

    def test_repeated_request_is_idempotent(self) -> None:
        first, created1 = self.enqueue()
        second, created2 = self.enqueue()
        self.assertEqual(first, second)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(self.store.counts(), {"events": 1, "outbox": 1})

    def test_restart_preserves_deduplication(self) -> None:
        first, _ = self.enqueue()
        restarted = EventStore(self.db)
        second, created = restarted.enqueue(
            self.scenario,
            self.decision,
            request_id="req-1",
            dedupe_key="dedupe-other",
            expected_fingerprint=self.cost.quote_fingerprint or "",
            expires_at=NOW + timedelta(minutes=5),
            now=NOW,
        )
        self.assertEqual(first, second)
        self.assertFalse(created)

    def test_concurrent_enqueue_creates_one_event(self) -> None:
        def submit(_: int) -> tuple[str, bool]:
            return self.enqueue()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            rows = list(executor.map(submit, range(20)))
        self.assertEqual(sum(created for _, created in rows), 1)
        self.assertEqual(len({event for event, _ in rows}), 1)
        self.assertEqual(self.store.counts(), {"events": 1, "outbox": 1})

    def test_mock_delivery_marks_delivered(self) -> None:
        event, _ = self.enqueue()
        sink = MockSink()
        self.assertEqual(self.store.deliver(event, sink, now=NOW + timedelta(minutes=1)), EventStatus.DELIVERED)
        self.assertEqual(len(sink.deliveries), 1)

    def test_expired_event_not_delivered(self) -> None:
        event, _ = self.enqueue()
        sink = MockSink()
        self.assertEqual(self.store.deliver(event, sink, now=NOW + timedelta(minutes=6)), EventStatus.EXPIRED)
        self.assertEqual(sink.deliveries, [])

    def test_price_raise_supersedes_queued_event(self) -> None:
        event, _ = self.enqueue()
        changed_at = NOW + timedelta(seconds=1)
        self.store.set_current_state(
            current(
                self.scenario,
                self.cost,
                quote_fingerprint="fp-v2",
                semantic_fingerprint="semantic-v2",
                total_minor=1500,
                observed_at=changed_at,
                received_at=changed_at,
            ),
            now=changed_at,
        )
        self.assertEqual(self.store.deliver(event, MockSink(), now=NOW + timedelta(minutes=1)), EventStatus.SUPERSEDED)

    def test_stock_membership_source_and_notification_changes_supersede(self) -> None:
        changes = (
            {"stock": "OUT_OF_STOCK"},
            {"membership_context": "NON_WOW"},
            {"source_enabled": False},
            {"notifications_enabled": False},
            {"eligibility_state": "UNKNOWN"},
        )
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                db = Path(self.temp.name) / f"change-{index}.sqlite3"
                store = EventStore(db)
                store.set_current_state(current(self.scenario, self.cost), now=NOW)
                event, _ = store.enqueue(
                    self.scenario,
                    self.decision,
                    request_id=f"r-{index}",
                    dedupe_key=f"d-{index}",
                    expected_fingerprint=self.cost.quote_fingerprint or "",
                    expires_at=NOW + timedelta(minutes=5),
                    now=NOW,
                )
                changed_at = NOW + timedelta(seconds=1)
                store.set_current_state(
                    current(
                        self.scenario,
                        self.cost,
                        observed_at=changed_at,
                        received_at=changed_at,
                        **change,
                    ),
                    now=changed_at,
                )
                self.assertEqual(store.deliver(event, MockSink(), now=NOW + timedelta(minutes=1)), EventStatus.SUPERSEDED)

    def test_ambiguous_and_failed_delivery_are_distinct(self) -> None:
        event1, _ = self.enqueue(request="r-a", dedupe="d-a")
        self.assertEqual(self.store.deliver(event1, MockSink("ambiguous"), now=NOW), EventStatus.DELIVERY_UNKNOWN)
        changed_at = NOW + timedelta(seconds=1)
        self.store.set_current_state(
            current(
                self.scenario,
                self.cost,
                availability_version="availability-v2",
                observed_at=changed_at,
                received_at=changed_at,
            ),
            now=changed_at,
        )
        event2, _ = self.store.enqueue(
            self.scenario,
            self.decision,
            request_id="r-b",
            dedupe_key="d-b",
            expected_fingerprint=self.cost.quote_fingerprint or "",
            expires_at=NOW + timedelta(minutes=5),
            now=changed_at,
        )
        self.assertEqual(self.store.deliver(event2, MockSink("fail"), now=changed_at), EventStatus.FAILED)


class DemoAndBoundaryTests(unittest.TestCase):
    def test_demo_covers_required_scenarios_and_revocation(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "demo_cases.json"
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            result = run_demo(fixture, Path(directory) / "demo.sqlite3")
        self.assertTrue(result["all_expected_reasons_match"])
        rows = {row["id"]: row for row in result["results"]}
        self.assertEqual(rows["queued-price-revoked"]["delivery_status"], EventStatus.SUPERSEDED)
        self.assertEqual(rows["target-800-only-20pct"]["decision_reason"], "TARGET_REACHED")

    def test_source_has_no_network_or_real_notification_imports(self) -> None:
        source_root = Path(__file__).parents[1] / "src" / "cdh_core"
        forbidden = ("import socket", "import requests", "import urllib", "playwright", "selenium", "telegram", "discord")
        combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in source_root.glob("*.py"))
        for marker in forbidden:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, combined)

    def test_fake_zero_counterexample_fixtures_fail_closed(self) -> None:
        from cdh_core.models import MoneyValue, ValueState
        from cdh_core.policy import decide
        from cdh_core.pricing import CouponTerms, PricingInput, calculate_total

        fixture = Path(__file__).parent / "fixtures" / "fake_zero_counterexamples.json"
        cases = json.loads(fixture.read_text(encoding="utf-8"))["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                unavailable = ValueState(case["unknown_state"])
                shipping = MoneyValue.unavailable(unavailable) if case["unknown_field"] == "shipping" else MoneyValue.known(0)
                tax = MoneyValue.unavailable(unavailable) if case["unknown_field"] == "tax" else MoneyValue.known(0)
                coupon = None
                if case["unknown_field"] == "coupon_cap":
                    coupon = CouponTerms("oversized", MoneyValue.known(2000), 0, True, True, False)
                pricing = PricingInput(
                    MoneyValue.known(case["subtotal_minor"]), shipping, (), tax, 1, True, coupon=coupon
                )
                scenario = make_scenario()
                calculated = calculate_total(scenario, pricing)
                decision = decide(scenario, calculated, None)
                self.assertFalse(calculated.complete)
                self.assertFalse(decision.notify)
                self.assertNotEqual(decision.primary_reason, "S0")


if __name__ == "__main__":
    unittest.main()

