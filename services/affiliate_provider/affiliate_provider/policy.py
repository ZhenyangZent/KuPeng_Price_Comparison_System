"""Pure offline validation for a future verified affiliate link candidate.

Passing this validator does not activate F01.  The production provider remains
PENDING_OFFICIAL_DOCS until a separately reviewed authority update replaces it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit

from .models import ProductIdentity


REQUIRED_VERIFIED_CAPABILITIES = frozenset(
    {
        "url_conversion",
        "exact_variant_binding",
        "official_output_host_allowlist",
        "ttl_and_revocation",
        "tw_disclosure_rule",
    }
)
REDIRECT_QUERY_KEYS = frozenset(
    {"url", "redirect", "redirect_uri", "return", "return_url", "next", "target", "continue"}
)


@dataclass(frozen=True, slots=True)
class AffiliateCandidate:
    market: str
    click_url: str
    identity: ProductIdentity
    generated_at: datetime
    expires_at: datetime
    disclosure_text: str
    evidence_ids: frozenset[str]
    verified_capabilities: frozenset[str]
    link_source: str = "OFFICIAL_PROVIDER"
    revoked: bool = False
    user_initiated: bool = True


@dataclass(frozen=True, slots=True)
class CandidatePolicy:
    expected_identity: ProductIdentity
    evaluated_at: datetime
    official_output_hosts: frozenset[str]
    required_evidence_ids: frozenset[str]
    required_disclosure_text: str
    max_link_ttl_seconds: int
    provider_state: str
    provider_account_eligible: bool
    official_evidence_verified: bool
    authority_revoked: bool = False


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _host_errors(hosts: frozenset[str]) -> list[str]:
    errors: list[str] = []
    if not hosts:
        return ["OFFICIAL_HOST_ALLOWLIST_EMPTY"]
    for host in hosts:
        if (
            not isinstance(host, str)
            or not host
            or not host.isascii()
            or host != host.casefold()
            or host.startswith(".")
            or host.endswith(".")
            or "*" in host
            or any(character in host for character in "/\\:@?#")
        ):
            errors.append("OFFICIAL_HOST_ALLOWLIST_INVALID")
            break
    return errors


def _url_errors(url: object, allowed_hosts: frozenset[str]) -> list[str]:
    if not isinstance(url, str) or not url or any(ord(character) < 0x20 for character in url):
        return ["AFFILIATE_URL_INVALID"]
    if "\\" in url:
        return ["AFFILIATE_URL_BACKSLASH_DENIED"]
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return ["AFFILIATE_URL_MALFORMED"]
    errors: list[str] = []
    if parsed.scheme != "https":
        errors.append("AFFILIATE_URL_NOT_HTTPS")
    if parsed.username is not None or parsed.password is not None:
        errors.append("AFFILIATE_URL_USERINFO_DENIED")
    if port not in (None, 443):
        errors.append("AFFILIATE_URL_PORT_DENIED")
    if parsed.fragment:
        errors.append("AFFILIATE_URL_FRAGMENT_DENIED")
    normalized_host = host.casefold() if isinstance(host, str) else ""
    if not normalized_host or not normalized_host.isascii() or normalized_host.endswith("."):
        errors.append("AFFILIATE_HOST_INVALID")
    elif normalized_host not in allowed_hosts:
        errors.append("AFFILIATE_HOST_NOT_ALLOWED")
    try:
        query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)}
    except ValueError:
        errors.append("AFFILIATE_QUERY_MALFORMED")
    else:
        if query_keys & REDIRECT_QUERY_KEYS:
            errors.append("OPEN_REDIRECT_PARAMETER_DENIED")
    return errors


def validate_candidate(candidate: AffiliateCandidate, policy: CandidatePolicy) -> tuple[str, ...]:
    """Return stable fail-closed reason codes; never opens or requests the URL."""

    errors: list[str] = []
    if policy.provider_state != "VERIFIED":
        errors.append("PROVIDER_NOT_VERIFIED")
    if not policy.provider_account_eligible:
        errors.append("PROVIDER_ACCOUNT_INELIGIBLE")
    if not policy.official_evidence_verified:
        errors.append("OFFICIAL_EVIDENCE_UNVERIFIED")
    if policy.authority_revoked:
        errors.append("PROVIDER_AUTHORITY_REVOKED")
    if candidate.revoked:
        errors.append("AFFILIATE_LINK_REVOKED")
    if not candidate.user_initiated:
        errors.append("USER_INITIATED_CLICK_REQUIRED")
    if candidate.market != "TW":
        errors.append("AFFILIATE_MARKET_MISMATCH")
    errors.extend(policy.expected_identity.errors())
    errors.extend(candidate.identity.errors())
    if candidate.identity.product_id != policy.expected_identity.product_id:
        errors.append("AFFILIATE_PRODUCT_MISMATCH")
    if candidate.identity.variant_id != policy.expected_identity.variant_id:
        errors.append("AFFILIATE_VARIANT_MISMATCH")
    if candidate.identity.seller_id != policy.expected_identity.seller_id:
        errors.append("AFFILIATE_SELLER_MISMATCH")
    if candidate.link_source != "OFFICIAL_PROVIDER":
        errors.append("AFFILIATE_LINK_SOURCE_UNVERIFIED")
    errors.extend(_host_errors(policy.official_output_hosts))
    errors.extend(_url_errors(candidate.click_url, policy.official_output_hosts))
    ttl_policy_valid = isinstance(policy.max_link_ttl_seconds, int) and policy.max_link_ttl_seconds > 0
    if not ttl_policy_valid:
        errors.append("PROVIDER_TTL_POLICY_INVALID")
    if not _aware(policy.evaluated_at) or not _aware(candidate.generated_at) or not _aware(candidate.expires_at):
        errors.append("AFFILIATE_TIME_INVALID")
    else:
        if candidate.generated_at > policy.evaluated_at:
            errors.append("AFFILIATE_GENERATED_IN_FUTURE")
        if candidate.expires_at <= policy.evaluated_at:
            errors.append("AFFILIATE_LINK_EXPIRED")
        ttl = (candidate.expires_at - candidate.generated_at).total_seconds()
        if ttl <= 0 or (ttl_policy_valid and ttl > policy.max_link_ttl_seconds):
            errors.append("AFFILIATE_TTL_INVALID")
    if not policy.required_disclosure_text or candidate.disclosure_text != policy.required_disclosure_text:
        errors.append("AFFILIATE_DISCLOSURE_MISSING_OR_MISMATCHED")
    if not policy.required_evidence_ids or not policy.required_evidence_ids.issubset(candidate.evidence_ids):
        errors.append("AFFILIATE_EVIDENCE_INCOMPLETE")
    if not REQUIRED_VERIFIED_CAPABILITIES.issubset(candidate.verified_capabilities):
        errors.append("AFFILIATE_CAPABILITY_INCOMPLETE")
    return tuple(dict.fromkeys(errors))
