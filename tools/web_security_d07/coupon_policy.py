from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


SCHEMA = "CDH-COUPON-PRICE-V4"
STATUSES = {
    "CONFIRMED_APPLICABLE", "CLAIM_REQUIRED", "UNVERIFIED", "INELIGIBLE",
    "EXPIRED", "UNKNOWN", "NONE",
}
IDENTITY_FIELDS = {
    "platform", "product_id", "sku_id", "seller_id", "condition", "package_signature",
}
TOP_FIELDS = {
    "schema_version", "series_identity", "data_classification", "source_id", "observed_at",
    "base_price_twd", "coupon", "confirmed_coupon_price_twd", "possible_coupon_price_twd",
    "display_price_twd", "display_basis", "shipping_status", "required_total_twd", "history",
}
COUPON_FIELDS = {
    "coupon_id", "status", "discount_twd", "already_included_in_base", "eligibility_profile",
    "valid_from", "valid_until", "scope_evidence",
}
HISTORY_FIELDS = {"before_coupon", "confirmed_after_coupon"}
BEFORE_HISTORY_FIELDS = {
    "observed_at", "price_twd", "series_identity", "source_id", "data_classification",
}
AFTER_HISTORY_FIELDS = BEFORE_HISTORY_FIELDS | {"coupon_id", "eligibility_profile", "scope_evidence"}


class CouponContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CouponContractError("INVALID_TYPE", f"{path} must be an object")
    return value


def _exact_fields(value: dict[str, Any], expected: set[str], path: str) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        raise CouponContractError("INVALID_FIELDS", f"{path} missing={sorted(missing)} unknown={sorted(unknown)}")


def _text(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value or len(value) > 256:
        raise CouponContractError("INVALID_TEXT", f"{path} must be a bounded non-empty string")
    stripped = value.lstrip()
    if any(ord(character) < 0x20 for character in value) or stripped[:1] in {"=", "+", "-", "@"}:
        raise CouponContractError("TEXT_INJECTION", f"{path} contains control/CSV formula syntax")
    if "<" in value or ">" in value:
        raise CouponContractError("TEXT_INJECTION", f"{path} contains markup syntax")
    return value


def _integer(value: Any, path: str, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CouponContractError("INVALID_PRICE", f"{path} must be a non-negative integer or explicit null")
    return value


def _timestamp(value: Any, path: str) -> datetime:
    raw = _text(value, path)
    assert raw is not None
    if not raw.endswith("Z"):
        raise CouponContractError("INVALID_TIMESTAMP", f"{path} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00")
    except ValueError as exc:
        raise CouponContractError("INVALID_TIMESTAMP", f"{path} is not a valid timestamp") from exc
    return parsed.astimezone(timezone.utc)


def _identity(value: Any, path: str) -> dict[str, str]:
    raw = _object(value, path)
    _exact_fields(raw, IDENTITY_FIELDS, path)
    result = {name: _text(raw[name], f"{path}.{name}") for name in sorted(IDENTITY_FIELDS)}
    if result["platform"] != "COUPANG_TW":
        raise CouponContractError("PLATFORM_MISMATCH", f"{path}.platform must be COUPANG_TW")
    return {name: value for name, value in result.items() if value is not None}


def _history_point(value: Any, path: str, *, after: bool, identity: dict[str, str]) -> dict[str, Any]:
    raw = _object(value, path)
    _exact_fields(raw, AFTER_HISTORY_FIELDS if after else BEFORE_HISTORY_FIELDS, path)
    point_identity = _identity(raw["series_identity"], f"{path}.series_identity")
    if point_identity != identity:
        raise CouponContractError("HISTORY_IDENTITY_MISMATCH", f"{path} belongs to a different exact series")
    result = {
        "observed_at": _text(raw["observed_at"], f"{path}.observed_at"),
        "price_twd": _integer(raw["price_twd"], f"{path}.price_twd"),
        "series_identity": point_identity,
        "source_id": _text(raw["source_id"], f"{path}.source_id"),
        "data_classification": _text(raw["data_classification"], f"{path}.data_classification"),
    }
    _timestamp(result["observed_at"], f"{path}.observed_at")
    if result["data_classification"] != "SYNTHETIC_FIXTURE":
        raise CouponContractError("SOURCE_NOT_AUTHORIZED", f"{path} is not an authorized synthetic fixture")
    if after:
        result.update({
            "coupon_id": _text(raw["coupon_id"], f"{path}.coupon_id"),
            "eligibility_profile": _text(raw["eligibility_profile"], f"{path}.eligibility_profile"),
            "scope_evidence": _text(raw["scope_evidence"], f"{path}.scope_evidence"),
        })
    return result


def _history(value: Any, identity: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    raw = _object(value, "history")
    _exact_fields(raw, HISTORY_FIELDS, "history")
    before = raw["before_coupon"]
    after = raw["confirmed_after_coupon"]
    if not isinstance(before, list) or not isinstance(after, list):
        raise CouponContractError("INVALID_HISTORY", "history branches must be arrays")
    return {
        "before_coupon": [_history_point(item, f"history.before_coupon[{index}]", after=False, identity=identity) for index, item in enumerate(before)],
        "confirmed_after_coupon": [_history_point(item, f"history.confirmed_after_coupon[{index}]", after=True, identity=identity) for index, item in enumerate(after)],
    }


def evaluate_coupon_v4(
    payload: dict[str, Any],
    *,
    now: datetime,
    expected_identity: dict[str, str] | None = None,
    eligibility_profile: str | None = None,
    minimum_purchase_quantity: int = 1,
    discount_scope: str = "UNIT",
) -> dict[str, Any]:
    """Strict, synthetic-only reference evaluation for the frozen R06 V4 contract."""
    raw = _object(deepcopy(payload), "payload")
    _exact_fields(raw, TOP_FIELDS, "payload")
    if raw["schema_version"] != SCHEMA:
        raise CouponContractError("VERSION_MISMATCH", f"schema_version must be {SCHEMA}")
    identity = _identity(raw["series_identity"], "series_identity")
    if expected_identity is not None and identity != expected_identity:
        raise CouponContractError("REQUEST_IDENTITY_MISMATCH", "payload series does not match requested exact series")
    classification = _text(raw["data_classification"], "data_classification")
    source_id = _text(raw["source_id"], "source_id")
    observed_at = _text(raw["observed_at"], "observed_at")
    _timestamp(observed_at, "observed_at")
    if classification != "SYNTHETIC_FIXTURE" or not str(source_id).startswith("SYN-"):
        raise CouponContractError("SOURCE_NOT_AUTHORIZED", "D07 accepts synthetic fixtures only")
    base = _integer(raw["base_price_twd"], "base_price_twd", nullable=True)
    declared_confirmed = _integer(raw["confirmed_coupon_price_twd"], "confirmed_coupon_price_twd", nullable=True)
    possible = _integer(raw["possible_coupon_price_twd"], "possible_coupon_price_twd", nullable=True)
    _integer(raw["display_price_twd"], "display_price_twd", nullable=True)
    _integer(raw["required_total_twd"], "required_total_twd", nullable=True)
    _text(raw["display_basis"], "display_basis")
    shipping = _text(raw["shipping_status"], "shipping_status")
    if shipping not in {"FREE", "PAID", "UNKNOWN"}:
        raise CouponContractError("INVALID_SHIPPING", "shipping_status is invalid")
    if isinstance(minimum_purchase_quantity, bool) or not isinstance(minimum_purchase_quantity, int) or minimum_purchase_quantity < 1:
        raise CouponContractError("INVALID_QUANTITY", "minimum_purchase_quantity must be a positive integer")
    if discount_scope not in {"UNIT", "ORDER"}:
        raise CouponContractError("INVALID_DISCOUNT_SCOPE", "discount_scope must be UNIT or ORDER")

    coupon = _object(raw["coupon"], "coupon")
    _exact_fields(coupon, COUPON_FIELDS, "coupon")
    coupon_id = _text(coupon["coupon_id"], "coupon.coupon_id", nullable=True)
    status = _text(coupon["status"], "coupon.status")
    if status not in STATUSES:
        raise CouponContractError("INVALID_STATUS", "coupon.status is invalid")
    discount = _integer(coupon["discount_twd"], "coupon.discount_twd", nullable=True)
    included = coupon["already_included_in_base"]
    if not isinstance(included, bool):
        raise CouponContractError("INVALID_INCLUDED_FLAG", "already_included_in_base must be boolean")
    profile = _text(coupon["eligibility_profile"], "coupon.eligibility_profile", nullable=True)
    scope_evidence = _text(coupon["scope_evidence"], "coupon.scope_evidence", nullable=True)
    valid_from = _timestamp(coupon["valid_from"], "coupon.valid_from") if coupon["valid_from"] is not None else None
    valid_until = _timestamp(coupon["valid_until"], "coupon.valid_until") if coupon["valid_until"] is not None else None
    history = _history(raw["history"], identity)

    reasons: list[str] = []
    confirmed = status == "CONFIRMED_APPLICABLE"
    if not confirmed:
        reasons.append(f"COUPON_{status}")
        if declared_confirmed is not None:
            raise CouponContractError("UNCONFIRMED_PRICE_PRESENT", "non-confirmed coupon cannot provide confirmed_coupon_price_twd")
    if confirmed:
        if base is None or discount is None or coupon_id is None or profile is None or scope_evidence is None:
            reasons.append("CONFIRMATION_EVIDENCE_INCOMPLETE")
        if valid_from is None or valid_until is None or not (valid_from <= now.astimezone(timezone.utc) < valid_until):
            reasons.append("COUPON_OUTSIDE_VALIDITY")
        if eligibility_profile is not None and profile != eligibility_profile:
            reasons.append("ELIGIBILITY_PROFILE_MISMATCH")

    usable = confirmed and not reasons
    required_total: int | None = None
    computed_confirmed: int | None = None
    if usable:
        assert base is not None and discount is not None
        if included:
            computed_confirmed = base
            required_total = base * minimum_purchase_quantity
        elif discount_scope == "UNIT":
            if discount > base:
                raise CouponContractError("DISCOUNT_EXCEEDS_PRICE", "discount cannot manufacture a negative/zero-clamped price")
            computed_confirmed = base - discount
            required_total = computed_confirmed * minimum_purchase_quantity
        else:
            order_total = base * minimum_purchase_quantity - discount
            if order_total < 0:
                raise CouponContractError("DISCOUNT_EXCEEDS_PRICE", "order discount exceeds required merchandise total")
            if order_total % minimum_purchase_quantity:
                reasons.append("UNIT_PRICE_NOT_EXACT_INTEGER")
                usable = False
            else:
                computed_confirmed = order_total // minimum_purchase_quantity
                required_total = order_total
        if usable and declared_confirmed != computed_confirmed:
            raise CouponContractError("CONFIRMED_PRICE_MISMATCH", "declared confirmed price does not match evidence-preserving calculation")

    if shipping != "FREE":
        required_total = None

    display = computed_confirmed if usable else base
    basis = "CONFIRMED_COUPON" if usable else ("BASE_PRICE" if base is not None else "PRICE_UNKNOWN")
    expected_declared_display = raw["display_price_twd"]
    expected_declared_basis = raw["display_basis"]
    expected_declared_total = raw["required_total_twd"]
    if expected_declared_display != display or expected_declared_basis != basis:
        raise CouponContractError("DISPLAY_MISMATCH", "declared display does not match fail-closed evaluation")
    if expected_declared_total != required_total:
        raise CouponContractError("REQUIRED_TOTAL_MISMATCH", "required_total_twd does not match quantity/shipping-safe calculation")

    return {
        "schema_version": SCHEMA,
        "series_identity": identity,
        "data_classification": classification,
        "source_id": source_id,
        "base_price_twd": base,
        "confirmed_coupon_price_twd": computed_confirmed if usable else None,
        "possible_coupon_price_twd": possible,
        "display_price_twd": display,
        "display_basis": basis,
        "shipping_status": shipping,
        "required_total_twd": required_total,
        "coupon_applied": usable,
        "reasons": sorted(set(reasons)),
        "history": history,
        "cta_enabled": False,
        "cta_url": None,
    }
