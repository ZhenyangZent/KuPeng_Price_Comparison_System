"""Immutable F05 models."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SeriesIdentity:
    platform: str
    product_id: str
    sku_id: str
    seller_id: str
    condition: str
    package_signature: str

    @property
    def binding_sha256(self) -> str:
        return _digest("\x1f".join((self.platform, self.product_id, self.sku_id, self.seller_id, self.condition, self.package_signature)))


@dataclass(frozen=True, slots=True)
class CouponEvidence:
    coupon_id: str
    status: str
    discount_twd: int | None
    already_included_in_base: bool
    eligibility_profile: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    scope_evidence: str | None


@dataclass(frozen=True, slots=True)
class CouponPriceSnapshot:
    series_identity: SeriesIdentity
    data_classification: str
    source_id: str
    observed_at: datetime
    base_price_twd: int | None
    coupon: CouponEvidence
    confirmed_coupon_price_twd: int | None
    possible_coupon_price_twd: int | None
    upstream_display_price_twd: int | None
    upstream_display_basis: str
    shipping_status: str
    upstream_required_total_twd: int | None
    before_coupon_history_count: int
    confirmed_after_coupon_history_count: int


@dataclass(frozen=True, slots=True)
class AffiliateTrustInput:
    state: str
    cta_enabled: bool
    click_url: str | None
    metadata_verified: bool
    envelope_id: str | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuntimeCeiling:
    state: str
    source_authorization_required: bool
    account_authorized: bool
    runtime_authorized: bool
    cta_enabled: bool
    click_url: str | None
    endpoint_hosts: frozenset[str]
    redirect_hosts: frozenset[str]


@dataclass(frozen=True, slots=True)
class GateRequest:
    identity: SeriesIdentity
    eligibility_profile: str | None
    user_initiated: bool


@dataclass(frozen=True, slots=True)
class CombinedDecision:
    state: str
    base_price_twd: int | None
    confirmed_coupon_price_twd: int | None
    display_price_twd: int | None
    display_basis: str
    coupon_applied: bool
    shipping_status: str
    required_total_twd: int | None
    affiliate_trust_state: str
    cta_enabled: bool
    click_url: str | None
    reason_codes: tuple[str, ...]
    audit_event: dict[str, Any]
