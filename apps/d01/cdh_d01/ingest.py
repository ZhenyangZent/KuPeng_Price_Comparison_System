from __future__ import annotations

import csv
import codecs
import hashlib
import io
import json
import sqlite3
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .database import automatic_operation_allowed, canonical_raw_json, hash_bytes
from .model import ValidatedRecord, ValidationError, utc_now_text
from .validation import MAX_JSON_BYTES, canonical_json_bytes, decode_json_bytes, validate_record

MAX_CSV_BYTES = 50 * 1024 * 1024
MAX_CSV_ROWS = 10_000


@dataclass(frozen=True)
class IngestResult:
    status: str
    submission_id: str | None
    raw_sha256: str | None
    reason_code: str | None = None
    reason_detail: str | None = None


def _attempt(
    conn: sqlite3.Connection,
    *,
    source_path: str,
    status: str,
    raw_sha256: str | None,
    submission_id: str | None,
    reason_code: str | None = None,
    reason_detail: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO ingest_attempts
        (attempted_at_utc, source_path, raw_sha256, submission_id, status, reason_code, reason_detail)
        VALUES(?,?,?,?,?,?,?)""",
        (utc_now_text(), source_path, raw_sha256, submission_id, status, reason_code, reason_detail),
    )


def _quarantine(
    conn: sqlite3.Connection,
    *,
    source_path: str,
    raw_sha256: str | None,
    submission_id: str | None,
    reason_code: str,
    reason_detail: str,
    conflicting_raw_sha256: str | None = None,
    manage_transaction: bool = True,
) -> IngestResult:
    with conn if manage_transaction else nullcontext():
        conn.execute(
            """INSERT INTO quarantine
            (quarantined_at_utc, source_path, raw_sha256, submission_id, reason_code, reason_detail, conflicting_raw_sha256)
            VALUES(?,?,?,?,?,?,?)""",
            (utc_now_text(), source_path, raw_sha256, submission_id, reason_code, reason_detail, conflicting_raw_sha256),
        )
        _attempt(
            conn,
            source_path=source_path,
            status="QUARANTINED",
            raw_sha256=raw_sha256,
            submission_id=submission_id,
            reason_code=reason_code,
            reason_detail=reason_detail,
        )
    return IngestResult("QUARANTINED", submission_id, raw_sha256, reason_code, reason_detail)


def ingest_validated(
    conn: sqlite3.Connection,
    record: ValidatedRecord,
    *,
    raw_bytes: bytes,
    source_path: str,
    manage_transaction: bool = True,
) -> IngestResult:
    raw_sha = hash_bytes(raw_bytes)
    if record.source_kind == "APPROVED_FEED" and not automatic_operation_allowed(
        conn, record.source_id or "", "AUTOMATED_INGEST"
    ):
        return _quarantine(
            conn,
            source_path=source_path,
            raw_sha256=raw_sha,
            submission_id=record.submission_id,
            reason_code="SOURCE_OPERATION_NOT_APPROVED",
            reason_detail="source permission gate is not APPROVED for AUTOMATED_INGEST",
            manage_transaction=manage_transaction,
        )
    existing = conn.execute(
        "SELECT raw_sha256 FROM raw_submissions WHERE submission_id=? ORDER BY raw_submission_id LIMIT 1",
        (record.submission_id,),
    ).fetchone()
    if existing:
        if existing["raw_sha256"] == raw_sha:
            with conn if manage_transaction else nullcontext():
                _attempt(
                    conn,
                    source_path=source_path,
                    status="DUPLICATE_NOOP",
                    raw_sha256=raw_sha,
                    submission_id=record.submission_id,
                    reason_code="IDENTICAL_REPLAY",
                    reason_detail="same submission_id and raw SHA-256 already imported",
                )
            return IngestResult("DUPLICATE_NOOP", record.submission_id, raw_sha, "IDENTICAL_REPLAY")
        return _quarantine(
            conn,
            source_path=source_path,
            raw_sha256=raw_sha,
            submission_id=record.submission_id,
            reason_code="SUBMISSION_ID_CONFLICT",
            reason_detail="submission_id already exists with different content",
            conflicting_raw_sha256=existing["raw_sha256"],
            manage_transaction=manage_transaction,
        )
    imported_at = utc_now_text()
    try:
        with conn if manage_transaction else nullcontext():
            cursor = conn.execute(
                """INSERT INTO raw_submissions
                (submission_id, raw_sha256, source_path, source_id, source_kind, received_at_utc, schema_version, raw_json)
                VALUES(?,?,?,?,?,?,'CDH-EXCHANGE-1',?)""",
                (
                    record.submission_id,
                    raw_sha,
                    source_path,
                    record.source_id,
                    record.source_kind,
                    imported_at,
                    canonical_raw_json(record),
                ),
            )
            raw_id = cursor.lastrowid
            if record.record_type == "USER_PRICE_OBSERVATION":
                conn.execute(
                    """INSERT INTO observations
                    (raw_submission_id, submission_id, observed_at_utc, imported_at_utc, source_id, source_kind,
                    permission_scope, source_url, product_title, product_id, variant_id, seller_id,
                    displayed_price_twd, price_basis, minimum_purchase_quantity, shipping_status,
                    shipping_fee_twd, stock_status, coupon_status, account_eligibility_status,
                    mandatory_fee_status, qualification_state, is_synthetic, notes)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'UNVERIFIED',?,?)""",
                    (
                        raw_id,
                        record.submission_id,
                        record.observed_at_utc,
                        imported_at,
                        record.source_id,
                        record.source_kind,
                        record.permission_scope,
                        record.source_url,
                        record.product_title,
                        record.product_id,
                        record.variant_id,
                        record.seller_id,
                        record.displayed_price_twd,
                        record.price_basis,
                        record.minimum_purchase_quantity,
                        record.shipping_status,
                        record.shipping_fee_twd,
                        record.stock_status,
                        record.coupon_status,
                        record.account_eligibility_status,
                        record.mandatory_fee_status,
                        int(record.is_synthetic),
                        record.notes,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO leads
                    (raw_submission_id, submission_id, observed_at_utc, published_at_utc, imported_at_utc,
                    source_id, source_kind, permission_scope, source_url, product_title, promo_claim,
                    qualification_state, is_synthetic)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,'UNVERIFIED',?)""",
                    (
                        raw_id,
                        record.submission_id,
                        record.observed_at_utc,
                        record.published_at_utc,
                        imported_at,
                        record.source_id,
                        record.source_kind,
                        record.permission_scope,
                        record.source_url,
                        record.product_title,
                        record.promo_claim,
                        int(record.is_synthetic),
                    ),
                )
            _attempt(
                conn,
                source_path=source_path,
                status="IMPORTED",
                raw_sha256=raw_sha,
                submission_id=record.submission_id,
            )
    except sqlite3.Error:
        raise
    return IngestResult("IMPORTED", record.submission_id, raw_sha)


def ingest_json_bytes(
    conn: sqlite3.Connection,
    data: bytes,
    *,
    source_path: str,
    manage_transaction: bool = True,
) -> IngestResult:
    raw_sha = hashlib.sha256(data).hexdigest()
    try:
        payload = decode_json_bytes(data)
        record = validate_record(payload)
    except ValidationError as exc:
        submission_id = None
        try:
            candidate = json.loads(data.decode("utf-8-sig"))
            if isinstance(candidate, dict) and isinstance(candidate.get("submission_id"), str):
                submission_id = candidate["submission_id"][:128]
        except Exception:
            pass
        return _quarantine(
            conn,
            source_path=source_path,
            raw_sha256=raw_sha,
            submission_id=submission_id,
            reason_code=exc.code,
            reason_detail=exc.detail,
            manage_transaction=manage_transaction,
        )
    return ingest_validated(
        conn,
        record,
        raw_bytes=data,
        source_path=source_path,
        manage_transaction=manage_transaction,
    )


def ingest_json_file(
    conn: sqlite3.Connection,
    path: Path,
    *,
    manage_transaction: bool = True,
) -> IngestResult:
    try:
        size = path.stat().st_size
    except OSError as exc:
        return _quarantine(
            conn,
            source_path=str(path),
            raw_sha256=None,
            submission_id=None,
            reason_code="FILE_READ_ERROR",
            reason_detail=str(exc),
            manage_transaction=manage_transaction,
        )
    if size > MAX_JSON_BYTES:
        return _quarantine(
            conn,
            source_path=str(path),
            raw_sha256=None,
            submission_id=None,
            reason_code="FILE_TOO_LARGE",
            reason_detail=f"JSON exceeds {MAX_JSON_BYTES} bytes",
            manage_transaction=manage_transaction,
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        return _quarantine(
            conn,
            source_path=str(path),
            raw_sha256=None,
            submission_id=None,
            reason_code="FILE_READ_ERROR",
            reason_detail=str(exc),
            manage_transaction=manage_transaction,
        )
    return ingest_json_bytes(
        conn,
        data,
        source_path=str(path),
        manage_transaction=manage_transaction,
    )


def _csv_integer(value: str, field: str, *, nullable: bool = True) -> int | None:
    value = value.strip()
    if not value and nullable:
        return None
    if not value.isascii() or not value.isdigit():
        raise ValidationError("INVALID_INTEGER", f"CSV {field} must contain decimal digits")
    result = int(value)
    if result > 100_000_000:
        raise ValidationError("INVALID_INTEGER_RANGE", f"CSV {field} is too large")
    return result


def csv_row_to_payload(row: dict[str, str]) -> dict[str, object]:
    is_synthetic_raw = row.get("is_synthetic", "false").strip().lower()
    if is_synthetic_raw not in {"true", "false"}:
        raise ValidationError("INVALID_BOOLEAN", "CSV is_synthetic must be true or false")
    return {
        "schema_version": "CDH-EXCHANGE-1",
        "submission_id": row.get("submission_id", "").strip(),
        "record_type": row.get("record_type", "USER_PRICE_OBSERVATION").strip() or "USER_PRICE_OBSERVATION",
        "created_at_utc": row.get("created_at_utc", "").strip(),
        "observed_at_utc": row.get("observed_at_utc", "").strip(),
        "published_at_utc": row.get("published_at_utc", "").strip() or None,
        "promo_claim": row.get("promo_claim", ""),
        "source": {
            "source_kind": "SYNTHETIC_TEST" if is_synthetic_raw == "true" else "USER_FILE",
            "permission_scope": "SYNTHETIC_ONLY" if is_synthetic_raw == "true" else "USER_PROVIDED_ONLY",
            "url": row.get("source_url", "").strip() or None,
            "note": row.get("source_note", ""),
        },
        "offer": {
            "platform": row.get("platform", "TW_COUPANG").strip() or "TW_COUPANG",
            "product_title": row.get("product_title", ""),
            "product_id": row.get("product_id", "").strip() or None,
            "variant_id": row.get("variant_id", "").strip() or None,
            "seller_id": row.get("seller_id", "").strip() or None,
            "displayed_price_twd": _csv_integer(row.get("displayed_price_twd", ""), "displayed_price_twd"),
            "price_basis": row.get("price_basis", "DISPLAYED_UNKNOWN").strip() or "DISPLAYED_UNKNOWN",
            "minimum_purchase_quantity": _csv_integer(row.get("minimum_purchase_quantity", ""), "minimum_purchase_quantity"),
            "shipping_status": row.get("shipping_status", "UNKNOWN").strip() or "UNKNOWN",
            "shipping_fee_twd": _csv_integer(row.get("shipping_fee_twd", ""), "shipping_fee_twd"),
            "stock_status": row.get("stock_status", "UNKNOWN").strip() or "UNKNOWN",
            "coupon_status": row.get("coupon_status", "UNKNOWN").strip() or "UNKNOWN",
            "account_eligibility_status": row.get("account_eligibility_status", "UNKNOWN").strip() or "UNKNOWN",
            "mandatory_fee_status": row.get("mandatory_fee_status", "UNKNOWN").strip() or "UNKNOWN",
            "notes": row.get("notes", ""),
        },
        "is_synthetic": is_synthetic_raw == "true",
    }


def ingest_csv_file(conn: sqlite3.Connection, path: Path) -> Iterator[IngestResult]:
    if path.stat().st_size > MAX_CSV_BYTES:
        yield _quarantine(
            conn,
            source_path=str(path),
            raw_sha256=None,
            submission_id=None,
            reason_code="FILE_TOO_LARGE",
            reason_detail=f"CSV exceeds {MAX_CSV_BYTES} bytes",
        )
        return
    try:
        decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
        with path.open("rb") as binary:
            for chunk in iter(lambda: binary.read(1024 * 1024), b""):
                decoder.decode(chunk)
            decoder.decode(b"", final=True)
    except (OSError, UnicodeDecodeError) as exc:
        yield _quarantine(
            conn,
            source_path=str(path),
            raw_sha256=None,
            submission_id=None,
            reason_code="INVALID_ENCODING",
            reason_detail=f"CSV must be UTF-8: {exc}",
        )
        return
    try:
        stream = path.open("r", encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as exc:
        yield _quarantine(
            conn,
            source_path=str(path),
            raw_sha256=None,
            submission_id=None,
            reason_code="FILE_READ_ERROR",
            reason_detail=str(exc),
        )
        return
    with stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "submission_id" not in reader.fieldnames:
            yield _quarantine(
                conn,
                source_path=str(path),
                raw_sha256=None,
                submission_id=None,
                reason_code="CSV_HEADER_INVALID",
                reason_detail="CSV requires a submission_id header",
            )
            return
        for index, row in enumerate(reader, 1):
            if index > MAX_CSV_ROWS:
                yield _quarantine(
                    conn,
                    source_path=str(path),
                    raw_sha256=None,
                    submission_id=None,
                    reason_code="CSV_ROW_LIMIT_EXCEEDED",
                    reason_detail=f"CSV exceeds {MAX_CSV_ROWS} rows",
                )
                return
            try:
                payload = csv_row_to_payload(row)
                raw_bytes = canonical_json_bytes(payload)
                record = validate_record(payload)
                yield ingest_validated(conn, record, raw_bytes=raw_bytes, source_path=f"{path}#row={index}")
            except ValidationError as exc:
                raw_bytes = json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
                yield _quarantine(
                    conn,
                    source_path=f"{path}#row={index}",
                    raw_sha256=hash_bytes(raw_bytes),
                    submission_id=row.get("submission_id"),
                    reason_code=exc.code,
                    reason_detail=exc.detail,
                )


def scan_inbox(conn: sqlite3.Connection, inbox: Path) -> list[IngestResult]:
    results: list[IngestResult] = []
    if not inbox.exists():
        return results
    for path in sorted(inbox.iterdir(), key=lambda item: item.name):
        if path.is_symlink():
            results.append(
                _quarantine(
                    conn,
                    source_path=str(path),
                    raw_sha256=None,
                    submission_id=None,
                    reason_code="SYMLINK_NOT_ALLOWED",
                    reason_detail="inbox symlinks are not read",
                )
            )
            continue
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        results.append(ingest_json_file(conn, path))
    return results

