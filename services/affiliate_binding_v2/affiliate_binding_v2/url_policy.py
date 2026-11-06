"""Offline URL policy.  No URL is opened or requested."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit


REDIRECT_KEYS = frozenset(
    {"url", "redirect", "redirect_uri", "return", "return_url", "next", "target", "continue", "dest", "destination"}
)
DENIED_REDIRECT_PATH_PREFIXES = ("/r/", "/redirect", "/go/", "/out/", "/link/")


def validate_authority_url_policy(
    allowed_hosts: frozenset[str], allowed_path_prefixes: tuple[str, ...]
) -> tuple[str, ...]:
    errors: list[str] = []
    if not allowed_hosts:
        errors.append("C03_OUTPUT_HOSTS_MISSING")
    elif any(
        not isinstance(host, str)
        or not host
        or not host.isascii()
        or host != host.casefold()
        or host.startswith(".")
        or host.endswith(".")
        or "*" in host
        or any(character in host for character in "/\\:@?#")
        for host in allowed_hosts
    ):
        errors.append("C03_OUTPUT_HOST_INVALID")
    if not allowed_path_prefixes:
        errors.append("C03_ALLOWED_PATHS_MISSING")
    elif any(
        not isinstance(prefix, str)
        or not prefix.startswith("/")
        or "\\" in prefix
        or "?" in prefix
        or "#" in prefix
        or ".." in prefix.split("/")
        for prefix in allowed_path_prefixes
    ):
        errors.append("C03_ALLOWED_PATH_INVALID")
    return tuple(errors)


def validate_click_url(
    url: object,
    *,
    allowed_hosts: frozenset[str],
    allowed_path_prefixes: tuple[str, ...],
) -> tuple[str, ...]:
    if not isinstance(url, str) or not url or any(ord(character) < 0x20 for character in url):
        return ("AFFILIATE_URL_INVALID",)
    if "\\" in url:
        return ("AFFILIATE_URL_BACKSLASH_DENIED",)
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return ("AFFILIATE_URL_MALFORMED",)
    errors: list[str] = []
    if parsed.scheme != "https":
        errors.append("AFFILIATE_URL_NOT_HTTPS")
    if parsed.username is not None or parsed.password is not None:
        errors.append("AFFILIATE_URL_USERINFO_DENIED")
    if port not in (None, 443):
        errors.append("AFFILIATE_URL_PORT_DENIED")
    if parsed.fragment:
        errors.append("AFFILIATE_URL_FRAGMENT_DENIED")
    normalized_host = host.casefold() if isinstance(host, str) else ""
    if not normalized_host or not normalized_host.isascii() or normalized_host.endswith("."):
        errors.append("AFFILIATE_HOST_INVALID")
    elif normalized_host not in allowed_hosts:
        errors.append("AFFILIATE_HOST_NOT_ALLOWED")
    if not allowed_path_prefixes or not any(parsed.path.startswith(prefix) for prefix in allowed_path_prefixes):
        errors.append("AFFILIATE_PATH_NOT_ALLOWED")
    if any(parsed.path.casefold().startswith(prefix) for prefix in DENIED_REDIRECT_PATH_PREFIXES):
        errors.append("REDIRECT_ALIAS_PATH_DENIED")
    try:
        keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)}
    except ValueError:
        errors.append("AFFILIATE_QUERY_MALFORMED")
    else:
        if keys & REDIRECT_KEYS:
            errors.append("OPEN_REDIRECT_PARAMETER_DENIED")
    return tuple(dict.fromkeys(errors))
