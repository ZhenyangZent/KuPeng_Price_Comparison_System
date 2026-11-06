"""Strict parser for the frozen synthetic CDH-COUPON-PRICE-V4 boundary."""

from __future__ import annotations

from datetime import datetime

from .models import CouponEvidence, CouponPriceSnapshot, SeriesIdentity


TOP_FIELDS = frozenset(
    {
        "schema_version", "series_identity", "data_classification", "source_id", "observed_at",
        "base_price_twd", "coupon", "confirmed_coupon_price_twd", "possible_coupon_price_twd",
        "display_price_twd", "display_basis", "shipping_status", "required_total_twd", "history",
    }
)
IDENTITY_FIELDS = frozenset({"platform", "product_id", "sku_id", "seller_id", "condition", "package_signature"})
COUPON_FIELDS = frozenset(
    {"coupon_id", "status", "discount_twd", "already_included_in_base", "eligibility_profile", "valid_from", "valid_until", "scope_evidence"}
)
HISTORY_FIELDS = frozenset({"before_coupon", "confirmed_after_coupon"})
STATUSES = frozenset({"CONFIRMED_APPLICABLE", "CLAIM_REQUIRED", "UNVERIFIED", "INELIGIBLE", "EXPIRED", "UNKNOWN", "NONE"})
FORBIDDEN_KEYS = frozenset(
    {"url", "click_url", "affiliate_url", "redirect", "token", "secret", "api_key", "cookie", "authorization", "password"}
)


class CouponContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _all_keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            found.add(str(key).casefold())
            found.update(_all_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_all_keys(child))
    return found


def _identifier(value: object, name: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 256:
        raise CouponContractError(f"{name.upper()}_INVALID", f"{name} must be a bounded non-empty string")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value) or "://" in value:
        raise CouponContractError(f"{name.upper()}_INVALID", f"{name} contains forbidden characters or URL data")
    return value


def _time(value: object, name: str, *, nullable: bool = False) -> datetime | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value:
        raise CouponContractError(f"{name.upper()}_INVALID", f"{name} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CouponContractError(f"{name.upper()}_INVALID", f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CouponContractError(f"{name.upper()}_INVALID", f"{name} must include timezone")
    return parsed


def _price(value: object, name: str, *, nullable: bool = True) -> int | None:
    if nullable and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CouponContractError(f"{name.upper()}_INVALID", f"{name} must be a non-negative integer or null")
    return value


def parse_coupon_snapshot(value: object) -> CouponPriceSnapshot:
    if not isinstance(value, dict) or set(value) != TOP_FIELDS:
        raise CouponContractError("V4_STRUCTURE_INVALID", "exact CDH-COUPON-PRICE-V4 field set required")
    forbidden = sorted(_all_keys(value) & FORBIDDEN_KEYS)
    if forbidden:
        raise CouponContractError("FORBIDDEN_SECRET_OR_URL_FIELD", f"forbidden keys: {forbidden}")
    if value.get("schema_version") != "CDH-COUPON-PRICE-V4":
        raise CouponContractError("V4_SCHEMA_INVALID", "CDH-COUPON-PRICE-V4 required")
    identity = value.get("series_identity")
    coupon = value.get("coupon")
    history = value.get("history")
    if not isinstance(identity, dict) or set(identity) != IDENTITY_FIELDS:
        raise CouponContractError("SERIES_IDENTITY_INVALID", "exact series identity required")
    if not isinstance(coupon, dict) or set(coupon) != COUPON_FIELDS:
        raise CouponContractError("COUPON_STRUCTURE_INVALID", "exact coupon evidence fields required")
    if not isinstance(history, dict) or set(history) != HISTORY_FIELDS:
        raise CouponContractError("HISTORY_STRUCTURE_INVALID", "before/after histories required")
    if not isinstance(history["before_coupon"], list) or not isinstance(history["confirmed_after_coupon"], list):
        raise CouponContractError("HISTORY_ARRAY_INVALID", "history values must be arrays")
    series = SeriesIdentity(
        platform=_identifier(identity.get("platform"), "platform"),
        product_id=_identifier(identity.get("product_id"), "product_id"),
        sku_id=_identifier(identity.get("sku_id"), "sku_id"),
        seller_id=_identifier(identity.get("seller_id"), "seller_id"),
        condition=_identifier(identity.get("condition"), "condition"),
        package_signature=_identifier(identity.get("package_signature"), "package_signature"),
    )
    if series.platform != "COUPANG_TW":
        raise CouponContractError("PLATFORM_INVALID", "COUPANG_TW required")
    classification = value.get("data_classification")
    if classification != "SYNTHETIC_FIXTURE":
        raise CouponContractError("CLASSIFICATION_NOT_AUTHORIZED", "F05 accepts synthetic fixture snapshots only")
    status = coupon.get("status")
    if status not in STATUSES:
        raise CouponContractError("COUPON_STATUS_INVALID", "coupon status is invalid")
    already_included = coupon.get("already_included_in_base")
    if not isinstance(already_included, bool):
        raise CouponContractError("ALREADY_INCLUDED_INVALID", "already_included_in_base must be boolean")
    shipping = value.get("shipping_status")
    if shipping not in {"FREE", "PAID", "UNKNOWN"}:
        raise CouponContractError("SHIPPING_STATUS_INVALID", "shipping status is invalid")
    basis = value.get("display_basis")
    if basis not in {"CONFIRMED_COUPON", "BASE", "PRICE_UNKNOWN", "CONFIRMED_ALREADY_INCLUDED"}:
        raise CouponContractError("DISPLAY_BASIS_INVALID", "display basis is invalid")
    evidence = CouponEvidence(
        coupon_id=_identifier(coupon.get("coupon_id"), "coupon_id"),
        status=status,
        discount_twd=_price(coupon.get("discount_twd"), "discount_twd"),
        already_included_in_base=already_included,
        eligibility_profile=_identifier(coupon.get("eligibility_profile"), "eligibility_profile", nullable=True),
        valid_from=_time(coupon.get("valid_from"), "valid_from", nullable=True),
        valid_until=_time(coupon.get("valid_until"), "valid_until", nullable=True),
        scope_evidence=_identifier(coupon.get("scope_evidence"), "scope_evidence", nullable=True),
    )
    return CouponPriceSnapshot(
        series_identity=series,
        data_classification=classification,
        source_id=_identifier(value.get("source_id"), "source_id"),
        observed_at=_time(value.get("observed_at"), "observed_at"),
        base_price_twd=_price(value.get("base_price_twd"), "base_price_twd"),
        coupon=evidence,
        confirmed_coupon_price_twd=_price(value.get("confirmed_coupon_price_twd"), "confirmed_coupon_price_twd"),
        possible_coupon_price_twd=_price(value.get("possible_coupon_price_twd"), "possible_coupon_price_twd"),
        upstream_display_price_twd=_price(value.get("display_price_twd"), "display_price_twd"),
        upstream_display_basis=basis,
        shipping_status=shipping,
        upstream_required_total_twd=_price(value.get("required_total_twd"), "required_total_twd"),
        before_coupon_history_count=len(history["before_coupon"]),
        confirmed_after_coupon_history_count=len(history["confirmed_after_coupon"]),
    )
