"""Coupon pricing and affiliate CTA composition with one-way authority flow."""

from __future__ import annotations

from datetime import datetime

from .audit import MockSink, build_event
from .models import AffiliateTrustInput, CombinedDecision, CouponPriceSnapshot, GateRequest, RuntimeCeiling


CONFIRMED = "CONFIRMED_APPLICABLE"


def _same_identity(left, right) -> bool:
    return left == right


class AffiliateCouponGateV5:
    def __init__(self, *, sink: MockSink | None = None) -> None:
        self.sink = sink or MockSink()

    def evaluate(
        self,
        *,
        snapshot: CouponPriceSnapshot,
        request: GateRequest,
        affiliate: AffiliateTrustInput,
        ceiling: RuntimeCeiling,
        now: datetime,
    ) -> CombinedDecision:
        reasons: list[str] = []
        identity_matches = _same_identity(snapshot.series_identity, request.identity)
        if not identity_matches:
            reasons.append("COUPON_SERIES_IDENTITY_MISMATCH")
        base = snapshot.base_price_twd
        confirmed = snapshot.confirmed_coupon_price_twd
        coupon = snapshot.coupon
        evidence_complete = all(
            (
                coupon.eligibility_profile,
                coupon.scope_evidence,
                coupon.valid_from,
                coupon.valid_until,
                coupon.discount_twd is not None,
            )
        )
        if coupon.status != CONFIRMED:
            reasons.append(f"COUPON_STATUS_{coupon.status}_NOT_CONFIRMED")
        if request.eligibility_profile is None or coupon.eligibility_profile != request.eligibility_profile:
            reasons.append("COUPON_ELIGIBILITY_PROFILE_MISMATCH")
        if not evidence_complete:
            reasons.append("COUPON_EVIDENCE_INCOMPLETE")
        if coupon.valid_from is None or coupon.valid_until is None or not (coupon.valid_from <= now < coupon.valid_until):
            reasons.append("COUPON_NOT_CURRENTLY_VALID")
        if (
            coupon.valid_from is None
            or coupon.valid_until is None
            or not (coupon.valid_from <= snapshot.observed_at < coupon.valid_until)
        ):
            reasons.append("COUPON_NOT_VALID_AT_OBSERVATION")
        if snapshot.observed_at > now:
            reasons.append("OBSERVATION_IN_FUTURE")
        if coupon.status == CONFIRMED and snapshot.possible_coupon_price_twd is not None:
            reasons.append("POSSIBLE_PRICE_PRESENT_WITH_CONFIRMED")
        if base is None:
            reasons.append("BASE_PRICE_UNKNOWN")
        if confirmed is None:
            reasons.append("CONFIRMED_COUPON_PRICE_UNKNOWN")
        price_math_valid = False
        if base is not None and confirmed is not None and coupon.discount_twd is not None:
            if coupon.already_included_in_base:
                price_math_valid = confirmed == base
                if not price_math_valid:
                    reasons.append("ALREADY_INCLUDED_DOUBLE_DISCOUNT_RISK")
            elif coupon.discount_twd > base:
                reasons.append("COUPON_DISCOUNT_EXCEEDS_BASE")
            else:
                price_math_valid = confirmed == base - coupon.discount_twd
                if not price_math_valid:
                    reasons.append("CONFIRMED_COUPON_PRICE_MATH_MISMATCH")
        confirmed_applicable = (
            identity_matches
            and coupon.status == CONFIRMED
            and request.eligibility_profile is not None
            and coupon.eligibility_profile == request.eligibility_profile
            and evidence_complete
            and coupon.valid_from is not None
            and coupon.valid_until is not None
            and coupon.valid_from <= now < coupon.valid_until
            and coupon.valid_from <= snapshot.observed_at < coupon.valid_until
            and snapshot.observed_at <= now
            and snapshot.possible_coupon_price_twd is None
            and price_math_valid
        )
        if confirmed_applicable:
            display_price = confirmed
            display_basis = "CONFIRMED_ALREADY_INCLUDED" if coupon.already_included_in_base else "CONFIRMED_COUPON"
            coupon_applied = not coupon.already_included_in_base
        elif base is not None:
            display_price = base
            display_basis = "BASE"
            coupon_applied = False
            confirmed = None
        else:
            display_price = None
            display_basis = "PRICE_UNKNOWN"
            coupon_applied = False
            confirmed = None
        if snapshot.upstream_display_price_twd != display_price or snapshot.upstream_display_basis != display_basis:
            reasons.append("UPSTREAM_DISPLAY_MISMATCH")
        if snapshot.shipping_status == "UNKNOWN" and snapshot.upstream_required_total_twd is not None:
            reasons.append("UNKNOWN_SHIPPING_REQUIRED_TOTAL_MUST_BE_NULL")
        required_total = snapshot.upstream_required_total_twd
        if snapshot.shipping_status == "UNKNOWN":
            required_total = None
        affiliate_authorized = (
            ceiling.state == "RUNTIME_AUTHORIZED"
            and ceiling.runtime_authorized
            and ceiling.account_authorized
            and ceiling.cta_enabled
            and bool(ceiling.endpoint_hosts)
            and bool(ceiling.redirect_hosts)
        )
        if not affiliate_authorized:
            reasons.append("SOURCE_AUTHORIZATION_REQUIRED")
        if not request.user_initiated:
            reasons.append("USER_INITIATED_CLICK_REQUIRED")
        envelope_id_valid = (
            isinstance(affiliate.envelope_id, str)
            and len(affiliate.envelope_id) == 64
            and all(character in "0123456789abcdef" for character in affiliate.envelope_id)
        )
        affiliate_trust_valid = bool(
            affiliate.state == "VERIFIED"
            and affiliate.cta_enabled
            and affiliate.metadata_verified
            and affiliate.click_url
            and envelope_id_valid
        )
        if affiliate.cta_enabled and not affiliate_trust_valid:
            reasons.append("AFFILIATE_TRUST_INPUT_INVALID")
        cta_enabled = bool(
            affiliate_authorized
            and request.user_initiated
            and affiliate_trust_valid
        )
        click_url = affiliate.click_url if cta_enabled else None
        if not cta_enabled and affiliate.click_url is not None:
            reasons.append("UNTRUSTED_CLICK_URL_SUPPRESSED")
        state = "VERIFIED" if cta_enabled else "SOURCE_AUTHORIZATION_REQUIRED"
        final_reasons = tuple(dict.fromkeys(reasons))
        event = build_event(
            identity=request.identity,
            source_id=snapshot.source_id,
            coupon_id=coupon.coupon_id,
            eligibility_profile=request.eligibility_profile,
            affiliate_envelope_id=affiliate.envelope_id,
            display_price_twd=display_price,
            display_basis=display_basis,
            coupon_applied=coupon_applied,
            cta_enabled=cta_enabled,
            reasons=final_reasons,
            evaluated_at=now,
        )
        self.sink.emit(event)
        return CombinedDecision(
            state=state,
            base_price_twd=base,
            confirmed_coupon_price_twd=confirmed,
            display_price_twd=display_price,
            display_basis=display_basis,
            coupon_applied=coupon_applied,
            shipping_status=snapshot.shipping_status,
            required_total_twd=required_total,
            affiliate_trust_state=affiliate.state,
            cta_enabled=cta_enabled,
            click_url=click_url,
            reason_codes=final_reasons,
            audit_event=event,
        )
