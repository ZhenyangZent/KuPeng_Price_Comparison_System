from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .schema import parse_utc


CONTRACT = "CDH-D04-PRICE-HISTORY-1"
MAX_REPORT_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class D04ReportStatus:
    state: str
    detail: str
    generated_at: str | None = None
    item_count: int | None = None


def read_d04_report(path: Path) -> D04ReportStatus:
    if not path.exists():
        return D04ReportStatus("NOT_ENABLED", "歷史報表尚未啟用")
    if path.is_symlink() or not path.is_file():
        return D04ReportStatus("INVALID", "歷史報表路徑類型不安全")
    if path.stat().st_size > MAX_REPORT_BYTES:
        return D04ReportStatus("INVALID", "歷史報表超過 5 MiB 上限")
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return D04ReportStatus("INVALID", f"歷史報表無法驗證：{exc}")
    if not isinstance(value, dict):
        return D04ReportStatus("INVALID", "歷史報表必須是 JSON 物件")
    if value.get("contract") != CONTRACT:
        return D04ReportStatus("INCOMPATIBLE", "歷史報表版本不相容")
    if value.get("source_status") != "SOURCE_BLOCKED":
        return D04ReportStatus("INVALID", "歷史報表不得提升來源權限")
    rows = value.get("items")
    if not isinstance(rows, list) or len(rows) > 10_000:
        return D04ReportStatus("INVALID", "歷史報表 items 無效")
    generated = value.get("generated_at")
    if not isinstance(generated, str):
        return D04ReportStatus("INVALID", "歷史報表缺少 generated_at")
    try:
        parsed = parse_utc(generated, "generated_at")
    except Exception as exc:
        return D04ReportStatus("INVALID", f"歷史報表時間無效：{exc}")
    return D04ReportStatus("READY", "已唯讀載入 D04 本機歷史報表", parsed.isoformat(), len(rows))
