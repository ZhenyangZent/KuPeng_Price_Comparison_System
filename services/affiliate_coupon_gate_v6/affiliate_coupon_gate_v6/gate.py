"""Fail-closed B10 pricing gate; R07 grants no affiliate CTA authority."""

from __future__ import annotations

from datetime import datetime

from .audit import MockSink, build_event
from .models import AffiliateTrustInput, CombinedDecision, CouponPriceSnapshot, GateRequest, RuntimeCeiling


class AffiliateCouponGateV6:
    def __init__(self, *, sink: MockSink | None = None) -> None:
        self.sink = sink or MockSink()

    def evaluate(
        self, *, snapshot: CouponPriceSnapshot, request: GateRequest,
        affiliate: AffiliateTrustInput, ceiling: RuntimeCeiling, now: datetime,
    ) -> CombinedDecision:
        reasons: list[str] = []
        coupon = snapshot.coupon
        base = snapshot.base_price_twd
        before = snapshot.before_coupon_price_twd
        confirmed = snapshot.confirmed_coupon_price_twd
        quantity = snapshot.minimum_purchase_quantity
        identity_matches = snapshot.series_identity == request.identity
        if not identity_matches:
            reasons.append("COUPON_SERIES_IDENTITY_MISMATCH")
        if not snapshot.source_permission.allowed:
            reasons.append(snapshot.source_permission.reason)
        if snapshot.source_permission.state != "ACTIVE_SYNTHETIC_FIXTURE":
            reasons.append("SOURCE_PERMISSION_NOT_ACTIVE")
        if snapshot.data_classification != "SYNTHETIC_FIXTURE":
            reasons.append("CLASSIFICATION_NOT_AUTHORIZED")
        if snapshot.observed_at is None or snapshot.source_id is None:
            reasons.append("OBSERVATION_EVIDENCE_INCOMPLETE")
        elif snapshot.observed_at > now:
            reasons.append("OBSERVATION_IN_FUTURE")
        evidence_complete = all(
            value is not None
            for value in (coupon.coupon_id, coupon.discount_twd, coupon.eligibility_profile, coupon.valid_from, coupon.valid_until, coupon.scope_evidence)
        )
        if coupon.status != "CONFIRMED_APPLICABLE":
            reasons.append(f"COUPON_STATUS_{coupon.status}_NOT_CONFIRMED")
        if request.eligibility_profile is None or coupon.eligibility_profile != request.eligibility_profile:
            reasons.append("COUPON_ELIGIBILITY_PROFILE_MISMATCH")
        if not evidence_complete:
            reasons.append("COUPON_EVIDENCE_INCOMPLETE")
        if coupon.evaluation_reasons:
            reasons.append("UPSTREAM_COUPON_EVALUATION_REJECTED")
        if snapshot.quality_flags:
            reasons.append("UPSTREAM_QUALITY_FLAGS_PRESENT")
        if coupon.valid_from is None or coupon.valid_until is None or coupon.valid_from > coupon.valid_until or not (coupon.valid_from <= now <= coupon.valid_until):
            reasons.append("COUPON_NOT_CURRENTLY_VALID")
        if snapshot.observed_at is None or coupon.valid_from is None or coupon.valid_until is None or not (coupon.valid_from <= snapshot.observed_at <= coupon.valid_until):
            reasons.append("COUPON_NOT_VALID_AT_OBSERVATION")
        if confirmed is not None and snapshot.possible_coupon_price_twd is not None:
            reasons.append("CONFIRMED_AND_POSSIBLE_CONFLICT")
        price_math_valid = False
        expected_spend: int | None = None
        if base is not None and confirmed is not None and coupon.discount_twd is not None:
            if coupon.already_included_in_base:
                price_math_valid = (
                    confirmed == base and before is not None and before - base == coupon.discount_twd
                    and coupon.pre_coupon_comparison_source is not None
                )
                expected_spend = confirmed * quantity if price_math_valid else None
                if not price_math_valid:
                    reasons.append("ALREADY_INCLUDED_EVIDENCE_INVALID")
            elif coupon.discount_scope == "UNIT":
                price_math_valid = coupon.discount_twd <= base and confirmed == base - coupon.discount_twd
                expected_spend = confirmed * quantity if price_math_valid else None
                if not price_math_valid:
                    reasons.append("UNIT_DISCOUNT_MISMATCH")
            elif coupon.discount_scope == "ORDER_TOTAL":
                order_total = base * quantity - coupon.discount_twd
                price_math_valid = order_total >= 0 and order_total % quantity == 0 and confirmed == order_total // quantity
                expected_spend = order_total if price_math_valid else None
                if not price_math_valid:
                    reasons.append("ORDER_DISCOUNT_MISMATCH")
            else:
                reasons.append("DISCOUNT_SCOPE_INVALID")
        else:
            reasons.append("CONFIRMED_PRICE_EVIDENCE_INCOMPLETE")
        confirmed_applicable = (
            identity_matches
            and snapshot.source_permission.allowed
            and snapshot.source_permission.state == "ACTIVE_SYNTHETIC_FIXTURE"
            and snapshot.data_classification == "SYNTHETIC_FIXTURE"
            and snapshot.observed_at is not None
            and snapshot.source_id is not None
            and snapshot.observed_at <= now
            and coupon.status == "CONFIRMED_APPLICABLE"
            and request.eligibility_profile is not None
            and coupon.eligibility_profile == request.eligibility_profile
            and evidence_complete
            and not coupon.evaluation_reasons
            and not snapshot.quality_flags
            and coupon.valid_from is not None
            and coupon.valid_until is not None
            and coupon.valid_from <= snapshot.observed_at <= coupon.valid_until
            and coupon.valid_from <= now <= coupon.valid_until
            and snapshot.possible_coupon_price_twd is None
            and price_math_valid
        )
        if confirmed_applicable:
            display_price = confirmed
            display_basis = "CONFIRMED_COUPON"
            coupon_applied = not coupon.already_included_in_base
            minimum_item_spend = expected_spend
        elif snapshot.source_permission.allowed and base is not None:
            display_price = base
            display_basis = "BASE_PRICE"
            coupon_applied = False
            confirmed = None
            minimum_item_spend = base * quantity
        else:
            display_price = None
            display_basis = "PRICE_UNAVAILABLE"
            coupon_applied = False
            confirmed = None
            minimum_item_spend = None
        if snapshot.upstream_display_price_twd != display_price or snapshot.upstream_display_basis != display_basis:
            reasons.append("UPSTREAM_DISPLAY_MISMATCH")
        if snapshot.minimum_item_spend_twd != minimum_item_spend:
            reasons.append("UPSTREAM_MINIMUM_ITEM_SPEND_MISMATCH")
        required_total = snapshot.upstream_required_total_twd
        if snapshot.shipping_status == "UNKNOWN":
            if required_total is not None:
                reasons.append("UNKNOWN_SHIPPING_REQUIRED_TOTAL_MUST_BE_NULL")
            required_total = None
        elif required_total is not None and minimum_item_spend is not None and required_total < minimum_item_spend:
            reasons.append("REQUIRED_TOTAL_BELOW_ITEM_SPEND")
            required_total = None
        # R07 carries no authority that can enable a real affiliate destination. Even
        # internally consistent positive-looking inputs are deliberately non-authoritative.
        reasons.append("AFFILIATE_AUTHORITY_NOT_GRANTED_R07")
        if not request.user_initiated:
            reasons.append("USER_INITIATED_CLICK_REQUIRED")
        if affiliate.cta_enabled or affiliate.click_url is not None:
            reasons.append("UNTRUSTED_CLICK_URL_SUPPRESSED")
        if any((ceiling.runtime_authorized, ceiling.account_authorized, ceiling.cta_enabled, bool(ceiling.endpoint_hosts), bool(ceiling.redirect_hosts))):
            reasons.append("UNAUTHORIZED_POSITIVE_CEILING_SUPPRESSED")
        final_reasons = tuple(dict.fromkeys(reasons))
        event = build_event(
            identity=request.identity,
            series_key=snapshot.series_key,
            source_id=snapshot.source_id,
            coupon_id=coupon.coupon_id,
            eligibility_profile=request.eligibility_profile,
            data_version=snapshot.data_version,
            display_price_twd=display_price,
            display_basis=display_basis,
            coupon_applied=coupon_applied,
            cta_enabled=False,
            reasons=final_reasons,
            evaluated_at=now,
        )
        self.sink.emit(event)
        return CombinedDecision(
            state="SOURCE_AUTHORIZATION_REQUIRED",
            base_price_twd=base,
            before_coupon_price_twd=before,
            confirmed_coupon_price_twd=confirmed,
            display_price_twd=display_price,
            display_basis=display_basis,
            coupon_applied=coupon_applied,
            minimum_purchase_quantity=quantity,
            minimum_item_spend_twd=minimum_item_spend,
            shipping_status=snapshot.shipping_status,
            required_total_twd=required_total,
            source_permission_state=snapshot.source_permission.state,
            before_coupon_history_count=len(snapshot.before_coupon_history),
            confirmed_after_coupon_history_count=len(snapshot.confirmed_after_coupon_history),
            affiliate_trust_state=affiliate.state,
            cta_enabled=False,
            click_url=None,
            reason_codes=final_reasons,
            audit_event=event,
        )
