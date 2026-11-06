"""Immutable models for F09's non-clickable adapter."""

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
    variant_id: str | None
    seller_id: str
    condition: str
    package_signature: str

    @property
    def binding_sha256(self) -> str:
        return _digest(
            (
                self.market,
                self.platform,
                self.product_id,
                self.sku_id,
                self.variant_id or "<VARIANT_MISSING>",
                self.seller_id,
                self.condition,
                self.package_signature,
            )
        )


@dataclass(frozen=True, slots=True)
class ProductSnapshot:
    series_key: str
    identity: ProductIdentity
    coupon_id: str | None
    coupon_status: str
    coupon_valid_from: datetime | None
    coupon_valid_until: datetime | None
    base_price_twd: int | None
    display_price_twd: int | None
    display_basis: str
    source_allowed: bool
    source_state: str
    source_reason: str
    coupon_binding_sha256: str
    price_binding_sha256: str
    source_binding_sha256: str


@dataclass(frozen=True, slots=True)
class VariantEvidence:
    classification: str
    identity: ProductIdentity
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class AccountEvidence:
    classification: str
    state: str
    account_reference_sha256: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class ReferenceCandidate:
    kind: str
    host: str


@dataclass(frozen=True, slots=True)
class InertAction:
    action_kind: str
    verification_state: str
    enabled: bool
    url: None


@dataclass(frozen=True, slots=True)
class InertClickIntent:
    schema_version: str
    state: str
    a11_release_sha256: str
    b11_release_sha256: str
    identity: ProductIdentity
    identity_binding_sha256: str
    coupon_status: str
    source_state: str
    general_product_page: InertAction
    affiliate_link: InertAction
    cta_enabled: bool
    click_url: None
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return the stable wire shape without ever serializing an input URL."""
        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "a11_release_sha256": self.a11_release_sha256,
            "b11_release_sha256": self.b11_release_sha256,
            "identity": {
                "market": self.identity.market,
                "platform": self.identity.platform,
                "product_id": self.identity.product_id,
                "sku_id": self.identity.sku_id,
                "variant_id": self.identity.variant_id,
                "seller_id": self.identity.seller_id,
                "condition": self.identity.condition,
                "package_signature": self.identity.package_signature,
            },
            "identity_binding_sha256": self.identity_binding_sha256,
            "coupon_status": self.coupon_status,
            "source_state": self.source_state,
            "general_product_page": {
                "action_kind": self.general_product_page.action_kind,
                "verification_state": self.general_product_page.verification_state,
                "enabled": self.general_product_page.enabled,
                "url": self.general_product_page.url,
            },
            "affiliate_link": {
                "action_kind": self.affiliate_link.action_kind,
                "verification_state": self.affiliate_link.verification_state,
                "enabled": self.affiliate_link.enabled,
                "url": self.affiliate_link.url,
            },
            "cta_enabled": self.cta_enabled,
            "click_url": self.click_url,
            "reason_codes": list(self.reason_codes),
        }

