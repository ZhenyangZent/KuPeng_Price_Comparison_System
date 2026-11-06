from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath

from . import dependencies as _dependencies  # noqa: F401
from private_observation_b15.validation import ValidationError, parse_and_validate


REQUEST_SCHEMA = "CDH-B16-BATCH-PREVIEW-REQUEST-1"
FILE_SCHEMA = "CDH-B16-BATCH-FILE-1"
MAX_FILE_BYTES = 1024 * 1024
MAX_ENVELOPE_BYTES = 1_500_000
MAX_ROWS = 500
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")
CSV_HEADERS = (
    "submission_id", "title", "platform", "product_id", "sku_id", "seller_id", "condition",
    "package_signature", "currency", "observed_at", "quantity", "before_coupon_price_twd",
    "coupon_status", "coupon_price_twd", "coupon_eligibility", "coupon_evidence_level",
    "coupon_evidence_note", "coupon_valid_from", "coupon_valid_until", "shipping_status",
    "shipping_fee_twd", "mandatory_fee_twd", "source_class", "visibility", "source_note",
)


class BatchValidationError(ValueError):
    def __init__(self, code: str, *, input_sha256: str | None = None) -> None:
        self.code = code
        self.input_sha256 = input_sha256
        super().__init__(code)


class _DuplicateKey(ValueError):
    pass


class _InvalidConstant(ValueError):
    pass


@dataclass(frozen=True)
class ParsedBatch:
    filename: str
    media_type: str
    file_sha256: str
    rows: list[dict[str, object]]


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = value
    return result


def strict_json(raw: bytes, *, maximum: int, too_large_code: str) -> tuple[object, str]:
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) > maximum:
        raise BatchValidationError(too_large_code, input_sha256=digest)
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise BatchValidationError("JSON_NOT_UTF8", input_sha256=digest) from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(_InvalidConstant()),
        )
    except _DuplicateKey as exc:
        raise BatchValidationError("JSON_DUPLICATE_KEY", input_sha256=digest) from exc
    except (_InvalidConstant, json.JSONDecodeError, RecursionError) as exc:
        raise BatchValidationError("JSON_INVALID", input_sha256=digest) from exc
    return value, digest


def _integer(value: str, code: str, *, nullable: bool = False) -> int | None:
    if nullable and value == "":
        return None
    if not re.fullmatch(r"0|[1-9][0-9]{0,11}", value):
        raise BatchValidationError(code)
    return int(value)


def _nullable(value: str) -> str | None:
    return None if value == "" else value


def _csv_row(row: dict[str, str], row_number: int) -> dict[str, object]:
    if None in row or set(row) != set(CSV_HEADERS) or any(value is None for value in row.values()):
        raise BatchValidationError("CSV_ROW_SHAPE_INVALID")
    try:
        return {
            "schema_version": "CDH-B15-MANUAL-OBSERVATION-1",
            "submission_id": row["submission_id"],
            "title": row["title"],
            "identity": {
                "platform": row["platform"],
                "product_id": row["product_id"],
                "sku_id": row["sku_id"],
                "seller_id": row["seller_id"],
                "condition": row["condition"],
                "package_signature": row["package_signature"],
                "currency": row["currency"],
            },
            "observed_at": row["observed_at"],
            "quantity": _integer(row["quantity"], "QUANTITY_INVALID"),
            "before_coupon_price_twd": _integer(row["before_coupon_price_twd"], "BEFORE_COUPON_PRICE_INVALID"),
            "user_reported_coupon": {
                "status": row["coupon_status"],
                "price_twd": _integer(row["coupon_price_twd"], "USER_REPORTED_COUPON_PRICE_INVALID", nullable=True),
                "eligibility": row["coupon_eligibility"],
                "evidence_level": row["coupon_evidence_level"],
                "evidence_note": _nullable(row["coupon_evidence_note"]),
                "valid_from": _nullable(row["coupon_valid_from"]),
                "valid_until": _nullable(row["coupon_valid_until"]),
            },
            "shipping": {
                "status": row["shipping_status"],
                "shipping_fee_twd": _integer(row["shipping_fee_twd"], "SHIPPING_FEE_INVALID", nullable=True),
                "mandatory_fee_twd": _integer(row["mandatory_fee_twd"], "MANDATORY_FEE_INVALID", nullable=True),
            },
            "source": {
                "source_class": row["source_class"],
                "visibility": row["visibility"],
                "note": row["source_note"],
            },
        }
    except BatchValidationError as exc:
        raise BatchValidationError(exc.code) from exc


def _parse_csv(content: bytes) -> list[tuple[int, dict[str, object]]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError as exc:
        raise BatchValidationError("CSV_NOT_UTF8") from exc
    if "\x00" in text:
        raise BatchValidationError("CSV_INVALID")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if reader.fieldnames is None or tuple(reader.fieldnames) != CSV_HEADERS or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise BatchValidationError("CSV_HEADERS_MISMATCH")
        result = []
        for index, row in enumerate(reader, start=2):
            try:
                result.append((index, _csv_row(row, index)))
            except BatchValidationError as exc:
                result.append((index, {"__batch_row_error__": exc.code}))
    except (csv.Error, UnicodeError) as exc:
        raise BatchValidationError("CSV_INVALID") from exc
    return result


def _parse_json_file(content: bytes) -> list[tuple[int, dict[str, object]]]:
    value, _digest = strict_json(content, maximum=MAX_FILE_BYTES, too_large_code="FILE_TOO_LARGE")
    if not isinstance(value, dict) or set(value) != {"schema_version", "observations"} or value.get("schema_version") != FILE_SCHEMA:
        raise BatchValidationError("BATCH_FILE_FIELDS_MISMATCH")
    observations = value.get("observations")
    if not isinstance(observations, list):
        raise BatchValidationError("BATCH_OBSERVATIONS_INVALID")
    return [(index, item) for index, item in enumerate(observations, start=1)]


def parse_preview_request(raw: bytes, *, now: datetime) -> ParsedBatch:
    value, request_sha = strict_json(raw, maximum=MAX_ENVELOPE_BYTES, too_large_code="REQUEST_BODY_TOO_LARGE")
    fields = {"schema_version", "filename", "media_type", "content_base64"}
    if not isinstance(value, dict) or set(value) != fields or value.get("schema_version") != REQUEST_SCHEMA:
        raise BatchValidationError("PREVIEW_REQUEST_FIELDS_MISMATCH", input_sha256=request_sha)
    filename = value.get("filename")
    media_type = value.get("media_type")
    encoded = value.get("content_base64")
    if not isinstance(filename, str) or not SAFE_FILENAME.fullmatch(filename) or PurePath(filename).name != filename:
        raise BatchValidationError("FILENAME_INVALID", input_sha256=request_sha)
    if media_type not in {"text/csv", "application/json"}:
        raise BatchValidationError("MEDIA_TYPE_NOT_ALLOWED", input_sha256=request_sha)
    if not isinstance(encoded, str):
        raise BatchValidationError("CONTENT_BASE64_INVALID", input_sha256=request_sha)
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BatchValidationError("CONTENT_BASE64_INVALID", input_sha256=request_sha) from exc
    if not content:
        raise BatchValidationError("FILE_EMPTY", input_sha256=request_sha)
    if len(content) > MAX_FILE_BYTES:
        raise BatchValidationError("FILE_TOO_LARGE", input_sha256=hashlib.sha256(content).hexdigest())
    suffix = PurePath(filename).suffix.casefold()
    if (media_type, suffix) not in {("text/csv", ".csv"), ("application/json", ".json")}:
        raise BatchValidationError("FILE_EXTENSION_MEDIA_TYPE_MISMATCH", input_sha256=request_sha)
    raw_rows = _parse_csv(content) if media_type == "text/csv" else _parse_json_file(content)
    if not 1 <= len(raw_rows) <= MAX_ROWS:
        raise BatchValidationError("ROW_COUNT_INVALID", input_sha256=hashlib.sha256(content).hexdigest())
    rows: list[dict[str, object]] = []
    for row_number, item in raw_rows:
        if isinstance(item, dict) and set(item) == {"__batch_row_error__"}:
            rows.append({"row_number": row_number, "error": item["__batch_row_error__"]})
            continue
        if not isinstance(item, dict):
            rows.append({"row_number": row_number, "error": "ROW_NOT_OBJECT"})
            continue
        encoded_item = json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        try:
            normalized = parse_and_validate(encoded_item, now=now)
        except ValidationError as exc:
            rows.append({"row_number": row_number, "error": exc.code, "input_sha256": exc.input_sha256})
        else:
            rows.append({"row_number": row_number, "normalized": normalized})
    return ParsedBatch(filename=filename, media_type=media_type, file_sha256=hashlib.sha256(content).hexdigest(), rows=rows)

