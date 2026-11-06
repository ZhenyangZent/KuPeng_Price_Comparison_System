"""Strict local loaders for the frozen B06, C03, and F01 contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    B06AffiliateResponse,
    CapabilitySnapshot,
    CapabilityState,
    DISABLED_STATES,
    ProviderDecision,
    identifier_errors,
)


B06_SCHEMA = "CDH-WEB-CONTRACT-V2"
C03_SCHEMA = "CDH-AFFILIATE-CAPABILITY-EVIDENCE-V2"
F01_SCHEMA = "CDH-AFFILIATE-PROVIDER-CONTRACT-V1"
CLASSIFICATION_PAIRS = {
    ("USER_RECORDED_ONLY", "USER_RECORDED"),
    ("SYNTHETIC_FIXTURE_ONLY", "SYNTHETIC_DEMO_ONLY"),
}
EXPECTED_B06_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "product_id",
        "data_source_status",
        "data_classification",
        "contract_compatibility",
        "affiliate",
    }
)
EXPECTED_B06_AFFILIATE = frozenset(
    {"state", "click_url", "verified_product_match", "bound_product_id"}
)
FORBIDDEN_SECRET_KEYS = frozenset(
    {
        "access_key",
        "secret_key",
        "api_key",
        "token",
        "password",
        "cookie",
        "authorization",
        "account_id",
        "account_identifier",
    }
)


class ContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


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


def _load_json(path: str | Path, label: str) -> dict[str, Any]:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ContractError(f"{label}_FILE_INVALID", f"{label} must be a regular local file")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label}_JSON_INVALID", str(exc)) from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label}_ROOT_INVALID", f"{label} root must be an object")
    forbidden = sorted(_walk_keys(value) & FORBIDDEN_SECRET_KEYS)
    if forbidden:
        raise ContractError(f"{label}_SECRET_KEY_DENIED", f"secret-bearing keys denied: {forbidden}")
    return value


def parse_b06_affiliate_response(value: object) -> B06AffiliateResponse:
    if not isinstance(value, dict):
        raise ContractError("B06_STRUCTURE_INVALID", "B06 response must be an object")
    if set(value) != EXPECTED_B06_TOP_LEVEL:
        raise ContractError("B06_STRUCTURE_INVALID", "B06 V2 top-level fields must match the frozen contract")
    if value.get("schema_version") != B06_SCHEMA:
        raise ContractError("B06_SCHEMA_INVALID", "legacy V1 and unknown schemas are denied")
    compatibility = value.get("contract_compatibility")
    if compatibility != ["CDH-WEB-CONTRACT-V1"]:
        raise ContractError("B06_COMPATIBILITY_INVALID", "frozen compatibility marker is invalid")
    pair = (value.get("data_source_status"), value.get("data_classification"))
    if pair not in CLASSIFICATION_PAIRS:
        raise ContractError("B06_CLASSIFICATION_INVALID", "source status and classification pair is invalid")
    product_errors = identifier_errors("canonical_product_id", value.get("product_id"))
    if product_errors:
        raise ContractError(product_errors[0], "canonical product ID is invalid")
    affiliate = value.get("affiliate")
    if not isinstance(affiliate, dict) or set(affiliate) != EXPECTED_B06_AFFILIATE:
        raise ContractError("B06_AFFILIATE_STRUCTURE_INVALID", "nested affiliate fields must match V2 exactly")
    state = affiliate.get("state")
    if state not in DISABLED_STATES:
        raise ContractError("B06_AFFILIATE_STATE_INVALID", "B06 cannot provide a runtime-verified link")
    if affiliate.get("click_url") is not None:
        raise ContractError("B06_CLICK_URL_DENIED", "B06 click URL and legacy fallback are denied")
    if affiliate.get("verified_product_match") is not False or affiliate.get("bound_product_id") is not None:
        raise ContractError("B06_AFFILIATE_CLAIM_DENIED", "B06 cannot claim an affiliate binding")
    return B06AffiliateResponse(
        schema_version=B06_SCHEMA,
        canonical_product_id=value["product_id"],
        data_source_status=value["data_source_status"],
        data_classification=value["data_classification"],
        affiliate_state=state,
    )


def load_c03_capability_snapshot(path: str | Path) -> CapabilitySnapshot:
    value = _load_json(path, "C03")
    if value.get("schema_version") != C03_SCHEMA:
        raise ContractError("C03_SCHEMA_INVALID", "unsupported C03 evidence schema")
    if value.get("provider_id") != "coupang_tw_partners" or value.get("market") != "TW":
        raise ContractError("C03_PROVIDER_INVALID", "C03 provider identity must be Coupang Partners Taiwan")
    if value.get("source_discovery_status") != "SOURCE_BLOCKED":
        raise ContractError("C03_SOURCE_BOUNDARY_INVALID", "affiliate evidence cannot unlock source discovery")
    raw_capabilities = value.get("capabilities")
    if not isinstance(raw_capabilities, dict):
        raise ContractError("C03_CAPABILITIES_INVALID", "C03 capabilities are missing")
    capabilities: dict[str, CapabilityState] = {}
    for name, item in raw_capabilities.items():
        if not isinstance(item, dict):
            raise ContractError("C03_CAPABILITY_INVALID", f"capability is invalid: {name}")
        state = item.get("state")
        runtime_enabled = item.get("runtime_enabled")
        evidence_ids = item.get("evidence_ids")
        if not isinstance(state, str) or not isinstance(runtime_enabled, bool) or not isinstance(evidence_ids, list):
            raise ContractError("C03_CAPABILITY_INVALID", f"capability fields are invalid: {name}")
        if any(not isinstance(evidence_id, str) or not evidence_id for evidence_id in evidence_ids):
            raise ContractError("C03_EVIDENCE_ID_INVALID", f"evidence IDs are invalid: {name}")
        capabilities[name] = CapabilityState(state, runtime_enabled, frozenset(evidence_ids))
    runtime = value.get("runtime")
    if not isinstance(runtime, dict):
        raise ContractError("C03_RUNTIME_INVALID", "C03 runtime block is missing")
    if value.get("provider_state") != "SOURCE_AUTHORIZATION_REQUIRED":
        raise ContractError("C03_CURRENT_STATE_INVALID", "F02 production loader accepts the frozen current C03 state only")
    if runtime.get("conversion_enabled") is not False or runtime.get("cta_enabled") is not False:
        raise ContractError("C03_RUNTIME_MUST_BE_DISABLED", "current C03 runtime must remain disabled")
    for name in ("endpoint", "affiliate_url", "expires_at", "disclosure_text"):
        if runtime.get(name) is not None:
            raise ContractError("C03_RUNTIME_VALUE_DENIED", f"current C03 runtime field must be null: {name}")
    if runtime.get("output_host_allowlist") != []:
        raise ContractError("C03_HOST_ALLOWLIST_DENIED", "current C03 host allowlist must be empty")
    if any(item.runtime_enabled for item in capabilities.values()):
        raise ContractError("C03_RUNTIME_CAPABILITY_DENIED", "current C03 capabilities cannot be runtime-enabled")
    return CapabilitySnapshot(
        provider_id="coupang_tw_partners",
        market="TW",
        provider_state="SOURCE_AUTHORIZATION_REQUIRED",
        capabilities=capabilities,
        output_hosts=frozenset(),
        allowed_path_prefixes=(),
        disclosure_text=None,
        account_authorized=False,
        authority_expires_at=None,
        max_link_ttl_seconds=None,
        revoked=False,
    )


def load_f01_provider_snapshot(path: str | Path) -> ProviderDecision:
    value = _load_json(path, "F01")
    if value.get("schema_version") != F01_SCHEMA:
        raise ContractError("F01_SCHEMA_INVALID", "unsupported F01 provider schema")
    if value.get("provider_id") != "coupang_tw_partners" or value.get("market") != "TW":
        raise ContractError("F01_PROVIDER_INVALID", "F01 provider identity must be Coupang Partners Taiwan")
    if value.get("provider_state") != "PENDING_OFFICIAL_DOCS":
        raise ContractError("F01_STATE_INVALID", "frozen F01 state must be pending")
    conversion = value.get("conversion")
    response = value.get("response")
    gates = value.get("gates")
    if not isinstance(conversion, dict) or conversion.get("enabled") is not False:
        raise ContractError("F01_CONVERSION_INVALID", "F01 conversion must remain disabled")
    if conversion.get("output_host_allowlist") != [] or conversion.get("endpoint") is not None:
        raise ContractError("F01_CONVERSION_VALUE_DENIED", "F01 endpoint and host list must remain empty")
    if not isinstance(response, dict) or response.get("affiliate_url") is not None:
        raise ContractError("F01_URL_DENIED", "F01 affiliate URL must remain null")
    if response.get("verified_product_match") is not False:
        raise ContractError("F01_MATCH_CLAIM_DENIED", "F01 cannot claim a verified match")
    if not isinstance(gates, dict) or any(item is not False for item in gates.values()):
        raise ContractError("F01_GATE_INVALID", "all frozen F01 gates must remain false")
    return ProviderDecision(
        state="PENDING_OFFICIAL_DOCS",
        market="TW",
        click_url=None,
        verified_product_match=False,
        bound_provider_product_id=None,
        bound_variant_id=None,
        bound_seller_id=None,
        generated_at=None,
        expires_at=None,
        disclosure_text=None,
        evidence_ids=frozenset(),
        link_source=None,
        revoked=False,
        user_initiated=False,
    )
