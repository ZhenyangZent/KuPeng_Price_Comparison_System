from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SCHEMA = "CDH-COUPON-PRICE-V4"
CONFIRMED = "CONFIRMED_APPLICABLE"
STATUSES = {CONFIRMED, "CLAIM_REQUIRED", "UNVERIFIED", "INELIGIBLE", "EXPIRED", "UNKNOWN", "NONE"}
IDENTITY_KEYS = ("platform", "product_id", "sku_id", "seller_id", "condition", "package_signature")


class ContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContractError("INVALID_TIMESTAMP", f"{field} must use canonical UTC Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError("INVALID_TIMESTAMP", f"{field} is invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ContractError("INVALID_TIMESTAMP", f"{field} must be UTC")
    return parsed


def money(value: Any, field: str, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError("INVALID_MONEY", f"{field} must be a non-negative integer TWD value")
    return value


def identity(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(value.get(key), str) or not value[key] for key in IDENTITY_KEYS):
        raise ContractError("INVALID_IDENTITY", f"{field} must bind exact product/SKU/seller/condition/package")
    return {key: value[key] for key in IDENTITY_KEYS}


def validate_history(items: Any, kind: str, series: dict[str, str]) -> None:
    if not isinstance(items, list):
        raise ContractError("INVALID_HISTORY", f"history.{kind} must be an array")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ContractError("INVALID_HISTORY", f"history.{kind}[{index}] must be an object")
        utc(item.get("observed_at"), f"history.{kind}[{index}].observed_at")
        money(item.get("price_twd"), f"history.{kind}[{index}].price_twd")
        if identity(item.get("series_identity"), f"history.{kind}[{index}].series_identity") != series:
            raise ContractError("HISTORY_IDENTITY_MISMATCH", f"history.{kind}[{index}] identity mismatch")
        if not item.get("source_id") or not item.get("scope_evidence"):
            raise ContractError("HISTORY_EVIDENCE_MISSING", f"history.{kind}[{index}] lacks source evidence")
        if kind == "confirmed_after_coupon" and item.get("coupon_status") != CONFIRMED:
            raise ContractError("UNCONFIRMED_HISTORY", "after-coupon history requires confirmed applicability")


def validate_v4(value: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if value.get("schema_version") != SCHEMA:
        raise ContractError("SCHEMA_MISMATCH", "V4 opt-in schema required")
    series = identity(value.get("series_identity"), "series_identity")
    if value.get("data_classification") != "SYNTHETIC_FIXTURE":
        raise ContractError("SOURCE_NOT_AUTHORIZED", "H04 only accepts TEST_ONLY synthetic fixtures")
    if not value.get("source_id"):
        raise ContractError("SOURCE_NOT_AUTHORIZED", "source_id is required")
    observed = utc(value.get("observed_at"), "observed_at")
    current = now or datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    base = money(value.get("base_price_twd"), "base_price_twd", nullable=True)
    confirmed = money(value.get("confirmed_coupon_price_twd"), "confirmed_coupon_price_twd", nullable=True)
    possible = money(value.get("possible_coupon_price_twd"), "possible_coupon_price_twd", nullable=True)
    display = money(value.get("display_price_twd"), "display_price_twd", nullable=True)
    coupon = value.get("coupon")
    if not isinstance(coupon, dict) or coupon.get("status") not in STATUSES:
        raise ContractError("INVALID_COUPON", "coupon status is invalid")
    status = coupon["status"]
    bound = identity(coupon.get("bound_identity"), "coupon.bound_identity") if coupon.get("bound_identity") is not None else None
    confirmed_evidence = status == CONFIRMED and bound == series and bool(coupon.get("eligibility_profile")) and bool(coupon.get("scope_evidence"))
    if status == CONFIRMED:
        valid_from = utc(coupon.get("valid_from"), "coupon.valid_from")
        valid_until = utc(coupon.get("valid_until"), "coupon.valid_until")
        confirmed_evidence = confirmed_evidence and valid_from <= observed <= valid_until and valid_from <= current <= valid_until
    if confirmed_evidence:
        if base is None:
            raise ContractError("BASE_REQUIRED", "confirmed coupon requires a valid base price")
        discount = money(coupon.get("discount_twd"), "coupon.discount_twd")
        if coupon.get("discount_scope") == "ORDER":
            quantity = value.get("minimum_quantity")
            if not isinstance(quantity, int) or quantity < 1:
                raise ContractError("INVALID_QUANTITY", "minimum_quantity is required for order coupon")
            total = money(value.get("required_merchandise_total_twd"), "required_merchandise_total_twd")
            expected_total = base * quantity if coupon.get("already_included_in_base") else base * quantity - discount
            if expected_total < 0 or total != expected_total or confirmed != expected_total // quantity:
                raise ContractError("ORDER_COUPON_MATH", "order coupon quantity math is inconsistent")
        else:
            expected = base if coupon.get("already_included_in_base") else base - discount
            if expected < 0:
                raise ContractError("NEGATIVE_COUPON_PRICE", "coupon cannot manufacture a zero price")
            if confirmed != expected:
                raise ContractError("COUPON_MATH", "confirmed coupon price is inconsistent")
        if display != confirmed or value.get("display_basis") != "CONFIRMED_COUPON":
            raise ContractError("DISPLAY_BASIS", "confirmed coupon price must be the primary display price")
    else:
        if confirmed is not None:
            raise ContractError("UNCONFIRMED_DISCOUNT", "unconfirmed coupon cannot produce a confirmed price")
        if display != base or value.get("display_basis") != ("BASE_PRICE" if base is not None else "UNAVAILABLE"):
            raise ContractError("DISPLAY_BASIS", "display must fall back to base or unavailable")
    if possible is not None and confirmed_evidence:
        raise ContractError("POSSIBLE_PRICE_CONFLICT", "confirmed and possible price cannot coexist")
    if value.get("shipping_status") == "UNKNOWN" and value.get("required_total_twd") is not None:
        raise ContractError("UNKNOWN_TOTAL", "unknown shipping requires null required total")
    history = value.get("history")
    if not isinstance(history, dict):
        raise ContractError("INVALID_HISTORY", "history object is required")
    validate_history(history.get("before_coupon"), "before_coupon", series)
    validate_history(history.get("confirmed_after_coupon"), "confirmed_after_coupon", series)
    if not confirmed_evidence and history.get("confirmed_after_coupon"):
        raise ContractError("UNCONFIRMED_HISTORY", "current unconfirmed coupon cannot populate current confirmed history")
    return {"display_price_twd": display, "display_basis": value["display_basis"], "confirmed": confirmed_evidence}
