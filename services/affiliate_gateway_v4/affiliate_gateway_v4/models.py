"""Immutable models for the F04 trust boundary."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any


MAX_ID_LENGTH = 256


def identifier_errors(name: str, value: object) -> tuple[str, ...]:
    label = name.upper()
    if not isinstance(value, str) or not value:
        return (f"{label}_MISSING",)
    errors: list[str] = []
    if value != value.strip():
        errors.append(f"{label}_WHITESPACE")
    if len(value) > MAX_ID_LENGTH:
        errors.append(f"{label}_TOO_LONG")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        errors.append(f"{label}_CONTROL_CHARACTER")
    return tuple(errors)


@dataclass(frozen=True, slots=True)
class ExactIdentity:
    platform: str
    canonical_product_id: str
    provider_product_id: str
    sku_id: str
    seller_id: str
    original_url: str

    def errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        for name, value in (
            ("platform", self.platform),
            ("canonical_product_id", self.canonical_product_id),
            ("provider_product_id", self.provider_product_id),
            ("sku_id", self.sku_id),
            ("seller_id", self.seller_id),
        ):
            errors.extend(identifier_errors(name, value))
        if self.platform != "COUPANG_TW":
            errors.append("PLATFORM_NOT_COUPANG_TW")
        if not isinstance(self.original_url, str) or not self.original_url:
            errors.append("ORIGINAL_URL_MISSING")
        return tuple(dict.fromkeys(errors))

    @property
    def original_url_sha256(self) -> str:
        return hashlib.sha256(self.original_url.encode("utf-8")).hexdigest()

    @property
    def binding_sha256(self) -> str:
        material = "\x1f".join(
            (
                self.platform,
                self.canonical_product_id,
                self.provider_product_id,
                self.sku_id,
                self.seller_id,
                self.original_url_sha256,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LinkRequest:
    identity: ExactIdentity
    user_initiated: bool


@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    runtime_enabled: bool
    evidence_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class AuthoritySnapshot:
    state: str
    provider_id: str
    market: str
    account_state: str
    credential_state: str
    capabilities: dict[str, CapabilityEvidence]
    input_hosts: frozenset[str]
    input_paths: tuple[str, ...]
    output_hosts: frozenset[str]
    output_paths: tuple[str, ...]
    disclosure_text: str | None
    authority_expires_at: datetime | None
    max_ttl_seconds: int | None
    max_revocation_age_seconds: int | None
    revoked: bool


@dataclass(frozen=True, slots=True)
class TrustClaims:
    issuer: str
    audience: str
    fixture_class: str
    provider_id: str
    market: str
    canonical_product_id: str
    provider_product_id: str
    sku_id: str
    seller_id: str
    original_url_sha256: str
    verified_destination: str
    issued_at: datetime
    expires_at: datetime
    official_evidence_ids: tuple[str, ...]
    revocation_event_id: str
    revocation_status: str
    revocation_checked_at: datetime
    disclosure_text: str
    nonce: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            "audience": self.audience,
            "fixture_class": self.fixture_class,
            "provider_id": self.provider_id,
            "market": self.market,
            "canonical_product_id": self.canonical_product_id,
            "provider_product_id": self.provider_product_id,
            "sku_id": self.sku_id,
            "seller_id": self.seller_id,
            "original_url_sha256": self.original_url_sha256,
            "verified_destination": self.verified_destination,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "official_evidence_ids": list(self.official_evidence_ids),
            "revocation_event_id": self.revocation_event_id,
            "revocation_status": self.revocation_status,
            "revocation_checked_at": self.revocation_checked_at.isoformat(),
            "disclosure_text": self.disclosure_text,
            "nonce": self.nonce,
        }


@dataclass(frozen=True, slots=True)
class TrustDecision:
    state: str
    cta_enabled: bool
    click_url: str | None
    metadata_verified: bool
    envelope_id: str | None
    reason_codes: tuple[str, ...]
    audit_event: dict[str, Any]
