"""V2 preservation plus a separate candidate sidecar view model."""

from __future__ import annotations

import copy
from typing import Any

from .models import TrustDecision


TOP_FIELDS = frozenset(
    {"schema_version", "product_id", "data_source_status", "data_classification", "contract_compatibility", "affiliate"}
)
AFFILIATE_FIELDS = frozenset({"state", "click_url", "verified_product_match", "bound_product_id"})
DISABLED_STATES = frozenset({"UNCONFIGURED", "PENDING_OFFICIAL_DOCS", "FAILED", "DISABLED", "SOURCE_AUTHORIZATION_REQUIRED"})


class BridgeError(ValueError):
    pass


def preserve_v2_affiliate(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != TOP_FIELDS:
        raise BridgeError("exact CDH-WEB-CONTRACT-V2 Affiliate envelope required")
    if value.get("schema_version") != "CDH-WEB-CONTRACT-V2" or value.get("contract_compatibility") != ["CDH-WEB-CONTRACT-V1"]:
        raise BridgeError("V2 schema or compatibility marker invalid")
    if (value.get("data_source_status"), value.get("data_classification")) not in {
        ("USER_RECORDED_ONLY", "USER_RECORDED"), ("SYNTHETIC_FIXTURE_ONLY", "SYNTHETIC_DEMO_ONLY")
    }:
        raise BridgeError("source classification pair invalid")
    if not isinstance(value.get("product_id"), str) or not value["product_id"]:
        raise BridgeError("product ID missing")
    affiliate = value.get("affiliate")
    if not isinstance(affiliate, dict) or set(affiliate) != AFFILIATE_FIELDS:
        raise BridgeError("exact four-field Affiliate object required")
    if (
        affiliate.get("state") not in DISABLED_STATES
        or affiliate.get("click_url") is not None
        or affiliate.get("verified_product_match") is not False
        or affiliate.get("bound_product_id") is not None
    ):
        raise BridgeError("V2 Affiliate must remain disabled and unbound")
    return copy.deepcopy(value)


def build_candidate_sidecar(product_id: str, decision: TrustDecision) -> dict[str, Any]:
    if not isinstance(product_id, str) or not product_id:
        raise BridgeError("product ID missing")
    return {
        "schema_version": "CDH-AFFILIATE-TRUST-SIDECAR-CANDIDATE-1",
        "product_id": product_id,
        "trust": {
            "state": decision.state,
            "metadata_verified": decision.metadata_verified,
            "cta_enabled": decision.cta_enabled,
            "click_url": decision.click_url,
            "envelope_id": decision.envelope_id,
        },
    }
