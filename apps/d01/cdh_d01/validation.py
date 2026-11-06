from __future__ import annotations

import ipaddress
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .model import (
    GENERIC_STATES,
    PRICE_BASES,
    RECORD_TYPES,
    SCHEMA_VERSION,
    SHIPPING_STATES,
    SOURCE_KINDS,
    STOCK_STATES,
    ValidatedRecord,
    ValidationError,
)

MAX_JSON_BYTES = 1_048_576
MAX_TEXT = 4096
SAFE_QUERY_KEYS = {"itemId", "vendorItemId", "productId"}


def _text(value: Any, field: str, *, required: bool = False, limit: int = MAX_TEXT) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError("INVALID_TEXT", f"{field} must be a string")
    value = value.strip()
    if required and not value:
        raise ValidationError("MISSING_REQUIRED_FIELD", f"{field} is required")
    if len(value) > limit:
        raise ValidationError("TEXT_TOO_LONG", f"{field} exceeds {limit} characters")
    return value


def _nullable_id(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    text = _text(value, field, required=True, limit=256)
    if any(ord(ch) < 32 for ch in text):
        raise ValidationError("INVALID_IDENTIFIER", f"{field} contains a control character")
    return text


def _integer(value: Any, field: str, *, nullable: bool = True, positive: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("INVALID_INTEGER", f"{field} must be an integer and not bool")
    if value < (1 if positive else 0):
        raise ValidationError("INVALID_INTEGER_RANGE", f"{field} is outside the accepted range")
    if value > 100_000_000:
        raise ValidationError("INVALID_INTEGER_RANGE", f"{field} is outside the accepted range")
    return value


def _timestamp(value: Any, field: str, *, now: datetime, future_tolerance: timedelta) -> str:
    text = _text(value, field, required=True, limit=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("INVALID_TIMESTAMP", f"{field} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError("TIMESTAMP_WITHOUT_TIMEZONE", f"{field} must include timezone")
    parsed = parsed.astimezone(timezone.utc)
    if parsed > now + future_tolerance:
        raise ValidationError("TIMESTAMP_TOO_FAR_FUTURE", f"{field} is too far in the future")
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def sanitize_url(value: Any, field: str = "source.url") -> str | None:
    if value is None or value == "":
        return None
    text = _text(value, field, required=True, limit=2048)
    try:
        parts = urlsplit(text)
    except ValueError as exc:
        raise ValidationError("UNSAFE_URL", f"{field} cannot be parsed") from exc
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValidationError("UNSAFE_URL", f"{field} must be an http(s) URL")
    if parts.username or parts.password or parts.port not in {None, 80, 443}:
        raise ValidationError("UNSAFE_URL", f"{field} contains credentials or a nonstandard port")
    host = parts.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValidationError("UNSAFE_URL", f"{field} points to localhost")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
        raise ValidationError("UNSAFE_URL", f"{field} points to a non-public address")
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        raise ValidationError("UNSAFE_URL", f"{field} has an invalid host")
    safe_query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=False) if key in SAFE_QUERY_KEYS]
    netloc = host
    if parts.port and parts.port not in {80, 443}:
        netloc = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", urlencode(safe_query), ""))


def _enum(value: Any, field: str, allowed: set[str]) -> str:
    text = _text(value, field, required=True, limit=64)
    if text not in allowed:
        raise ValidationError("INVALID_ENUM", f"{field} has unsupported value {text!r}")
    return text


def _reject_non_json_numbers(value: Any) -> None:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValidationError("NON_FINITE_NUMBER", "NaN and Infinity are not accepted")
    if isinstance(value, dict):
        for child in value.values():
            _reject_non_json_numbers(child)
    elif isinstance(value, list):
        for child in value:
            _reject_non_json_numbers(child)


def decode_json_bytes(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_JSON_BYTES:
        raise ValidationError("FILE_TOO_LARGE", f"JSON exceeds {MAX_JSON_BYTES} bytes")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("INVALID_ENCODING", "JSON must be UTF-8") from exc
    try:
        value = json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValidationError("MALFORMED_JSON", "JSON cannot be decoded") from exc
    if not isinstance(value, dict):
        raise ValidationError("INVALID_DOCUMENT_TYPE", "top-level JSON must be an object")
    _reject_non_json_numbers(value)
    return value


def validate_record(payload: dict[str, Any], *, now: datetime | None = None) -> ValidatedRecord:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError("SCHEMA_VERSION_MISMATCH", "schema_version must equal CDH-EXCHANGE-1")
    submission_text = _text(payload.get("submission_id"), "submission_id", required=True, limit=36)
    try:
        submission_id = str(uuid.UUID(submission_text))
    except ValueError as exc:
        raise ValidationError("INVALID_UUID", "submission_id must be a valid UUID") from exc
    if submission_id != submission_text.lower():
        raise ValidationError("NON_CANONICAL_UUID", "submission_id must use canonical UUID form")
    record_type = _enum(payload.get("record_type"), "record_type", RECORD_TYPES)
    created_at = _timestamp(payload.get("created_at_utc"), "created_at_utc", now=now, future_tolerance=timedelta(minutes=5))
    observed_at = _timestamp(payload.get("observed_at_utc"), "observed_at_utc", now=now, future_tolerance=timedelta(minutes=5))
    source = payload.get("source")
    offer = payload.get("offer")
    if not isinstance(source, dict) or not isinstance(offer, dict):
        raise ValidationError("MISSING_REQUIRED_OBJECT", "source and offer must be objects")
    source_kind = _enum(source.get("source_kind"), "source.source_kind", SOURCE_KINDS)
    source_id = _nullable_id(source.get("source_id"), "source.source_id")
    permission_scope = _text(source.get("permission_scope"), "source.permission_scope", required=True, limit=128)
    source_url = sanitize_url(source.get("url"))
    if source_url:
        host = urlsplit(source_url).hostname
        if record_type == "USER_PRICE_OBSERVATION" and host not in {"www.tw.coupang.com", "tw.coupang.com"}:
            raise ValidationError("UNSUPPORTED_PRODUCT_URL_HOST", "observation URLs must use the Coupang Taiwan host")
        if record_type == "PROMO_CLUE" and source_kind == "PUBLIC_NOTICE_MANUAL" and host != "tw.coupangcorp.com":
            raise ValidationError("UNSUPPORTED_NOTICE_URL_HOST", "manual official notices must use tw.coupangcorp.com")
    source_note = _text(source.get("note"), "source.note", limit=MAX_TEXT)
    platform = _text(offer.get("platform"), "offer.platform", required=True, limit=64)
    if platform != "TW_COUPANG":
        raise ValidationError("UNSUPPORTED_PLATFORM", "only TW_COUPANG is supported")
    title = _text(offer.get("product_title"), "offer.product_title", required=True, limit=512)
    price = _integer(offer.get("displayed_price_twd"), "offer.displayed_price_twd")
    price_basis = _enum(offer.get("price_basis", "DISPLAYED_UNKNOWN"), "offer.price_basis", PRICE_BASES)
    minimum_quantity = _integer(offer.get("minimum_purchase_quantity"), "offer.minimum_purchase_quantity", positive=True)
    shipping_status = _enum(offer.get("shipping_status", "UNKNOWN"), "offer.shipping_status", SHIPPING_STATES)
    shipping_fee = _integer(offer.get("shipping_fee_twd"), "offer.shipping_fee_twd")
    stock_status = _enum(offer.get("stock_status", "UNKNOWN"), "offer.stock_status", STOCK_STATES)
    coupon_status = _enum(offer.get("coupon_status", "UNKNOWN"), "offer.coupon_status", GENERIC_STATES)
    account_status = _enum(offer.get("account_eligibility_status", "UNKNOWN"), "offer.account_eligibility_status", GENERIC_STATES)
    fee_status = _enum(offer.get("mandatory_fee_status", "UNKNOWN"), "offer.mandatory_fee_status", GENERIC_STATES)
    if not isinstance(payload.get("is_synthetic"), bool):
        raise ValidationError("INVALID_BOOLEAN", "is_synthetic must be boolean")
    is_synthetic = payload["is_synthetic"]
    if source_kind == "SYNTHETIC_TEST" and not is_synthetic:
        raise ValidationError("SYNTHETIC_FLAG_MISMATCH", "SYNTHETIC_TEST requires is_synthetic=true")
    if source_kind == "APPROVED_FEED" and permission_scope != "APPROVED":
        raise ValidationError("PERMISSION_SCOPE_MISMATCH", "APPROVED_FEED requires explicit APPROVED scope")
    if source_kind == "APPROVED_FEED" and source_id is None:
        raise ValidationError("MISSING_SOURCE_ID", "APPROVED_FEED requires source.source_id")
    promo_claim = payload.get("promo_claim")
    published_at: str | None = None
    if record_type == "PROMO_CLUE":
        promo_claim = _text(promo_claim, "promo_claim", required=True, limit=MAX_TEXT)
        if source_kind not in {"PUBLIC_NOTICE_MANUAL", "SYNTHETIC_TEST", "USER_FILE"}:
            raise ValidationError("PROMO_SOURCE_NOT_ALLOWED", "PROMO_CLUE must use a clue-appropriate source kind")
        if payload.get("published_at_utc") is not None:
            published_at = _timestamp(payload.get("published_at_utc"), "published_at_utc", now=now, future_tolerance=timedelta(minutes=5))
    else:
        if price is None:
            raise ValidationError("MISSING_PRICE", "an observation requires displayed_price_twd")
        promo_claim = None
    return ValidatedRecord(
        raw=payload,
        submission_id=submission_id,
        record_type=record_type,
        created_at_utc=created_at,
        observed_at_utc=observed_at,
        source_id=source_id,
        source_kind=source_kind,
        permission_scope=permission_scope,
        source_url=source_url,
        source_note=source_note,
        product_title=title,
        product_id=_nullable_id(offer.get("product_id"), "offer.product_id"),
        variant_id=_nullable_id(offer.get("variant_id"), "offer.variant_id"),
        seller_id=_nullable_id(offer.get("seller_id"), "offer.seller_id"),
        displayed_price_twd=price,
        price_basis=price_basis,
        minimum_purchase_quantity=minimum_quantity,
        shipping_status=shipping_status,
        shipping_fee_twd=shipping_fee,
        stock_status=stock_status,
        coupon_status=coupon_status,
        account_eligibility_status=account_status,
        mandatory_fee_status=fee_status,
        notes=_text(offer.get("notes"), "offer.notes", limit=MAX_TEXT),
        promo_claim=promo_claim,
        published_at_utc=published_at,
        is_synthetic=is_synthetic,
    )


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

