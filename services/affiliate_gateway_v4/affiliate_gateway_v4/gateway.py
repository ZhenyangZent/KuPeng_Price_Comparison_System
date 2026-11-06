"""Fail-closed evaluator for the F04 signed trust envelope candidate."""

from __future__ import annotations

from datetime import datetime

from .audit import MockSink, build_event
from .envelope import EnvelopeError, TrustEnvelopeCodec
from .models import AuthoritySnapshot, LinkRequest, TrustDecision
from .replay import InMemoryReplayGuard
from .url_policy import is_reserved_nonproduction_url, validate_policy, validate_url


REQUIRED_CAPABILITIES = frozenset(
    {
        "api_link_generation", "account_api_scope", "exact_product_variant_seller",
        "allowed_hosts_paths_redirects", "link_validity_revocation", "disclosure_for_tw",
    }
)


def _aware(value: datetime | None) -> bool:
    return value is not None and value.tzinfo is not None and value.utcoffset() is not None


class AffiliateTrustGatewayV4:
    def __init__(
        self,
        codec: TrustEnvelopeCodec,
        *,
        replay_guard: InMemoryReplayGuard | None = None,
        sink: MockSink | None = None,
    ) -> None:
        self.codec = codec
        self.replay_guard = replay_guard or InMemoryReplayGuard()
        self.sink = sink or MockSink()

    def _decision(
        self,
        *,
        request: LinkRequest,
        state: str,
        cta_enabled: bool,
        click_url: str | None,
        metadata_verified: bool,
        envelope_id: str | None,
        reasons: tuple[str, ...],
        now: datetime,
        audit_destination: str | None = None,
    ) -> TrustDecision:
        event = build_event(
            identity=request.identity,
            state=state,
            cta_enabled=cta_enabled,
            metadata_verified=metadata_verified,
            envelope_id=envelope_id,
            destination=audit_destination,
            reason_codes=reasons,
            evaluated_at=now,
        )
        self.sink.emit(event)
        return TrustDecision(state, cta_enabled, click_url, metadata_verified, envelope_id, reasons, event)

    def resolve(
        self,
        *,
        envelope: object | None,
        request: LinkRequest,
        authority: AuthoritySnapshot,
        now: datetime,
    ) -> TrustDecision:
        if not _aware(now):
            return self._decision(
                request=request, state="INVALID_INPUT", cta_enabled=False, click_url=None, metadata_verified=False,
                envelope_id=None, reasons=("EVALUATED_AT_INVALID",), now=now,
            )
        if authority.state not in {"RUNTIME_AUTHORIZED", "CONTRACT_FIXTURE_ONLY"}:
            return self._decision(
                request=request, state="SOURCE_AUTHORIZATION_REQUIRED", cta_enabled=False, click_url=None,
                metadata_verified=False, envelope_id=None, reasons=("SOURCE_AUTHORIZATION_REQUIRED",), now=now,
            )
        if envelope is None:
            return self._decision(
                request=request, state="DISABLED", cta_enabled=False, click_url=None, metadata_verified=False,
                envelope_id=None, reasons=("TRUST_ENVELOPE_REQUIRED",), now=now,
            )
        try:
            claims, key_id, envelope_id = self.codec.verify(envelope)
        except EnvelopeError as exc:
            return self._decision(
                request=request, state="DISABLED", cta_enabled=False, click_url=None, metadata_verified=False,
                envelope_id=None, reasons=(exc.code,), now=now,
            )
        errors: list[str] = list(request.identity.errors())
        if claims.issuer != "affiliate_gateway_v4" or claims.audience != "cdh_trusted_backend":
            errors.append("ISSUER_OR_AUDIENCE_INVALID")
        if claims.provider_id != authority.provider_id or claims.market != authority.market:
            errors.append("PROVIDER_OR_MARKET_MISMATCH")
        if claims.canonical_product_id != request.identity.canonical_product_id:
            errors.append("CANONICAL_PRODUCT_ID_MISMATCH")
        if claims.provider_product_id != request.identity.provider_product_id:
            errors.append("PROVIDER_PRODUCT_ID_MISMATCH")
        if claims.sku_id != request.identity.sku_id:
            errors.append("SKU_ID_MISMATCH")
        if claims.seller_id != request.identity.seller_id:
            errors.append("SELLER_ID_MISMATCH")
        if claims.original_url_sha256 != request.identity.original_url_sha256:
            errors.append("ORIGINAL_URL_HASH_MISMATCH")
        if not request.user_initiated:
            errors.append("USER_INITIATED_CLICK_REQUIRED")
        if authority.revoked:
            errors.append("AUTHORITY_REVOKED")
        if authority.account_state != "AUTHORIZED" and authority.state == "RUNTIME_AUTHORIZED":
            errors.append("ACCOUNT_NOT_AUTHORIZED")
        if authority.credential_state != "VALID" and authority.state == "RUNTIME_AUTHORIZED":
            errors.append("CREDENTIAL_NOT_VALID")
        if authority.state == "RUNTIME_AUTHORIZED":
            for name in sorted(REQUIRED_CAPABILITIES):
                capability = authority.capabilities.get(name)
                if capability is None or not capability.runtime_enabled or not capability.evidence_ids:
                    errors.append(f"CAPABILITY_{name.upper()}_NOT_RUNTIME_AUTHORIZED")
        errors.extend(validate_policy(authority.input_hosts, authority.input_paths, "INPUT_POLICY"))
        errors.extend(validate_policy(authority.output_hosts, authority.output_paths, "OUTPUT_POLICY"))
        errors.extend(
            validate_url(
                request.identity.original_url, allowed_hosts=authority.input_hosts, allowed_paths=authority.input_paths,
                label="ORIGINAL", deny_manual_tracking=True,
            )
        )
        errors.extend(
            validate_url(
                claims.verified_destination, allowed_hosts=authority.output_hosts, allowed_paths=authority.output_paths,
                label="DESTINATION", deny_manual_tracking=False,
            )
        )
        if claims.disclosure_text != authority.disclosure_text or not claims.disclosure_text:
            errors.append("DISCLOSURE_MISMATCH")
        required_evidence = frozenset().union(
            *(item.evidence_ids for name, item in authority.capabilities.items() if name in REQUIRED_CAPABILITIES)
        )
        if authority.state == "RUNTIME_AUTHORIZED" and (
            not required_evidence or not required_evidence.issubset(claims.official_evidence_ids)
        ):
            errors.append("OFFICIAL_EVIDENCE_INCOMPLETE")
        if claims.issued_at > now:
            errors.append("ENVELOPE_ISSUED_IN_FUTURE")
        if claims.expires_at <= now:
            errors.append("ENVELOPE_EXPIRED")
        ttl = (claims.expires_at - claims.issued_at).total_seconds()
        if not isinstance(authority.max_ttl_seconds, int) or authority.max_ttl_seconds <= 0 or ttl <= 0 or ttl > authority.max_ttl_seconds:
            errors.append("ENVELOPE_TTL_INVALID")
        if not _aware(authority.authority_expires_at) or authority.authority_expires_at <= now:
            errors.append("AUTHORITY_EXPIRED_OR_INVALID")
        elif claims.expires_at > authority.authority_expires_at:
            errors.append("ENVELOPE_OUTLIVES_AUTHORITY")
        if claims.revocation_status != "ACTIVE" or not claims.revocation_event_id:
            errors.append("REVOCATION_EVENT_NOT_ACTIVE")
        age = (now - claims.revocation_checked_at).total_seconds()
        if (
            not isinstance(authority.max_revocation_age_seconds, int)
            or authority.max_revocation_age_seconds <= 0
            or age < 0
            or age > authority.max_revocation_age_seconds
        ):
            errors.append("REVOCATION_READBACK_STALE")
        if claims.fixture_class not in {"CONTRACT_FIXTURE_TEST_ONLY", "OFFICIAL_RUNTIME"}:
            errors.append("FIXTURE_CLASS_INVALID")
        if claims.fixture_class == "CONTRACT_FIXTURE_TEST_ONLY" and authority.state != "CONTRACT_FIXTURE_ONLY":
            errors.append("FIXTURE_AUTHORITY_MISMATCH")
        if claims.fixture_class == "OFFICIAL_RUNTIME" and authority.state != "RUNTIME_AUTHORIZED":
            errors.append("OFFICIAL_RUNTIME_AUTHORITY_REQUIRED")
        if claims.fixture_class == "OFFICIAL_RUNTIME" and (
            is_reserved_nonproduction_url(request.identity.original_url)
            or is_reserved_nonproduction_url(claims.verified_destination)
        ):
            errors.append("NONPRODUCTION_HOST_DENIED_FOR_OFFICIAL_RUNTIME")
        reasons = tuple(dict.fromkeys(errors))
        if reasons:
            return self._decision(
                request=request, state="DISABLED", cta_enabled=False, click_url=None, metadata_verified=False,
                envelope_id=envelope_id, reasons=reasons, now=now, audit_destination=claims.verified_destination,
            )
        if not self.replay_guard.claim(
            issuer=claims.issuer, key_id=key_id, nonce=claims.nonce, binding_sha256=request.identity.binding_sha256,
            expires_at=claims.expires_at, now=now,
        ):
            return self._decision(
                request=request, state="DISABLED", cta_enabled=False, click_url=None, metadata_verified=False,
                envelope_id=envelope_id, reasons=("REPLAY_DETECTED",), now=now,
                audit_destination=claims.verified_destination,
            )
        if claims.fixture_class == "CONTRACT_FIXTURE_TEST_ONLY":
            return self._decision(
                request=request, state="CONTRACT_FIXTURE_VERIFIED_NONCLICKABLE", cta_enabled=False, click_url=None,
                metadata_verified=True, envelope_id=envelope_id,
                reasons=("CONTRACT_FIXTURE_NEVER_ENABLES_EXTERNAL_CTA",), now=now,
                audit_destination=claims.verified_destination,
            )
        return self._decision(
            request=request, state="VERIFIED", cta_enabled=True, click_url=claims.verified_destination,
            metadata_verified=True, envelope_id=envelope_id, reasons=(), now=now,
            audit_destination=claims.verified_destination,
        )
