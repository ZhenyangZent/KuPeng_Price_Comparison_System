"""Immutable models for the F03 gateway boundary."""

from __future__ import annotations

import hashlib
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
class ExactIdentity:
    platform: str
    canonical_product_id: str
    provider_product_id: str
    variant_id: str
    seller_id: str
    original_url: str

    def errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        for name, value in (
            ("platform", self.platform),
            ("canonical_product_id", self.canonical_product_id),
            ("provider_product_id", self.provider_product_id),
            ("variant_id", self.variant_id),
            ("seller_id", self.seller_id),
        ):
            errors.extend(identifier_errors(name, value))
        if self.platform != "COUPANG_TW":
            errors.append("PLATFORM_NOT_COUPANG_TW")
        if not isinstance(self.original_url, str) or not self.original_url:
            errors.append("ORIGINAL_URL_MISSING")
        return tuple(dict.fromkeys(errors))

    def cache_key(self) -> str:
        raw = "\x1f".join(
            (
                self.platform,
                self.canonical_product_id,
                self.provider_product_id,
                self.variant_id,
                self.seller_id,
                hashlib.sha256(self.original_url.encode("utf-8")).hexdigest(),
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LinkRequest:
    identity: ExactIdentity
    user_initiated: bool


@dataclass(frozen=True, slots=True)
class CapabilityState:
    state: str
    runtime_enabled: bool
    evidence_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class AuthoritySnapshot:
    provider_id: str
    market: str
    provider_state: str
    capabilities: dict[str, CapabilityState]
    account_state: str
    credential_state: str
    input_hosts: frozenset[str]
    input_path_prefixes: tuple[str, ...]
    output_hosts: frozenset[str]
    output_path_prefixes: tuple[str, ...]
    disclosure_text: str | None
    authority_expires_at: datetime | None
    max_link_ttl_seconds: int | None
    max_revocation_age_seconds: int | None
    revoked: bool


@dataclass(frozen=True, slots=True)
class AdapterResult:
    status: str
    provider_id: str
    market: str
    official_evidence_ids: frozenset[str]
    verified_destination: str | None
    generated_at: datetime | None
    expires_at: datetime | None
    bound_provider_product_id: str | None
    bound_variant_id: str | None
    bound_seller_id: str | None
    disclosure_text: str | None
    revocation_status: str
    revocation_event_id: str | None
    revocation_checked_at: datetime | None
    generated_by_official_provider: bool


@dataclass(frozen=True, slots=True)
class ParsedB06Affiliate:
    canonical_product_id: str
    data_source_status: str
    data_classification: str


@dataclass(frozen=True, slots=True)
class GatewayDecision:
    api_response: dict[str, Any] | None
    state: str
    cta_enabled: bool
    verified_destination: str | None
    expires_at: str | None
    official_evidence_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    audit_event: dict[str, Any]
    cache_status: str
