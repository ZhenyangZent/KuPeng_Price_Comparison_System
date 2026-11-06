from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cdh_core.models import (
    EvidenceBasis,
    EventStatus,
    MoneyValue,
    OfferIdentity,
    PurchaseScenario,
    ValueState,
)
from cdh_core.persistence import CurrentState, DecisionBindingError, EventStore, MockSink
from cdh_core.policy import PolicyContext, decide, verify_decision_approval
from cdh_core.pricing import (
    CostComponentEvidence,
    CouponTerms,
    FeeComponent,
    PricingInput,
    calculate_total,
)


NOW = datetime(2026, 11, 1, 16, 0, tzinfo=timezone.utc)
TEST_TEMP_ROOT = Path(__file__).parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)
OFFER = OfferIdentity("SYNTHETIC", "r04-product", "r04-sku", "seller", "NEW", "piece", "LOCAL")


def scenario(*, coupon: str | None = None, price_basis: str = "CURRENT_TOTAL") -> PurchaseScenario:
    return PurchaseScenario(
        OFFER,
        "ctx-r04",
        1,
        "WOW",
        coupon_plan_id=coupon,
        eligibility_profile_version="r04-profile-v1",
        price_basis=price_basis,
        purchase_channel="WEB",
        payment_method="MOCK",
    )


def coupon_terms(target: PurchaseScenario, *, expires_at: datetime) -> CouponTerms:
    return CouponTerms(
        "coupon-r04",
        MoneyValue.known(500),
        0,
        True,
        True,
        expires_at=expires_at,
        applicable_offer_keys=frozenset({target.offer.key}),
        applicable_seller_ids=frozenset({target.offer.seller_id}),
        claimed=True,
        remaining_uses=1,
        threshold_evidence_id="threshold-r04",
        rule_version="coupon-r04-v1",
        expiry_policy="FIXED",
        offer_scope_policy="LISTED",
        seller_scope_policy="LISTED",
        threshold_policy="FIXED",
        terms_evidence_id="coupon-proof-r04",
        terms_context_id=target.context_id,
        terms_membership_context=target.membership_context,
        terms_eligibility_profile_version=target.eligibility_profile_version,
        terms_evidence_basis=EvidenceBasis.OBSERVED,
        terms_source_record_sha256="c" * 64,
    )


def pricing(
    *,
    subtotal: int = 0,
    fees: tuple[FeeComponent, ...] = (),
    tax: MoneyValue = MoneyValue.known(0),
    coupon: CouponTerms | None = None,
    component_evidence: tuple[CostComponentEvidence, ...] = (),
) -> PricingInput:
    return PricingInput(
        subtotal=MoneyValue.known(subtotal),
        shipping=MoneyValue.known(0),
        fees=fees,
        tax=tax,
        minimum_quantity=1,
        independently_purchasable=True,
        coupon=coupon,
        component_evidence=component_evidence,
        evaluated_at=NOW,
        evidence_expires_at=NOW + timedelta(hours=1),
        quote_evidence_id="quote-r04",
    )


def policy(target: PurchaseScenario) -> PolicyContext:
    return PolicyContext.synthetic_verified(NOW, target, expires_at=NOW + timedelta(hours=1))


def component_proof(
    target: PurchaseScenario,
    *,
    kind: str,
    component_id: str,
    disposition: str,
    subtotal: int,
    component_minor: int,
    expires_at: datetime = NOW + timedelta(minutes=30),
) -> CostComponentEvidence:
    return CostComponentEvidence(
        kind,
        component_id,
        disposition,
        target.scope_key,
        "quote-r04",
        subtotal,
        component_minor,
        f"{kind.lower()}-{component_id}-proof",
        "component-r04-v1",
        NOW - timedelta(minutes=1),
        expires_at,
        EvidenceBasis.OBSERVED,
        "d" * 64,
    )


class ExpiryPropagationTests(unittest.TestCase):
    def bundle(self):
        target = scenario(coupon="coupon-r04")
        coupon_expiry = NOW + timedelta(minutes=1)
        cost = calculate_total(target, pricing(subtotal=500, coupon=coupon_terms(target, expires_at=coupon_expiry)))
        decision = decide(target, cost, None, policy(target))
        return target, coupon_expiry, cost, decision

    def test_coupon_expiry_is_quote_and_decision_deadline(self) -> None:
        _, coupon_expiry, cost, decision = self.bundle()
        self.assertEqual(cost.evidence_expires_at, coupon_expiry)
        self.assertEqual(decision.valid_until, coupon_expiry)

    def test_current_state_requested_lifetime_is_clamped(self) -> None:
        target, coupon_expiry, cost, _ = self.bundle()
        state = CurrentState.verified_from(target, cost, now=NOW, expires_at=NOW + timedelta(minutes=30))
        self.assertEqual(state.expires_at, coupon_expiry)

    def test_event_deadline_survives_restart_and_exact_expiry_blocks_delivery(self) -> None:
        target, coupon_expiry, cost, decision = self.bundle()
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            database = Path(directory) / "coupon-expiry.sqlite3"
            store = EventStore(database)
            state = CurrentState.verified_from(target, cost, now=NOW, expires_at=NOW + timedelta(minutes=30))
            store.set_current_state(state, now=NOW)
            event_id, created = store.enqueue(
                target,
                decision,
                request_id="expiry-r04",
                dedupe_key="expiry-r04",
                expected_fingerprint=cost.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=20),
                now=NOW,
            )
            self.assertTrue(created)
            with closing(sqlite3.connect(database)) as connection:
                stored_expiry = datetime.fromisoformat(
                    connection.execute("SELECT expires_at FROM deal_events WHERE event_id=?", (event_id,)).fetchone()[0]
                )
            self.assertEqual(stored_expiry, coupon_expiry)
            reopened = EventStore(database)
            sink = MockSink()
            self.assertEqual(reopened.deliver(event_id, sink, now=coupon_expiry), EventStatus.EXPIRED)
            self.assertEqual(sink.deliveries, [])

    def test_valid_coupon_before_expiry_still_delivers(self) -> None:
        target, _, cost, decision = self.bundle()
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "valid-coupon.sqlite3")
            store.set_current_state(
                CurrentState.verified_from(target, cost, now=NOW, expires_at=NOW + timedelta(minutes=30)),
                now=NOW,
            )
            event_id, _ = store.enqueue(
                target,
                decision,
                request_id="valid-r04",
                dedupe_key="valid-r04",
                expected_fingerprint=cost.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=20),
                now=NOW,
            )
            sink = MockSink()
            self.assertEqual(store.deliver(event_id, sink, now=NOW + timedelta(seconds=59)), EventStatus.DELIVERED)
            self.assertEqual(len(sink.deliveries), 1)


class ZeroCostProvenanceTests(unittest.TestCase):
    def test_model_level_permission_flag_cannot_turn_string_evidence_into_zero(self) -> None:
        value = MoneyValue.unavailable(ValueState.NOT_APPLICABLE, evidence_id="some-string")
        self.assertFalse(value.is_usable)
        with self.assertRaises(ValueError):
            value.resolved_minor(allow_not_applicable=True)

    def test_typed_not_applicable_fee_proof_is_valid(self) -> None:
        target = scenario()
        proof = component_proof(
            target,
            kind="FEE",
            component_id="service",
            disposition="NOT_APPLICABLE",
            subtotal=0,
            component_minor=0,
        )
        cost = calculate_total(
            target,
            pricing(
                fees=(FeeComponent("service", MoneyValue.unavailable(ValueState.NOT_APPLICABLE)),),
                component_evidence=(proof,),
            ),
        )
        self.assertTrue(cost.complete)
        self.assertEqual(cost.total_minor, 0)

    def test_typed_tax_included_proof_avoids_double_counting(self) -> None:
        target = scenario()
        proof = component_proof(
            target,
            kind="TAX",
            component_id="tax",
            disposition="INCLUDED_IN_SUBTOTAL",
            subtotal=10_000,
            component_minor=500,
        )
        cost = calculate_total(
            target,
            pricing(
                subtotal=10_000,
                tax=MoneyValue.unavailable(ValueState.NOT_APPLICABLE),
                component_evidence=(proof,),
            ),
        )
        self.assertTrue(cost.complete)
        self.assertEqual(cost.total_minor, 10_000)

    def test_cross_scenario_component_proof_fails_closed(self) -> None:
        target = scenario()
        other = PurchaseScenario(
            OfferIdentity("SYNTHETIC", "other", "sku", "seller", "NEW", "piece", "LOCAL"),
            "ctx-r04",
            1,
            "WOW",
            eligibility_profile_version="r04-profile-v1",
            purchase_channel="WEB",
            payment_method="MOCK",
        )
        proof = component_proof(
            other,
            kind="FEE",
            component_id="service",
            disposition="NOT_APPLICABLE",
            subtotal=0,
            component_minor=0,
        )
        cost = calculate_total(
            target,
            pricing(
                fees=(FeeComponent("service", MoneyValue.unavailable(ValueState.NOT_APPLICABLE)),),
                component_evidence=(proof,),
            ),
        )
        self.assertFalse(cost.complete)

    def test_expired_component_proof_fails_closed(self) -> None:
        target = scenario()
        proof = component_proof(
            target,
            kind="TAX",
            component_id="tax",
            disposition="NOT_APPLICABLE",
            subtotal=0,
            component_minor=0,
            expires_at=NOW,
        )
        cost = calculate_total(
            target,
            pricing(tax=MoneyValue.unavailable(ValueState.NOT_APPLICABLE), component_evidence=(proof,)),
        )
        self.assertFalse(cost.complete)


class PriceBasisAndDecisionAuthorityTests(unittest.TestCase):
    def test_non_purchase_price_types_are_all_suppressed(self) -> None:
        for basis in (
            "MONTHLY_INSTALLMENT",
            "CASHBACK_NET",
            "POINTS_NET",
            "SUBSCRIPTION_FIRST_PAYMENT",
            "MINIMUM_FROM_PRICE",
        ):
            with self.subTest(basis=basis):
                target = scenario(price_basis=basis)
                cost = calculate_total(target, pricing())
                self.assertFalse(cost.complete)
                self.assertFalse(decide(target, cost, None, policy(target)).notify)

    def test_genuine_policy_decision_has_verifiable_approval(self) -> None:
        target = scenario()
        cost = calculate_total(target, pricing())
        decision = decide(target, cost, None, policy(target))
        self.assertTrue(decision.notify)
        self.assertTrue(verify_decision_approval(decision))

    def test_forged_decision_with_recomputed_public_hash_is_rejected(self) -> None:
        target = scenario()
        cost = calculate_total(target, pricing(subtotal=5000))
        rejected = decide(target, cost, None, replace(policy(target), stock="OUT_OF_STOCK"))
        forged = replace(rejected, notify=True, primary_reason="S1", total_minor=cost.total_minor)
        forged = replace(forged, decision_fingerprint=forged.computed_fingerprint)
        self.assertFalse(verify_decision_approval(forged))
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            store = EventStore(Path(directory) / "forged.sqlite3")
            store.set_current_state(
                CurrentState.verified_from(target, cost, now=NOW, expires_at=NOW + timedelta(minutes=30)),
                now=NOW,
            )
            with self.assertRaises(DecisionBindingError):
                store.enqueue(
                    target,
                    forged,
                    request_id="forged",
                    dedupe_key="forged",
                    expected_fingerprint=cost.quote_fingerprint or "",
                    expires_at=NOW + timedelta(minutes=20),
                    now=NOW,
                )

    def test_policy_evidence_tamper_is_rejected(self) -> None:
        target = scenario()
        decision = decide(target, calculate_total(target, pricing()), None, policy(target))
        tampered = replace(decision, policy_evidence_json=(decision.policy_evidence_json or "") + " ")
        self.assertFalse(verify_decision_approval(tampered))

    def test_full_policy_evidence_is_persisted_with_event(self) -> None:
        target = scenario()
        cost = calculate_total(target, pricing())
        decision = decide(target, cost, None, policy(target))
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            database = Path(directory) / "evidence.sqlite3"
            store = EventStore(database)
            store.set_current_state(
                CurrentState.verified_from(target, cost, now=NOW, expires_at=NOW + timedelta(minutes=30)),
                now=NOW,
            )
            event_id, _ = store.enqueue(
                target,
                decision,
                request_id="evidence",
                dedupe_key="evidence",
                expected_fingerprint=cost.quote_fingerprint or "",
                expires_at=NOW + timedelta(minutes=20),
                now=NOW,
            )
            with closing(sqlite3.connect(database)) as connection:
                stored = connection.execute(
                    "SELECT policy_evidence_json, policy_evidence_fingerprint, approval_seal FROM deal_events WHERE event_id=?",
                    (event_id,),
                ).fetchone()
            self.assertEqual(stored, (decision.policy_evidence_json, decision.policy_evidence_fingerprint, decision.approval_seal))

    def test_schema_v4_is_archived_and_legacy_event_is_not_activated(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            database = Path(directory) / "v4.sqlite3"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
                connection.execute("INSERT INTO schema_version VALUES (4, 'before')")
                connection.execute("CREATE TABLE deal_events(legacy_value TEXT)")
                connection.execute("INSERT INTO deal_events VALUES ('legacy-event')")
                connection.execute("CREATE TABLE notification_outbox(legacy_value TEXT)")
                connection.execute("INSERT INTO notification_outbox VALUES ('legacy-outbox')")
                connection.commit()
            store = EventStore(database)
            self.assertEqual(store.schema_version(), 5)
            self.assertEqual(store.archived_v4_tables(), ("deal_events_v4_archive", "notification_outbox_v4_archive"))
            self.assertEqual(store.counts(), {"events": 0, "outbox": 0})


if __name__ == "__main__":
    unittest.main(verbosity=2)
