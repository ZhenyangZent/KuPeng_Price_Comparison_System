"""Immutable models for the F08 non-activating affiliate-link contract."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime


def _digest(parts: tuple[str, ...]) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ProductIdentity:
    market: str
    platform: str
    product_id: str
    sku_id: str
    variant_id: str
    seller_id: str
    condition: str
    package_signature: str

    @property
    def binding_sha256(self) -> str:
        return _digest((self.market, self.platform, self.product_id, self.sku_id, self.variant_id, self.seller_id, self.condition, self.package_signature))


@dataclass(frozen=True, slots=True)
class LinkIntent:
    schema_version: str
    identity: ProductIdentity
    requested_at: datetime
    user_initiated: bool
    intent_nonce: str


@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    schema_version: str
    evidence_classification: str
    provider_id: str
    market: str
    account_reference_sha256: str
    product_level_supported: bool
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    allowed_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    attribution_ttl_seconds: int
    identity_binding_sha256: str
    endpoint_contract_sha256: str


@dataclass(frozen=True, slots=True)
class CandidateDestination:
    schema_version: str
    url: str
    created_at: datetime
    attribution_expires_at: datetime
    identity_binding_sha256: str


@dataclass(frozen=True, slots=True)
class CouponContext:
    status: str
    base_price_twd: int | None
    display_price_twd: int | None
    display_basis: str
    source_permission_allowed: bool
    reference_url: str | None


@dataclass(frozen=True, slots=True)
class RuntimeAuthority:
    state: str
    official_tw_source_authorized: bool
    official_tw_account_verified: bool
    product_endpoint_verified: bool
    host_rules_verified: bool
    cta_enabled: bool
    click_url: str | None
    allowed_hosts: frozenset[str]


@dataclass(frozen=True, slots=True)
class CtaDecision:
    state: str
    identity_binding_sha256: str
    destination_host: str | None
    evidence_current: bool
    identity_matches: bool
    cta_enabled: bool
    click_url: str | None
    reason_codes: tuple[str, ...]
