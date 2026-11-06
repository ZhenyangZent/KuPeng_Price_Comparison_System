from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage import atomic_json_write, read_json


DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 1,
    "wow_membership": "UNKNOWN",
    "first_purchase_eligibility": "UNKNOWN",
    "o1_prefer_free_shipping": True,
    "o2_paid_shipping_exception_threshold_twd": None,
    "scope": "A01_PREVIEW_ONLY_NOT_CORE_POLICY",
}


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        data = read_json(self.path, dict(DEFAULT_SETTINGS))
        if not isinstance(data, dict) or data.get("scope") != DEFAULT_SETTINGS["scope"]:
            raise ValueError("A01 設定檔格式損壞")
        return {**DEFAULT_SETTINGS, **data}

    def save(self, *, wow_active: bool, paid_shipping_threshold: int | None) -> dict[str, Any]:
        if paid_shipping_threshold is not None and (isinstance(paid_shipping_threshold, bool) or paid_shipping_threshold < 0):
            raise ValueError("門檻必須是非負整數或空值")
        data = dict(DEFAULT_SETTINGS)
        data["wow_membership"] = "USER_DECLARED_ACTIVE" if wow_active else "UNKNOWN"
        data["o2_paid_shipping_exception_threshold_twd"] = paid_shipping_threshold
        atomic_json_write(self.path, data)
        return data
