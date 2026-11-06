"""Strict offline URL validation for original and verified destinations."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit


REDIRECT_KEYS = frozenset(
    {"url", "redirect", "redirect_uri", "return", "return_url", "next", "target", "continue", "dest", "destination"}
)
MANUAL_TRACKING_KEYS = frozenset(
    {"affiliate", "affiliate_id", "aff", "subid", "sub_id", "tag", "tracking", "tracking_id", "ref", "referrer"}
)
DENIED_REDIRECT_PATHS = ("/r/", "/redirect", "/go/", "/out/", "/link/")


def _path_matches(path: str, prefix: str) -> bool:
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix or path.startswith(prefix + "/")


def validate_policy(hosts: frozenset[str], paths: tuple[str, ...], label: str) -> tuple[str, ...]:
    errors: list[str] = []
    if not hosts:
        errors.append(f"{label}_HOSTS_MISSING")
    elif any(
        not isinstance(host, str)
        or not host
        or not host.isascii()
        or host != host.casefold()
        or host.startswith(".")
        or host.endswith(".")
        or "*" in host
        or any(character in host for character in "/\\:@?#")
        for host in hosts
    ):
        errors.append(f"{label}_HOST_INVALID")
    if not paths:
        errors.append(f"{label}_PATHS_MISSING")
    elif any(
        not isinstance(path, str)
        or not path.startswith("/")
        or "\\" in path
        or "?" in path
        or "#" in path
        or ".." in path.split("/")
        for path in paths
    ):
        errors.append(f"{label}_PATH_INVALID")
    return tuple(errors)


def validate_url(
    value: object,
    *,
    allowed_hosts: frozenset[str],
    allowed_paths: tuple[str, ...],
    label: str,
    deny_manual_tracking: bool,
) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or any(ord(character) < 0x20 for character in value):
        return (f"{label}_URL_INVALID",)
    if "\\" in value:
        return (f"{label}_URL_BACKSLASH_DENIED",)
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return (f"{label}_URL_MALFORMED",)
    errors: list[str] = []
    if parsed.scheme != "https":
        errors.append(f"{label}_URL_NOT_HTTPS")
    if parsed.username is not None or parsed.password is not None:
        errors.append(f"{label}_URL_USERINFO_DENIED")
    if port not in (None, 443):
        errors.append(f"{label}_URL_PORT_DENIED")
    if parsed.fragment:
        errors.append(f"{label}_URL_FRAGMENT_DENIED")
    normalized_host = host.casefold() if isinstance(host, str) else ""
    if not normalized_host or normalized_host not in allowed_hosts:
        errors.append(f"{label}_HOST_NOT_ALLOWED")
    if not allowed_paths or not any(_path_matches(parsed.path, prefix) for prefix in allowed_paths):
        errors.append(f"{label}_PATH_NOT_ALLOWED")
    if any(parsed.path.casefold().startswith(prefix) for prefix in DENIED_REDIRECT_PATHS):
        errors.append(f"{label}_REDIRECT_ALIAS_DENIED")
    try:
        query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)}
    except ValueError:
        errors.append(f"{label}_QUERY_MALFORMED")
    else:
        if query_keys & REDIRECT_KEYS:
            errors.append(f"{label}_OPEN_REDIRECT_DENIED")
        if deny_manual_tracking and query_keys & MANUAL_TRACKING_KEYS:
            errors.append(f"{label}_MANUAL_TRACKING_DENIED")
    return tuple(dict.fromkeys(errors))
