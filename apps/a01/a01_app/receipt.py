from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .constants import (
    EXCHANGE_VERSION,
    MAX_RECEIPT_BYTES,
    MAX_RECEIPT_ENTRIES,
    MAX_SNAPSHOT_BYTES,
    MAX_SUBMISSION_BYTES,
    RECEIPT_STALE_HOURS,
    RECEIPT_VERSION,
    SOURCE_AUTHORITY_STATUS,
)
from .schema import ValidationError, parse_utc


HEX64 = re.compile(r"^[0-9a-f]{64}$")
ENTRY_FIELDS = {"filename", "file_sha256", "status", "reason_code"}
ROOT_FIELDS = {"receipt_version", "exchange_version", "generated_at_utc", "source_status", "snapshot_sha256", "entries"}
ALLOWED_STATUSES = {"IMPORTED", "DUPLICATE_NOOP", "QUARANTINED", "RETRY_NEEDED"}
PROCESSED_STATUSES = {"IMPORTED", "DUPLICATE_NOOP"}
FILENAME = re.compile(r"^submission_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.json$")


class ReceiptError(ValueError):
    pass


@dataclass(frozen=True)
class ReceiptDocument:
    data: dict[str, Any]
    generated_at: datetime
    stale: bool


@dataclass(frozen=True)
class SyncStatus:
    state: str
    detail: str
    raw_inbox_count: int
    imported_count: int | None = None
    pending_count: int | None = None
    quarantined_count: int | None = None
    retry_count: int | None = None
    generated_at: datetime | None = None
    receipt_stale: bool = False

    @property
    def counts_known(self) -> bool:
        return self.imported_count is not None and self.pending_count is not None and self.quarantined_count is not None


def _closed_mapping(value: object, fields: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReceiptError(f"{where} 必須是 JSON 物件")
    if set(value) != fields:
        raise ReceiptError(f"{where} 欄位不符；缺少={sorted(fields - set(value))}；多出={sorted(set(value) - fields)}")
    return value


def _hash_text(value: object, field: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ReceiptError(f"{field} 必須是 64 位 lowercase SHA-256")
    return value


def _filename(value: object) -> str:
    if not isinstance(value, str) or len(value) > 80 or "/" in value or "\\" in value:
        raise ReceiptError("entry.filename 必須是頂層 canonical submission 檔名")
    match = FILENAME.fullmatch(value)
    if match is None:
        raise ReceiptError("entry.filename 不符合 submission_<canonical-uuid>.json")
    try:
        parsed = uuid.UUID(match.group(1))
    except ValueError as exc:
        raise ReceiptError("entry.filename UUID 無效") from exc
    if str(parsed) != match.group(1):
        raise ReceiptError("entry.filename UUID 必須 canonical lowercase")
    return value


def validate_receipt(value: object, *, now: datetime | None = None) -> ReceiptDocument:
    root = _closed_mapping(value, ROOT_FIELDS, "receipt")
    if root["receipt_version"] != RECEIPT_VERSION:
        raise ReceiptError("receipt_version 不支援")
    if root["exchange_version"] != EXCHANGE_VERSION:
        raise ReceiptError("exchange_version 不符")
    if root["source_status"] != SOURCE_AUTHORITY_STATUS:
        raise ReceiptError("source_status 必須維持 SOURCE_BLOCKED")
    snapshot_hash = _hash_text(root["snapshot_sha256"], "snapshot_sha256")
    if snapshot_hash != root["snapshot_sha256"]:
        raise ReceiptError("snapshot_sha256 無效")
    check_now = now or datetime.now(timezone.utc)
    try:
        generated = parse_utc(root["generated_at_utc"], "generated_at_utc", now=check_now)
    except ValidationError as exc:
        raise ReceiptError(exc.detail) from exc
    entries = root["entries"]
    if not isinstance(entries, list):
        raise ReceiptError("entries 必須是陣列")
    if len(entries) > MAX_RECEIPT_ENTRIES:
        raise ReceiptError(f"entries 超過 {MAX_RECEIPT_ENTRIES} 上限")
    seen: set[str] = set()
    for index, raw_entry in enumerate(entries):
        entry = _closed_mapping(raw_entry, ENTRY_FIELDS, f"entries[{index}]")
        filename = _filename(entry["filename"])
        folded = filename.casefold()
        if folded in seen:
            raise ReceiptError("entries 有重複或大小寫碰撞檔名")
        seen.add(folded)
        _hash_text(entry["file_sha256"], f"entries[{index}].file_sha256")
        status = entry["status"]
        if not isinstance(status, str) or status not in ALLOWED_STATUSES:
            raise ReceiptError(f"entries[{index}].status 不在允許清單")
        reason = entry["reason_code"]
        if reason is not None and (not isinstance(reason, str) or not reason.strip() or len(reason) > 128):
            raise ReceiptError(f"entries[{index}].reason_code 無效")
        if status == "IMPORTED" and reason is not None:
            raise ReceiptError(f"entries[{index}] IMPORTED 不可附 reason_code")
        if status == "DUPLICATE_NOOP" and reason not in {None, "IDENTICAL_REPLAY"}:
            raise ReceiptError(f"entries[{index}] DUPLICATE_NOOP reason_code 不在相容允許清單")
    stale = check_now - generated > timedelta(hours=RECEIPT_STALE_HOURS)
    return ReceiptDocument(dict(root), generated, stale)


def read_receipt(path: Path, *, now: datetime | None = None) -> ReceiptDocument:
    if path.is_symlink():
        raise ReceiptError("receipt 不可是 symbolic link")
    size = path.stat().st_size
    if size > MAX_RECEIPT_BYTES:
        raise ReceiptError("receipt 超過 5 MiB 上限")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), parse_constant=lambda token: (_ for _ in ()).throw(ReceiptError(f"不接受 {token}")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptError(f"receipt 無法讀取：{exc}") from exc
    return validate_receipt(value, now=now)


def _file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ReceiptError(f"inbox 檔案類型不安全：{path.name}")
    if path.stat().st_size > MAX_SUBMISSION_BYTES:
        raise ReceiptError(f"inbox 檔案超過 1 MiB：{path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scan_inbox_hashes(inbox: Path) -> tuple[dict[str, str], int]:
    if not inbox.exists():
        return {}, 0
    if inbox.is_symlink() or not inbox.is_dir():
        raise ReceiptError("inbox 路徑不是安全目錄")
    matches = sorted(path for path in inbox.iterdir() if path.name.startswith("submission_") and path.name.endswith(".json"))
    hashes: dict[str, str] = {}
    for path in matches:
        _filename(path.name)
        folded = path.name.casefold()
        if folded in (name.casefold() for name in hashes):
            raise ReceiptError("inbox 有重複或大小寫碰撞檔名")
        hashes[path.name] = _file_sha256(path)
    return hashes, len(matches)


def receipt_status(receipt_path: Path, snapshot_path: Path, inbox: Path, *, now: datetime | None = None) -> SyncStatus:
    try:
        inbox_hashes, raw_count = scan_inbox_hashes(inbox)
    except ReceiptError as exc:
        return SyncStatus("UNKNOWN", f"狀態未知：{exc}", 0)
    if not receipt_path.exists():
        return SyncStatus("NO_RECEIPT", "D01 尚無回執／資料仍在同步", raw_count)
    try:
        receipt = read_receipt(receipt_path, now=now)
    except (OSError, ReceiptError) as exc:
        return SyncStatus("UNKNOWN", f"狀態未知：D01 回執無效（{exc}）", raw_count)
    if not snapshot_path.exists() or snapshot_path.is_symlink() or not snapshot_path.is_file():
        return SyncStatus("SYNCING", "正在同步／尚未一致：回執找不到對應快照", raw_count, generated_at=receipt.generated_at, receipt_stale=receipt.stale)
    try:
        if snapshot_path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return SyncStatus("SYNCING", "正在同步／尚未一致：快照超過 50 MiB 上限", raw_count, generated_at=receipt.generated_at, receipt_stale=receipt.stale)
        snapshot_hash = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    except OSError as exc:
        return SyncStatus("SYNCING", f"正在同步／尚未一致：快照無法讀取（{exc}）", raw_count, generated_at=receipt.generated_at, receipt_stale=receipt.stale)
    if snapshot_hash != receipt.data["snapshot_sha256"]:
        return SyncStatus("SYNCING", "正在同步／尚未一致：回執與快照 SHA-256 不符", raw_count, generated_at=receipt.generated_at, receipt_stale=receipt.stale)
    # Hash binding is necessary but not sufficient: a crash could publish bytes
    # that match a receipt yet do not satisfy the frozen D01 snapshot contract.
    from .snapshot import read_snapshot

    snapshot_result = read_snapshot(snapshot_path, now=now)
    if snapshot_result.data is None:
        return SyncStatus("SYNCING", "正在同步／尚未一致：回執所指快照無效", raw_count, generated_at=receipt.generated_at, receipt_stale=receipt.stale)
    if snapshot_result.stale:
        return SyncStatus("STALE", "狀態未知：D01 快照已過期", raw_count, generated_at=receipt.generated_at, receipt_stale=receipt.stale)
    entries = {entry["filename"]: entry for entry in receipt.data["entries"]}
    if set(entries) - set(inbox_hashes):
        return SyncStatus("UNKNOWN", "狀態未知：回執引用的收件檔不存在", raw_count, generated_at=receipt.generated_at, receipt_stale=receipt.stale)
    imported = pending = quarantined = retry = 0
    for filename, file_hash in inbox_hashes.items():
        entry = entries.get(filename)
        if entry is None or entry["file_sha256"] != file_hash:
            pending += 1
            continue
        if entry["status"] in PROCESSED_STATUSES:
            imported += 1
        elif entry["status"] == "QUARANTINED":
            quarantined += 1
        else:
            pending += 1
            retry += 1
    if receipt.stale:
        return SyncStatus("STALE", "狀態未知：D01 回執已過期；顯示上次可驗證計數", raw_count, imported, pending, quarantined, retry, receipt.generated_at, True)
    detail = "同步完成" if pending == 0 and quarantined == 0 else "已讀取 D01 回執；仍有待處理或隔離錯誤"
    return SyncStatus("READY", detail, raw_count, imported, pending, quarantined, retry, receipt.generated_at, False)
