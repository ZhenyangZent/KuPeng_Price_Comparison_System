"""F03 gateway orchestration; offline and fail-closed by construction."""

from __future__ import annotations

from datetime import datetime

from .cache import VerifiedLinkCache
from .contracts import ContractError, parse_b06_affiliate_response
from .models import AdapterResult, AuthoritySnapshot, GatewayDecision, LinkRequest
from .provider import ProviderAdapter
from .sink import MockSink, build_event
from .url_policy import validate_policy, validate_url


REQUIRED_CAPABILITIES = frozenset(
    {
        "api_link_generation",
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


class AffiliateGatewayV3:
    def __init__(self, provider: ProviderAdapter, *, cache: VerifiedLinkCache | None = None, sink: MockSink | None = None) -> None:
        self.provider = provider
        self.cache = cache or VerifiedLinkCache()
        self.sink = sink or MockSink()

    def _decision(
        self,
        *,
        parsed,
        request: LinkRequest,
        result: AdapterResult | None,
        state: str,
        enabled: bool,
        reasons: tuple[str, ...],
        now: datetime,
        cache_status: str,
    ) -> GatewayDecision:
        affiliate = {
            "state": "VERIFIED" if enabled else state,
            "click_url": result.verified_destination if enabled and result else None,
            "verified_product_match": enabled,
            "bound_product_id": request.identity.canonical_product_id if enabled else None,
        }
        response = None
        if parsed is not None:
            response = {
                "schema_version": "CDH-WEB-CONTRACT-V2",
                "product_id": parsed.canonical_product_id,
                "data_source_status": parsed.data_source_status,
                "data_classification": parsed.data_classification,
                "contract_compatibility": ["CDH-WEB-CONTRACT-V1"],
                "affiliate": affiliate,
            }
        event = build_event(
            identity=request.identity,
            result=result,
            state=affiliate["state"],
            cta_enabled=enabled,
            reasons=reasons,
            evaluated_at=now,
            cache_status=cache_status,
        )
        self.sink.emit(event)
        return GatewayDecision(
            api_response=response,
            state=affiliate["state"],
            cta_enabled=enabled,
            verified_destination=affiliate["click_url"],
            expires_at=result.expires_at.isoformat() if enabled and result and result.expires_at else None,
            official_evidence_ids=tuple(sorted(result.official_evidence_ids)) if enabled and result else (),
            reason_codes=reasons,
            audit_event=event,
            cache_status=cache_status,
        )

    def resolve(
        self,
        *,
        b06_payload: object,
        request: LinkRequest,
        authority: AuthoritySnapshot,
        now: datetime,
    ) -> GatewayDecision:
        if not _aware(now):
            return self._decision(
                parsed=None,
                request=request,
                result=None,
                state="INVALID_INPUT",
                enabled=False,
                reasons=("EVALUATED_AT_INVALID",),
                now=now,
                cache_status="BYPASS",
            )
        try:
            parsed = parse_b06_affiliate_response(b06_payload)
        except ContractError as exc:
            return self._decision(
                parsed=None,
                request=request,
                result=None,
                state="INVALID_INPUT",
                enabled=False,
                reasons=(exc.code,),
                now=now,
                cache_status="BYPASS",
            )
        errors: list[str] = list(request.identity.errors())
        if parsed.canonical_product_id != request.identity.canonical_product_id:
            errors.append("CANONICAL_PRODUCT_ID_MISMATCH")
        if not request.user_initiated:
            errors.append("USER_INITIATED_CLICK_REQUIRED")
        if authority.provider_id != "coupang_tw_partners" or authority.market != "TW":
            errors.append("AUTHORITY_PROVIDER_OR_MARKET_MISMATCH")
        if authority.provider_state != "RUNTIME_VERIFIED":
            errors.append("AUTHORITY_NOT_RUNTIME_VERIFIED")
        if authority.account_state != "AUTHORIZED":
            errors.append("ACCOUNT_NOT_AUTHORIZED")
        if authority.credential_state != "VALID":
            errors.append("CREDENTIAL_NOT_VALID")
        if authority.revoked:
            errors.append("AUTHORITY_REVOKED")
        for name in sorted(REQUIRED_CAPABILITIES):
            item = authority.capabilities.get(name)
            if item is None or item.state != "RUNTIME_VERIFIED" or not item.runtime_enabled or not item.evidence_ids:
                errors.append(f"CAPABILITY_{name.upper()}_NOT_RUNTIME_VERIFIED")
        errors.extend(validate_policy(authority.input_hosts, authority.input_path_prefixes, "INPUT_POLICY"))
        errors.extend(validate_policy(authority.output_hosts, authority.output_path_prefixes, "OUTPUT_POLICY"))
        errors.extend(
            validate_url(
                request.identity.original_url,
                allowed_hosts=authority.input_hosts,
                allowed_paths=authority.input_path_prefixes,
                label="ORIGINAL",
                deny_manual_tracking=True,
            )
        )
        if not authority.disclosure_text:
            errors.append("AUTHORITY_DISCLOSURE_MISSING")
        if not _aware(authority.authority_expires_at):
            errors.append("AUTHORITY_EXPIRY_INVALID")
        elif authority.authority_expires_at <= now:
            errors.append("AUTHORITY_EXPIRED")
        if not isinstance(authority.max_link_ttl_seconds, int) or authority.max_link_ttl_seconds <= 0:
            errors.append("AUTHORITY_TTL_POLICY_INVALID")
        if not isinstance(authority.max_revocation_age_seconds, int) or authority.max_revocation_age_seconds <= 0:
            errors.append("AUTHORITY_REVOCATION_POLICY_INVALID")
        if errors:
            state = authority.provider_state if authority.provider_state != "RUNTIME_VERIFIED" else "DISABLED"
            if authority.provider_state in ABSORBING_STATES:
                state = authority.provider_state
            return self._decision(
                parsed=parsed,
                request=request,
                result=None,
                state=state,
                enabled=False,
                reasons=tuple(dict.fromkeys(errors)),
                now=now,
                cache_status="BYPASS",
            )

        cached = self.cache.get(
            request.identity,
            now=now,
            max_revocation_age_seconds=authority.max_revocation_age_seconds,
        )
        cache_status = "HIT" if cached is not None else "MISS"
        result = cached
        if result is None:
            try:
                result = self.provider.resolve(request)
            except Exception:
                return self._decision(
                    parsed=parsed,
                    request=request,
                    result=None,
                    state="FAILED",
                    enabled=False,
                    reasons=("PROVIDER_RESOLUTION_FAILED",),
                    now=now,
                    cache_status="MISS",
                )

        result_errors: list[str] = []
        if result.status != "VERIFIED":
            result_errors.append("PROVIDER_RESULT_NOT_VERIFIED")
        if result.provider_id != authority.provider_id or result.market != "TW":
            result_errors.append("PROVIDER_RESULT_IDENTITY_INVALID")
        if not result.generated_by_official_provider:
            result_errors.append("PROVIDER_GENERATION_UNVERIFIED")
        if result.bound_provider_product_id != request.identity.provider_product_id:
            result_errors.append("PROVIDER_PRODUCT_MISMATCH")
        if result.bound_variant_id != request.identity.variant_id:
            result_errors.append("PROVIDER_VARIANT_MISMATCH")
        if result.bound_seller_id != request.identity.seller_id:
            result_errors.append("PROVIDER_SELLER_MISMATCH")
        if result.disclosure_text != authority.disclosure_text or not result.disclosure_text:
            result_errors.append("PROVIDER_DISCLOSURE_MISMATCH")
        required_evidence = frozenset().union(
            *(item.evidence_ids for name, item in authority.capabilities.items() if name in REQUIRED_CAPABILITIES)
        )
        if not required_evidence or not required_evidence.issubset(result.official_evidence_ids):
            result_errors.append("PROVIDER_EVIDENCE_INCOMPLETE")
        result_errors.extend(
            validate_url(
                result.verified_destination,
                allowed_hosts=authority.output_hosts,
                allowed_paths=authority.output_path_prefixes,
                label="DESTINATION",
                deny_manual_tracking=False,
            )
        )
        if not _aware(result.generated_at) or not _aware(result.expires_at):
            result_errors.append("PROVIDER_LINK_TIME_INVALID")
        else:
            if result.generated_at > now:
                result_errors.append("PROVIDER_LINK_GENERATED_IN_FUTURE")
            if result.expires_at <= now:
                result_errors.append("PROVIDER_LINK_EXPIRED")
            if _aware(authority.authority_expires_at) and result.expires_at > authority.authority_expires_at:
                result_errors.append("PROVIDER_LINK_OUTLIVES_AUTHORITY")
            ttl = (result.expires_at - result.generated_at).total_seconds()
            if ttl <= 0 or ttl > authority.max_link_ttl_seconds:
                result_errors.append("PROVIDER_LINK_TTL_INVALID")
        if result.revocation_status != "ACTIVE":
            result_errors.append("PROVIDER_REVOCATION_NOT_ACTIVE")
        if not result.revocation_event_id:
            result_errors.append("PROVIDER_REVOCATION_EVENT_MISSING")
        if not _aware(result.revocation_checked_at):
            result_errors.append("PROVIDER_REVOCATION_CHECK_MISSING")
        else:
            age = (now - result.revocation_checked_at).total_seconds()
            if age < 0 or age > authority.max_revocation_age_seconds:
                result_errors.append("PROVIDER_REVOCATION_CHECK_STALE")

        reasons = tuple(dict.fromkeys(result_errors))
        enabled = not reasons
        if enabled and cache_status == "MISS":
            self.cache.put(request.identity, result)
        return self._decision(
            parsed=parsed,
            request=request,
            result=result,
            state="VERIFIED" if enabled else "DISABLED",
            enabled=enabled,
            reasons=reasons,
            now=now,
            cache_status=cache_status,
        )
