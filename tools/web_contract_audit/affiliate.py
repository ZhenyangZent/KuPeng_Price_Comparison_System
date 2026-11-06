from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .models import Assessment, Finding


REDIRECT_KEYS = frozenset({"url", "redirect", "redirect_uri", "return", "return_url", "next", "target", "continue"})
UNKNOWN_RUNTIME_CAPABILITIES = frozenset({"link_generation", "api_credentials", "exact_product_variant_seller", "allowed_input_output_hosts", "link_validity_revocation", "disclosure_for_tw"})


def _finding(code: str, severity: str, owner: str, location: str, detail: str, reproduction: str, needs_a06: bool = False) -> Finding:
    return Finding(code, severity, owner, location, detail, reproduction, needs_a06)


def assess_affiliate_evidence(c03: dict[str, Any], f01_response: dict[str, Any]) -> Assessment:
    findings: list[Finding] = []
    capabilities = c03.get("capabilities") if isinstance(c03.get("capabilities"), dict) else {}
    for name in sorted(UNKNOWN_RUNTIME_CAPABILITIES):
        value = capabilities.get(name)
        if not isinstance(value, dict) or value.get("state") != "UNKNOWN" or value.get("runtime_enabled") is not False:
            findings.append(_finding("C03_RUNTIME_CAPABILITY_NOT_CLOSED", "CRITICAL", "C", f"capabilities.{name}", "Runtime capability must remain UNKNOWN/false.", f"Set {name} to a non-UNKNOWN state in a synthetic copy."))
    runtime = c03.get("runtime") if isinstance(c03.get("runtime"), dict) else {}
    if runtime.get("cta_enabled") is not False or runtime.get("affiliate_url") is not None or runtime.get("conversion_enabled") is not False:
        findings.append(_finding("C03_RUNTIME_ACTIVATION_DENIED", "CRITICAL", "C/F", "runtime", "Documentary evidence must not activate runtime CTA or conversion.", "Set a synthetic runtime URL or cta_enabled=true."))
    if runtime.get("output_host_allowlist") != []:
        findings.append(_finding("C03_HOST_ALLOWLIST_UNVERIFIED", "CRITICAL", "C/F", "runtime.output_host_allowlist", "No official output hosts are authorized yet.", "Add a host to a synthetic C03 evidence copy."))
    if f01_response.get("state") != "PENDING_OFFICIAL_DOCS":
        findings.append(_finding("F01_STATE_NOT_PENDING", "CRITICAL", "F", "affiliate.state", "F01 shell must remain pending.", "Change a synthetic response state to VERIFIED."))
    if f01_response.get("click_url") is not None or f01_response.get("cta_enabled") is not False:
        findings.append(_finding("F01_PENDING_RESPONSE_CLICKABLE", "CRITICAL", "F", "affiliate", "Pending provider cannot expose a URL or enabled CTA.", "Inject an ordinary Coupang URL into a synthetic response."))
    if f01_response.get("verified_product_match") is not False:
        findings.append(_finding("F01_PENDING_RESPONSE_CLAIMS_MATCH", "HIGH", "F", "affiliate.verified_product_match", "Pending provider cannot claim verified product binding.", "Set verified_product_match=true in a synthetic response."))
    return Assessment.from_iterable(findings, checks=len(UNKNOWN_RUNTIME_CAPABILITIES) + 6)


def _aware(value: datetime | None) -> bool:
    return value is not None and value.tzinfo is not None and value.utcoffset() is not None


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def validate_affiliate_candidate_url(candidate: dict[str, Any], policy: dict[str, Any], *, evaluated_at: datetime) -> Assessment:
    findings: list[Finding] = []
    reproduction = "Call validate_affiliate_candidate_url with the supplied synthetic candidate/policy pair."
    if policy.get("provider_state") != "RUNTIME_VERIFIED" or policy.get("account_authorized") is not True or policy.get("official_evidence_verified") is not True:
        findings.append(_finding("AFFILIATE_AUTHORITY_INCOMPLETE", "CRITICAL", "C/F", "policy", "Documentary evidence alone cannot enable a CTA.", reproduction))
    expected = policy.get("expected_identity") if isinstance(policy.get("expected_identity"), dict) else {}
    identity = candidate.get("identity") if isinstance(candidate.get("identity"), dict) else {}
    for field in ("product_id", "variant_id", "seller_id"):
        if not expected.get(field) or identity.get(field) != expected.get(field):
            findings.append(_finding(f"AFFILIATE_{field.upper()}_MISMATCH", "CRITICAL", "F", f"identity.{field}", "Exact identity binding failed.", reproduction))
    if candidate.get("revoked") is not False:
        findings.append(_finding("AFFILIATE_LINK_REVOKED", "CRITICAL", "F", "revoked", "Revoked links must fail closed.", reproduction))
    if candidate.get("user_initiated") is not True:
        findings.append(_finding("USER_INITIATED_CLICK_REQUIRED", "HIGH", "A/F", "user_initiated", "CTA cannot auto-open or simulate a click.", reproduction, True))
    if candidate.get("market") != "TW" or candidate.get("disclosure_text") != policy.get("required_disclosure_text") or not policy.get("required_disclosure_text"):
        findings.append(_finding("TW_MARKET_OR_DISCLOSURE_INVALID", "HIGH", "C/F", "market/disclosure", "TW market and exact disclosure are mandatory.", reproduction))
    hosts = policy.get("official_hosts")
    allowed_hosts = {str(value).casefold() for value in hosts} if isinstance(hosts, list) and hosts else set()
    url = candidate.get("click_url")
    try:
        parsed = urlsplit(url if isinstance(url, str) else "")
        host = (parsed.hostname or "").casefold()
        port = parsed.port
    except ValueError:
        parsed = None
        host = ""
        port = None
        findings.append(_finding("AFFILIATE_URL_MALFORMED", "CRITICAL", "F", "click_url", "URL cannot be parsed safely.", reproduction))
    if parsed is not None:
        if parsed.scheme != "https":
            findings.append(_finding("AFFILIATE_URL_NOT_HTTPS", "CRITICAL", "F", "click_url", "Only HTTPS is allowed.", reproduction))
        if parsed.username is not None or parsed.password is not None:
            findings.append(_finding("AFFILIATE_URL_USERINFO_DENIED", "CRITICAL", "F", "click_url", "URL userinfo is forbidden.", reproduction))
        if port not in (None, 443):
            findings.append(_finding("AFFILIATE_URL_PORT_DENIED", "HIGH", "F", "click_url", "Nonstandard ports are forbidden.", reproduction))
        if not allowed_hosts or host not in allowed_hosts:
            findings.append(_finding("AFFILIATE_HOST_NOT_OFFICIALLY_ALLOWED", "CRITICAL", "C/F", "click_url", "Host must exactly match the evidence-bound allowlist.", reproduction))
        try:
            query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)}
        except ValueError:
            findings.append(_finding("AFFILIATE_QUERY_MALFORMED", "HIGH", "F", "click_url", "Malformed query denied.", reproduction))
        else:
            if query_keys & REDIRECT_KEYS:
                findings.append(_finding("AFFILIATE_REDIRECT_PARAMETER_DENIED", "CRITICAL", "F", "click_url", "Redirect-bearing parameters are forbidden.", reproduction))
    generated = _parse_time(candidate.get("generated_at"))
    expires = _parse_time(candidate.get("expires_at"))
    max_ttl = policy.get("max_ttl_seconds")
    if not _aware(evaluated_at) or not _aware(generated) or not _aware(expires):
        findings.append(_finding("AFFILIATE_TIME_INVALID", "HIGH", "F", "generated_at/expires_at", "Timezone-aware timestamps are mandatory.", reproduction))
    else:
        if generated > evaluated_at:
            findings.append(_finding("AFFILIATE_CLOCK_ROLLBACK", "HIGH", "F/Orchestrator", "generated_at", "Evaluator clock precedes generation time.", reproduction))
        if expires <= evaluated_at:
            findings.append(_finding("AFFILIATE_LINK_EXPIRED", "CRITICAL", "F", "expires_at", "Expired links are disabled.", reproduction))
        ttl = (expires - generated).total_seconds()
        if not isinstance(max_ttl, int) or max_ttl <= 0 or ttl <= 0 or ttl > max_ttl:
            findings.append(_finding("AFFILIATE_TTL_INVALID", "HIGH", "F", "expires_at", "TTL exceeds the evidence-bound limit.", reproduction))
    return Assessment.from_iterable(findings, checks=14)
