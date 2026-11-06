from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "CDH-EXCHANGE-1"
SOURCE_KINDS = {
    "USER_ENTERED",
    "USER_FILE",
    "PUBLIC_NOTICE_MANUAL",
    "SYNTHETIC_TEST",
    "APPROVED_FEED",
}
RECORD_TYPES = {"USER_PRICE_OBSERVATION", "PROMO_CLUE"}
PRICE_BASES = {
    "DISPLAYED_UNKNOWN",
    "CURRENT_ITEM_PRICE",
    "REFERENCE_PRICE",
    "COUPON_INCLUDED_DISPLAY",
}
SHIPPING_STATES = {"UNKNOWN", "FREE", "PAID", "NOT_APPLICABLE", "CONFLICT"}
STOCK_STATES = {"UNKNOWN", "IN_STOCK", "OUT_OF_STOCK", "CONFLICT"}
GENERIC_STATES = {"UNKNOWN", "CONFIRMED", "NOT_APPLICABLE", "INELIGIBLE", "CONFLICT"}


class ValidationError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ValidatedRecord:
    raw: dict[str, Any]
    submission_id: str
    record_type: str
    created_at_utc: str
    observed_at_utc: str
    source_id: str | None
    source_kind: str
    permission_scope: str
    source_url: str | None
    source_note: str
    product_title: str
    product_id: str | None
    variant_id: str | None
    seller_id: str | None
    displayed_price_twd: int | None
    price_basis: str
    minimum_purchase_quantity: int | None
    shipping_status: str
    shipping_fee_twd: int | None
    stock_status: str
    coupon_status: str
    account_eligibility_status: str
    mandatory_fee_status: str
    notes: str
    promo_claim: str | None
    published_at_utc: str | None
    is_synthetic: bool


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

