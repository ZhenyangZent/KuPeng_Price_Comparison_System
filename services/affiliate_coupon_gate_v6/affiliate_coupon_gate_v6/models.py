"""Immutable models for the B10 wire-aware F06 gate."""

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
    coupon_id: str | None
    status: str
    discount_twd: int | None
    discount_scope: str
    already_included_in_base: bool
    eligibility_profile: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    scope_evidence: str | None
    pre_coupon_comparison_source: str | None
    evaluation_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourcePermission:
    allowed: bool
    state: str
    reason: str


@dataclass(frozen=True, slots=True)
class HistoryPoint:
    observed_at: datetime
    price_twd: int
    source_id: str
    series_key: str
    comparison_source: str | None = None
    coupon_id: str | None = None
    eligibility_profile: str | None = None
    scope_evidence: str | None = None


@dataclass(frozen=True, slots=True)
class HistoryQuality:
    raw_sample_count: int
    daily_representatives: tuple[tuple[str, int, int], ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class CouponPriceSnapshot:
    wire_source: str
    data_version: str
    series_key: str
    title: str
    series_identity: SeriesIdentity
    data_classification: str
    source_id: str | None
    observed_at: datetime | None
    base_price_twd: int | None
    before_coupon_price_twd: int | None
    coupon: CouponEvidence
    confirmed_coupon_price_twd: int | None
    possible_coupon_price_twd: int | None
    upstream_display_price_twd: int | None
    upstream_display_basis: str
    minimum_purchase_quantity: int
    minimum_item_spend_twd: int | None
    shipping_status: str
    upstream_required_total_twd: int | None
    source_permission: SourcePermission
    quality_flags: tuple[str, ...]
    before_coupon_history: tuple[HistoryPoint, ...]
    confirmed_after_coupon_history: tuple[HistoryPoint, ...]
    before_coupon_history_quality: HistoryQuality | None
    confirmed_after_coupon_history_quality: HistoryQuality | None


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
    before_coupon_price_twd: int | None
    confirmed_coupon_price_twd: int | None
    display_price_twd: int | None
    display_basis: str
    coupon_applied: bool
    minimum_purchase_quantity: int
    minimum_item_spend_twd: int | None
    shipping_status: str
    required_total_twd: int | None
    source_permission_state: str
    before_coupon_history_count: int
    confirmed_after_coupon_history_count: int
    affiliate_trust_state: str
    cta_enabled: bool
    click_url: str | None
    reason_codes: tuple[str, ...]
    audit_event: dict[str, Any]
