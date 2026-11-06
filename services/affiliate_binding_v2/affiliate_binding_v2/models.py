"""Immutable models for CDH affiliate V2 binding."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


MAX_ID_LENGTH = 256
DISABLED_STATES = frozenset(
    {
        "UNCONFIGURED",
        "PENDING_OFFICIAL_DOCS",
        "SOURCE_AUTHORIZATION_REQUIRED",
        "UNKNOWN",
        "CANDIDATE",
        "DOCUMENTARY_VERIFIED",
        "ACCOUNT_AUTHORIZED",
        "REJECTED",
        "REVOKED",
        "EXPIRED",
        "FAILED",
        "DISABLED",
    }
)


def identifier_errors(name: str, value: object) -> tuple[str, ...]:
    prefix = name.upper()
    if not isinstance(value, str) or not value:
        return (f"{prefix}_MISSING",)
    errors: list[str] = []
    if value != value.strip():
        errors.append(f"{prefix}_WHITESPACE")
    if len(value) > MAX_ID_LENGTH:
        errors.append(f"{prefix}_TOO_LONG")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        errors.append(f"{prefix}_CONTROL_CHARACTER")
    return tuple(errors)


@dataclass(frozen=True, slots=True)
class CanonicalIdentity:
    """B06 canonical row ID plus exact provider identity from its selected offer."""

    canonical_product_id: str
    provider_product_id: str
    variant_id: str
    seller_id: str

    def errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        for name, value in (
            ("canonical_product_id", self.canonical_product_id),
            ("provider_product_id", self.provider_product_id),
            ("variant_id", self.variant_id),
            ("seller_id", self.seller_id),
        ):
            errors.extend(identifier_errors(name, value))
        return tuple(errors)


@dataclass(frozen=True, slots=True)
class B06AffiliateResponse:
    schema_version: str
    canonical_product_id: str
    data_source_status: str
    data_classification: str
    affiliate_state: str


@dataclass(frozen=True, slots=True)
class CapabilityState:
    state: str
    runtime_enabled: bool
    evidence_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    provider_id: str
    market: str
    provider_state: str
    capabilities: dict[str, CapabilityState]
    output_hosts: frozenset[str]
    allowed_path_prefixes: tuple[str, ...]
    disclosure_text: str | None
    account_authorized: bool
    authority_expires_at: datetime | None
    max_link_ttl_seconds: int | None
    revoked: bool


@dataclass(frozen=True, slots=True)
class ProviderDecision:
    state: str
    market: str
    click_url: str | None
    verified_product_match: bool
    bound_provider_product_id: str | None
    bound_variant_id: str | None
    bound_seller_id: str | None
    generated_at: datetime | None
    expires_at: datetime | None
    disclosure_text: str | None
    evidence_ids: frozenset[str]
    link_source: str | None
    revoked: bool
    user_initiated: bool


@dataclass(frozen=True, slots=True)
class BindingOutcome:
    api_response: dict[str, Any] | None
    ui_cta_state: str
    reason_codes: tuple[str, ...]
    audit_summary: dict[str, Any]

    @property
    def enabled(self) -> bool:
        return self.ui_cta_state == "ENABLED"
