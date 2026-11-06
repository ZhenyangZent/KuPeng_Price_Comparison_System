from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .receipt import ReceiptError, read_receipt
from .schema import ValidationError, validate_submission
from .snapshot import SnapshotResult


@dataclass(frozen=True)
class HistoryRow:
    submission_id: str
    title: str
    price: str
    observed_at: str
    source_kind: str
    verification: str
    sync_state: str
    data_type: str


def _price(value: object) -> str:
    return f"NT$ {value:,}" if isinstance(value, int) and not isinstance(value, bool) else "未知"


def local_history_rows(inbox: Path, snapshot: SnapshotResult | None, receipt_path: Path) -> list[HistoryRow]:
    entries: dict[str, dict[str, object]] = {}
    try:
        receipt = read_receipt(receipt_path) if receipt_path.is_file() else None
    except (OSError, ReceiptError):
        receipt = None
    if receipt is not None:
        entries = {str(item["filename"]): item for item in receipt.data["entries"]}
    rows: dict[str, HistoryRow] = {}
    if inbox.is_dir() and not inbox.is_symlink():
        for path in sorted(inbox.glob("submission_*.json")):
            try:
                raw = path.read_bytes()
                if len(raw) > 1_048_576:
                    raise ValueError("submission too large")
                record = validate_submission(json.loads(raw.decode("utf-8")))
                offer = record["offer"]
                source = record["source"]
                entry = entries.get(path.name)
                digest = hashlib.sha256(raw).hexdigest()
                if entry is None or entry.get("file_sha256") != digest:
                    state = "等待本地同步"
                elif entry.get("status") == "IMPORTED":
                    state = "已匯入"
                elif entry.get("status") == "DUPLICATE_NOOP":
                    state = "重播無新增"
                elif entry.get("status") == "QUARANTINED":
                    state = "隔離拒收"
                else:
                    state = "待審查／等待重試"
                source_kind = str(source["source_kind"])
                synthetic = bool(record["is_synthetic"])
                verification = f"UNVERIFIED｜運費 {offer['shipping_status']}｜券 {offer['coupon_status']}"
                row = HistoryRow(
                    str(record["submission_id"]), str(offer["product_title"]), _price(offer["displayed_price_twd"]),
                    str(record["observed_at_utc"]), source_kind, verification, state,
                    "合成測試" if synthetic else (f"使用者新觀測（{source_kind}）" if state == "等待本地同步" else source_kind),
                )
                rows[row.submission_id] = row
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
                rows[path.name] = HistoryRow(path.name, "無法驗證的收件檔", "未知", "未知", "UNKNOWN", "UNVERIFIED", "格式錯誤", "不可匯入")
    if snapshot is not None and snapshot.data is not None:
        for item in snapshot.data.get("items", []):
            identity = str(item.get("submission_id", ""))
            if identity in rows:
                continue
            source_kind = str(item.get("source_kind", "UNKNOWN"))
            synthetic = bool(item.get("is_synthetic"))
            rows[identity] = HistoryRow(
                identity,
                str(item.get("product_title", "")),
                _price(item.get("displayed_price_twd")),
                str(item.get("observed_at_utc", "")),
                source_kind,
                str(item.get("qualification_state", "UNVERIFIED")),
                "已匯入／快照",
                "合成測試" if synthetic else source_kind,
            )
    return sorted(rows.values(), key=lambda row: row.observed_at, reverse=True)
