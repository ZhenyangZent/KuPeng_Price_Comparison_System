"""Strict, loss-aware adapter for the exact B10 Search and Detail wire."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import median_low
from zoneinfo import ZoneInfo

from .models import (
    CouponEvidence,
    CouponPriceSnapshot,
    HistoryPoint,
    HistoryQuality,
    SeriesIdentity,
    SourcePermission,
)


SCHEMA_VERSION = "CDH-COUPON-PRICE-V4"
CLASSIFICATION = "SYNTHETIC_FIXTURE"
TAIPEI = ZoneInfo("Asia/Taipei")
SEARCH_FIELDS = frozenset({"schema_version", "data_classification", "items", "page", "limit", "total", "data_version"})
DETAIL_FIELDS = frozenset({"schema_version", "data_classification", "product", "history", "history_quality", "data_version"})
PRODUCT_FIELDS = frozenset(
    {
        "series_key", "title", "series_identity", "data_classification", "source_id", "observed_at",
        "base_price_twd", "before_coupon_price_twd", "coupon", "confirmed_coupon_price_twd",
        "possible_coupon_price_twd", "display_price_twd", "display_basis", "minimum_purchase_quantity",
        "minimum_item_spend_twd", "shipping_status", "required_total_twd", "source_permission", "quality_flags",
    }
)
IDENTITY_FIELDS = frozenset({"platform", "product_id", "sku_id", "seller_id", "condition", "package_signature"})
COUPON_FIELDS = frozenset(
    {
        "coupon_id", "status", "discount_twd", "discount_scope", "already_included_in_base",
        "eligibility_profile", "valid_from", "valid_until", "scope_evidence",
        "pre_coupon_comparison_source", "evaluation_reasons",
    }
)
PERMISSION_FIELDS = frozenset({"allowed", "state", "reason"})
HISTORY_FIELDS = frozenset({"before_coupon", "confirmed_after_coupon"})
QUALITY_FIELDS = HISTORY_FIELDS
BEFORE_FIELDS = frozenset({"observed_at", "price_twd", "source_id", "comparison_source", "series_key"})
AFTER_FIELDS = frozenset({"observed_at", "price_twd", "coupon_id", "eligibility_profile", "source_id", "scope_evidence", "series_key"})
TRACK_QUALITY_FIELDS = frozenset({"raw_sample_count", "daily_representatives", "truncated"})
DAILY_FIELDS = frozenset({"taipei_date", "representative_price_twd", "sample_count"})
STATUSES = frozenset({"CONFIRMED_APPLICABLE", "CLAIM_REQUIRED", "UNVERIFIED", "INELIGIBLE", "EXPIRED", "UNKNOWN", "NONE"})
SCOPES = frozenset({"UNIT", "ORDER_TOTAL", "NONE"})
DISPLAY_BASES = frozenset({"CONFIRMED_COUPON", "BASE_PRICE", "PRICE_UNAVAILABLE"})
SHIPPING_STATES = frozenset({"UNKNOWN", "KNOWN"})
FORBIDDEN_KEYS = frozenset({"url", "click_url", "affiliate_url", "redirect", "token", "secret", "api_key", "cookie", "authorization", "password"})


class B10WireError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            found.add(str(key).casefold())
            found.update(_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_keys(child))
    return found


def _exact(value: object, fields: frozenset[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise B10WireError(code, f"exact fields required: {sorted(fields)}")
    return value


def _identifier(value: object, name: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 256:
        raise B10WireError(f"{name.upper()}_INVALID", f"{name} must be a bounded non-empty string")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in value) or "://" in value:
        raise B10WireError(f"{name.upper()}_INVALID", f"{name} contains forbidden characters or URL data")
    return value


def _integer(value: object, name: str, *, nullable: bool = True, minimum: int = 0) -> int | None:
    if nullable and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise B10WireError(f"{name.upper()}_INVALID", f"{name} must be an integer >= {minimum} or null")
    return value


def _time(value: object, name: str, *, nullable: bool = False) -> datetime | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise B10WireError(f"{name.upper()}_INVALID", f"{name} must use canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise B10WireError(f"{name.upper()}_INVALID", f"{name} must be ISO-8601") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise B10WireError(f"{name.upper()}_INVALID", f"{name} must be UTC")
    return parsed.astimezone(timezone.utc)


def _reason_list(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item or len(item) > 128 for item in value):
        raise B10WireError(f"{name.upper()}_INVALID", f"{name} must be a bounded string array")
    if len(value) != len(set(value)) or value != sorted(value):
        raise B10WireError(f"{name.upper()}_INVALID", f"{name} must be sorted and unique")
    return tuple(value)


def _validate_envelope(value: object, fields: frozenset[str], code: str) -> dict[str, object]:
    envelope = _exact(value, fields, code)
    forbidden = sorted(_keys(envelope) & FORBIDDEN_KEYS)
    if forbidden:
        raise B10WireError("FORBIDDEN_SECRET_OR_URL_FIELD", f"forbidden keys: {forbidden}")
    if envelope["schema_version"] != SCHEMA_VERSION:
        raise B10WireError("V4_SCHEMA_INVALID", "B10 V4 schema version required")
    if envelope["data_classification"] != CLASSIFICATION:
        raise B10WireError("CLASSIFICATION_NOT_AUTHORIZED", "synthetic fixture classification required")
    _identifier(envelope["data_version"], "data_version")
    return envelope


def _product(value: object, *, wire_source: str, data_version: str) -> CouponPriceSnapshot:
    product = _exact(value, PRODUCT_FIELDS, "B10_PRODUCT_STRUCTURE_INVALID")
    identity_value = _exact(product["series_identity"], IDENTITY_FIELDS, "SERIES_IDENTITY_INVALID")
    identity = SeriesIdentity(
        platform=_identifier(identity_value["platform"], "platform"),
        product_id=_identifier(identity_value["product_id"], "product_id"),
        sku_id=_identifier(identity_value["sku_id"], "sku_id"),
        seller_id=_identifier(identity_value["seller_id"], "seller_id"),
        condition=_identifier(identity_value["condition"], "condition"),
        package_signature=_identifier(identity_value["package_signature"], "package_signature"),
    )
    if identity.platform != "COUPANG_TW":
        raise B10WireError("PLATFORM_INVALID", "COUPANG_TW required")
    if product["data_classification"] != CLASSIFICATION:
        raise B10WireError("PRODUCT_CLASSIFICATION_INVALID", "product classification must match the synthetic envelope")
    coupon_value = _exact(product["coupon"], COUPON_FIELDS, "COUPON_STRUCTURE_INVALID")
    status = coupon_value["status"]
    if status not in STATUSES:
        raise B10WireError("COUPON_STATUS_INVALID", "unsupported B10 coupon status")
    scope = coupon_value["discount_scope"]
    if scope not in SCOPES:
        raise B10WireError("DISCOUNT_SCOPE_INVALID", "unsupported B10 discount scope")
    if not isinstance(coupon_value["already_included_in_base"], bool):
        raise B10WireError("ALREADY_INCLUDED_INVALID", "already_included_in_base must be boolean")
    coupon = CouponEvidence(
        coupon_id=_identifier(coupon_value["coupon_id"], "coupon_id", nullable=True),
        status=status,
        discount_twd=_integer(coupon_value["discount_twd"], "discount_twd"),
        discount_scope=scope,
        already_included_in_base=coupon_value["already_included_in_base"],
        eligibility_profile=_identifier(coupon_value["eligibility_profile"], "eligibility_profile", nullable=True),
        valid_from=_time(coupon_value["valid_from"], "valid_from", nullable=True),
        valid_until=_time(coupon_value["valid_until"], "valid_until", nullable=True),
        scope_evidence=_identifier(coupon_value["scope_evidence"], "scope_evidence", nullable=True),
        pre_coupon_comparison_source=_identifier(coupon_value["pre_coupon_comparison_source"], "pre_coupon_comparison_source", nullable=True),
        evaluation_reasons=_reason_list(coupon_value["evaluation_reasons"], "evaluation_reasons"),
    )
    permission_value = _exact(product["source_permission"], PERMISSION_FIELDS, "SOURCE_PERMISSION_STRUCTURE_INVALID")
    if not isinstance(permission_value["allowed"], bool):
        raise B10WireError("SOURCE_PERMISSION_ALLOWED_INVALID", "allowed must be boolean")
    permission = SourcePermission(
        allowed=permission_value["allowed"],
        state=_identifier(permission_value["state"], "source_permission_state"),
        reason=_identifier(permission_value["reason"], "source_permission_reason"),
    )
    if permission.allowed != (permission.state == "ACTIVE_SYNTHETIC_FIXTURE" and permission.reason == "SOURCE_PERMISSION_ACTIVE"):
        raise B10WireError("SOURCE_PERMISSION_CONTRADICTION", "allowed must exactly match the active synthetic permission state")
    display_basis = product["display_basis"]
    if display_basis not in DISPLAY_BASES:
        raise B10WireError("DISPLAY_BASIS_INVALID", "unsupported B10 display basis")
    shipping = product["shipping_status"]
    if shipping not in SHIPPING_STATES:
        raise B10WireError("SHIPPING_STATUS_INVALID", "unsupported B10 shipping state")
    snapshot = CouponPriceSnapshot(
        wire_source=wire_source,
        data_version=data_version,
        series_key=_identifier(product["series_key"], "series_key"),
        title=_identifier(product["title"], "title"),
        series_identity=identity,
        data_classification=CLASSIFICATION,
        source_id=_identifier(product["source_id"], "source_id", nullable=True),
        observed_at=_time(product["observed_at"], "observed_at", nullable=True),
        base_price_twd=_integer(product["base_price_twd"], "base_price_twd"),
        before_coupon_price_twd=_integer(product["before_coupon_price_twd"], "before_coupon_price_twd"),
        coupon=coupon,
        confirmed_coupon_price_twd=_integer(product["confirmed_coupon_price_twd"], "confirmed_coupon_price_twd"),
        possible_coupon_price_twd=_integer(product["possible_coupon_price_twd"], "possible_coupon_price_twd"),
        upstream_display_price_twd=_integer(product["display_price_twd"], "display_price_twd"),
        upstream_display_basis=display_basis,
        minimum_purchase_quantity=_integer(product["minimum_purchase_quantity"], "minimum_purchase_quantity", nullable=False, minimum=1),
        minimum_item_spend_twd=_integer(product["minimum_item_spend_twd"], "minimum_item_spend_twd"),
        shipping_status=shipping,
        upstream_required_total_twd=_integer(product["required_total_twd"], "required_total_twd"),
        source_permission=permission,
        quality_flags=_reason_list(product["quality_flags"], "quality_flags"),
        before_coupon_history=(),
        confirmed_after_coupon_history=(),
        before_coupon_history_quality=None,
        confirmed_after_coupon_history_quality=None,
    )
    _validate_product_consistency(snapshot)
    return snapshot


def _validate_product_consistency(snapshot: CouponPriceSnapshot) -> None:
    if not snapshot.source_permission.allowed:
        if any(value is not None for value in (snapshot.base_price_twd, snapshot.before_coupon_price_twd, snapshot.confirmed_coupon_price_twd, snapshot.possible_coupon_price_twd, snapshot.upstream_display_price_twd, snapshot.minimum_item_spend_twd, snapshot.upstream_required_total_twd)):
            raise B10WireError("SOURCE_PERMISSION_PRICE_LEAK", "blocked source permission must suppress every price")
        if snapshot.upstream_display_basis != "PRICE_UNAVAILABLE":
            raise B10WireError("SOURCE_PERMISSION_DISPLAY_LEAK", "blocked source permission must be unavailable")
        if snapshot.source_permission.reason not in snapshot.quality_flags:
            raise B10WireError("SOURCE_PERMISSION_REASON_MISSING", "permission denial reason must be retained in quality flags")
    if snapshot.confirmed_coupon_price_twd is not None and snapshot.possible_coupon_price_twd is not None:
        raise B10WireError("CONFIRMED_AND_POSSIBLE_CONFLICT", "confirmed and possible coupon prices cannot coexist")
    if snapshot.upstream_display_basis == "CONFIRMED_COUPON":
        if snapshot.upstream_display_price_twd != snapshot.confirmed_coupon_price_twd or snapshot.confirmed_coupon_price_twd is None:
            raise B10WireError("CONFIRMED_DISPLAY_MISMATCH", "confirmed display must equal confirmed coupon price")
    elif snapshot.upstream_display_basis == "BASE_PRICE":
        if snapshot.upstream_display_price_twd != snapshot.base_price_twd or snapshot.base_price_twd is None or snapshot.confirmed_coupon_price_twd is not None:
            raise B10WireError("BASE_DISPLAY_MISMATCH", "base display must equal the known base without a confirmed price")
    elif snapshot.upstream_display_price_twd is not None:
        raise B10WireError("UNAVAILABLE_DISPLAY_MISMATCH", "unavailable display must be null")
    quantity = snapshot.minimum_purchase_quantity
    expected_spend = None
    if snapshot.upstream_display_basis == "CONFIRMED_COUPON" and snapshot.confirmed_coupon_price_twd is not None:
        if snapshot.coupon.discount_scope == "ORDER_TOTAL" and snapshot.coupon.discount_twd is not None and snapshot.base_price_twd is not None:
            expected_spend = snapshot.base_price_twd * quantity - snapshot.coupon.discount_twd
        else:
            expected_spend = snapshot.confirmed_coupon_price_twd * quantity
    elif snapshot.upstream_display_basis == "BASE_PRICE" and snapshot.base_price_twd is not None:
        expected_spend = snapshot.base_price_twd * quantity
    if snapshot.minimum_item_spend_twd != expected_spend:
        raise B10WireError("MINIMUM_ITEM_SPEND_MISMATCH", "minimum item spend does not preserve B10 quantity semantics")
    if snapshot.shipping_status == "UNKNOWN" and snapshot.upstream_required_total_twd is not None:
        raise B10WireError("UNKNOWN_SHIPPING_TOTAL_INVALID", "unknown shipping requires null total")
    if snapshot.upstream_required_total_twd is not None and expected_spend is not None and snapshot.upstream_required_total_twd < expected_spend:
        raise B10WireError("REQUIRED_TOTAL_BELOW_ITEM_SPEND", "required total cannot be below minimum item spend")
    coupon = snapshot.coupon
    if coupon.already_included_in_base and snapshot.confirmed_coupon_price_twd is not None:
        if snapshot.base_price_twd != snapshot.confirmed_coupon_price_twd or snapshot.before_coupon_price_twd is None or coupon.discount_twd is None or snapshot.before_coupon_price_twd - snapshot.base_price_twd != coupon.discount_twd or coupon.pre_coupon_comparison_source is None:
            raise B10WireError("ALREADY_INCLUDED_EVIDENCE_INVALID", "already-included coupon must retain comparison price/source and exact math")
    elif snapshot.base_price_twd is not None and snapshot.before_coupon_price_twd != snapshot.base_price_twd:
        raise B10WireError("BEFORE_COUPON_PRICE_MISMATCH", "non-included before-coupon price must equal base")


def _history_point(value: object, *, kind: str, series_key: str) -> HistoryPoint:
    fields = BEFORE_FIELDS if kind == "before_coupon" else AFTER_FIELDS
    item = _exact(value, fields, "B10_HISTORY_POINT_INVALID")
    if item["series_key"] != series_key:
        raise B10WireError("HISTORY_SERIES_MISMATCH", "history point series_key must match product")
    common = dict(
        observed_at=_time(item["observed_at"], "history_observed_at"),
        price_twd=_integer(item["price_twd"], "history_price_twd", nullable=False),
        source_id=_identifier(item["source_id"], "history_source_id"),
        series_key=series_key,
    )
    if kind == "before_coupon":
        return HistoryPoint(**common, comparison_source=_identifier(item["comparison_source"], "comparison_source"))
    return HistoryPoint(
        **common,
        coupon_id=_identifier(item["coupon_id"], "history_coupon_id"),
        eligibility_profile=_identifier(item["eligibility_profile"], "history_eligibility_profile"),
        scope_evidence=_identifier(item["scope_evidence"], "history_scope_evidence"),
    )


def _history_quality(value: object, *, points: tuple[HistoryPoint, ...], kind: str) -> HistoryQuality:
    quality = _exact(value, TRACK_QUALITY_FIELDS, "B10_HISTORY_QUALITY_INVALID")
    count = _integer(quality["raw_sample_count"], "raw_sample_count", nullable=False)
    if count != len(points):
        raise B10WireError("HISTORY_RAW_COUNT_MISMATCH", "raw_sample_count must equal returned raw history length")
    if not isinstance(quality["truncated"], bool):
        raise B10WireError("HISTORY_TRUNCATED_INVALID", "truncated must be boolean")
    if not isinstance(quality["daily_representatives"], list):
        raise B10WireError("DAILY_REPRESENTATIVES_INVALID", "daily representatives must be an array")
    daily: list[tuple[str, int, int]] = []
    for value_item in quality["daily_representatives"]:
        item = _exact(value_item, DAILY_FIELDS, "DAILY_REPRESENTATIVE_INVALID")
        date = _identifier(item["taipei_date"], "taipei_date")
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError as exc:
            raise B10WireError("TAIPEI_DATE_INVALID", "daily date must be YYYY-MM-DD") from exc
        daily.append((date, _integer(item["representative_price_twd"], "representative_price_twd", nullable=False), _integer(item["sample_count"], "sample_count", nullable=False, minimum=1)))
    groups: dict[str, list[int]] = defaultdict(list)
    for point in points:
        groups[point.observed_at.astimezone(TAIPEI).date().isoformat()].append(point.price_twd)
    expected = tuple((date, median_low(prices), len(prices)) for date, prices in sorted(groups.items()))
    if tuple(daily) != expected:
        raise B10WireError("DAILY_REPRESENTATIVE_MISMATCH", f"{kind} daily representatives do not match raw history")
    return HistoryQuality(count, tuple(daily), quality["truncated"])


def adapt_search_envelope(value: object) -> tuple[CouponPriceSnapshot, ...]:
    envelope = _validate_envelope(value, SEARCH_FIELDS, "B10_SEARCH_STRUCTURE_INVALID")
    page = _integer(envelope["page"], "page", nullable=False, minimum=1)
    limit = _integer(envelope["limit"], "limit", nullable=False, minimum=1)
    total = _integer(envelope["total"], "total", nullable=False)
    if limit > 100 or not isinstance(envelope["items"], list) or total < len(envelope["items"]):
        raise B10WireError("B10_SEARCH_PAGINATION_INVALID", "pagination or item count is inconsistent")
    data_version = _identifier(envelope["data_version"], "data_version")
    del page
    return tuple(_product(item, wire_source="B10_SEARCH", data_version=data_version) for item in envelope["items"])


def adapt_detail_envelope(value: object) -> CouponPriceSnapshot:
    envelope = _validate_envelope(value, DETAIL_FIELDS, "B10_DETAIL_STRUCTURE_INVALID")
    data_version = _identifier(envelope["data_version"], "data_version")
    snapshot = _product(envelope["product"], wire_source="B10_DETAIL", data_version=data_version)
    history = _exact(envelope["history"], HISTORY_FIELDS, "B10_HISTORY_STRUCTURE_INVALID")
    quality = _exact(envelope["history_quality"], QUALITY_FIELDS, "B10_HISTORY_QUALITY_STRUCTURE_INVALID")
    if not isinstance(history["before_coupon"], list) or not isinstance(history["confirmed_after_coupon"], list):
        raise B10WireError("B10_HISTORY_ARRAY_INVALID", "both history tracks must be arrays")
    before = tuple(_history_point(item, kind="before_coupon", series_key=snapshot.series_key) for item in history["before_coupon"])
    after = tuple(_history_point(item, kind="confirmed_after_coupon", series_key=snapshot.series_key) for item in history["confirmed_after_coupon"])
    if any(left.observed_at > right.observed_at for left, right in zip(before, before[1:])) or any(left.observed_at > right.observed_at for left, right in zip(after, after[1:])):
        raise B10WireError("HISTORY_ORDER_INVALID", "history tracks must be chronological")
    before_quality = _history_quality(quality["before_coupon"], points=before, kind="before_coupon")
    after_quality = _history_quality(quality["confirmed_after_coupon"], points=after, kind="confirmed_after_coupon")
    if not snapshot.source_permission.allowed and (before or after):
        raise B10WireError("SOURCE_PERMISSION_HISTORY_LEAK", "blocked permission must suppress both histories")
    return CouponPriceSnapshot(
        **{field: getattr(snapshot, field) for field in snapshot.__dataclass_fields__ if field not in {"before_coupon_history", "confirmed_after_coupon_history", "before_coupon_history_quality", "confirmed_after_coupon_history_quality"}},
        before_coupon_history=before,
        confirmed_after_coupon_history=after,
        before_coupon_history_quality=before_quality,
        confirmed_after_coupon_history_quality=after_quality,
    )
