from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterable


REQUIRED_CSP = {
    "default-src": {"'self'"},
    "script-src": {"'self'"},
    "connect-src": {"'self'"},
    "object-src": {"'none'"},
    "base-uri": {"'none'"},
    "frame-ancestors": {"'none'"},
    "form-action": {"'none'"},
}
FORBIDDEN_CSP_TOKENS = {"*", "'unsafe-inline'", "'unsafe-eval'", "http:", "https:"}
REQUIRED_DENIED_PERMISSIONS = {"camera", "microphone", "geolocation", "payment", "usb"}


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.headers: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "meta":
            return
        values = {name.casefold(): value for name, value in attrs if value is not None}
        key = values.get("http-equiv") or ("Referrer-Policy" if values.get("name", "").casefold() == "referrer" else None)
        if key and "content" in values:
            self.headers[key.casefold()] = values["content"]


def frontend_meta_headers(index_html: str) -> dict[str, str]:
    parser = _MetaParser()
    parser.feed(index_html)
    return parser.headers


def backend_literal_headers(api_source: str) -> dict[str, str]:
    pairs = re.findall(r"\(\s*[\"']([^\"']+)[\"']\s*,\s*[\"']([^\"']*)[\"']\s*\)", api_source)
    return {name.casefold(): value for name, value in pairs}


def _directives(value: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for raw in value.split(";"):
        parts = raw.strip().split()
        if parts:
            result[parts[0].casefold()] = {item.casefold() for item in parts[1:]}
    return result


def assess_csp(value: str | None) -> tuple[bool, list[str]]:
    if not value:
        return False, ["CSP_MISSING"]
    directives = _directives(value)
    reasons: list[str] = []
    for name, required in REQUIRED_CSP.items():
        actual = directives.get(name)
        if actual is None:
            reasons.append(f"CSP_{name.upper().replace('-', '_')}_MISSING")
        elif not required.issubset(actual):
            reasons.append(f"CSP_{name.upper().replace('-', '_')}_NOT_RESTRICTIVE")
    for name, tokens in directives.items():
        forbidden = tokens & FORBIDDEN_CSP_TOKENS
        if forbidden:
            reasons.append(f"CSP_{name.upper().replace('-', '_')}_UNSAFE:{','.join(sorted(forbidden))}")
        if any(token.startswith("data:") for token in tokens) and name != "img-src":
            reasons.append(f"CSP_{name.upper().replace('-', '_')}_DATA_UNSAFE")
    return not reasons, reasons


def assess_referrer(value: str | None) -> tuple[bool, list[str]]:
    if value is None:
        return False, ["REFERRER_POLICY_MISSING"]
    if value.strip().casefold() != "no-referrer":
        return False, ["REFERRER_POLICY_NOT_NO_REFERRER"]
    return True, []


def assess_frame(value: str | None) -> tuple[bool, list[str]]:
    if value is None:
        return False, ["X_FRAME_OPTIONS_MISSING"]
    if value.strip().casefold() != "deny":
        return False, ["X_FRAME_OPTIONS_NOT_DENY"]
    return True, []


def assess_permissions(value: str | None) -> tuple[bool, list[str]]:
    if value is None:
        return False, ["PERMISSIONS_POLICY_MISSING"]
    compact = re.sub(r"\s+", "", value.casefold())
    missing = sorted(name for name in REQUIRED_DENIED_PERMISSIONS if f"{name}=()" not in compact)
    return not missing, [f"PERMISSIONS_POLICY_NOT_DENIED:{name}" for name in missing]


def assess_header_set(headers: dict[str, str], *, require_frame: bool = True, require_permissions: bool = True) -> dict[str, object]:
    normalized = {key.casefold(): value for key, value in headers.items()}
    checks = {
        "csp": assess_csp(normalized.get("content-security-policy")),
        "referrer_policy": assess_referrer(normalized.get("referrer-policy")),
    }
    if require_frame:
        checks["frame"] = assess_frame(normalized.get("x-frame-options"))
    if require_permissions:
        checks["permissions_policy"] = assess_permissions(normalized.get("permissions-policy"))
    reasons = [reason for _name, (_passed, values) in checks.items() for reason in values]
    return {
        "passed": not reasons,
        "checks": {name: passed for name, (passed, _reasons) in checks.items()},
        "reasons": reasons,
    }


def merge_header_sources(*sources: Iterable[tuple[str, str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for source in sources:
        for name, value in source:
            result[name.casefold()] = value
    return result
