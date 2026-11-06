"""Strict reader for the immutable C05 capability decision."""

from __future__ import annotations

import json
from pathlib import Path

from .models import AuthoritySnapshot, CapabilityEvidence


class AuthorityError(ValueError):
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


def load_c05_authority(path: str | Path) -> AuthoritySnapshot:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise AuthorityError("C05_FILE_INVALID", "C05 decision must be a regular local file")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorityError("C05_JSON_INVALID", str(exc)) from exc
    if not isinstance(value, dict):
        raise AuthorityError("C05_ROOT_INVALID", "C05 decision root must be an object")
    forbidden = sorted(_keys(value) & FORBIDDEN_KEYS)
    if forbidden:
        raise AuthorityError("C05_SECRET_KEY_DENIED", f"secret-bearing keys denied: {forbidden}")
    if value.get("schema_version") != "CDH-C05-CAPABILITY-DECISION-1":
        raise AuthorityError("C05_SCHEMA_INVALID", "unexpected decision schema")
    if value.get("provider_id") != "coupang_tw_partners" or value.get("market") != "TW":
        raise AuthorityError("C05_PROVIDER_INVALID", "Taiwan provider identity required")
    if value.get("source_authorization_required") is not True or value.get("automatic_promotion") is not False:
        raise AuthorityError("C05_PROMOTION_BOUNDARY_INVALID", "C05 must remain source-blocked and non-promoting")
    raw_caps = value.get("capabilities")
    runtime = value.get("runtime_authority")
    account = value.get("account_authority")
    if not isinstance(raw_caps, dict) or not isinstance(runtime, dict) or not isinstance(account, dict):
        raise AuthorityError("C05_STRUCTURE_INVALID", "capability/account/runtime blocks are required")
    capabilities: dict[str, CapabilityEvidence] = {}
    for name, item in raw_caps.items():
        if not isinstance(item, dict) or item.get("runtime_eligible") is not False or not isinstance(item.get("evidence_ids"), list):
            raise AuthorityError("C05_CAPABILITY_INVALID", f"capability is not frozen fail-closed: {name}")
        capabilities[name] = CapabilityEvidence(False, frozenset(str(x) for x in item["evidence_ids"]))
    if account.get("state") != "SOURCE_BLOCKED" or account.get("credentials_present") is not False:
        raise AuthorityError("C05_ACCOUNT_INVALID", "account must remain source blocked")
    if (
        runtime.get("state") != "SOURCE_BLOCKED"
        or runtime.get("separate_authority_present") is not False
        or runtime.get("endpoint") is not None
        or runtime.get("input_host_allowlist") != []
        or runtime.get("output_host_allowlist") != []
        or runtime.get("click_url") is not None
        or runtime.get("cta_enabled") is not False
        or runtime.get("error_code") != "SOURCE_AUTHORIZATION_REQUIRED"
    ):
        raise AuthorityError("C05_RUNTIME_INVALID", "C05 runtime must remain source authorization required")
    return AuthoritySnapshot(
        state="SOURCE_AUTHORIZATION_REQUIRED",
        provider_id="coupang_tw_partners",
        market="TW",
        account_state="SOURCE_BLOCKED",
        credential_state="UNCONFIGURED",
        capabilities=capabilities,
        input_hosts=frozenset(),
        input_paths=(),
        output_hosts=frozenset(),
        output_paths=(),
        disclosure_text=None,
        authority_expires_at=None,
        max_ttl_seconds=None,
        max_revocation_age_seconds=None,
        revoked=False,
    )
