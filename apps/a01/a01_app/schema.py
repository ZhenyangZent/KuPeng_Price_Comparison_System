from __future__ import annotations

import copy
import ipaddress
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from .constants import EXCHANGE_VERSION


class ValidationError(ValueError):
    def __init__(self, code: str, detail: str, *, field: str | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.field = field


SUBMISSION_FIELDS = {
    "schema_version",
    "submission_id",
    "record_type",
    "created_at_utc",
    "observed_at_utc",
    "source",
    "offer",
    "is_synthetic",
}
SOURCE_FIELDS = {"source_kind", "permission_scope", "url", "note"}
OFFER_FIELDS = {
    "platform",
    "product_title",
    "product_id",
    "variant_id",
    "seller_id",
    "displayed_price_twd",
    "price_basis",
    "minimum_purchase_quantity",
    "shipping_status",
    "shipping_fee_twd",
    "stock_status",
    "coupon_status",
    "account_eligibility_status",
    "mandatory_fee_status",
    "notes",
}
SOURCE_PERMISSIONS = {
    "USER_ENTERED": "USER_PROVIDED_ONLY",
    "USER_FILE": "USER_PROVIDED_ONLY",
    "SYNTHETIC_TEST": "SYNTHETIC_ONLY",
    "PUBLIC_NOTICE_MANUAL": "PUBLIC_NOTICE_MANUAL_ONLY",
}
COUPANG_HOSTS = {"tw.coupang.com", "www.tw.coupang.com", "m.tw.coupang.com"}
PRICE_BASES = {"DISPLAYED_UNKNOWN", "DISPLAYED_UNIT", "DISPLAYED_TOTAL"}
SHIPPING_STATES = {"UNKNOWN", "FREE", "PAID", "CONFLICT"}
STOCK_STATES = {"UNKNOWN", "IN_STOCK", "OUT_OF_STOCK", "CONFLICT"}
COUPON_STATES = {"UNKNOWN", "NOT_APPLICABLE", "AVAILABLE_UNVERIFIED", "CONFIRMED", "INELIGIBLE"}
ELIGIBILITY_STATES = {"UNKNOWN", "USER_DECLARED_ACTIVE", "CONFIRMED", "INELIGIBLE"}
FEE_STATES = {"UNKNOWN", "KNOWN_ZERO", "KNOWN_AMOUNT", "NOT_APPLICABLE", "CONFLICT"}
UUID_TEXT = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _closed_dict(value: object, fields: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(code, "必須是 JSON 物件")
    if set(value) != fields:
        missing = sorted(fields - set(value))
        extra = sorted(set(value) - fields)
        raise ValidationError(code, f"欄位不符；缺少={missing}；多出={extra}")
    return value


def _text(value: object, field: str, *, required: bool = False, maximum: int = 500) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValidationError("INVALID_TEXT", f"{field} 必須是文字", field=field)
    cleaned = value.strip()
    if required and not cleaned:
        raise ValidationError("BLANK_TEXT", f"{field} 不可空白", field=field)
    if len(cleaned) > maximum:
        raise ValidationError("TEXT_TOO_LONG", f"{field} 超過 {maximum} 字元", field=field)
    return cleaned


def parse_utc(value: object, field: str, *, now: datetime | None = None) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValidationError("INVALID_TIMESTAMP", f"{field} 必須是有時區的 ISO-8601 UTC", field=field)
    if not (value.endswith("Z") or value.endswith("+00:00")):
        raise ValidationError("TIMESTAMP_TIMEZONE_REQUIRED", f"{field} 必須明示 UTC", field=field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("INVALID_TIMESTAMP", f"{field} 不是有效時間", field=field) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValidationError("TIMESTAMP_TIMEZONE_REQUIRED", f"{field} 必須是 UTC", field=field)
    check = now or datetime.now(timezone.utc)
    if check.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if parsed > check + timedelta(minutes=5):
        raise ValidationError("TIMESTAMP_TOO_FAR_FUTURE", f"{field} 過度位於未來", field=field)
    return parsed


def format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def strict_money(value: object, field: str, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("INVALID_MONEY", f"{field} 必須是整數 TWD；空值不等於 0", field=field)
    if value < 0 or value > 10_000_000:
        raise ValidationError("MONEY_OUT_OF_RANGE", f"{field} 超出允許範圍", field=field)
    return value


def parse_money_text(value: object, field: str = "displayed_price_twd") -> int:
    if not isinstance(value, str):
        raise ValidationError("INVALID_MONEY", f"{field} 必須是整數文字", field=field)
    cleaned = value.strip()
    if not cleaned:
        raise ValidationError("MONEY_REQUIRED", f"{field} 不可空白；空白不等於 0", field=field)
    lowered = cleaned.casefold()
    if lowered in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity"}:
        raise ValidationError("INVALID_MONEY", f"{field} 不接受 NaN/Infinity", field=field)
    if not re.fullmatch(r"0|[1-9][0-9]*", cleaned):
        raise ValidationError("INVALID_MONEY", f"{field} 必須是非負整數 TWD", field=field)
    return int(strict_money(int(cleaned), field))


def strict_quantity(value: object, field: str = "minimum_purchase_quantity") -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 10_000:
        raise ValidationError("INVALID_QUANTITY", f"{field} 必須是 1 以上整數或 null", field=field)
    return value


def safe_product_url(value: object) -> str | None:
    text = _text(value, "source.url", maximum=1000)
    if not text:
        return None
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationError("UNSAFE_URL", "URL 只接受 http/https", field="source.url")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError("UNSAFE_URL", "URL 不可包含帳密", field="source.url")
    host = parsed.hostname.casefold().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValidationError("PRIVATE_URL_BLOCKED", "不可使用 localhost", field="source.url")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValidationError("PRIVATE_URL_BLOCKED", "不可使用私有或本機 IP", field="source.url")
    if host not in COUPANG_HOSTS:
        raise ValidationError("UNAPPROVED_PRODUCT_HOST", "A01 僅保存核准的台灣酷澎商品網址", field="source.url")
    if parsed.port not in {None, 80, 443}:
        raise ValidationError("UNSAFE_URL", "URL port 不在允許範圍", field="source.url")
    return text


def _enum(value: object, field: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValidationError("INVALID_ENUM", f"{field} 必須是 {sorted(allowed)}", field=field)
    return value


def validate_submission(value: object, *, now: datetime | None = None) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError("INVALID_SUBMISSION", "提交必須是 JSON 物件")
    allowed_top = set(SUBMISSION_FIELDS)
    record_type = value.get("record_type")
    if record_type == "PROMO_CLUE":
        allowed_top.add("promo_claim")
    root = _closed_dict(value, allowed_top, "INVALID_SUBMISSION_FIELDS")
    if root["schema_version"] != EXCHANGE_VERSION:
        raise ValidationError("SCHEMA_VERSION_MISMATCH", "交換契約版本不符", field="schema_version")
    submission_id = root["submission_id"]
    if not isinstance(submission_id, str) or UUID_TEXT.fullmatch(submission_id) is None:
        raise ValidationError("INVALID_SUBMISSION_ID", "submission_id 必須是 canonical UUID", field="submission_id")
    try:
        parsed_uuid = uuid.UUID(submission_id)
    except ValueError as exc:
        raise ValidationError("INVALID_SUBMISSION_ID", "submission_id 不是 UUID", field="submission_id") from exc
    if str(parsed_uuid) != submission_id:
        raise ValidationError("INVALID_SUBMISSION_ID", "submission_id 必須使用小寫 canonical UUID", field="submission_id")
    if record_type not in {"USER_PRICE_OBSERVATION", "PROMO_CLUE"}:
        raise ValidationError("INVALID_RECORD_TYPE", "不支援的 record_type", field="record_type")
    current = now or datetime.now(timezone.utc)
    created = parse_utc(root["created_at_utc"], "created_at_utc", now=current)
    observed = parse_utc(root["observed_at_utc"], "observed_at_utc", now=current)
    if observed > created + timedelta(minutes=5):
        raise ValidationError("OBSERVED_AFTER_CREATED", "觀測時間不可晚於建立時間", field="observed_at_utc")

    source = _closed_dict(root["source"], SOURCE_FIELDS, "INVALID_SOURCE_FIELDS")
    source_kind = source["source_kind"]
    if source_kind not in SOURCE_PERMISSIONS:
        raise ValidationError("SOURCE_KIND_NOT_AUTHORIZED", "A01 不接受此來源類型", field="source.source_kind")
    if source["permission_scope"] != SOURCE_PERMISSIONS[source_kind]:
        raise ValidationError("SOURCE_PERMISSION_MISMATCH", "來源權限與來源類型不符", field="source.permission_scope")
    safe_product_url(source["url"])
    _text(source["note"], "source.note", required=True, maximum=500)

    offer = _closed_dict(root["offer"], OFFER_FIELDS, "INVALID_OFFER_FIELDS")
    if offer["platform"] != "TW_COUPANG":
        raise ValidationError("INVALID_PLATFORM", "platform 必須是 TW_COUPANG", field="offer.platform")
    _text(offer["product_title"], "offer.product_title", required=True, maximum=200)
    for field in ("product_id", "variant_id", "seller_id"):
        _text(offer[field], f"offer.{field}", maximum=128)
    price = strict_money(offer["displayed_price_twd"], "offer.displayed_price_twd", nullable=record_type == "PROMO_CLUE")
    if record_type == "USER_PRICE_OBSERVATION" and price is None:
        raise ValidationError("PRICE_REQUIRED", "價格觀測必須有明確整數價格", field="offer.displayed_price_twd")
    _enum(offer["price_basis"], "offer.price_basis", PRICE_BASES)
    strict_quantity(offer["minimum_purchase_quantity"])
    shipping = _enum(offer["shipping_status"], "offer.shipping_status", SHIPPING_STATES)
    shipping_fee = strict_money(offer["shipping_fee_twd"], "offer.shipping_fee_twd", nullable=True)
    if shipping == "UNKNOWN" and shipping_fee is not None:
        raise ValidationError("SHIPPING_EVIDENCE_CONFLICT", "運費 UNKNOWN 時不得附數字", field="offer.shipping_fee_twd")
    if shipping == "FREE" and shipping_fee not in {None, 0}:
        raise ValidationError("SHIPPING_EVIDENCE_CONFLICT", "FREE 與非零運費衝突", field="offer.shipping_fee_twd")
    if shipping == "PAID" and (shipping_fee is None or shipping_fee <= 0):
        raise ValidationError("SHIPPING_FEE_REQUIRED", "PAID 必須有正整數運費", field="offer.shipping_fee_twd")
    _enum(offer["stock_status"], "offer.stock_status", STOCK_STATES)
    _enum(offer["coupon_status"], "offer.coupon_status", COUPON_STATES)
    _enum(offer["account_eligibility_status"], "offer.account_eligibility_status", ELIGIBILITY_STATES)
    _enum(offer["mandatory_fee_status"], "offer.mandatory_fee_status", FEE_STATES)
    _text(offer["notes"], "offer.notes", maximum=1000)

    if not isinstance(root["is_synthetic"], bool):
        raise ValidationError("INVALID_SYNTHETIC_FLAG", "is_synthetic 必須是 boolean", field="is_synthetic")
    if (source_kind == "SYNTHETIC_TEST") != bool(root["is_synthetic"]):
        raise ValidationError("SYNTHETIC_NAMESPACE_MISMATCH", "合成旗標與來源 namespace 不一致", field="is_synthetic")
    if record_type == "PROMO_CLUE":
        _text(root["promo_claim"], "promo_claim", required=True, maximum=500)
    return copy.deepcopy(root)


def reject_nonfinite(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError("NONFINITE_NUMBER", "不接受 NaN 或 Infinity")
