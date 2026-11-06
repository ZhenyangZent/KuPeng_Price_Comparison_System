from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .constants import EXCHANGE_VERSION, MAX_SNAPSHOT_BYTES, SNAPSHOT_STALE_HOURS
from .schema import ValidationError, parse_utc, strict_money


class SnapshotError(ValueError):
    pass


@dataclass(frozen=True)
class SnapshotResult:
    data: dict[str, Any] | None
    state: str
    detail: str
    generated_at: datetime | None = None
    stale: bool = False


def _required(mapping: dict[str, Any], names: set[str], where: str) -> None:
    missing = names - set(mapping)
    if missing:
        raise SnapshotError(f"{where} 缺少欄位: {sorted(missing)}")


def validate_snapshot(value: object, *, now: datetime | None = None) -> tuple[dict[str, Any], datetime, bool]:
    if not isinstance(value, dict):
        raise SnapshotError("snapshot 必須是 JSON 物件")
    _required(value, {"schema_version", "snapshot_generated_at_utc", "source", "counts", "items", "source_status"}, "snapshot")
    if value["schema_version"] != EXCHANGE_VERSION or value["source"] != "D01_LOCAL_LEDGER":
        raise SnapshotError("snapshot 契約版本或來源不符")
    check_now = now or datetime.now(timezone.utc)
    try:
        generated = parse_utc(value["snapshot_generated_at_utc"], "snapshot_generated_at_utc", now=check_now)
    except ValidationError as exc:
        raise SnapshotError(exc.detail) from exc
    counts = value["counts"]
    if not isinstance(counts, dict):
        raise SnapshotError("counts 必須是物件")
    for name in ("total_entries", "real_observations", "synthetic_observations", "unverified_leads"):
        number = counts.get(name)
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise SnapshotError(f"counts.{name} 必須是非負整數")
    items = value["items"]
    if not isinstance(items, list):
        raise SnapshotError("items 必須是陣列")
    required = {"submission_id", "record_type", "observed_at_utc", "product_title", "displayed_price_twd", "is_synthetic", "qualification_state", "source_kind", "source_url"}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise SnapshotError(f"items[{index}] 必須是物件")
        _required(item, required, f"items[{index}]")
        try:
            parse_utc(item["observed_at_utc"], f"items[{index}].observed_at_utc", now=check_now)
            strict_money(item["displayed_price_twd"], f"items[{index}].displayed_price_twd", nullable=True)
        except ValidationError as exc:
            raise SnapshotError(exc.detail) from exc
        if not isinstance(item["product_title"], str) or not item["product_title"].strip():
            raise SnapshotError(f"items[{index}].product_title 無效")
        if not isinstance(item["is_synthetic"], bool):
            raise SnapshotError(f"items[{index}].is_synthetic 必須是 boolean")
    status = value["source_status"]
    if not isinstance(status, dict) or status.get("live_coupang_discovery") != "SOURCE_BLOCKED":
        raise SnapshotError("來源狀態必須明示 SOURCE_BLOCKED")
    stale = check_now - generated > timedelta(hours=SNAPSHOT_STALE_HOURS)
    return value, generated, stale


def read_snapshot(path: Path, *, now: datetime | None = None) -> SnapshotResult:
    if not path.exists():
        return SnapshotResult(None, "WAITING", "資料等待中：D01 尚未提供 snapshot")
    try:
        size = path.stat().st_size
        if size > MAX_SNAPSHOT_BYTES:
            raise SnapshotError("snapshot 超過 50 MiB 上限")
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"), parse_constant=lambda token: (_ for _ in ()).throw(SnapshotError(f"不接受 {token}")))
        valid, generated, stale = validate_snapshot(data, now=now)
        return SnapshotResult(valid, "STALE" if stale else "READY", "快照已過期" if stale else "快照可用", generated, stale)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SnapshotError) as exc:
        return SnapshotResult(None, "FAULT", f"snapshot 故障：{exc}")


class SnapshotCache:
    def __init__(self) -> None:
        self.current: SnapshotResult | None = None

    def accept(self, candidate: SnapshotResult) -> bool:
        if candidate.data is None or candidate.generated_at is None:
            return False
        if self.current and self.current.generated_at and candidate.generated_at <= self.current.generated_at:
            return False
        self.current = candidate
        return True
