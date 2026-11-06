from __future__ import annotations

import csv
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .exchange import DuplicateSubmissionError, build_submission, safe_write_submission
from .schema import ValidationError, parse_money_text, parse_utc, strict_money


REQUIRED_COLUMNS = {"product_title", "displayed_price_twd", "observed_at_utc"}
OPTIONAL_COLUMNS = {"url", "product_id", "variant_id", "seller_id", "sku", "specification", "notes"}
JSON_FIELDS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS
USER_FILE_NAMESPACE = uuid.UUID("4b5be21a-f5b2-4b90-92e4-173fbab4ec5f")
MAX_IMPORT_ROWS = 10_000


@dataclass(frozen=True)
class ImportRowResult:
    row: int
    status: str
    detail: str
    output: str | None = None


def _safe_cell(value: str) -> str:
    cleaned = value.strip()
    if cleaned[:1] in {"=", "+", "-", "@"}:
        raise ValueError("儲存格看似試算表公式，已拒絕")
    return cleaned


def _submission_id(row_number: int, values: dict[str, object]) -> str:
    canonical = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return str(uuid.uuid5(USER_FILE_NAMESPACE, f"{row_number}:{canonical}"))


def _build_user_file(values: dict[str, object], *, row_number: int, now: datetime) -> dict[str, object]:
    title = values["product_title"]
    if not isinstance(title, str):
        raise ValueError("product_title 必須是文字")
    title = _safe_cell(title)
    raw_price = values["displayed_price_twd"]
    price = parse_money_text(raw_price) if isinstance(raw_price, str) else strict_money(raw_price, "displayed_price_twd")
    raw_observed = values["observed_at_utc"]
    observed = parse_utc(raw_observed, "observed_at_utc", now=now)
    clean: dict[str, str | None] = {}
    for name in OPTIONAL_COLUMNS:
        raw = values.get(name)
        if raw is None:
            clean[name] = None
        elif not isinstance(raw, str):
            raise ValueError(f"{name} 必須是文字或 null")
        else:
            clean[name] = _safe_cell(raw) or None
    notes = "；".join(part for part in (clean["specification"], clean["notes"]) if part)
    identity = {
        "product_title": title,
        "displayed_price_twd": price,
        "observed_at_utc": str(raw_observed),
        **clean,
    }
    return build_submission(
        product_title=title,
        displayed_price_twd=int(price),
        observed_at=observed,
        url=clean["url"],
        product_id=clean["product_id"],
        variant_id=clean["variant_id"] or clean["sku"] or clean["specification"],
        seller_id=clean["seller_id"],
        notes=notes,
        created_at=now,
        source_kind="USER_FILE",
        submission_id=_submission_id(row_number, identity),
    )


def _store_row(record: dict[str, object], inbox: Path, row_number: int) -> ImportRowResult:
    try:
        output, _ = safe_write_submission(inbox, record)
        return ImportRowResult(row_number, "IMPORTED", "匯入成功；等待本地同步", output.name)
    except DuplicateSubmissionError:
        return ImportRowResult(row_number, "DUPLICATE_NOOP", "相同資料已在收件匣，未重複建立")


def import_csv(path: Path, inbox: Path, *, now: datetime | None = None) -> list[ImportRowResult]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("CSV 必須是使用者明確選取的普通檔案")
    if path.stat().st_size > 1_048_576:
        raise ValueError("CSV 超過 1 MiB 上限")
    results: list[ImportRowResult] = []
    check_now = now or datetime.now(timezone.utc)
    try:
        stream = path.open("r", encoding="utf-8-sig", newline="")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV 必須是 UTF-8") from exc
    try:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
            raise ValueError(f"CSV 必須至少包含 {sorted(REQUIRED_COLUMNS)}")
        unknown = set(reader.fieldnames) - REQUIRED_COLUMNS - OPTIONAL_COLUMNS
        if unknown:
            raise ValueError(f"CSV 含未支援欄位：{sorted(unknown)}")
        for row_number, row in enumerate(reader, start=2):
            if row_number > MAX_IMPORT_ROWS + 1:
                raise ValueError(f"CSV 超過 {MAX_IMPORT_ROWS} 列上限")
            try:
                values = {name: row.get(name) for name in REQUIRED_COLUMNS | OPTIONAL_COLUMNS}
                record = _build_user_file(values, row_number=row_number, now=check_now)
                results.append(_store_row(record, inbox, row_number))
            except (ValueError, ValidationError, OSError) as exc:
                results.append(ImportRowResult(row_number, "REJECTED", str(exc)))
    except UnicodeDecodeError as exc:
        raise ValueError("CSV 含無效 UTF-8，未隱藏編碼錯誤") from exc
    finally:
        stream.close()
    return results


def import_json(path: Path, inbox: Path, *, now: datetime | None = None) -> list[ImportRowResult]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("JSON 必須是使用者明確選取的普通檔案")
    if path.stat().st_size > 1_048_576:
        raise ValueError("JSON 超過 1 MiB 上限")
    try:
        value = json.loads(path.read_bytes().decode("utf-8"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"不接受 {token}")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"JSON 必須是有效 UTF-8：{exc}") from exc
    rows = value if isinstance(value, list) else [value]
    if len(rows) > MAX_IMPORT_ROWS:
        raise ValueError(f"JSON 超過 {MAX_IMPORT_ROWS} 筆上限")
    results: list[ImportRowResult] = []
    check_now = now or datetime.now(timezone.utc)
    for index, raw in enumerate(rows, start=1):
        try:
            if not isinstance(raw, dict):
                raise ValueError("每筆 JSON 必須是物件")
            missing = REQUIRED_COLUMNS - set(raw)
            extra = set(raw) - JSON_FIELDS
            if missing or extra:
                raise ValueError(f"JSON 欄位不符；缺少={sorted(missing)}；多出={sorted(extra)}")
            record = _build_user_file(dict(raw), row_number=index, now=check_now)
            results.append(_store_row(record, inbox, index))
        except (ValueError, ValidationError, OSError) as exc:
            results.append(ImportRowResult(index, "REJECTED", str(exc)))
    return results
