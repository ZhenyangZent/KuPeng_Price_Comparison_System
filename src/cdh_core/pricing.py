from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from typing import Any

from .models import (
    ALLOWED_COMPLETE_PRICE_BASES,
    PRICE_BASIS_RULE_VERSION,
    CostResult,
    EvidenceBasis,
    MoneyValue,
    PurchaseScenario,
    ValueState,
    canonical_digest,
    require_aware,
    strict_int,
)


@dataclass(frozen=True, slots=True)
class FeeComponent:
    component_id: str
    amount: MoneyValue


@dataclass(frozen=True, slots=True)
class IncludedFeeEvidence:
    """Evidence that one mandatory fee is already present in the quoted subtotal."""

    fee_id: str
    scenario_scope: str
    quote_evidence_id: str
    subtotal_minor: int
    fee_minor: int
    evidence_id: str
    rule_version: str
    observed_at: datetime
    expires_at: datetime
    basis: EvidenceBasis
    source_record_sha256: str

    def __post_init__(self) -> None:
        for field_name in ("fee_id", "scenario_scope", "quote_evidence_id", "evidence_id", "rule_version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value == "UNVERIFIED":
                raise ValueError(f"{field_name} must contain verified evidence")
        strict_int(self.subtotal_minor, "subtotal_minor")
        strict_int(self.fee_minor, "fee_minor")
        require_aware(self.observed_at, "observed_at")
        require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.observed_at:
            raise ValueError("included fee evidence must expire after observation")
        if self.basis not in (EvidenceBasis.OBSERVED, EvidenceBasis.RULE_DERIVED):
            raise ValueError("included fee evidence must have an authoritative basis")
        if (
            len(self.source_record_sha256) != 64
            or self.source_record_sha256.lower() != self.source_record_sha256
            or any(character not in "0123456789abcdef" for character in self.source_record_sha256)
        ):
            raise ValueError("source_record_sha256 must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class CostComponentEvidence:
    """Typed proof for resolving one non-numeric mandatory cost component to zero.

    A free-form ``MoneyValue.evidence_id`` is deliberately insufficient.  The
    evidence must bind the disposition to the exact quote, scenario, subtotal,
    component, validity interval and source record.
    """

    component_kind: str
    component_id: str
    disposition: str
    scenario_scope: str
    quote_evidence_id: str
    subtotal_minor: int
    component_minor: int
    evidence_id: str
    rule_version: str
    observed_at: datetime
    expires_at: datetime
    basis: EvidenceBasis
    source_record_sha256: str

    def __post_init__(self) -> None:
        if self.component_kind not in {"FEE", "TAX"}:
            raise ValueError("component_kind must be FEE or TAX")
        if self.disposition not in {"INCLUDED_IN_SUBTOTAL", "NOT_APPLICABLE"}:
            raise ValueError("unsupported component disposition")
        for field_name in (
            "component_id",
            "scenario_scope",
            "quote_evidence_id",
            "evidence_id",
            "rule_version",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value == "UNVERIFIED":
                raise ValueError(f"{field_name} must contain verified evidence")
        strict_int(self.subtotal_minor, "subtotal_minor")
        strict_int(self.component_minor, "component_minor")
        if self.disposition == "NOT_APPLICABLE" and self.component_minor != 0:
            raise ValueError("NOT_APPLICABLE evidence requires component_minor=0")
        if self.disposition == "INCLUDED_IN_SUBTOTAL" and self.subtotal_minor < self.component_minor:
            raise ValueError("included component cannot exceed the bound subtotal")
        require_aware(self.observed_at, "observed_at")
        require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.observed_at:
            raise ValueError("component evidence must expire after observation")
        if self.basis not in (EvidenceBasis.OBSERVED, EvidenceBasis.RULE_DERIVED):
            raise ValueError("component evidence must have an authoritative basis")
        if (
            len(self.source_record_sha256) != 64
            or self.source_record_sha256.lower() != self.source_record_sha256
            or any(character not in "0123456789abcdef" for character in self.source_record_sha256)
        ):
            raise ValueError("source_record_sha256 must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class CouponTerms:
    coupon_id: str
    discount: MoneyValue
    minimum_subtotal_minor: int | None
    eligibility: bool | None
    restrictions_satisfied: bool | None
    cap_behavior_confirmed: bool = False
    expires_at: datetime | None = None
    applicable_offer_keys: frozenset[str] = frozenset()
    applicable_seller_ids: frozenset[str] = frozenset()
    claimed: bool | None = None
    stack_group: str | None = None
    remaining_uses: int | None = None
    requires_app: bool = False
    allowed_payment_method: str | None = None
    threshold_evidence_id: str | None = None
    rule_version: str = "coupon-rule-unverified"
    expiry_policy: str = "UNKNOWN"
    offer_scope_policy: str = "UNKNOWN"
    seller_scope_policy: str = "UNKNOWN"
    threshold_policy: str = "UNKNOWN"
    terms_evidence_id: str | None = None
    terms_context_id: str | None = None
    terms_membership_context: str | None = None
    terms_eligibility_profile_version: str | None = None
    terms_evidence_basis: EvidenceBasis = EvidenceBasis.UNKNOWN
    terms_source_record_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.coupon_id:
            raise ValueError("coupon_id is required")
        if self.minimum_subtotal_minor is not None:
            strict_int(self.minimum_subtotal_minor, "minimum_subtotal_minor")
        if self.expires_at is not None:
            require_aware(self.expires_at, "expires_at")
        if self.remaining_uses is not None:
            strict_int(self.remaining_uses, "remaining_uses")
        if not self.rule_version:
            raise ValueError("rule_version is required")
        allowed = {
            "expiry_policy": {"UNKNOWN", "FIXED", "PERPETUAL"},
            "offer_scope_policy": {"UNKNOWN", "LISTED", "ALL"},
            "seller_scope_policy": {"UNKNOWN", "LISTED", "ALL"},
            "threshold_policy": {"UNKNOWN", "FIXED", "NONE"},
        }
        for field_name, choices in allowed.items():
            if getattr(self, field_name) not in choices:
                raise ValueError(f"{field_name} is invalid")


@dataclass(frozen=True, slots=True)
class PricingInput:
    subtotal: MoneyValue
    shipping: MoneyValue
    fees: tuple[FeeComponent, ...]
    tax: MoneyValue
    minimum_quantity: int
    independently_purchasable: bool
    requires_additional_items: bool = False
    coupon: CouponTerms | None = None
    included_adjustment_ids: frozenset[str] = frozenset()
    included_fee_ids: frozenset[str] = frozenset()
    included_fee_evidence: tuple[IncludedFeeEvidence, ...] = ()
    component_evidence: tuple[CostComponentEvidence, ...] = ()
    evaluated_at: datetime | None = None
    quote_evidence_id: str = "UNVERIFIED"
    rule_version: str = "pricing-v3.0-c01-r04.5"
    evidence_expires_at: datetime | None = None

    def __post_init__(self) -> None:
        strict_int(self.minimum_quantity, "minimum_quantity", minimum=1)
        if self.evaluated_at is not None:
            require_aware(self.evaluated_at, "evaluated_at")
        if self.evidence_expires_at is not None:
            require_aware(self.evidence_expires_at, "evidence_expires_at")
        if not self.quote_evidence_id or not self.rule_version:
            raise ValueError("quote_evidence_id and rule_version are required")


def parse_minor(value: Any, *, currency: str = "TWD") -> MoneyValue:
    if currency != "TWD":
        raise ValueError("unsupported currency")
    if value is None or value == "":
        return MoneyValue.unavailable(ValueState.UNKNOWN)
    if isinstance(value, (bool, float)):
        return MoneyValue.unavailable(ValueState.PARSE_ERROR)
    if not isinstance(value, int) or value < 0:
        return MoneyValue.unavailable(ValueState.PARSE_ERROR)
    return MoneyValue.known(value)


def _resolve(
    component: MoneyValue,
    label: str,
    reasons: list[str],
) -> int | None:
    if component.is_numeric:
        return component.resolved_minor()
    if component.state == ValueState.NOT_APPLICABLE:
        reasons.append(f"{label}_NOT_APPLICABLE_UNVERIFIED")
        return None
    reasons.append(f"{label}_{component.state}")
    return None


def _quote_fingerprint(
    scenario: PurchaseScenario,
    pricing: PricingInput,
    *,
    subtotal: int | None,
    shipping: int | None,
    fees: int,
    tax: int | None,
    discount: int,
    applied: set[str],
) -> str:
    coupon = pricing.coupon
    return canonical_digest(
        "quote",
        {
            "scenario_scope": scenario.scope_key,
            "price_basis": scenario.price_basis,
            "subtotal": subtotal,
            "shipping": shipping,
            "fees": fees,
            "tax": tax,
            "discount": discount,
            "applied_adjustments": sorted(applied),
            "declared_included_adjustments": sorted(pricing.included_adjustment_ids),
            "included_fees": sorted(pricing.included_fee_ids),
            "included_fee_evidence": sorted(
                (
                    item.fee_id,
                    item.evidence_id,
                    item.rule_version,
                    item.basis,
                    item.source_record_sha256,
                )
                for item in pricing.included_fee_evidence
            ),
            "component_evidence": sorted(
                (
                    item.component_kind,
                    item.component_id,
                    item.disposition,
                    item.component_minor,
                    item.evidence_id,
                    item.rule_version,
                    item.basis,
                    item.source_record_sha256,
                )
                for item in pricing.component_evidence
            ),
            "price_basis_rule_version": PRICE_BASIS_RULE_VERSION,
            "quote_evidence_id": pricing.quote_evidence_id,
            "rule_version": pricing.rule_version,
            "coupon_rule_version": None if coupon is None else coupon.rule_version,
            "coupon_terms_evidence_id": None if coupon is None else coupon.terms_evidence_id,
            "coupon_terms_evidence_basis": None if coupon is None else coupon.terms_evidence_basis,
            "coupon_terms_source_record_sha256": (
                None if coupon is None else coupon.terms_source_record_sha256
            ),
        },
    )


def _semantic_fingerprint(
    scenario: PurchaseScenario,
    pricing: PricingInput,
    *,
    subtotal: int | None,
    shipping: int | None,
    fees: int,
    tax: int | None,
    discount: int,
    applied: set[str],
) -> str:
    """Stable notification identity: material terms only, never volatile evidence IDs/clocks."""
    coupon = pricing.coupon
    return canonical_digest(
        "quote-semantic",
        {
            "scenario_scope": scenario.scope_key,
            "price_basis": scenario.price_basis,
            "subtotal": subtotal,
            "shipping": shipping,
            "fees": fees,
            "tax": tax,
            "discount": discount,
            "applied_adjustments": sorted(applied),
            "declared_included_adjustments": sorted(pricing.included_adjustment_ids),
            "included_fees": sorted(pricing.included_fee_ids),
            "included_fee_rules": sorted(
                (item.fee_id, item.rule_version)
                for item in pricing.included_fee_evidence
            ),
            "component_disposition_rules": sorted(
                (item.component_kind, item.component_id, item.disposition, item.component_minor, item.rule_version)
                for item in pricing.component_evidence
            ),
            "price_basis_rule_version": PRICE_BASIS_RULE_VERSION,
            "rule_version": pricing.rule_version,
            "coupon_rule_version": None if coupon is None else coupon.rule_version,
            "coupon_terms": None
            if coupon is None
            else {
                "coupon_id": coupon.coupon_id,
                "minimum_subtotal_minor": coupon.minimum_subtotal_minor,
                "expiry_policy": coupon.expiry_policy,
                "expires_at": None if coupon.expires_at is None else coupon.expires_at.isoformat(),
                "offer_scope_policy": coupon.offer_scope_policy,
                "applicable_offer_keys": sorted(coupon.applicable_offer_keys),
                "seller_scope_policy": coupon.seller_scope_policy,
                "applicable_seller_ids": sorted(coupon.applicable_seller_ids),
                "threshold_policy": coupon.threshold_policy,
                "rule_version": coupon.rule_version,
                "terms_evidence_basis": coupon.terms_evidence_basis,
            },
        },
    )


def calculate_total(scenario: PurchaseScenario, pricing: PricingInput) -> CostResult:
    evaluated_at = pricing.evaluated_at or datetime.now(timezone.utc)
    reasons: list[str] = []
    dependency_expiries: list[datetime] = []
    if pricing.evaluated_at is None:
        reasons.append("QUOTE_EVALUATION_TIME_MISSING")
    if pricing.evidence_expires_at is None:
        reasons.append("QUOTE_EXPIRY_MISSING")
    elif pricing.evidence_expires_at <= evaluated_at:
        reasons.append("QUOTE_EXPIRED_OR_INVALID")
    else:
        dependency_expiries.append(pricing.evidence_expires_at)
    if pricing.quote_evidence_id == "UNVERIFIED":
        reasons.append("QUOTE_EVIDENCE_UNVERIFIED")
    if scenario.quantity < pricing.minimum_quantity:
        reasons.append("MINIMUM_QUANTITY_NOT_MET")
    if not pricing.independently_purchasable:
        reasons.append("NOT_INDEPENDENTLY_PURCHASABLE")
    if pricing.requires_additional_items:
        reasons.append("REQUIRES_BUNDLE")
    if scenario.price_basis not in ALLOWED_COMPLETE_PRICE_BASES:
        reasons.append("PRICE_BASIS_NOT_COMPLETE_PURCHASE_PRICE")

    subtotal = _resolve(pricing.subtotal, "SUBTOTAL", reasons)
    shipping = _resolve(pricing.shipping, "SHIPPING", reasons)

    evidence_by_component: dict[tuple[str, str], CostComponentEvidence] = {}
    duplicate_component_evidence = False
    for evidence in pricing.component_evidence:
        key = (evidence.component_kind, evidence.component_id)
        if key in evidence_by_component:
            duplicate_component_evidence = True
        else:
            evidence_by_component[key] = evidence
    if duplicate_component_evidence:
        reasons.append("DUPLICATE_COMPONENT_EVIDENCE")
    used_component_evidence: set[tuple[str, str]] = set()

    def resolve_non_numeric_component(component: MoneyValue, kind: str, component_id: str, label: str) -> int | None:
        if component.is_numeric:
            return component.resolved_minor()
        if component.state != ValueState.NOT_APPLICABLE:
            reasons.append(f"{label}_{component.state}")
            return None
        key = (kind, component_id)
        evidence = evidence_by_component.get(key)
        valid = bool(
            evidence is not None
            and evidence.scenario_scope == scenario.scope_key
            and evidence.quote_evidence_id == pricing.quote_evidence_id
            and evidence.subtotal_minor == subtotal
            and evidence.observed_at <= evaluated_at < evidence.expires_at
            and evidence.rule_version != "component-rule-unverified"
            and subtotal is not None
        )
        if not valid:
            reasons.append(f"{label}_NOT_APPLICABLE_EVIDENCE_INVALID")
            return None
        assert evidence is not None
        used_component_evidence.add(key)
        dependency_expiries.append(evidence.expires_at)
        return 0

    tax = resolve_non_numeric_component(pricing.tax, "TAX", "tax", "TAX")

    fee_total = 0
    fee_unknown = False
    seen_fee_ids: set[str] = set()
    evidence_by_fee: dict[str, IncludedFeeEvidence] = {}
    duplicate_evidence_ids: set[str] = set()
    for evidence in pricing.included_fee_evidence:
        if evidence.fee_id in evidence_by_fee:
            duplicate_evidence_ids.add(evidence.fee_id)
        else:
            evidence_by_fee[evidence.fee_id] = evidence
    if duplicate_evidence_ids:
        reasons.append("DUPLICATE_INCLUDED_FEE_EVIDENCE")
        fee_unknown = True
    for fee in pricing.fees:
        if not fee.component_id or fee.component_id in seen_fee_ids:
            reasons.append("DUPLICATE_FEE_ID")
            fee_unknown = True
            continue
        seen_fee_ids.add(fee.component_id)
        if fee.component_id in pricing.included_fee_ids:
            evidence = evidence_by_fee.get(fee.component_id)
            fee_minor = fee.amount.resolved_minor() if fee.amount.is_numeric else None
            evidence_valid = bool(
                evidence is not None
                and evidence.fee_id == fee.component_id
                and evidence.scenario_scope == scenario.scope_key
                and evidence.quote_evidence_id == pricing.quote_evidence_id
                and evidence.subtotal_minor == subtotal
                and evidence.fee_minor == fee_minor
                and evidence.observed_at <= evaluated_at < evidence.expires_at
                and evidence.rule_version != "included-fee-rule-unverified"
                and subtotal is not None
                and fee_minor is not None
                and subtotal >= fee_minor
            )
            if not evidence_valid:
                reasons.append(f"INCLUDED_FEE_{fee.component_id}_EVIDENCE_INVALID")
                fee_unknown = True
            else:
                assert evidence is not None
                dependency_expiries.append(evidence.expires_at)
            continue
        value = resolve_non_numeric_component(fee.amount, "FEE", fee.component_id, f"FEE_{fee.component_id}")
        if value is None:
            fee_unknown = True
        else:
            fee_total += value
    if pricing.included_fee_ids - seen_fee_ids:
        reasons.append("UNKNOWN_INCLUDED_FEE_ID")
        fee_unknown = True
    if set(evidence_by_fee) - pricing.included_fee_ids:
        reasons.append("UNREFERENCED_INCLUDED_FEE_EVIDENCE")
        fee_unknown = True
    if set(evidence_by_component) - used_component_evidence:
        reasons.append("UNREFERENCED_COMPONENT_EVIDENCE")
        fee_unknown = True

    discount = 0
    applied: set[str] = set()
    coupon = pricing.coupon
    selected_coupon = scenario.coupon_plan_id
    coupon_blocked = False
    if pricing.included_adjustment_ids and (selected_coupon is None or coupon is None):
        reasons.append("INCLUDED_ADJUSTMENT_UNBOUND")
        coupon_blocked = True
    if selected_coupon is None and coupon is not None:
        reasons.append("UNSELECTED_COUPON_SUPPLIED")
        coupon_blocked = True
    elif selected_coupon is not None and coupon is None:
        reasons.append("SELECTED_COUPON_TERMS_MISSING")
        coupon_blocked = True
    elif selected_coupon is not None and coupon is not None:
        if coupon.coupon_id != selected_coupon:
            reasons.append("COUPON_PLAN_MISMATCH")
            coupon_blocked = True
        else:
            included = coupon.coupon_id in pricing.included_adjustment_ids
            if pricing.included_adjustment_ids - {coupon.coupon_id}:
                reasons.append("UNKNOWN_INCLUDED_ADJUSTMENT")
                coupon_blocked = True
            expiry_known = (
                (coupon.expiry_policy == "FIXED" and coupon.expires_at is not None)
                or (coupon.expiry_policy == "PERPETUAL" and coupon.expires_at is None)
            )
            offer_scope_known = (
                (coupon.offer_scope_policy == "LISTED" and bool(coupon.applicable_offer_keys))
                or (coupon.offer_scope_policy == "ALL" and not coupon.applicable_offer_keys)
            )
            seller_scope_known = (
                (coupon.seller_scope_policy == "LISTED" and bool(coupon.applicable_seller_ids))
                or (coupon.seller_scope_policy == "ALL" and not coupon.applicable_seller_ids)
            )
            threshold_known = (
                (
                    coupon.threshold_policy == "FIXED"
                    and coupon.minimum_subtotal_minor is not None
                    and coupon.threshold_evidence_id is not None
                )
                or (
                    coupon.threshold_policy == "NONE"
                    and coupon.minimum_subtotal_minor in (None, 0)
                )
            )
            checks = (
                (coupon.terms_evidence_id not in (None, "", "UNVERIFIED"), "COUPON_TERMS_EVIDENCE_MISSING"),
                (
                    coupon.terms_evidence_basis in (EvidenceBasis.OBSERVED, EvidenceBasis.RULE_DERIVED),
                    "COUPON_TERMS_EVIDENCE_BASIS_INVALID",
                ),
                (
                    coupon.terms_source_record_sha256 is not None
                    and len(coupon.terms_source_record_sha256) == 64
                    and coupon.terms_source_record_sha256.lower() == coupon.terms_source_record_sha256
                    and all(
                        character in "0123456789abcdef"
                        for character in coupon.terms_source_record_sha256
                    ),
                    "COUPON_TERMS_SOURCE_HASH_INVALID",
                ),
                (coupon.terms_context_id == scenario.context_id, "COUPON_CONTEXT_MISMATCH"),
                (coupon.terms_membership_context == scenario.membership_context, "COUPON_MEMBERSHIP_CONTEXT_MISMATCH"),
                (
                    coupon.terms_eligibility_profile_version == scenario.eligibility_profile_version,
                    "COUPON_ELIGIBILITY_PROFILE_MISMATCH",
                ),
                (expiry_known, "COUPON_EXPIRY_POLICY_UNKNOWN_OR_INCOHERENT"),
                (offer_scope_known, "COUPON_OFFER_SCOPE_POLICY_UNKNOWN_OR_INCOHERENT"),
                (seller_scope_known, "COUPON_SELLER_SCOPE_POLICY_UNKNOWN_OR_INCOHERENT"),
                (threshold_known, "COUPON_THRESHOLD_POLICY_UNKNOWN_OR_INCOHERENT"),
                (
                    coupon.offer_scope_policy == "ALL" or scenario.offer.key in coupon.applicable_offer_keys,
                    "COUPON_SCOPE_MISMATCH",
                ),
                (
                    coupon.seller_scope_policy == "ALL" or scenario.offer.seller_id in coupon.applicable_seller_ids,
                    "COUPON_SELLER_MISMATCH",
                ),
                (
                    coupon.expiry_policy == "PERPETUAL"
                    or (coupon.expires_at is not None and evaluated_at < coupon.expires_at),
                    "COUPON_EXPIRED",
                ),
                (coupon.claimed is True, "COUPON_CLAIM_STATUS_UNKNOWN_OR_FALSE"),
                (coupon.remaining_uses is not None and coupon.remaining_uses > 0, "COUPON_REMAINING_USES_UNKNOWN_OR_ZERO"),
                (coupon.eligibility is True, "COUPON_ELIGIBILITY_UNKNOWN_OR_FALSE"),
                (coupon.restrictions_satisfied is True, "COUPON_RESTRICTIONS_UNKNOWN_OR_FALSE"),
                (not coupon.requires_app or scenario.purchase_channel == "APP", "COUPON_APP_CHANNEL_MISMATCH"),
                (
                    coupon.allowed_payment_method is None or scenario.payment_method == coupon.allowed_payment_method,
                    "COUPON_PAYMENT_METHOD_MISMATCH",
                ),
                (
                    coupon.threshold_policy == "NONE" or coupon.threshold_evidence_id is not None,
                    "COUPON_THRESHOLD_EVIDENCE_MISSING",
                ),
                (coupon.rule_version != "coupon-rule-unverified", "COUPON_RULE_UNVERIFIED"),
            )
            for passed, reason in checks:
                if not passed:
                    reasons.append(reason)
                    coupon_blocked = True
            if subtotal is not None and coupon.minimum_subtotal_minor is not None and subtotal < coupon.minimum_subtotal_minor:
                reasons.append("COUPON_THRESHOLD_NOT_MET")
                coupon_blocked = True
            resolved_discount = _resolve(coupon.discount, "COUPON", reasons)
            if resolved_discount is None:
                coupon_blocked = True
            elif subtotal is not None and not coupon_blocked:
                if not included and resolved_discount > subtotal and not coupon.cap_behavior_confirmed:
                    reasons.append("COUPON_EXCEEDS_SUBTOTAL_UNCONFIRMED")
                    coupon_blocked = True
                else:
                    applied.add(coupon.coupon_id)
                    if coupon.expiry_policy == "FIXED" and coupon.expires_at is not None:
                        dependency_expiries.append(coupon.expires_at)
                    if included:
                        reasons.append("COUPON_ALREADY_INCLUDED")
                    else:
                        discount = min(resolved_discount, subtotal)

    effective_expiry = min(dependency_expiries) if dependency_expiries else pricing.evidence_expires_at
    blocking = bool(reasons) and any(
        reason not in {"COUPON_ALREADY_INCLUDED"}
        for reason in reasons
    )
    complete = (
        subtotal is not None
        and shipping is not None
        and tax is not None
        and not fee_unknown
        and not blocking
        and not coupon_blocked
    )
    fingerprint = _quote_fingerprint(
        scenario,
        pricing,
        subtotal=subtotal,
        shipping=shipping,
        fees=fee_total,
        tax=tax,
        discount=discount,
        applied=applied,
    )
    semantic_fingerprint = _semantic_fingerprint(
        scenario,
        pricing,
        subtotal=subtotal,
        shipping=shipping,
        fees=fee_total,
        tax=tax,
        discount=discount,
        applied=applied,
    )
    if not complete:
        return CostResult(
            False,
            None,
            None,
            subtotal,
            discount,
            shipping,
            fee_total,
            tax,
            tuple(reasons),
            frozenset(applied),
            scenario.scope_key,
            fingerprint,
            scenario.price_basis,
            evaluated_at,
            effective_expiry,
            pricing.quote_evidence_id,
            pricing.rule_version,
            semantic_fingerprint,
        )

    assert subtotal is not None and shipping is not None and tax is not None
    total = subtotal - discount + shipping + fee_total + tax
    if total < 0:
        raise AssertionError("validated total cannot be negative")
    return CostResult(
        True,
        total,
        Fraction(total, scenario.quantity),
        subtotal,
        discount,
        shipping,
        fee_total,
        tax,
        tuple(reasons),
        frozenset(applied),
        scenario.scope_key,
        fingerprint,
        scenario.price_basis,
        evaluated_at,
        effective_expiry,
        pricing.quote_evidence_id,
        pricing.rule_version,
        semantic_fingerprint,
    )

