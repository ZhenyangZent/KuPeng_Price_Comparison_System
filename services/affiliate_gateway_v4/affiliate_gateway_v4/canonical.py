"""Canonical JSON primitives used by the signed envelope."""

from __future__ import annotations

import json
from typing import Any


def _reject_unsupported(value: object, path: str = "$.") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        raise ValueError(f"floating point is forbidden at {path}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_unsupported(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"non-string object key at {path}")
        for key, item in value.items():
            _reject_unsupported(item, f"{path}{key}.")
        return
    raise ValueError(f"unsupported canonical JSON type at {path}")


def canonical_json(value: Any) -> bytes:
    _reject_unsupported(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
