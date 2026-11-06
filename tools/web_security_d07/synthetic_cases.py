from __future__ import annotations

from copy import deepcopy
from typing import Any


IDENTITY = {
    "platform": "COUPANG_TW",
    "product_id": "SYN-P-1",
    "sku_id": "SYN-SKU-1",
    "seller_id": "SYN-SELLER-1",
    "condition": "NEW",
    "package_signature": "1x100ml",
}


def confirmed_payload() -> dict[str, Any]:
    return {
        "schema_version": "CDH-COUPON-PRICE-V4",
        "series_identity": deepcopy(IDENTITY),
        "data_classification": "SYNTHETIC_FIXTURE",
        "source_id": "SYN-SOURCE-1",
        "observed_at": "2026-11-05T00:00:00Z",
        "base_price_twd": 99,
        "coupon": {
            "coupon_id": "SYN-COUPON-1",
            "status": "CONFIRMED_APPLICABLE",
            "discount_twd": 50,
            "already_included_in_base": False,
            "eligibility_profile": "SYN-ELIGIBLE-PROFILE",
            "valid_from": "2026-11-01T00:00:00Z",
            "valid_until": "2026-11-30T23:59:59Z",
            "scope_evidence": "SYN-TEST-EVIDENCE",
        },
        "confirmed_coupon_price_twd": 49,
        "possible_coupon_price_twd": None,
        "display_price_twd": 49,
        "display_basis": "CONFIRMED_COUPON",
        "shipping_status": "UNKNOWN",
        "required_total_twd": None,
        "history": {"before_coupon": [], "confirmed_after_coupon": []},
    }


def unconfirmed_payload(status: str = "UNVERIFIED") -> dict[str, Any]:
    value = confirmed_payload()
    value["coupon"].update({
        "status": status,
        "discount_twd": 50,
        "eligibility_profile": None,
        "scope_evidence": None,
    })
    value["confirmed_coupon_price_twd"] = None
    value["possible_coupon_price_twd"] = 49
    value["display_price_twd"] = 99
    value["display_basis"] = "BASE_PRICE"
    value["required_total_twd"] = None
    return value


def history_point(*, price: int, after: bool = False) -> dict[str, Any]:
    value: dict[str, Any] = {
        "observed_at": "2026-11-04T00:00:00Z",
        "price_twd": price,
        "series_identity": deepcopy(IDENTITY),
        "source_id": "SYN-HISTORY-SOURCE",
        "data_classification": "SYNTHETIC_FIXTURE",
    }
    if after:
        value.update({
            "coupon_id": "SYN-COUPON-OLD",
            "eligibility_profile": "SYN-ELIGIBLE-PROFILE",
            "scope_evidence": "SYN-HISTORY-EVIDENCE",
        })
    return value
