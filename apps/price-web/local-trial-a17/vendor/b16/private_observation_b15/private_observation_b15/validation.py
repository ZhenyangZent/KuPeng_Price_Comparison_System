from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


SCHEMA_VERSION = "CDH-B15-MANUAL-OBSERVATION-1"
MAX_BODY_BYTES = 128 * 1024
TAIPEI = ZoneInfo("Asia/Taipei")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SUBMISSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
UNSAFE_TEXT = re.compile(r"[<>\x00-\x1f]|(?:^|\s)[a-z][a-z0-9+.-]*://", re.IGNORECASE)


class _DuplicateKey(ValueError):
    pass


class _InvalidConstant(ValueError):
    pass


class ValidationError(ValueError):
    def __init__(self, code: str, *, input_sha256: str | None = None) -> None:
        self.code = code
        self.input_sha256 = input_sha256
        super().__init__(code)


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = value
    return result


def strict_json(raw: bytes) -> tuple[object, str]:
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) > MAX_BODY_BYTES:
        raise ValidationError("REQUEST_BODY_TOO_LARGE", input_sha256=digest)
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValidationError("JSON_NOT_UTF8", input_sha256=digest) from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(_InvalidConstant()),
        )
    except _DuplicateKey as exc:
        raise ValidationError("JSON_DUPLICATE_KEY", input_sha256=digest) from exc
    except (_InvalidConstant, json.JSONDecodeError, RecursionError) as exc:
        raise ValidationError("JSON_INVALID", input_sha256=digest) from exc
    return value, digest


def _exact(value: object, fields: set[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError(code)
    return value


def _identifier(value: object, code: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValidationError(code)
    return value


def _text(value: object, code: str, *, maximum: int, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or UNSAFE_TEXT.search(value):
        raise ValidationError(code)
    return value.strip()


def _price(value: object, code: str, *, nullable: bool = False) -> int | None:
    if nullable and value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 100_000_000:
        raise ValidationError(code)
    return value


def _timestamp(value: object, code: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40 or not re.search(r"(?:Z|[+-]\d\d:\d\d)$", value):
        raise ValidationError(code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValidationError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(code)
    return parsed


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def parse_and_validate(raw: bytes, *, now: datetime) -> dict[str, object]:
    value, input_sha = strict_json(raw)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValidationError("CLOCK_NOT_TIMEZONE_AWARE", input_sha256=input_sha)
    top = _exact(value, {
        "schema_version", "submission_id", "title", "identity", "observed_at", "quantity",
        "before_coupon_price_twd", "user_reported_coupon", "shipping", "source",
    }, "TOP_LEVEL_FIELDS_MISMATCH")
    if top["schema_version"] != SCHEMA_VERSION:
        raise ValidationError("SCHEMA_VERSION_MISMATCH", input_sha256=input_sha)
    submission_id = top["submission_id"]
    if not isinstance(submission_id, str) or not SUBMISSION.fullmatch(submission_id):
        raise ValidationError("SUBMISSION_ID_INVALID", input_sha256=input_sha)
    title = _text(top["title"], "TITLE_INVALID", maximum=300)
    identity = _exact(top["identity"], {"platform", "product_id", "sku_id", "seller_id", "condition", "package_signature", "currency"}, "IDENTITY_FIELDS_MISMATCH")
    normalized_identity = {
        "platform": _identifier(identity["platform"], "PLATFORM_INVALID"),
        "product_id": _identifier(identity["product_id"], "PRODUCT_ID_INVALID"),
        "sku_id": _identifier(identity["sku_id"], "SKU_ID_INVALID"),
        "seller_id": _identifier(identity["seller_id"], "SELLER_ID_INVALID"),
        "condition": _identifier(identity["condition"], "CONDITION_INVALID"),
        "package_signature": _identifier(identity["package_signature"], "PACKAGE_SIGNATURE_INVALID"),
        "currency": _identifier(identity["currency"], "CURRENCY_INVALID"),
    }
    if normalized_identity["platform"] != "COUPANG_TW" or normalized_identity["currency"] != "TWD":
        raise ValidationError("PLATFORM_OR_CURRENCY_NOT_ALLOWED", input_sha256=input_sha)
    observed_local = _timestamp(top["observed_at"], "OBSERVED_AT_INVALID")
    observed_utc = observed_local.astimezone(timezone.utc)
    if observed_utc > now.astimezone(timezone.utc) + timedelta(seconds=1):
        raise ValidationError("OBSERVED_AT_FUTURE", input_sha256=input_sha)
    quantity = top["quantity"]
    if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 10_000:
        raise ValidationError("QUANTITY_INVALID", input_sha256=input_sha)
    before = _price(top["before_coupon_price_twd"], "BEFORE_COUPON_PRICE_INVALID")

    coupon = _exact(top["user_reported_coupon"], {"status", "price_twd", "eligibility", "evidence_level", "evidence_note", "valid_from", "valid_until"}, "COUPON_FIELDS_MISMATCH")
    status = coupon["status"]
    if status not in {"NONE", "USER_REPORTED"}:
        raise ValidationError("COUPON_STATUS_NOT_ALLOWED", input_sha256=input_sha)
    reported = _price(coupon["price_twd"], "USER_REPORTED_COUPON_PRICE_INVALID", nullable=True)
    eligibility = coupon["eligibility"]
    evidence_level = coupon["evidence_level"]
    evidence_note = _text(coupon["evidence_note"], "COUPON_EVIDENCE_NOTE_INVALID", maximum=500, nullable=True)
    valid_from = None if coupon["valid_from"] is None else _timestamp(coupon["valid_from"], "COUPON_VALID_FROM_INVALID")
    valid_until = None if coupon["valid_until"] is None else _timestamp(coupon["valid_until"], "COUPON_VALID_UNTIL_INVALID")
    if status == "NONE":
        if reported is not None or eligibility != "UNKNOWN" or evidence_level != "NONE" or evidence_note is not None or valid_from is not None or valid_until is not None:
            raise ValidationError("NONE_COUPON_MUST_BE_EMPTY", input_sha256=input_sha)
    else:
        if reported is None or reported > before:
            raise ValidationError("USER_REPORTED_COUPON_PRICE_INVALID", input_sha256=input_sha)
        if eligibility not in {"UNKNOWN", "USER_ASSERTED_ELIGIBLE"}:
            raise ValidationError("COUPON_ELIGIBILITY_INVALID", input_sha256=input_sha)
        if evidence_level not in {"NONE", "USER_DESCRIPTION", "USER_LOCAL_REFERENCE"}:
            raise ValidationError("COUPON_EVIDENCE_LEVEL_INVALID", input_sha256=input_sha)
        if evidence_level == "NONE" and evidence_note is not None:
            raise ValidationError("COUPON_EVIDENCE_NOTE_UNEXPECTED", input_sha256=input_sha)
        if evidence_level != "NONE" and evidence_note is None:
            raise ValidationError("COUPON_EVIDENCE_NOTE_REQUIRED", input_sha256=input_sha)
        if (valid_from is None) != (valid_until is None):
            raise ValidationError("COUPON_VALIDITY_PAIR_REQUIRED", input_sha256=input_sha)
        if valid_from is not None and (valid_from > valid_until or not valid_from <= observed_local <= valid_until):
            raise ValidationError("COUPON_NOT_VALID_AT_OBSERVATION", input_sha256=input_sha)

    shipping = _exact(top["shipping"], {"status", "shipping_fee_twd", "mandatory_fee_twd"}, "SHIPPING_FIELDS_MISMATCH")
    shipping_status = shipping["status"]
    shipping_fee = _price(shipping["shipping_fee_twd"], "SHIPPING_FEE_INVALID", nullable=True)
    mandatory_fee = _price(shipping["mandatory_fee_twd"], "MANDATORY_FEE_INVALID", nullable=True)
    if shipping_status == "UNKNOWN":
        if shipping_fee is not None or mandatory_fee is not None:
            raise ValidationError("UNKNOWN_SHIPPING_FEES_MUST_BE_NULL", input_sha256=input_sha)
    elif shipping_status == "KNOWN":
        if shipping_fee is None or mandatory_fee is None:
            raise ValidationError("KNOWN_SHIPPING_FEES_REQUIRED", input_sha256=input_sha)
    else:
        raise ValidationError("SHIPPING_STATUS_INVALID", input_sha256=input_sha)

    source = _exact(top["source"], {"source_class", "visibility", "note"}, "SOURCE_FIELDS_MISMATCH")
    if source["source_class"] != "USER_ENTERED" or source["visibility"] != "PRIVATE_LOCAL":
        raise ValidationError("SOURCE_CLASS_NOT_ALLOWED", input_sha256=input_sha)
    source_note = _text(source["note"], "SOURCE_NOTE_INVALID", maximum=500)

    series_key = hashlib.sha256(_canonical(normalized_identity)).hexdigest()
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "submission_id": submission_id,
        "title": title,
        "series_key": series_key,
        "identity": normalized_identity,
        "observed_at": _utc_text(observed_utc),
        "taipei_date": observed_utc.astimezone(TAIPEI).date().isoformat(),
        "quantity": quantity,
        "before_coupon_price_twd": before,
        "confirmed_after_coupon_price_twd": None,
        "user_reported_coupon": {
            "status": status,
            "price_twd": reported,
            "eligibility": eligibility,
            "evidence_level": evidence_level,
            "evidence_note": evidence_note,
            "valid_from": None if valid_from is None else _utc_text(valid_from),
            "valid_until": None if valid_until is None else _utc_text(valid_until),
        },
        "shipping": {"status": shipping_status, "shipping_fee_twd": shipping_fee, "mandatory_fee_twd": mandatory_fee},
        "required_total_twd": None if shipping_status == "UNKNOWN" else before * quantity + shipping_fee + mandatory_fee,
        "user_reported_required_total_twd": None if reported is None or shipping_status == "UNKNOWN" else reported * quantity + shipping_fee + mandatory_fee,
        "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": source_note, "platform_verified": False},
        "input_sha256": input_sha,
    }
    fingerprint_value = {key: item for key, item in normalized.items() if key not in {"submission_id", "input_sha256"}}
    normalized["observation_fingerprint"] = hashlib.sha256(_canonical(fingerprint_value)).hexdigest()
    return normalized
