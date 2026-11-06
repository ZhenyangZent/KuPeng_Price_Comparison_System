"""F08 CTA verifier: evaluates evidence but can never activate a link."""

from __future__ import annotations

from datetime import datetime, timedelta

from .contract import destination_parts
from .models import CandidateDestination, CapabilityEvidence, CouponContext, CtaDecision, LinkIntent, RuntimeAuthority


class AffiliateCtaVerifierF08:
    def evaluate(
        self, *, intent: LinkIntent, evidence: CapabilityEvidence, destination: CandidateDestination,
        coupon: CouponContext, authority: RuntimeAuthority, now: datetime,
    ) -> CtaDecision:
        reasons: list[str] = []
        binding = intent.identity.binding_sha256
        identity_matches = evidence.identity_binding_sha256 == binding and destination.identity_binding_sha256 == binding
        if not identity_matches:
            reasons.append("IDENTITY_BINDING_MISMATCH")
        if intent.identity.market != evidence.market or intent.identity.market != "TW":
            reasons.append("MARKET_MISMATCH")
        if not intent.user_initiated:
            reasons.append("USER_INITIATED_INTENT_REQUIRED")
        evidence_current = (
            evidence.issued_at <= now < evidence.expires_at
            and evidence.revoked_at is None
            and evidence.issued_at <= intent.requested_at <= now
        )
        if evidence.issued_at > now:
            reasons.append("CAPABILITY_EVIDENCE_NOT_YET_VALID")
        if now >= evidence.expires_at:
            reasons.append("CAPABILITY_EVIDENCE_EXPIRED")
        if evidence.revoked_at is not None:
            reasons.append("CAPABILITY_EVIDENCE_REVOKED")
        if intent.requested_at < evidence.issued_at or intent.requested_at > now:
            reasons.append("INTENT_TIME_OUTSIDE_EVIDENCE")
        if not evidence.product_level_supported:
            reasons.append("PRODUCT_LEVEL_CAPABILITY_UNVERIFIED")
        if destination.created_at < intent.requested_at or destination.created_at > now:
            reasons.append("DESTINATION_CREATION_TIME_INVALID")
        max_expiry = destination.created_at + timedelta(seconds=evidence.attribution_ttl_seconds)
        if destination.attribution_expires_at > max_expiry or now >= destination.attribution_expires_at:
            reasons.append("ATTRIBUTION_STALE_OR_TTL_EXCEEDED")
        host, path = destination_parts(destination)
        if host not in evidence.allowed_hosts:
            reasons.append("DESTINATION_HOST_NOT_ALLOWLISTED")
        if not any(path.startswith(prefix) for prefix in evidence.allowed_path_prefixes):
            reasons.append("DESTINATION_PATH_NOT_ALLOWLISTED")
        # Price, source permission and reference URLs are deliberately non-authoritative.
        reasons.append("COUPON_CONTEXT_NON_AUTHORITATIVE")
        if coupon.reference_url is not None:
            reasons.append("REFERENCE_URL_NON_AUTHORITATIVE")
        if evidence.evidence_classification == "CONTRACT_FIXTURE_TEST_ONLY":
            reasons.append("CAPABILITY_EVIDENCE_FIXTURE_ONLY")
        if (
            authority.state != "SOURCE_BLOCKED"
            or authority.official_tw_source_authorized
            or authority.official_tw_account_verified
            or authority.product_endpoint_verified
            or authority.host_rules_verified
            or authority.cta_enabled
            or authority.click_url is not None
            or authority.allowed_hosts
        ):
            reasons.append("F08_AUTHORITY_BOUNDARY_INVALID")
        reasons.append("OFFICIAL_TW_AFFILIATE_AUTHORITY_REQUIRED")
        final_reasons = tuple(dict.fromkeys(reasons))
        return CtaDecision(
            state="SOURCE_AUTHORIZATION_REQUIRED",
            identity_binding_sha256=binding,
            destination_host=host,
            evidence_current=evidence_current,
            identity_matches=identity_matches,
            cta_enabled=False,
            click_url=None,
            reason_codes=final_reasons,
        )
