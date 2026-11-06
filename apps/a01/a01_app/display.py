from __future__ import annotations

from typing import Any


def money_text(value: object) -> str:
    if value is None:
        return "未知"
    if isinstance(value, bool) or not isinstance(value, int):
        return "無效"
    return f"NT$ {value:,}"


def shipping_text(item: dict[str, Any]) -> str:
    status = item.get("shipping_status", "UNKNOWN")
    if status == "FREE":
        return "免運（觀測紀錄）"
    if status == "PAID":
        return f"運費 {money_text(item.get('shipping_fee_twd'))}"
    return "運費未知（未確認 WOW 免運）"


def snapshot_rows(snapshot: dict[str, Any], *, include_synthetic: bool = True) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in snapshot.get("items", []):
        if item.get("is_synthetic") and not include_synthetic:
            continue
        rows.append({
            "title": str(item.get("product_title", "")),
            "price": money_text(item.get("displayed_price_twd")),
            "observed": str(item.get("observed_at_utc", "")),
            "qualification": str(item.get("qualification_state", "UNVERIFIED")),
            "source": str(item.get("source_kind", "UNKNOWN")),
            "synthetic": "合成測試" if item.get("is_synthetic") else "使用者觀測",
        })
    return sorted(rows, key=lambda row: row["observed"], reverse=True)
