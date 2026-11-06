"""Fail-closed V2 affiliate binding decision."""

from __future__ import annotations

from datetime import datetime

from .audit import build_audit_summary
from .contracts import ContractError, parse_b06_affiliate_response
from .models import (
    BindingOutcome,
    CanonicalIdentity,
    CapabilitySnapshot,
    ProviderDecision,
)
from .url_policy import validate_authority_url_policy, validate_click_url


REQUIRED_RUNTIME_CAPABILITIES = frozenset(
    {
        "link_generation",
        "api_credentials",
        "exact_product_variant_seller",
        "allowed_input_output_hosts",
        "link_validity_revocation",
        "disclosure_for_tw",
    }
)
ABSORBING_STATES = frozenset({"REJECTED", "REVOKED", "EXPIRED"})


def _aware(value: datetime | None) -> bool:
    return value is not None and value.tzinfo is not None and value.utcoffset() is not None


def _disabled_state(capabilities: CapabilitySnapshot, provider: ProviderDecision) -> str:
    if capabilities.provider_state in ABSORBING_STATES:
        return capabilities.provider_state
    if provider.state in ABSORBING_STATES:
        return provider.state
    if capabilities.provider_state != "RUNTIME_VERIFIED":
        return capabilities.provider_state
    if provider.state != "RUNTIME_VERIFIED":
        return provider.state
    return "FAILED"


class AffiliateBindingV2:
    """Pure adapter; it performs no I/O and never opens the candidate URL."""

    @staticmethod
    def bind(
        *,
        b06_payload: object,
        identity: CanonicalIdentity,
        capabilities: CapabilitySnapshot,
        provider: ProviderDecision,
        evaluated_at: datetime,
    ) -> BindingOutcome:
        if not _aware(evaluated_at):
            reasons = ("EVALUATED_AT_INVALID",)
            return BindingOutcome(
                api_response=None,
                ui_cta_state="DISABLED",
                reason_codes=reasons,
                audit_summary=build_audit_summary(
                    identity=identity,
                    provider=provider,
                    state="INVALID_INPUT",
                    ui_cta_state="DISABLED",
                    reasons=reasons,
                    evaluated_at=evaluated_at,
                ),
            )
        try:
            b06 = parse_b06_affiliate_response(b06_payload)
        except ContractError as exc:
            reasons = (exc.code,)
            return BindingOutcome(
                api_response=None,
                ui_cta_state="DISABLED",
                reason_codes=reasons,
                audit_summary=build_audit_summary(
                    identity=identity,
                    provider=provider,
                    state="INVALID_INPUT",
                    ui_cta_state="DISABLED",
                    reasons=reasons,
                    evaluated_at=evaluated_at,
                ),
            )

        errors: list[str] = list(identity.errors())
        if b06.canonical_product_id != identity.canonical_product_id:
            errors.append("CANONICAL_PRODUCT_ID_MISMATCH")
        if capabilities.provider_id != "coupang_tw_partners" or capabilities.market != "TW":
            errors.append("C03_PROVIDER_OR_MARKET_MISMATCH")
        if capabilities.provider_state != "RUNTIME_VERIFIED":
            errors.append("C03_PROVIDER_NOT_RUNTIME_VERIFIED")
        if not capabilities.account_authorized:
            errors.append("C03_ACCOUNT_NOT_AUTHORIZED")
        if capabilities.revoked:
            errors.append("C03_AUTHORITY_REVOKED")
        for name in sorted(REQUIRED_RUNTIME_CAPABILITIES):
            item = capabilities.capabilities.get(name)
            if item is None or item.state != "RUNTIME_VERIFIED" or not item.runtime_enabled or not item.evidence_ids:
                errors.append(f"C03_CAPABILITY_{name.upper()}_NOT_RUNTIME_VERIFIED")
        errors.extend(
            validate_authority_url_policy(
                capabilities.output_hosts, capabilities.allowed_path_prefixes
            )
        )
        if not capabilities.disclosure_text:
            errors.append("C03_DISCLOSURE_MISSING")
        if not _aware(capabilities.authority_expires_at):
            errors.append("C03_AUTHORITY_EXPIRY_INVALID")
        elif capabilities.authority_expires_at <= evaluated_at:
            errors.append("C03_AUTHORITY_EXPIRED")
        if not isinstance(capabilities.max_link_ttl_seconds, int) or capabilities.max_link_ttl_seconds <= 0:
            errors.append("C03_TTL_POLICY_INVALID")

        if provider.state != "RUNTIME_VERIFIED":
            errors.append("F01_PROVIDER_NOT_RUNTIME_VERIFIED")
        if provider.market != "TW":
            errors.append("F01_PROVIDER_MARKET_MISMATCH")
        if provider.link_source != "OFFICIAL_PROVIDER":
            errors.append("F01_LINK_SOURCE_UNVERIFIED")
        if provider.revoked:
            errors.append("F01_LINK_REVOKED")
        if not provider.user_initiated:
            errors.append("USER_INITIATED_CLICK_REQUIRED")
        if not provider.verified_product_match:
            errors.append("F01_PRODUCT_MATCH_FALSE")
        if provider.bound_provider_product_id != identity.provider_product_id:
            errors.append("F01_PRODUCT_MISMATCH")
        if provider.bound_variant_id != identity.variant_id:
            errors.append("F01_VARIANT_MISMATCH")
        if provider.bound_seller_id != identity.seller_id:
            errors.append("F01_SELLER_MISMATCH")
        if provider.disclosure_text != capabilities.disclosure_text or not provider.disclosure_text:
            errors.append("F01_DISCLOSURE_MISMATCH")
        required_evidence = frozenset().union(
            *(item.evidence_ids for name, item in capabilities.capabilities.items() if name in REQUIRED_RUNTIME_CAPABILITIES)
        )
        if not required_evidence or not required_evidence.issubset(provider.evidence_ids):
            errors.append("F01_EVIDENCE_INCOMPLETE")
        errors.extend(
            validate_click_url(
                provider.click_url,
                allowed_hosts=capabilities.output_hosts,
                allowed_path_prefixes=capabilities.allowed_path_prefixes,
            )
        )
        if not _aware(provider.generated_at) or not _aware(provider.expires_at):
            errors.append("F01_LINK_TIME_INVALID")
        else:
            if provider.generated_at > evaluated_at:
                errors.append("F01_LINK_GENERATED_IN_FUTURE")
            if provider.expires_at <= evaluated_at:
                errors.append("F01_LINK_EXPIRED")
            if _aware(capabilities.authority_expires_at) and provider.expires_at > capabilities.authority_expires_at:
                errors.append("F01_LINK_OUTLIVES_AUTHORITY")
            ttl = (provider.expires_at - provider.generated_at).total_seconds()
            if (
                ttl <= 0
                or not isinstance(capabilities.max_link_ttl_seconds, int)
                or capabilities.max_link_ttl_seconds <= 0
                or ttl > capabilities.max_link_ttl_seconds
            ):
                errors.append("F01_LINK_TTL_INVALID")

        reasons = tuple(dict.fromkeys(errors))
        enabled = not reasons
        state = "RUNTIME_VERIFIED" if enabled else _disabled_state(capabilities, provider)
        affiliate = {
            "state": state,
            "click_url": provider.click_url if enabled else None,
            "verified_product_match": enabled,
            "bound_product_id": identity.canonical_product_id if enabled else None,
        }
        response = {
            "schema_version": "CDH-WEB-CONTRACT-V2",
            "product_id": b06.canonical_product_id,
            "data_source_status": b06.data_source_status,
            "data_classification": b06.data_classification,
            "contract_compatibility": ["CDH-WEB-CONTRACT-V1"],
            "affiliate": affiliate,
        }
        ui_state = "ENABLED" if enabled else "DISABLED"
        return BindingOutcome(
            api_response=response,
            ui_cta_state=ui_state,
            reason_codes=reasons,
            audit_summary=build_audit_summary(
                identity=identity,
                provider=provider,
                state=state,
                ui_cta_state=ui_state,
                reasons=reasons,
                evaluated_at=evaluated_at,
            ),
        )
