"""Strict parsers and URL policy for F08 synthetic contract fixtures."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, unquote, urlsplit

from .models import (
    CandidateDestination,
    CapabilityEvidence,
    CouponContext,
    LinkIntent,
    ProductIdentity,
    RuntimeAuthority,
)


INTENT_FIELDS = frozenset({"schema_version", "identity", "requested_at", "user_initiated", "intent_nonce"})
IDENTITY_FIELDS = frozenset({"market", "platform", "product_id", "sku_id", "variant_id", "seller_id", "condition", "package_signature"})
EVIDENCE_FIELDS = frozenset(
    {
        "schema_version", "evidence_classification", "provider_id", "market", "account_reference_sha256",
        "product_level_supported", "issued_at", "expires_at", "revoked_at", "allowed_hosts",
        "allowed_path_prefixes", "attribution_ttl_seconds", "identity_binding_sha256", "endpoint_contract_sha256",
    }
)
DESTINATION_FIELDS = frozenset({"schema_version", "url", "created_at", "attribution_expires_at", "identity_binding_sha256"})
COUPON_FIELDS = frozenset({"status", "base_price_twd", "display_price_twd", "display_basis", "source_permission_allowed", "reference_url"})
AUTHORITY_FIELDS = frozenset({"state", "official_tw_source_authorized", "official_tw_account_verified", "product_endpoint_verified", "host_rules_verified", "cta_enabled", "click_url", "allowed_hosts"})
REDIRECT_KEYS = frozenset({"redirect", "redirect_url", "url", "next", "return", "return_url", "continue", "destination", "target", "callback"})
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _exact(value: object, fields: frozenset[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractError(code, f"exact fields required: {sorted(fields)}")
    return value


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 256:
        raise ContractError(f"{name.upper()}_INVALID", f"{name} must be a bounded non-empty string")
    if "://" in value or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ContractError(f"{name.upper()}_INVALID", f"{name} contains URL or control data")
    return value


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ContractError(f"{name.upper()}_INVALID", f"{name} must be lowercase SHA-256")
    return value


def _time(value: object, name: str, *, nullable: bool = False) -> datetime | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContractError(f"{name.upper()}_INVALID", f"{name} must use canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError(f"{name.upper()}_INVALID", f"{name} must be ISO-8601") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ContractError(f"{name.upper()}_INVALID", f"{name} must be UTC")
    return parsed.astimezone(timezone.utc)


def _price(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{name.upper()}_INVALID", f"{name} must be a non-negative integer or null")
    return value


def _host(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.lower() or value != value.strip() or len(value) > 253:
        raise ContractError("HOST_INVALID", "host must be bounded lowercase ASCII")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ContractError("UNICODE_HOST_REJECTED", "Unicode hostnames are not accepted") from exc
    if "*" in value or value.startswith(".") or value.endswith(".") or ".." in value:
        raise ContractError("HOST_INVALID", "wildcard or malformed host rejected")
    if any(label.startswith("xn--") for label in value.split(".")):
        raise ContractError("PUNYCODE_HOST_REJECTED", "punycode hostnames are not accepted in F08 fixtures")
    if value.encode("idna").decode("ascii") != value:
        raise ContractError("HOST_IDNA_MISMATCH", "host must be canonical ASCII")
    if not value.endswith(".invalid"):
        raise ContractError("NON_SYNTHETIC_HOST_REJECTED", "F08 accepts synthetic .invalid hosts only")
    return value


def _path_prefix(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 256:
        raise ContractError("PATH_PREFIX_INVALID", "path prefix must be a bounded absolute path")
    lowered = value.casefold()
    if "\\" in value or ".." in value or "//" in value or any(token in lowered for token in ("%2e", "%2f", "%5c")):
        raise ContractError("PATH_PREFIX_INVALID", "ambiguous path prefix rejected")
    return value


def parse_identity(value: object) -> ProductIdentity:
    data = _exact(value, IDENTITY_FIELDS, "IDENTITY_STRUCTURE_INVALID")
    identity = ProductIdentity(**{field: _identifier(data[field], field) for field in IDENTITY_FIELDS})
    if identity.market != "TW" or identity.platform != "COUPANG_TW":
        raise ContractError("MARKET_PLATFORM_INVALID", "TW / COUPANG_TW required")
    return identity


def identity_from_b11_product(product: object, *, explicit_variant_id: object) -> ProductIdentity:
    if not isinstance(product, dict) or product.get("data_classification") != "SYNTHETIC_FIXTURE":
        raise ContractError("B11_PRODUCT_INVALID", "synthetic B11 product required")
    raw = product.get("series_identity")
    if not isinstance(raw, dict) or set(raw) != {"platform", "product_id", "sku_id", "seller_id", "condition", "package_signature"}:
        raise ContractError("B11_IDENTITY_INVALID", "exact B11 series identity required")
    if explicit_variant_id is None:
        raise ContractError("VARIANT_ID_REQUIRED", "B11 has no explicit variant_id; separate evidence is required")
    return parse_identity(
        {
            "market": "TW",
            "platform": raw["platform"],
            "product_id": raw["product_id"],
            "sku_id": raw["sku_id"],
            "variant_id": explicit_variant_id,
            "seller_id": raw["seller_id"],
            "condition": raw["condition"],
            "package_signature": raw["package_signature"],
        }
    )


def parse_intent(value: object) -> LinkIntent:
    data = _exact(value, INTENT_FIELDS, "INTENT_STRUCTURE_INVALID")
    if data["schema_version"] != "CDH-F08-LINK-INTENT-1":
        raise ContractError("INTENT_SCHEMA_INVALID", "unexpected intent schema")
    if not isinstance(data["user_initiated"], bool):
        raise ContractError("USER_INITIATED_INVALID", "user_initiated must be boolean")
    return LinkIntent(
        schema_version=data["schema_version"], identity=parse_identity(data["identity"]),
        requested_at=_time(data["requested_at"], "requested_at"), user_initiated=data["user_initiated"],
        intent_nonce=_identifier(data["intent_nonce"], "intent_nonce"),
    )


def parse_evidence(value: object) -> CapabilityEvidence:
    data = _exact(value, EVIDENCE_FIELDS, "EVIDENCE_STRUCTURE_INVALID")
    if data["schema_version"] != "CDH-F08-CAPABILITY-EVIDENCE-1":
        raise ContractError("EVIDENCE_SCHEMA_INVALID", "unexpected evidence schema")
    if data["evidence_classification"] != "CONTRACT_FIXTURE_TEST_ONLY":
        raise ContractError("EVIDENCE_CLASSIFICATION_INVALID", "F08 accepts contract fixtures only")
    if data["provider_id"] != "coupang_tw_partners" or data["market"] != "TW":
        raise ContractError("PROVIDER_MARKET_INVALID", "Taiwan Partners candidate identity required")
    if not isinstance(data["product_level_supported"], bool):
        raise ContractError("PRODUCT_LEVEL_SUPPORTED_INVALID", "product_level_supported must be boolean")
    hosts = data["allowed_hosts"]
    prefixes = data["allowed_path_prefixes"]
    if not isinstance(hosts, list) or not hosts or not isinstance(prefixes, list) or not prefixes:
        raise ContractError("ALLOWLIST_INVALID", "non-empty host and path arrays required")
    parsed_hosts = tuple(_host(item) for item in hosts)
    parsed_prefixes = tuple(_path_prefix(item) for item in prefixes)
    if len(parsed_hosts) != len(set(parsed_hosts)) or list(parsed_hosts) != sorted(parsed_hosts):
        raise ContractError("HOST_ALLOWLIST_INVALID", "hosts must be sorted and unique")
    if len(parsed_prefixes) != len(set(parsed_prefixes)) or list(parsed_prefixes) != sorted(parsed_prefixes):
        raise ContractError("PATH_ALLOWLIST_INVALID", "path prefixes must be sorted and unique")
    ttl = data["attribution_ttl_seconds"]
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= 3600:
        raise ContractError("ATTRIBUTION_TTL_INVALID", "TTL must be 1..3600 seconds")
    return CapabilityEvidence(
        schema_version=data["schema_version"], evidence_classification=data["evidence_classification"],
        provider_id=data["provider_id"], market=data["market"],
        account_reference_sha256=_sha(data["account_reference_sha256"], "account_reference_sha256"),
        product_level_supported=data["product_level_supported"],
        issued_at=_time(data["issued_at"], "issued_at"), expires_at=_time(data["expires_at"], "expires_at"),
        revoked_at=_time(data["revoked_at"], "revoked_at", nullable=True),
        allowed_hosts=parsed_hosts, allowed_path_prefixes=parsed_prefixes, attribution_ttl_seconds=ttl,
        identity_binding_sha256=_sha(data["identity_binding_sha256"], "identity_binding_sha256"),
        endpoint_contract_sha256=_sha(data["endpoint_contract_sha256"], "endpoint_contract_sha256"),
    )


def parse_destination(value: object) -> CandidateDestination:
    data = _exact(value, DESTINATION_FIELDS, "DESTINATION_STRUCTURE_INVALID")
    if data["schema_version"] != "CDH-F08-CANDIDATE-DESTINATION-1":
        raise ContractError("DESTINATION_SCHEMA_INVALID", "unexpected destination schema")
    url = data["url"]
    if not isinstance(url, str) or len(url) > 2048:
        raise ContractError("DESTINATION_URL_INVALID", "bounded URL required")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ContractError("DESTINATION_URL_INVALID", "HTTPS URL without credentials or custom port required")
    _host(parsed.hostname)
    if parsed.fragment:
        raise ContractError("DESTINATION_FRAGMENT_REJECTED", "fragments are not permitted")
    raw_path = parsed.path or "/"
    if unquote(raw_path) != raw_path or "\\" in raw_path or ".." in raw_path or "//" in raw_path:
        raise ContractError("DESTINATION_PATH_AMBIGUOUS", "encoded or ambiguous paths rejected")
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    keys = [key.casefold() for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ContractError("DESTINATION_QUERY_DUPLICATE", "duplicate query keys rejected")
    blocked = sorted(set(keys) & REDIRECT_KEYS)
    if blocked:
        raise ContractError("OPEN_REDIRECT_PARAMETER_REJECTED", f"redirect-like parameters rejected: {blocked}")
    return CandidateDestination(
        schema_version=data["schema_version"], url=url,
        created_at=_time(data["created_at"], "created_at"),
        attribution_expires_at=_time(data["attribution_expires_at"], "attribution_expires_at"),
        identity_binding_sha256=_sha(data["identity_binding_sha256"], "identity_binding_sha256"),
    )


def parse_coupon_context(value: object) -> CouponContext:
    data = _exact(value, COUPON_FIELDS, "COUPON_CONTEXT_STRUCTURE_INVALID")
    if not isinstance(data["source_permission_allowed"], bool):
        raise ContractError("SOURCE_PERMISSION_INVALID", "source permission must be boolean")
    reference = data["reference_url"]
    if reference is not None and (not isinstance(reference, str) or len(reference) > 2048):
        raise ContractError("REFERENCE_URL_INVALID", "reference URL must be bounded or null")
    return CouponContext(
        status=_identifier(data["status"], "coupon_status"),
        base_price_twd=_price(data["base_price_twd"], "base_price_twd"),
        display_price_twd=_price(data["display_price_twd"], "display_price_twd"),
        display_basis=_identifier(data["display_basis"], "display_basis"),
        source_permission_allowed=data["source_permission_allowed"], reference_url=reference,
    )


def parse_authority(value: object) -> RuntimeAuthority:
    data = _exact(value, AUTHORITY_FIELDS, "AUTHORITY_STRUCTURE_INVALID")
    expected = {
        "state": "SOURCE_BLOCKED", "official_tw_source_authorized": False,
        "official_tw_account_verified": False, "product_endpoint_verified": False,
        "host_rules_verified": False, "cta_enabled": False, "click_url": None, "allowed_hosts": [],
    }
    if data != expected:
        raise ContractError("F08_AUTHORITY_BOUNDARY_INVALID", "F08 authority must remain source blocked and non-clickable")
    return RuntimeAuthority(
        state=data["state"], official_tw_source_authorized=False, official_tw_account_verified=False,
        product_endpoint_verified=False, host_rules_verified=False, cta_enabled=False, click_url=None,
        allowed_hosts=frozenset(),
    )


def destination_parts(destination: CandidateDestination) -> tuple[str, str]:
    parsed = urlsplit(destination.url)
    return parsed.hostname or "", parsed.path or "/"
