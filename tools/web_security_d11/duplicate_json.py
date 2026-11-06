from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class DuplicateKeyError(ValueError):
    key: str

    def __str__(self) -> str:
        return f"duplicate JSON object key: {self.key!r}"


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(key)
        result[key] = value
    return result


def strict_json_loads(text: str) -> object:
    """Reference oracle: reject duplicate decoded keys at every nesting depth."""
    return json.loads(text, object_pairs_hook=_strict_object)


DUPLICATE_MUTATIONS: dict[str, str] = {
    "top_level_same": '[{"record_id":"A","record_id":"A"}]',
    "top_level_different": '[{"record_id":"A","record_id":"B"}]',
    "nested_identity_different": '[{"identity":{"sku_id":"SYN-A","sku_id":"SYN-B"}}]',
    "nested_identity_same": '[{"identity":{"sku_id":"SYN-A","sku_id":"SYN-A"}}]',
    "unicode_escape_collision": '[{"identity":{"sku_id":"SYN-A","sku_\\u0069d":"SYN-B"}}]',
    "nested_source_collision": '[{"source":{"evidence_id":"E1","evidence_id":"E2"}}]',
    "nested_coupon_collision": '[{"coupon":{"status":"NONE","st\\u0061tus":"CONFIRMED_APPLICABLE"}}]',
    "three_way_collision": '[{"series_key":"A","series_key":"B","series_key":"C"}]',
}
