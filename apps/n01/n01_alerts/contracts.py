from __future__ import annotations

from datetime import datetime
from typing import Any

from cdh_core.models import Decision, PurchaseScenario
from cdh_core.policy import verify_decision_approval

from .models import NotificationCandidate, SYNTHETIC_SOURCE_STATUS


REAL_DELIVERY_ENABLED = False

WINDOWS_TOAST_INTERFACE = {
    "interface": "CDH-N01-WINDOWS-TOAST-PROPOSAL-1",
    "enabled": False,
    "required_input": ["event_id", "title", "body", "expires_at", "idempotency_key"],
    "result": ["accepted", "receipt_id", "ambiguous"],
    "credential_access": "NONE",
}

TELEGRAM_INTERFACE = {
    "interface": "CDH-N01-TELEGRAM-PROPOSAL-1",
    "enabled": False,
    "required_input": ["event_id", "chat_alias", "body", "expires_at", "idempotency_key"],
    "result": ["accepted", "receipt_id", "ambiguous"],
    "credential_access": "PROHIBITED_UNTIL_SEPARATE_AUTHORITY",
}


def candidate_from_c01(
    scenario: PurchaseScenario,
    decision: Decision,
    *,
    request_id: str,
    user_policy_scope: str,
    sku_id: str,
    minimum_quantity: int,
    policy_epoch: int,
    source_revision: int,
    subtotal_minor: int | None,
    shipping_minor: int | None,
    fees_minor: int | None,
    tax_minor: int | None,
    coupon_discount_minor: int | None,
    coupon_expires_at: datetime | None,
    stock: str,
    notifications_enabled: bool,
    user_enabled: bool,
    baseline_reliable: bool,
    cost_semantic_fingerprint: str,
    zero_total_provenance: str = "VERIFIED_PURCHASE_TOTAL",
) -> NotificationCandidate:
    """Convert an in-process C01 decision into the frozen N01 input contract.

    C01 approval seals are process-private by design, so validation happens at
    this boundary before the durable N01 event is created.
    """
    if not verify_decision_approval(decision):
        raise ValueError("C01_DECISION_APPROVAL_INVALID")
    if decision.scenario_scope != scenario.scope_key:
        raise ValueError("C01_SCENARIO_SCOPE_MISMATCH")
    if decision.evaluated_at is None or decision.valid_until is None:
        raise ValueError("C01_DECISION_TIME_UNBOUND")
    if not decision.decision_fingerprint or not decision.policy_evidence_fingerprint:
        raise ValueError("C01_DECISION_IDENTITY_UNBOUND")
    return NotificationCandidate(
        request_id=request_id,
        scenario_scope=scenario.scope_key,
        user_policy_scope=user_policy_scope,
        offer_key=scenario.offer.key,
        sku_id=sku_id,
        quantity=scenario.quantity,
        minimum_quantity=minimum_quantity,
        membership_context=scenario.membership_context,
        eligibility_profile_version=scenario.eligibility_profile_version,
        policy_epoch=policy_epoch,
        source_revision=source_revision,
        source_kind="SYNTHETIC",
        source_status=SYNTHETIC_SOURCE_STATUS,
        observed_at=decision.evaluated_at,
        expires_at=decision.valid_until,
        decision_fingerprint=decision.decision_fingerprint,
        policy_evidence_fingerprint=decision.policy_evidence_fingerprint,
        decision_reason=decision.primary_reason,
        decision_labels=decision.labels,
        decision_notify=decision.notify,
        total_minor=decision.total_minor,
        subtotal_minor=subtotal_minor,
        shipping_minor=shipping_minor,
        fees_minor=fees_minor,
        tax_minor=tax_minor,
        coupon_discount_minor=coupon_discount_minor,
        coupon_expires_at=coupon_expires_at,
        stock=stock,
        notifications_enabled=notifications_enabled,
        user_enabled=user_enabled,
        target_total_minor=scenario.target_total_minor,
        baseline_total_minor=decision.baseline_total_minor,
        baseline_reliable=baseline_reliable,
        cost_semantic_fingerprint=cost_semantic_fingerprint,
        zero_total_provenance=zero_total_provenance,
    )


def candidate_from_i01(result: Any, **kwargs: Any) -> NotificationCandidate:
    """Accept the approved I01 IntegrationResult shape without modifying I01."""
    if getattr(result, "status", None) != "QUEUED":
        raise ValueError("I01_RESULT_NOT_QUEUED")
    scenario = getattr(result, "scenario", None)
    decision = getattr(result, "decision", None)
    if not isinstance(scenario, PurchaseScenario) or not isinstance(decision, Decision):
        raise TypeError("I01_RESULT_CONTRACT_INVALID")
    return candidate_from_c01(scenario, decision, **kwargs)
