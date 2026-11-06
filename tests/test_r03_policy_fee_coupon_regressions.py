from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cdh_core.models import EvidenceBasis, EventStatus, MoneyValue, OfferIdentity, PurchaseScenario
from cdh_core.persistence import (
    CurrentState,
    EventStore,
    MockSink,
    PolicyEpochConflict,
    StaleCurrentState,
)
from cdh_core.policy import PolicyContext, decide
from cdh_core.pricing import (
    CouponTerms,
    FeeComponent,
    IncludedFeeEvidence,
    PricingInput,
    calculate_total,
)


NOW = datetime(2026, 11, 1, 16, 0, tzinfo=timezone.utc)
TEST_TEMP_ROOT = Path(__file__).parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)
OFFER = OfferIdentity("SYNTHETIC", "r03-product", "r03-sku", "seller", "NEW", "piece", "LOCAL")


def scenario(
    *,
    target: int | None = None,
    membership: str = "WOW",
    profile: str = "profile-test",
    coupon: str | None = None,
) -> PurchaseScenario:
    return PurchaseScenario(
        OFFER,
        "ctx",
        1,
        membership,
        coupon_plan_id=coupon,
        target_total_minor=target,
        eligibility_profile_version=profile,
        price_basis="CURRENT_TOTAL",
        purchase_channel="WEB",
        payment_method="MOCK",
    )


def price(
    target: PurchaseScenario,
    subtotal: int,
    *,
    fees: tuple[FeeComponent, ...] = (),
    included_fees: frozenset[str] = frozenset(),
    fee_evidence: tuple[IncludedFeeEvidence, ...] = (),
    coupon: CouponTerms | None = None,
    when: datetime = NOW,
    evidence_id: str = "SYNTHETIC-QUOTE",
):
    return calculate_total(
        target,
        PricingInput(
            subtotal=MoneyValue.known(subtotal),
            shipping=MoneyValue.known(0),
            fees=fees,
            tax=MoneyValue.known(0),
            minimum_quantity=1,
            independently_purchasable=True,
            included_fee_ids=included_fees,
            included_fee_evidence=fee_evidence,
            coupon=coupon,
            quote_evidence_id=evidence_id,
            evaluated_at=when,
            evidence_expires_at=when + timedelta(hours=1),
        ),
    )


def policy(target: PurchaseScenario, when: datetime = NOW) -> PolicyContext:
    return PolicyContext.synthetic_verified(when, target, expires_at=when + timedelta(hours=1))


def notifying_bundle(target: PurchaseScenario, subtotal: int = 500):
    calculated = price(target, subtotal)
    decision = decide(target, calculated, None, policy(target))
    state = CurrentState.verified_from(
        target,
        calculated,
        now=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    return calculated, decision, state


def queue(store: EventStore, target: PurchaseScenario, *, request_id: str = "request-1") -> tuple[str, CurrentState]:
    calculated, decision, state = notifying_bundle(target)
    store.set_current_state(state, now=NOW)
    event_id, created = store.enqueue(
        target,
        decision,
        request_id=request_id,
        dedupe_key=request_id,
        expected_fingerprint=calculated.quote_fingerprint,
        expires_at=NOW + timedelta(minutes=20),
        now=NOW,
    )
    assert created
    return event_id, state


class IncludedFeeEvidenceTests(unittest.TestCase):
    def test_shipping_or_fee_increase_cannot_create_s0(self) -> None:
        target = scenario()
        calculated = calculate_total(
            target,
            PricingInput(
                subtotal=MoneyValue.known(0),
                shipping=MoneyValue.known(100),
                fees=(FeeComponent("mandatory", MoneyValue.known(200)),),
                tax=MoneyValue.known(0),
                minimum_quantity=1,
                independently_purchasable=True,
                quote_evidence_id="SYNTHETIC-QUOTE",
                evaluated_at=NOW,
                evidence_expires_at=NOW + timedelta(hours=1),
            ),
        )
        self.assertEqual(calculated.total_minor, 300)
        self.assertNotEqual(decide(target, calculated, None, policy(target)).primary_reason, "S0")

    def test_unverified_included_mandatory_fee_fails_closed(self) -> None:
        target = scenario()
        calculated = price(
            target,
            0,
            fees=(FeeComponent("mandatory", MoneyValue.known(6000)),),
            included_fees=frozenset({"mandatory"}),
        )
        self.assertFalse(calculated.complete)
        self.assertIn("INCLUDED_FEE_mandatory_EVIDENCE_INVALID", calculated.reason_codes)
        self.assertFalse(decide(target, calculated, None, policy(target)).notify)

    def test_verified_included_fee_is_not_double_added(self) -> None:
        target = scenario()
        evidence = IncludedFeeEvidence(
            "mandatory",
            target.scope_key,
            "SYNTHETIC-QUOTE",
            10_000,
            6000,
            "included-fee-proof",
            "included-fee-rule-v1",
            NOW,
            NOW + timedelta(hours=1),
            EvidenceBasis.OBSERVED,
            "d" * 64,
        )
        calculated = price(
            target,
            10_000,
            fees=(FeeComponent("mandatory", MoneyValue.known(6000)),),
            included_fees=frozenset({"mandatory"}),
            fee_evidence=(evidence,),
        )
        self.assertTrue(calculated.complete)
        self.assertEqual(calculated.total_minor, 10_000)

    def test_included_fee_evidence_is_quote_and_scenario_bound(self) -> None:
        target = scenario()
        evidence = IncludedFeeEvidence(
            "mandatory",
            target.scope_key,
            "OTHER-QUOTE",
            6000,
            6000,
            "included-fee-proof",
            "included-fee-rule-v1",
            NOW,
            NOW + timedelta(hours=1),
            EvidenceBasis.OBSERVED,
            "e" * 64,
        )
        calculated = price(
            target,
            6000,
            fees=(FeeComponent("mandatory", MoneyValue.known(6000)),),
            included_fees=frozenset({"mandatory"}),
            fee_evidence=(evidence,),
        )
        self.assertFalse(calculated.complete)


class CouponSemanticsTests(unittest.TestCase):
    def test_unknown_expiry_scope_and_threshold_fail_closed(self) -> None:
        target = scenario(coupon="unknown")
        terms = CouponTerms(
            "unknown",
            MoneyValue.known(500),
            None,
            True,
            True,
            claimed=True,
            remaining_uses=1,
            rule_version="coupon-rule-v1",
        )
        calculated = price(target, 500, coupon=terms)
        self.assertFalse(calculated.complete)
        self.assertIn("COUPON_EXPIRY_POLICY_UNKNOWN_OR_INCOHERENT", calculated.reason_codes)

    def test_evidenced_permanent_all_items_no_threshold_coupon_is_valid(self) -> None:
        target = scenario(coupon="permanent")
        terms = CouponTerms(
            "permanent",
            MoneyValue.known(500),
            None,
            True,
            True,
            claimed=True,
            remaining_uses=1,
            rule_version="coupon-rule-v1",
            expiry_policy="PERPETUAL",
            offer_scope_policy="ALL",
            seller_scope_policy="ALL",
            threshold_policy="NONE",
            terms_evidence_id="coupon-terms-permanent",
            terms_context_id=target.context_id,
            terms_membership_context=target.membership_context,
            terms_eligibility_profile_version=target.eligibility_profile_version,
            terms_evidence_basis=EvidenceBasis.OBSERVED,
            terms_source_record_sha256="f" * 64,
        )
        calculated = price(target, 500, coupon=terms)
        self.assertTrue(calculated.complete)
        self.assertEqual(calculated.total_minor, 0)

    def test_evidenced_fixed_scoped_threshold_coupon_is_valid(self) -> None:
        target = scenario(coupon="scoped")
        terms = CouponTerms(
            "scoped",
            MoneyValue.known(100),
            500,
            True,
            True,
            expires_at=NOW + timedelta(hours=2),
            applicable_offer_keys=frozenset({target.offer.key}),
            applicable_seller_ids=frozenset({target.offer.seller_id}),
            claimed=True,
            remaining_uses=1,
            threshold_evidence_id="coupon-threshold-proof",
            rule_version="coupon-rule-v1",
            expiry_policy="FIXED",
            offer_scope_policy="LISTED",
            seller_scope_policy="LISTED",
            threshold_policy="FIXED",
            terms_evidence_id="coupon-terms-scoped",
            terms_context_id=target.context_id,
            terms_membership_context=target.membership_context,
            terms_eligibility_profile_version=target.eligibility_profile_version,
            terms_evidence_basis=EvidenceBasis.OBSERVED,
            terms_source_record_sha256="1" * 64,
        )
        calculated = price(target, 1000, coupon=terms)
        self.assertTrue(calculated.complete)
        self.assertEqual(calculated.total_minor, 900)


class NotificationPolicyEpochTests(unittest.TestCase):
    def test_policy_revocation_during_mock_delivery_never_finishes_delivered(self) -> None:
        target = scenario()
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "during-delivery.sqlite3")
            event_id, _ = queue(store, target, request_id="during-delivery")

            class RevokingSink:
                def deliver(self, payload: dict[str, object]) -> None:
                    store.update_user_policy(
                        target,
                        notifications_enabled=False,
                        source_allowed=True,
                        membership_context=target.membership_context,
                        eligibility_profile_version=target.eligibility_profile_version,
                        revision_id="revoked-during-mock-callback",
                        now=NOW + timedelta(seconds=1),
                        expected_epoch=1,
                    )

            result = store.deliver(event_id, RevokingSink(), now=NOW)
            self.assertEqual(result, EventStatus.SUPERSEDED)
            self.assertNotEqual(result, EventStatus.DELIVERED)

    def test_target_change_revokes_old_event_without_price_observation(self) -> None:
        old = scenario(target=500)
        new = scenario(target=100)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "target.sqlite3")
            event_id, state = queue(store, old, request_id="target-old")
            epoch = store.update_scenario_policy(
                new,
                target_total_minor=100,
                enabled=True,
                revision_id="target-tightened",
                now=NOW + timedelta(minutes=1),
                expected_epoch=1,
            )
            self.assertEqual(epoch, 2)
            self.assertEqual(store.event_status(event_id), EventStatus.SUPERSEDED)
            self.assertFalse(store.set_current_state(state, now=NOW + timedelta(minutes=1)))

    def test_membership_change_revokes_old_wow_event_across_scenarios(self) -> None:
        old = scenario()
        new = scenario(membership="NOT_WOW", profile="profile-v2")
        self.assertNotEqual(old.scope_key, new.scope_key)
        self.assertEqual(old.user_policy_scope_key, new.user_policy_scope_key)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "membership.sqlite3")
            event_id, _ = queue(store, old, request_id="wow-old")
            epoch = store.update_user_policy(
                new,
                notifications_enabled=True,
                source_allowed=True,
                membership_context=new.membership_context,
                eligibility_profile_version=new.eligibility_profile_version,
                revision_id="membership-revoked",
                now=NOW + timedelta(minutes=1),
                expected_epoch=1,
            )
            self.assertEqual(epoch, 2)
            self.assertEqual(store.event_status(event_id), EventStatus.SUPERSEDED)

    def test_notification_disable_is_independent_of_product_clock(self) -> None:
        target = scenario()
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "disable.sqlite3")
            event_id, state = queue(store, target, request_id="disable-old")
            store.update_user_policy(
                target,
                notifications_enabled=False,
                source_allowed=True,
                membership_context=target.membership_context,
                eligibility_profile_version=target.eligibility_profile_version,
                revision_id="notifications-disabled",
                now=NOW + timedelta(minutes=1),
                expected_epoch=1,
            )
            self.assertEqual(store.event_status(event_id), EventStatus.SUPERSEDED)
            self.assertEqual(store.deliver(event_id, MockSink(), now=NOW + timedelta(minutes=1)), EventStatus.SUPERSEDED)
            self.assertFalse(store.set_current_state(state, now=NOW + timedelta(minutes=1)))
            with self.assertRaises(StaleCurrentState):
                store.set_current_state(replace(state, observed_at=NOW - timedelta(seconds=1)), now=NOW)

    def test_source_permission_revoke_invalidates_old_event(self) -> None:
        target = scenario()
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "source.sqlite3")
            event_id, _ = queue(store, target, request_id="source-old")
            store.update_user_policy(
                target,
                notifications_enabled=True,
                source_allowed=False,
                membership_context=target.membership_context,
                eligibility_profile_version=target.eligibility_profile_version,
                revision_id="source-permission-revoked",
                now=NOW + timedelta(minutes=1),
                expected_epoch=1,
            )
            self.assertEqual(store.event_status(event_id), EventStatus.SUPERSEDED)

    def test_disable_reenable_allows_new_event_in_new_epoch(self) -> None:
        target = scenario()
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "reenable.sqlite3")
            old_event, _ = queue(store, target, request_id="before-disable")
            store.update_user_policy(
                target,
                notifications_enabled=False,
                source_allowed=True,
                membership_context=target.membership_context,
                eligibility_profile_version=target.eligibility_profile_version,
                revision_id="disabled",
                now=NOW + timedelta(minutes=1),
                expected_epoch=1,
            )
            epoch = store.update_user_policy(
                target,
                notifications_enabled=True,
                source_allowed=True,
                membership_context=target.membership_context,
                eligibility_profile_version=target.eligibility_profile_version,
                revision_id="reenabled",
                now=NOW + timedelta(minutes=2),
                expected_epoch=2,
            )
            self.assertEqual(epoch, 3)
            calculated, decision, _ = notifying_bundle(target)
            new_event, created = store.enqueue(
                target,
                decision,
                request_id="after-reenable",
                dedupe_key="after-reenable",
                expected_fingerprint=calculated.quote_fingerprint,
                expires_at=NOW + timedelta(minutes=20),
                now=NOW + timedelta(minutes=2),
            )
            self.assertTrue(created)
            self.assertNotEqual(old_event, new_event)
            self.assertEqual(store.deliver(new_event, MockSink(), now=NOW + timedelta(minutes=2)), EventStatus.DELIVERED)

    def test_policy_epoch_and_revocation_survive_database_restart(self) -> None:
        target = scenario()
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            database = Path(directory) / "restart.sqlite3"
            store = EventStore(database)
            event_id, _ = queue(store, target, request_id="restart-old")
            store.update_user_policy(
                target,
                notifications_enabled=False,
                source_allowed=True,
                membership_context=target.membership_context,
                eligibility_profile_version=target.eligibility_profile_version,
                revision_id="persist-disabled",
                now=NOW + timedelta(minutes=1),
                expected_epoch=1,
            )
            reopened = EventStore(database)
            self.assertEqual(reopened.policy_snapshot(target)["user"]["epoch"], 2)
            self.assertEqual(reopened.event_status(event_id), EventStatus.SUPERSEDED)

    def test_policy_compare_and_swap_rejects_stale_writer(self) -> None:
        target = scenario()
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "cas.sqlite3")
            queue(store, target, request_id="cas-old")
            store.update_user_policy(
                target,
                notifications_enabled=False,
                source_allowed=True,
                membership_context=target.membership_context,
                eligibility_profile_version=target.eligibility_profile_version,
                revision_id="writer-one",
                now=NOW + timedelta(minutes=1),
                expected_epoch=1,
            )
            with self.assertRaises(PolicyEpochConflict):
                store.update_user_policy(
                    target,
                    notifications_enabled=True,
                    source_allowed=True,
                    membership_context=target.membership_context,
                    eligibility_profile_version=target.eligibility_profile_version,
                    revision_id="stale-writer",
                    now=NOW + timedelta(minutes=2),
                    expected_epoch=1,
                )

    def test_schema_v3_is_archived_and_v5_starts_without_old_events(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            database = Path(directory) / "v3.sqlite3"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
                connection.execute("INSERT INTO schema_version VALUES (3, 'before')")
                connection.execute("CREATE TABLE current_state(legacy_value TEXT)")
                connection.execute("INSERT INTO current_state VALUES ('legacy-state')")
                connection.execute("CREATE TABLE deal_events(legacy_value TEXT)")
                connection.execute("INSERT INTO deal_events VALUES ('legacy-event')")
                connection.execute("CREATE TABLE notification_outbox(legacy_value TEXT)")
                connection.execute("INSERT INTO notification_outbox VALUES ('legacy-outbox')")
                connection.commit()
            store = EventStore(database)
            self.assertEqual(store.schema_version(), 5)
            self.assertEqual(
                store.archived_v3_tables(),
                ("current_state_v3_archive", "deal_events_v3_archive", "notification_outbox_v3_archive"),
            )
            self.assertEqual(store.counts(), {"events": 0, "outbox": 0})


if __name__ == "__main__":
    unittest.main(verbosity=2)
