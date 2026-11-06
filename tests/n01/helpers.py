from __future__ import annotations

import shutil
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path

from cdh_core.models import CostResult, OfferIdentity, PurchaseScenario
from cdh_core.policy import PolicyContext, decide

from n01_alerts.contracts import candidate_from_c01
from n01_alerts.models import LatestState, NotificationCandidate, digest


NOW = datetime(2026, 11, 4, 8, 0, tzinfo=timezone.utc)


def workspace() -> Path:
    root = Path("experiments/N01/tests") / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return root


def cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def candidate(**changes) -> NotificationCandidate:
    base = NotificationCandidate(
        request_id="req-1",
        scenario_scope="scenario-1",
        user_policy_scope="user-policy-1",
        offer_key="offer-1",
        sku_id="sku-1",
        quantity=1,
        minimum_quantity=1,
        membership_context="WOW",
        eligibility_profile_version="profile-1",
        policy_epoch=1,
        source_revision=1,
        source_kind="SYNTHETIC",
        source_status="SOURCE_BLOCKED",
        observed_at=NOW,
        expires_at=NOW + timedelta(days=3),
        decision_fingerprint="decision-1",
        policy_evidence_fingerprint="policy-evidence-1",
        decision_reason="S1",
        decision_labels=("FREE_SHIPPING",),
        decision_notify=True,
        total_minor=500,
        subtotal_minor=500,
        shipping_minor=0,
        fees_minor=0,
        tax_minor=0,
        coupon_discount_minor=0,
        coupon_expires_at=None,
        stock="IN_STOCK",
        notifications_enabled=True,
        user_enabled=True,
        target_total_minor=None,
        baseline_total_minor=None,
        baseline_reliable=False,
        cost_semantic_fingerprint="cost-semantic-1",
        zero_total_provenance="VERIFIED_PURCHASE_TOTAL",
    )
    return replace(base, **changes)


def state(item: NotificationCandidate, **changes) -> LatestState:
    return LatestState.from_candidate(item, **changes)


def approved_c01_candidate() -> tuple[PurchaseScenario, object, NotificationCandidate]:
    scenario = PurchaseScenario(
        offer=OfferIdentity("COUPANG", "p1", "sku-1", "seller-1", "NEW", "ONE", "ROCKET"),
        context_id="ctx-1",
        quantity=1,
        membership_context="WOW",
        eligibility_profile_version="profile-1",
        price_basis="CURRENT_TOTAL",
    )
    cost = CostResult(
        complete=True,
        total_minor=500,
        unit_minor=Fraction(500, 1),
        subtotal_minor=500,
        discount_minor=0,
        shipping_minor=0,
        fees_minor=0,
        tax_minor=0,
        reason_codes=(),
        scenario_scope=scenario.scope_key,
        quote_fingerprint="quote-fp",
        price_basis="CURRENT_TOTAL",
        calculated_at=NOW,
        evidence_expires_at=NOW + timedelta(hours=2),
        quote_evidence_id="synthetic-quote",
        rule_version="synthetic-price-rule-v1",
        semantic_fingerprint="cost-semantic-c01",
    )
    context = PolicyContext.synthetic_verified(NOW, scenario, expires_at=NOW + timedelta(hours=1))
    decision = decide(scenario, cost, None, context)
    assert decision.notify
    item = candidate_from_c01(
        scenario,
        decision,
        request_id="i01-request-1",
        user_policy_scope=scenario.user_policy_scope_key,
        sku_id="sku-1",
        minimum_quantity=1,
        policy_epoch=1,
        source_revision=1,
        subtotal_minor=500,
        shipping_minor=0,
        fees_minor=0,
        tax_minor=0,
        coupon_discount_minor=0,
        coupon_expires_at=None,
        stock="IN_STOCK",
        notifications_enabled=True,
        user_enabled=True,
        baseline_reliable=False,
        cost_semantic_fingerprint="cost-semantic-c01",
    )
    return scenario, decision, item
