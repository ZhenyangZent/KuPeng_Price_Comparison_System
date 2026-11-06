"""Strict B06 V2 and C04 readiness readers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import CapabilityState, AuthoritySnapshot, DISABLED_STATES, ParsedB06Affiliate, identifier_errors


B06_SCHEMA = "CDH-WEB-CONTRACT-V2"
C04_SCHEMA = "CDH-CAPABILITY-READINESS-1"
CLASSIFICATION_PAIRS = {
    ("USER_RECORDED_ONLY", "USER_RECORDED"),
    ("SYNTHETIC_FIXTURE_ONLY", "SYNTHETIC_DEMO_ONLY"),
}
TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "product_id",
        "data_source_status",
        "data_classification",
        "contract_compatibility",
        "affiliate",
    }
)
AFFILIATE_FIELDS = frozenset({"state", "click_url", "verified_product_match", "bound_product_id"})
FORBIDDEN_SECRET_KEYS = frozenset(
    {"access_key", "secret_key", "api_key", "token", "password", "cookie", "authorization", "account_id"}
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


def parse_b06_affiliate_response(value: object) -> ParsedB06Affiliate:
    if not isinstance(value, dict) or set(value) != TOP_LEVEL_FIELDS:
        raise ContractError("B06_STRUCTURE_INVALID", "exact B06 V2 nested envelope required")
    if value.get("schema_version") != B06_SCHEMA:
        raise ContractError("B06_SCHEMA_INVALID", "legacy and unknown schemas are denied")
    if value.get("contract_compatibility") != ["CDH-WEB-CONTRACT-V1"]:
        raise ContractError("B06_COMPATIBILITY_INVALID", "compatibility marker is invalid")
    pair = (value.get("data_source_status"), value.get("data_classification"))
    if pair not in CLASSIFICATION_PAIRS:
        raise ContractError("B06_CLASSIFICATION_INVALID", "classification pair is invalid")
    id_errors = identifier_errors("canonical_product_id", value.get("product_id"))
    if id_errors:
        raise ContractError(id_errors[0], "canonical product ID is invalid")
    affiliate = value.get("affiliate")
    if not isinstance(affiliate, dict) or set(affiliate) != AFFILIATE_FIELDS:
        raise ContractError("B06_AFFILIATE_STRUCTURE_INVALID", "affiliate fields differ from B06 V2")
    if affiliate.get("state") not in DISABLED_STATES:
        raise ContractError("B06_PREVERIFIED_STATE_DENIED", "B06 cannot pre-authorize the gateway")
    if affiliate.get("click_url") is not None:
        raise ContractError("B06_PREEXISTING_URL_DENIED", "old or caller-provided affiliate URL denied")
    if affiliate.get("verified_product_match") is not False or affiliate.get("bound_product_id") is not None:
        raise ContractError("B06_PREEXISTING_MATCH_DENIED", "B06 cannot pre-bind affiliate identity")
    return ParsedB06Affiliate(value["product_id"], value["data_source_status"], value["data_classification"])


def load_c04_readiness(path: str | Path) -> AuthoritySnapshot:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ContractError("C04_FILE_INVALID", "C04 readiness must be a regular local file")
    try:
        value: Any = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("C04_JSON_INVALID", str(exc)) from exc
    if not isinstance(value, dict):
        raise ContractError("C04_ROOT_INVALID", "C04 readiness root must be an object")
    forbidden = sorted(_walk_keys(value) & FORBIDDEN_SECRET_KEYS)
    if forbidden:
        raise ContractError("C04_SECRET_KEY_DENIED", f"secret-bearing keys denied: {forbidden}")
    if value.get("schema_version") != C04_SCHEMA:
        raise ContractError("C04_SCHEMA_INVALID", "unsupported C04 readiness schema")
    if value.get("provider_id") != "coupang_tw_partners" or value.get("market") != "TW":
        raise ContractError("C04_PROVIDER_INVALID", "Taiwan provider identity required")
    if value.get("provider_state") != "SOURCE_AUTHORIZATION_REQUIRED":
        raise ContractError("C04_STATE_INVALID", "frozen C04 provider state must remain source-authorized-required")
    if value.get("source_discovery_status") != "SOURCE_BLOCKED":
        raise ContractError("C04_SOURCE_BOUNDARY_INVALID", "C04 cannot unlock product source discovery")
    raw_capabilities = value.get("capabilities")
    if not isinstance(raw_capabilities, dict):
        raise ContractError("C04_CAPABILITIES_INVALID", "capabilities are missing")
    capabilities: dict[str, CapabilityState] = {}
    for name, item in raw_capabilities.items():
        if not isinstance(item, dict):
            raise ContractError("C04_CAPABILITY_INVALID", f"invalid capability: {name}")
        state = item.get("state")
        enabled = item.get("runtime_enabled")
        evidence = item.get("candidate_evidence_sha256")
        if state not in {"UNKNOWN", "CANDIDATE"} or enabled is not False or not isinstance(evidence, list):
            raise ContractError("C04_CAPABILITY_INVALID", f"frozen capability must remain candidate-or-lower: {name}")
        capabilities[name] = CapabilityState(state, False, frozenset(str(item) for item in evidence))
    runtime = value.get("runtime")
    if not isinstance(runtime, dict):
        raise ContractError("C04_RUNTIME_INVALID", "runtime block missing")
    if runtime.get("click_url") is not None or runtime.get("cta_enabled") is not False:
        raise ContractError("C04_RUNTIME_MUST_BE_DISABLED", "current C04 runtime must remain disabled")
    if runtime.get("input_host_allowlist") != [] or runtime.get("output_host_allowlist") != []:
        raise ContractError("C04_HOSTS_MUST_BE_EMPTY", "current C04 host lists must remain empty")
    return AuthoritySnapshot(
        provider_id="coupang_tw_partners",
        market="TW",
        provider_state="SOURCE_AUTHORIZATION_REQUIRED",
        capabilities=capabilities,
        account_state="UNAUTHORIZED",
        credential_state="UNCONFIGURED",
        input_hosts=frozenset(),
        input_path_prefixes=(),
        output_hosts=frozenset(),
        output_path_prefixes=(),
        disclosure_text=None,
        authority_expires_at=None,
        max_link_ttl_seconds=None,
        max_revocation_age_seconds=None,
        revoked=False,
    )
