from __future__ import annotations

import json
from pathlib import Path


def check_workline_registry(path: Path) -> dict:
    path = path.resolve()
    result = {"path": str(path), "record_count": 0, "conflicts": [], "passed": False}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        records = value.get("worklines", [])
        if not isinstance(records, list):
            raise ValueError("worklines must be a list")
        result["record_count"] = len(records)
        grouped: dict[str, set[tuple[str, str, str]]] = {}
        for record in records:
            key = str(record["workline"])
            identity = (
                str(record.get("task_id", "")),
                str(record.get("version", "")),
                str(record.get("source_sha256", "")),
            )
            grouped.setdefault(key, set()).add(identity)
        for workline, identities in sorted(grouped.items()):
            if len(identities) > 1:
                result["conflicts"].append(
                    {"workline": workline, "identities": [list(identity) for identity in sorted(identities)]}
                )
        result["passed"] = not result["conflicts"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        result["error"] = f"REGISTRY_ERROR: {error}"
    return result
