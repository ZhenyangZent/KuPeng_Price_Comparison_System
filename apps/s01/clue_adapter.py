"""Offline-only adapter for explicitly user-provided deal clues.

This module never opens a URL, imports C01, sends a notification, or upgrades a
claim into purchase qualification.  It only normalizes bounded local input into
an auditable clue envelope.
"""

from __future__ import annotations

import csv
import hashlib
import ipaddress
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SCHEMA_ID = "cdh-user-provided-clue-v1"
ADAPTER_VERSION = "1.0.0"
MAX_INPUT_BYTES = 1_048_576
MAX_RECORDS = 1_000
MAX_TEXT_LENGTH = 4_096

CSV_COLUMNS = {
    "clue_text",
    "source_url",
    "product_url",
    "claimed_at",
    "claim_price_minor",
    "claim_context",
}
CLAIM_CONTEXTS = {
    "UNSPECIFIED",
    "HISTORICAL",
    "CURRENT_CLAIM",
    "PROMOTION",
    "FIRST_PURCHASE_PROMOTION",
}
UNKNOWN_QUALIFICATION_FIELDS = (
    "sku_id",
    "seller",
    "current_price",
    "stock",
    "minimum_quantity",
    "wow_membership",
    "wow_product_eligibility",
    "shipping",
    "coupon",
    "required_fees",
    "tax_or_import_fees",
    "full_required_cost",
)

_URL_RE = re.compile(r"https://[^\s<>\]\[\)\(\"']+", re.IGNORECASE)
_PROMOTION_PATTERNS = (
    re.compile(r"首購", re.IGNORECASE),
    re.compile(r"新(?:用戶|會員|客)", re.IGNORECASE),
    re.compile(r"first[ -]?purchase", re.IGNORECASE),
    re.compile(r"(?:NT\$|\$)\s*1(?:\D|$)", re.IGNORECASE),
    re.compile(r"(?:^|\D)1\s*元(?:\D|$)", re.IGNORECASE),
)


class ClueInputError(ValueError):
    """The local input cannot be accepted without weakening a safety gate."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse_timestamp(value: str, field: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ClueInputError(f"{field} must not be empty")
    normalized = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ClueInputError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ClueInputError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _observation_time(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return _parse_timestamp(value, "observed_at")


def _validate_https_url(value: str, field: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ClueInputError(f"{field} must not be empty when provided")
    if len(candidate) > 2_048 or "\\" in candidate:
        raise ClueInputError(f"{field} is not a safe HTTPS URL")
    try:
        parts = urlsplit(candidate)
        port = parts.port
    except ValueError as exc:
        raise ClueInputError(f"{field} is not a valid URL") from exc
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise ClueInputError(f"{field} must use HTTPS")
    if parts.username or parts.password or port is not None:
        raise ClueInputError(f"{field} must not contain credentials or an explicit port")
    hostname = parts.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ClueInputError(f"{field} must not reference localhost")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ClueInputError(f"{field} must not reference a non-public IP address")
    return urlunsplit(("https", hostname, parts.path or "/", parts.query, ""))


def _canonical_product_url(value: str) -> str:
    safe_url = _validate_https_url(value, "product_url")
    parts = urlsplit(safe_url)
    if parts.hostname not in {"tw.coupang.com", "www.tw.coupang.com"}:
        raise ClueInputError("product_url must use the exact Coupang Taiwan host")
    if not (parts.path.startswith("/products/") or parts.path.startswith("/vp/products/")):
        raise ClueInputError("product_url must use a direct product path")
    query = sorted(
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=False)
        if key in {"itemId", "vendorItemId"} and val
    )
    host = "www.tw.coupang.com"
    return urlunsplit(("https", host, parts.path, urlencode(query), ""))


def _parse_price_minor(value: str) -> int | None:
    candidate = value.strip()
    if not candidate:
        return None
    if not re.fullmatch(r"0|[1-9][0-9]*", candidate):
        raise ClueInputError("claim_price_minor must be a non-negative base-10 integer")
    amount = int(candidate)
    if amount > 999_999_999_999:
        raise ClueInputError("claim_price_minor exceeds the bounded range")
    return amount


def _promotion_warnings(text: str, context: str) -> list[str]:
    warnings = ["USER_CLAIM_IS_NOT_PURCHASE_QUALIFICATION"]
    if context in {"HISTORICAL", "PROMOTION", "FIRST_PURCHASE_PROMOTION"}:
        warnings.append("HISTORICAL_OR_PROMOTIONAL_CLAIM_NOT_CURRENT_PRICE")
    if context == "FIRST_PURCHASE_PROMOTION" or any(p.search(text) for p in _PROMOTION_PATTERNS):
        warnings.append("FIRST_PURCHASE_OR_ONE_DOLLAR_ELIGIBILITY_UNPROVEN")
    return warnings


def _record_fingerprint(record: dict[str, Any]) -> str:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def _make_clue(
    *,
    source_type: str,
    input_label: str,
    record_index: int,
    clue_text: str,
    observed_at: str,
    source_url: str | None = None,
    product_url: str | None = None,
    claimed_at: str | None = None,
    claim_price_minor: int | None = None,
    claim_context: str = "UNSPECIFIED",
) -> dict[str, Any]:
    text = clue_text.strip()
    if not text or len(text) > MAX_TEXT_LENGTH:
        raise ClueInputError(f"clue_text must contain 1..{MAX_TEXT_LENGTH} characters")
    context = claim_context.strip().upper() or "UNSPECIFIED"
    if context not in CLAIM_CONTEXTS:
        raise ClueInputError(f"claim_context must be one of {sorted(CLAIM_CONTEXTS)}")
    safe_source_url = _validate_https_url(source_url, "source_url") if source_url else None
    safe_product_url = _canonical_product_url(product_url) if product_url else None
    normalized_claimed_at = _parse_timestamp(claimed_at, "claimed_at") if claimed_at else None

    identity = {
        "source_type": source_type,
        "input_label": input_label,
        "record_index": record_index,
        "clue_text": text,
        "source_url": safe_source_url,
        "product_url": safe_product_url,
        "claimed_at": normalized_claimed_at,
        "claim_price_minor": claim_price_minor,
        "claim_context": context,
    }
    qualification = {field: "UNKNOWN" for field in UNKNOWN_QUALIFICATION_FIELDS}
    return {
        "clue_id": f"uclue-{_record_fingerprint(identity)[:24]}",
        "clue_class": "USER_PROVIDED_CLUE",
        "source_type": source_type,
        "source_status": "LOCAL_USER_INPUT_ONLY",
        "automated_source_status": "SOURCE_BLOCKED",
        "upstream_permission_status": "NOT_PROVEN",
        "input_label": input_label,
        "record_index": record_index,
        "observed_at": observed_at,
        "claimed_at": normalized_claimed_at,
        "claim_time_status": "USER_ASSERTED" if normalized_claimed_at else "UNKNOWN",
        "claim_context": context,
        "clue_text": text,
        "source_url": safe_source_url,
        "product_url": safe_product_url,
        "claim_price_minor": claim_price_minor,
        "claim_price_status": "UNVERIFIED_USER_CLAIM" if claim_price_minor is not None else "UNKNOWN",
        "qualification": qualification,
        "qualification_status": "UNQUALIFIED_CLUE_ONLY",
        "notification_eligible": False,
        "c01_event_created": False,
        "links_fetched": 0,
        "warnings": _promotion_warnings(text, context),
    }


def _build_envelope(
    *, source_type: str, input_label: str, raw_bytes: bytes, observed_at: str, clues: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    clue_list = list(clues)
    return {
        "schema": SCHEMA_ID,
        "adapter_version": ADAPTER_VERSION,
        "generated_at": observed_at,
        "input": {
            "source_type": source_type,
            "label": input_label,
            "sha256": _sha256_bytes(raw_bytes),
            "bytes": len(raw_bytes),
            "record_count": len(clue_list),
        },
        "guardrails": {
            "network_access_count": 0,
            "url_fetch_count": 0,
            "c01_event_count": 0,
            "notification_count": 0,
            "automated_source_status": "SOURCE_BLOCKED",
        },
        "clues": clue_list,
    }


def import_csv_file(path: str | Path, *, observed_at: str | None = None) -> dict[str, Any]:
    input_path = Path(path)
    if input_path.suffix.lower() != ".csv":
        raise ClueInputError("CSV import requires a .csv file explicitly selected by the user")
    try:
        raw = input_path.read_bytes()
    except OSError as exc:
        raise ClueInputError(f"cannot read local CSV: {exc}") from exc
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise ClueInputError(f"CSV input must contain 1..{MAX_INPUT_BYTES} bytes")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ClueInputError("CSV input must be valid UTF-8") from exc
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise ClueInputError("CSV header is required")
    headers = [header.strip() for header in reader.fieldnames]
    if len(headers) != len(set(headers)):
        raise ClueInputError("CSV header contains duplicate columns")
    if "clue_text" not in headers:
        raise ClueInputError("CSV requires clue_text")
    unknown = sorted(set(headers) - CSV_COLUMNS)
    if unknown:
        raise ClueInputError(f"CSV contains unsupported columns: {unknown}")
    when = _observation_time(observed_at)
    clues: list[dict[str, Any]] = []
    for index, row in enumerate(reader, start=1):
        if index > MAX_RECORDS:
            raise ClueInputError(f"CSV exceeds {MAX_RECORDS} records")
        cleaned = {(key or "").strip(): (value or "").strip() for key, value in row.items()}
        clues.append(
            _make_clue(
                source_type="USER_FILE",
                input_label=input_path.name,
                record_index=index,
                clue_text=cleaned.get("clue_text", ""),
                observed_at=when,
                source_url=cleaned.get("source_url") or None,
                product_url=cleaned.get("product_url") or None,
                claimed_at=cleaned.get("claimed_at") or None,
                claim_price_minor=_parse_price_minor(cleaned.get("claim_price_minor", "")),
                claim_context=cleaned.get("claim_context", "UNSPECIFIED"),
            )
        )
    if not clues:
        raise ClueInputError("CSV must contain at least one clue")
    return _build_envelope(
        source_type="USER_FILE", input_label=input_path.name, raw_bytes=raw, observed_at=when, clues=clues
    )


def _import_text(
    text: str,
    *,
    raw: bytes,
    source_type: str,
    input_label: str,
    observed_at: str | None,
) -> dict[str, Any]:
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise ClueInputError(f"text input must contain 1..{MAX_INPUT_BYTES} UTF-8 bytes")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or len(lines) > MAX_RECORDS:
        raise ClueInputError(f"text input must contain 1..{MAX_RECORDS} non-empty lines")
    when = _observation_time(observed_at)
    clues: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        urls = _URL_RE.findall(line)
        source_url = None
        product_url = None
        for raw_url in urls:
            trimmed = raw_url.rstrip(".,;:!?，。；：！？")
            try:
                candidate = _canonical_product_url(trimmed)
            except ClueInputError:
                if source_url is None:
                    try:
                        source_url = _validate_https_url(trimmed, "source_url")
                    except ClueInputError:
                        pass
            else:
                product_url = candidate
                break
        clues.append(
            _make_clue(
                source_type=source_type,
                input_label=input_label,
                record_index=index,
                clue_text=line,
                observed_at=when,
                source_url=source_url,
                product_url=product_url,
            )
        )
    return _build_envelope(
        source_type=source_type, input_label=input_label, raw_bytes=raw, observed_at=when, clues=clues
    )


def import_pasted_text(text: str, *, observed_at: str | None = None) -> dict[str, Any]:
    raw = text.encode("utf-8")
    return _import_text(
        text,
        raw=raw,
        source_type="USER_ENTERED",
        input_label="pasted-text",
        observed_at=observed_at,
    )


def import_text_file(path: str | Path, *, observed_at: str | None = None) -> dict[str, Any]:
    input_path = Path(path)
    try:
        raw = input_path.read_bytes()
    except OSError as exc:
        raise ClueInputError(f"cannot read local text file: {exc}") from exc
    if len(raw) > MAX_INPUT_BYTES:
        raise ClueInputError(f"text file exceeds {MAX_INPUT_BYTES} bytes")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ClueInputError("text file must be valid UTF-8") from exc
    return _import_text(
        text,
        raw=raw,
        source_type="USER_FILE",
        input_label=input_path.name,
        observed_at=observed_at,
    )


def write_result(result: dict[str, Any], path: str | Path) -> None:
    output_path = Path(path)
    if output_path.exists():
        raise ClueInputError("output already exists; refusing to overwrite")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, output_path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
