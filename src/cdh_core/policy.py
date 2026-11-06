from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import (
    ALLOWED_COMPLETE_PRICE_BASES,
    PRICE_BASIS_RULE_VERSION,
    POLICY_VERSION,
    BaselineSnapshot,
    CostResult,
    Decision,
    EligibilityState,
    PurchaseScenario,
    StockState,
    canonical_digest,
    canonical_json,
    require_aware,
)


# This process-private key makes a policy approval materially different from a
# caller-recomputable identity hash.  The seal is an internal core trust
# boundary, not an external authentication or key-management claim.
_POLICY_APPROVAL_KEY = secrets.token_bytes(32)


def _approval_seal(decision_fingerprint: str, evidence_fingerprint: str) -> str:
    payload = f"{decision_fingerprint}:{evidence_fingerprint}".encode("utf-8")
    return hmac.new(_POLICY_APPROVAL_KEY, payload, hashlib.sha256).hexdigest()


def verify_decision_approval(decision: Decision) -> bool:
    """Verify that the current policy engine approved this exact decision."""
    if (
        not decision.policy_evidence_json
        or not decision.policy_evidence_fingerprint
        or not decision.approval_seal
        or not decision.decision_fingerprint
        or decision.policy_version != POLICY_VERSION
        or decision.decision_fingerprint != decision.computed_fingerprint
    ):
        return False
    try:
        evidence = json.loads(decision.policy_evidence_json)
    except (TypeError, ValueError):
        return False
    if canonical_json(evidence) != decision.policy_evidence_json:
        return False
    if canonical_digest("policy-evidence", evidence) != decision.policy_evidence_fingerprint:
        return False
    expected = _approval_seal(decision.decision_fingerprint, decision.policy_evidence_fingerprint)
    return hmac.compare_digest(expected, decision.approval_seal)


@dataclass(frozen=True, slots=True)
class PolicyContext:
    """Explicit, time-bounded policy evidence.

    Defaults are deliberately non-authoritative.  Tests and offline adapters must
    opt into a clearly named synthetic context instead of inheriting eligibility.
    """

    user_enabled: bool = False
    notifications_enabled: bool = False
    source_allowed: bool = False
    evidence_valid: bool = False
    eligibility: EligibilityState = EligibilityState.UNKNOWN
    stock: StockState = StockState.UNKNOWN
    subscription_or_deposit: bool = False
    historical_new_low: bool = False
    evaluated_at: datetime | None = None
    evidence_observed_at: datetime | None = None
    evidence_expires_at: datetime | None = None
    evidence_id: str | None = None
    rule_version: str | None = None
    source_permission_version: str | None = None
    scenario_scope: str | None = None
    membership_context: str | None = None
    eligibility_profile_version: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("evaluated_at", "evidence_observed_at", "evidence_expires_at"):
            value = getattr(self, field_name)
            if value is not None:
                require_aware(value, field_name)

    @classmethod
    def synthetic_verified(
        cls,
        now: datetime,
        scenario: PurchaseScenario,
        *,
        expires_at: datetime | None = None,
        eligibility: EligibilityState = EligibilityState.ELIGIBLE,
        stock: StockState = StockState.IN_STOCK,
        user_enabled: bool = True,
        notifications_enabled: bool = True,
        source_allowed: bool = True,
        subscription_or_deposit: bool = False,
        historical_new_low: bool = False,
    ) -> "PolicyContext":
        require_aware(now, "now")
        expiry = expires_at or (now + timedelta(minutes=5))
        require_aware(expiry, "expires_at")
        if expiry <= now:
            raise ValueError("verified context must expire after now")
        if scenario.eligibility_profile_version == "UNVERIFIED":
            raise ValueError("synthetic verified context requires an explicit eligibility profile")
        return cls(
            user_enabled=user_enabled,
            notifications_enabled=notifications_enabled,
            source_allowed=source_allowed,
            evidence_valid=True,
            eligibility=eligibility,
            stock=stock,
            subscription_or_deposit=subscription_or_deposit,
            historical_new_low=historical_new_low,
            evaluated_at=now,
            evidence_observed_at=now,
            evidence_expires_at=expiry,
            evidence_id="SYNTHETIC-POLICY-CONTEXT",
            rule_version=POLICY_VERSION,
            source_permission_version="offline-test-v1",
            scenario_scope=scenario.scope_key,
            membership_context=scenario.membership_context,
            eligibility_profile_version=scenario.eligibility_profile_version,
        )


def _make_decision(
    *,
    scenario: PurchaseScenario,
    cost: CostResult | None,
    context: PolicyContext,
    notify: bool,
    reason: str,
    labels: tuple[str, ...] = (),
    total_minor: int | None = None,
    baseline_total_minor: int | None = None,
    savings_minor: int | None = None,
    drop_basis_points: int | None = None,
) -> Decision:
    evaluated_at = context.evaluated_at
    validity_candidates = [value for value in (context.evidence_expires_at, None if cost is None else cost.evidence_expires_at) if value is not None]
    valid_until = min(validity_candidates) if validity_candidates else None
    cost_fingerprint = None if cost is None else cost.quote_fingerprint
    policy_evidence = {
        "policy_version": POLICY_VERSION,
        "price_basis_rule_version": PRICE_BASIS_RULE_VERSION,
        "scenario_scope": scenario.scope_key,
        "user_policy_scope": scenario.user_policy_scope_key,
        "membership_context": scenario.membership_context,
        "eligibility_profile_version": scenario.eligibility_profile_version,
        "price_basis": scenario.price_basis,
        "target_total_minor": scenario.target_total_minor,
        "cost_fingerprint": cost_fingerprint,
        "cost_semantic_fingerprint": None if cost is None else cost.semantic_fingerprint,
        "cost_evidence_expires_at": (
            None if cost is None or cost.evidence_expires_at is None else cost.evidence_expires_at.isoformat()
        ),
        "user_enabled": context.user_enabled,
        "notifications_enabled": context.notifications_enabled,
        "source_allowed": context.source_allowed,
        "evidence_valid": context.evidence_valid,
        "eligibility": context.eligibility,
        "stock": context.stock,
        "subscription_or_deposit": context.subscription_or_deposit,
        "historical_new_low": context.historical_new_low,
        "evaluated_at": None if evaluated_at is None else evaluated_at.isoformat(),
        "policy_evidence_observed_at": (
            None if context.evidence_observed_at is None else context.evidence_observed_at.isoformat()
        ),
        "policy_evidence_expires_at": (
            None if context.evidence_expires_at is None else context.evidence_expires_at.isoformat()
        ),
        "policy_evidence_id": context.evidence_id,
        "policy_rule_version": context.rule_version,
        "source_permission_version": context.source_permission_version,
        "valid_until": None if valid_until is None else valid_until.isoformat(),
    }
    policy_evidence_json = canonical_json(policy_evidence)
    policy_evidence_fingerprint = canonical_digest("policy-evidence", policy_evidence)
    fingerprint = canonical_digest(
        "decision",
        {
            "policy_version": POLICY_VERSION,
            "scenario_scope": scenario.scope_key,
            "cost_fingerprint": cost_fingerprint,
            "notify": notify,
            "reason": reason,
            "labels": labels,
            "total_minor": total_minor,
            "baseline_total_minor": baseline_total_minor,
            "savings_minor": savings_minor,
            "drop_basis_points": drop_basis_points,
            "evaluated_at": None if evaluated_at is None else evaluated_at.isoformat(),
            "valid_until": None if valid_until is None else valid_until.isoformat(),
            "policy_evidence_fingerprint": policy_evidence_fingerprint,
        },
    )
    return Decision(
        notify=notify,
        primary_reason=reason,
        labels=labels,
        total_minor=total_minor,
        baseline_total_minor=baseline_total_minor,
        savings_minor=savings_minor,
        drop_basis_points=drop_basis_points,
        policy_version=POLICY_VERSION,
        scenario_scope=scenario.scope_key,
        cost_fingerprint=cost_fingerprint,
        decision_fingerprint=fingerprint,
        evaluated_at=evaluated_at,
        valid_until=valid_until,
        policy_evidence_json=policy_evidence_json,
        policy_evidence_fingerprint=policy_evidence_fingerprint,
        approval_seal=_approval_seal(fingerprint, policy_evidence_fingerprint),
    )


def _silent(reason: str, scenario: PurchaseScenario, cost: CostResult | None, context: PolicyContext) -> Decision:
    return _make_decision(
        scenario=scenario,
        cost=cost,
        context=context,
        notify=False,
        reason=reason,
        total_minor=None if cost is None else cost.total_minor,
    )


def decide(
    scenario: PurchaseScenario,
    cost: CostResult,
    baseline: BaselineSnapshot | None,
    context: PolicyContext = PolicyContext(),
) -> Decision:
    now = context.evaluated_at
    if now is None or context.evidence_observed_at is None or context.evidence_expires_at is None:
        return _silent("POLICY_CONTEXT_UNVERIFIED", scenario, cost, context)
    if now < context.evidence_observed_at:
        return _silent("POLICY_EVIDENCE_NOT_YET_VALID", scenario, cost, context)
    if now >= context.evidence_expires_at:
        return _silent("POLICY_EVIDENCE_EXPIRED", scenario, cost, context)
    if not context.evidence_id or not context.rule_version or not context.source_permission_version:
        return _silent("POLICY_EVIDENCE_UNBOUND", scenario, cost, context)
    if (
        context.scenario_scope != scenario.scope_key
        or context.membership_context != scenario.membership_context
        or context.eligibility_profile_version != scenario.eligibility_profile_version
    ):
        return _silent("POLICY_SCENARIO_MISMATCH", scenario, cost, context)

    cost_binding_ok = (
        cost.scenario_scope == scenario.scope_key
        and cost.price_basis == scenario.price_basis
        and bool(cost.quote_fingerprint)
        and cost.calculated_at is not None
        and cost.calculated_at <= now
        and cost.evidence_expires_at is not None
        and now < cost.evidence_expires_at
        and bool(cost.quote_evidence_id)
        and cost.quote_evidence_id != "UNVERIFIED"
        and bool(cost.rule_version)
    )
    if not cost_binding_ok:
        return _silent("COST_BINDING_INVALID", scenario, cost, context)

    if scenario.price_basis not in ALLOWED_COMPLETE_PRICE_BASES:
        return _silent("PRICE_BASIS_NOT_COMPLETE_PURCHASE_PRICE", scenario, cost, context)

    hard_checks = (
        (context.user_enabled, "USER_DISABLED"),
        (context.notifications_enabled, "NOTIFICATIONS_DISABLED"),
        (context.source_allowed, "SOURCE_NOT_ALLOWED"),
        (context.evidence_valid, "EVIDENCE_INVALID"),
        (context.stock == StockState.IN_STOCK, "NOT_IN_STOCK"),
        (not context.subscription_or_deposit, "SUBSCRIPTION_OR_DEPOSIT"),
        (cost.complete, "COST_INCOMPLETE"),
    )
    for passed, reason in hard_checks:
        if not passed:
            return _silent(reason, scenario, cost, context)
    if context.eligibility != EligibilityState.ELIGIBLE:
        reason = {
            EligibilityState.INELIGIBLE: "INELIGIBLE",
            EligibilityState.UNKNOWN: "ELIGIBILITY_UNKNOWN",
            EligibilityState.CONFLICT: "ELIGIBILITY_CONFLICT",
        }[context.eligibility]
        return _silent(reason, scenario, cost, context)

    assert cost.total_minor is not None and cost.shipping_minor is not None
    total = cost.total_minor
    baseline_total: int | None = None
    savings: int | None = None
    drop_bps: int | None = None
    if baseline is not None:
        compatible, _ = baseline.compatibility(scenario, now)
        if compatible and baseline.item_minor is not None:
            baseline_total = baseline.item_minor * scenario.quantity
            savings = baseline_total - total
            if baseline_total > 0:
                drop_bps = savings * 10_000 // baseline_total

    def result(reason: str, *labels: str) -> Decision:
        return _make_decision(
            scenario=scenario,
            cost=cost,
            context=context,
            notify=True,
            reason=reason,
            labels=tuple(labels),
            total_minor=total,
            baseline_total_minor=baseline_total,
            savings_minor=savings,
            drop_basis_points=drop_bps,
        )

    if cost.shipping_minor == 0:
        if total == 0:
            return result("S0", "FREE_SHIPPING", "ZERO_TOTAL")
        if total <= 900 and (baseline_total is None or total < baseline_total):
            label = "LOW_PRICE_CANDIDATE" if baseline_total is None else "BELOW_BASELINE"
            return result("S1", "FREE_SHIPPING", label)
        if baseline_total is not None and savings is not None and drop_bps is not None:
            if (drop_bps >= 6000 and savings >= 20_000) or (
                context.historical_new_low and drop_bps >= 3000 and savings >= 20_000
            ):
                return result("S2", "FREE_SHIPPING", "BASELINE_SUPPORTED")
        if scenario.target_total_minor is not None and total <= scenario.target_total_minor:
            return result("TARGET_REACHED", "FREE_SHIPPING", "USER_TARGET")
        if baseline_total is not None and savings is not None and drop_bps is not None:
            if drop_bps >= 3000 and savings >= 10_000:
                return result("S3", "FREE_SHIPPING", "BASELINE_SUPPORTED")
        return _silent("NO_FREE_SHIPPING_POLICY_MATCH", scenario, cost, context)

    if baseline_total is None or savings is None:
        return _silent("PAID_SHIPPING_REQUIRES_BASELINE", scenario, cost, context)
    if total <= 3_900 and baseline_total >= 15_000:
        return result("O1", "PAID_SHIPPING_EXCEPTION")
    if baseline_total > 0 and savings >= 30_000 and savings * 100 >= baseline_total * 50:
        return result("O2", "PAID_SHIPPING_EXCEPTION")
    return _silent("NO_PAID_SHIPPING_EXCEPTION", scenario, cost, context)
