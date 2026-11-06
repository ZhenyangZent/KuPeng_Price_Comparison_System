"""Strict loader for the C02 fail-closed provider contract.

The caller must pass an explicit local path.  This module intentionally has no
environment loader and no network client.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


CONTRACT_SCHEMA_VERSION = "CDH-AFFILIATE-PROVIDER-CONTRACT-V1"
EXPECTED_PROVIDER_ID = "coupang_tw_partners"
EXPECTED_MARKET = "TW"
EXPECTED_STATE = "PENDING_OFFICIAL_DOCS"
OFFICIAL_EVIDENCE_HOSTS = frozenset({"privacy.coupang.com", "developers.coupang.com"})
FORBIDDEN_SECRET_KEYS = frozenset(
    {"access_key", "secret_key", "api_key", "token", "password", "cookie", "authorization"}
)
REQUIRED_FALSE_GATES = frozenset(
    {
        "cta_enabled",
        "tw_capability_verified",
        "provider_account_eligible",
        "host_allowlist_verified",
        "exact_match_verified",
        "ttl_and_revocation_verified",
        "disclosure_verified_for_tw",
        "user_intent_verified",
    }
)
REQUIRED_FALSE_BOUNDARIES = frozenset(
    {"auto_open", "coupon_claim", "add_to_cart", "checkout", "order", "payment"}
)
REQUIRED_UNKNOWN_CAPABILITIES = frozenset(
    {
        "url_conversion",
        "exact_variant_binding",
        "commission_eligibility",
        "tw_rate_limit",
        "tw_disclosure_rule",
    }
)
REQUIRED_PROHIBITIONS = frozenset(
    {
        "NO_FAKE_ENDPOINT",
        "NO_DIRECT_PRODUCT_URL_FALLBACK_AS_AFFILIATE",
        "NO_KR_RULE_TRANSPLANT_TO_TW",
        "NO_SELLER_API_AS_AFFILIATE_PROVIDER",
        "NO_PROVIDER_DATA_PRICE_HISTORY_WITHOUT_RIGHTS",
        "NO_LIVE_REQUEST_BEFORE_AUTHORITY",
    }
)


class ContractError(ValueError):
    """Raised when the controlled C02 contract is not safely fail-closed."""


@dataclass(frozen=True, slots=True)
class ProviderContract:
    provider_id: str
    market: str
    state: str
    as_of: str
    evidence_ids: tuple[str, ...]


def _walk_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).casefold())
            keys.update(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_walk_keys(child))
    return keys


def _require_false_map(data: object, required: frozenset[str], label: str) -> None:
    if not isinstance(data, dict) or not required.issubset(data):
        raise ContractError(f"{label} is incomplete")
    if any(data[name] is not False for name in required):
        raise ContractError(f"{label} must remain false")


def validate_provider_contract(data: object) -> ProviderContract:
    if not isinstance(data, dict):
        raise ContractError("contract must be a JSON object")
    if data.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        raise ContractError("unsupported schema_version")
    if data.get("provider_id") != EXPECTED_PROVIDER_ID or data.get("market") != EXPECTED_MARKET:
        raise ContractError("provider identity must be Coupang Partners Taiwan")
    if data.get("provider_state") != EXPECTED_STATE:
        raise ContractError("F01 production shell requires PENDING_OFFICIAL_DOCS")
    if data.get("source_discovery_status") != "SOURCE_BLOCKED":
        raise ContractError("affiliate contract cannot unlock source discovery")
    forbidden = sorted(_walk_keys(data) & FORBIDDEN_SECRET_KEYS)
    if forbidden:
        raise ContractError(f"secret-bearing keys are forbidden: {forbidden}")

    capabilities = data.get("capabilities")
    if not isinstance(capabilities, dict):
        raise ContractError("capabilities are missing")
    if any(capabilities.get(name) != "UNKNOWN" for name in REQUIRED_UNKNOWN_CAPABILITIES):
        raise ContractError("Taiwan activation capabilities must remain UNKNOWN")
    request = data.get("request")
    if not isinstance(request, dict) or request.get("user_initiated_click_required") is not True:
        raise ContractError("user-initiated click requirement is missing")
    if not REQUIRED_PROHIBITIONS.issubset(set(data.get("prohibitions") or [])):
        raise ContractError("required provider prohibitions are missing")

    conversion = data.get("conversion")
    if not isinstance(conversion, dict) or conversion.get("enabled") is not False:
        raise ContractError("conversion must be disabled")
    for name in ("endpoint", "authentication_contract", "rate_limit", "cache_ttl_seconds"):
        if conversion.get(name) is not None:
            raise ContractError(f"conversion.{name} must be null")
    for name in ("input_host_allowlist", "output_host_allowlist"):
        if conversion.get(name) != []:
            raise ContractError(f"conversion.{name} must be empty")

    response = data.get("response")
    if not isinstance(response, dict):
        raise ContractError("response contract is missing")
    if response.get("affiliate_url") is not None or response.get("disclosure_text") is not None:
        raise ContractError("pending response cannot expose a URL or disclosure")
    if response.get("verified_product_match") is not False:
        raise ContractError("pending response cannot claim an exact product match")
    if response.get("error_code") != EXPECTED_STATE:
        raise ContractError("pending response error_code must preserve provider state")

    _require_false_map(data.get("gates"), REQUIRED_FALSE_GATES, "runtime gates")
    _require_false_map(data.get("transaction_boundaries"), REQUIRED_FALSE_BOUNDARIES, "transaction boundaries")

    evidence = data.get("evidence")
    if not isinstance(evidence, list):
        raise ContractError("evidence must be an array")
    evidence_ids: list[str] = []
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("evidence_id"), str):
            raise ContractError("evidence identity is invalid")
        parsed = urlsplit(item.get("url") if isinstance(item.get("url"), str) else "")
        if parsed.scheme != "https" or not parsed.hostname:
            raise ContractError("evidence URL must be HTTPS")
        if item.get("market") == "TW":
            if item.get("authority_class") != "COUPANG_OFFICIAL":
                raise ContractError("Taiwan evidence must be official")
            if parsed.hostname.casefold() not in OFFICIAL_EVIDENCE_HOSTS:
                raise ContractError("Taiwan evidence host is not approved")
            if not item.get("document_version") or not item.get("effective_date"):
                raise ContractError("Taiwan evidence requires version and effective date")
        elif item.get("market") == "KR":
            if item.get("supports") or item.get("taiwan_applicability") != "UNKNOWN":
                raise ContractError("Korean evidence cannot authorize Taiwan capability")
        evidence_ids.append(item["evidence_id"])
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ContractError("evidence IDs must be unique")

    return ProviderContract(
        provider_id=EXPECTED_PROVIDER_ID,
        market=EXPECTED_MARKET,
        state=EXPECTED_STATE,
        as_of=str(data.get("as_of") or "UNKNOWN"),
        evidence_ids=tuple(evidence_ids),
    )


def load_provider_contract(path: str | Path) -> ProviderContract:
    contract_path = Path(path)
    if contract_path.is_symlink() or not contract_path.is_file():
        raise ContractError("contract must be a regular local file")
    try:
        data: Any = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"contract cannot be loaded: {exc}") from exc
    return validate_provider_contract(data)
