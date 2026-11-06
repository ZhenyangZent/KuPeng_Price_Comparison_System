from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import parse_money_text, safe_product_url
from .storage import atomic_json_write, read_json


class WatchlistStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list(self) -> list[dict[str, Any]]:
        data = read_json(self.path, {"version": 1, "items": []})
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("items"), list):
            raise ValueError("watchlist 格式損壞")
        return list(data["items"])

    def add(self, title: str, target_total_text: str, url: str | None = None) -> dict[str, Any]:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("商品名稱不可空白")
        target = parse_money_text(target_total_text, "target_total_twd")
        clean_url = safe_product_url(url) if url else None
        items = self.list()
        entry = {
            "watch_id": str(uuid.uuid4()),
            "title": clean_title,
            "target_total_twd": target,
            "url": clean_url,
            "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "scope": "A01_PREVIEW_ONLY_NOT_CORE_POLICY",
        }
        items.append(entry)
        atomic_json_write(self.path, {"version": 1, "items": items})
        return entry

    def remove(self, watch_id: str) -> bool:
        items = self.list()
        kept = [item for item in items if item.get("watch_id") != watch_id]
        if len(kept) == len(items):
            return False
        atomic_json_write(self.path, {"version": 1, "items": kept})
        return True
