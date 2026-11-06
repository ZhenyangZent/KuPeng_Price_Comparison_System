"""Strict C06 runtime ceiling reader."""

from __future__ import annotations

import json
from pathlib import Path

from .models import RuntimeCeiling


class CeilingError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


FORBIDDEN_KEYS = frozenset({"access_key", "secret_key", "api_key", "token", "password", "cookie", "authorization"})


def _keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            found.add(str(key).casefold())
            found.update(_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_keys(child))
    return found


def load_c06_ceiling(path: str | Path) -> RuntimeCeiling:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise CeilingError("C06_FILE_INVALID", "C06 decision must be a regular local file")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CeilingError("C06_JSON_INVALID", str(exc)) from exc
    if not isinstance(value, dict):
        raise CeilingError("C06_ROOT_INVALID", "C06 decision root must be an object")
    forbidden = sorted(_keys(value) & FORBIDDEN_KEYS)
    if forbidden:
        raise CeilingError("C06_SECRET_KEY_DENIED", f"secret-bearing keys denied: {forbidden}")
    if value.get("schema_version") != "CDH-C06-BASELINE-DECISION-1":
        raise CeilingError("C06_SCHEMA_INVALID", "unexpected C06 schema")
    if value.get("market") != "TW" or value.get("provider_id") != "coupang_tw_partners":
        raise CeilingError("C06_PROVIDER_INVALID", "Taiwan provider identity required")
    if (
        value.get("evidence_delta_from_c05") != "NO_NEW_OFFICIAL_EVIDENCE"
        or value.get("technical_state") != "SOURCE_BLOCKED"
        or value.get("source_authorization_required") is not True
        or value.get("account_authorized") is not False
        or value.get("runtime_authorized") is not False
        or value.get("automatic_promotion") is not False
        or value.get("cta_enabled") is not False
        or value.get("click_url") is not None
        or value.get("endpoint_hosts") != []
        or value.get("redirect_hosts") != []
    ):
        raise CeilingError("C06_RUNTIME_BOUNDARY_INVALID", "C06 must remain source blocked and non-clickable")
    return RuntimeCeiling(
        state="SOURCE_AUTHORIZATION_REQUIRED",
        source_authorization_required=True,
        account_authorized=False,
        runtime_authorized=False,
        cta_enabled=False,
        click_url=None,
        endpoint_hosts=frozenset(),
        redirect_hosts=frozenset(),
    )
