from __future__ import annotations

import json
import re
import sqlite3
import stat
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence
from urllib.parse import parse_qs, quote, urlparse


WEB_SCHEMA = "CDH-WEB-CONTRACT-V1"
PUBLIC_SOURCE_TYPES = frozenset({"USER_ENTERED", "USER_FILE"})
AFFILIATE_STATES = frozenset(
    {"UNCONFIGURED", "PENDING_OFFICIAL_DOCS", "VERIFIED", "FAILED", "DISABLED"}
)
NONCLICKABLE_AFFILIATE_STATES = AFFILIATE_STATES - {"VERIFIED"}
REDIRECT_QUERY_KEYS = frozenset(
    {"url", "redirect", "redirect_uri", "return", "return_url", "next", "target", "continue"}
)
TEXT_SUFFIXES = frozenset(
    {
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".css",
        ".html",
        ".htm",
        ".json",
        ".map",
        ".txt",
        ".log",
        ".md",
        ".xml",
        ".svg",
    }
)
SENSITIVE_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        "cookies.sqlite",
        "key4.db",
        "logins.json",
        "access_token",
        "refresh_token",
    }
)
SENSITIVE_SUFFIXES = frozenset({".pem", ".key", ".pfx", ".p12", ".reg"})
SECRET_ASSIGNMENT_RE = re.compile(
    rb"(?i)(?:api[_-]?key|client[_-]?secret|access[_-]?token|authorization)"
    rb"\s*[:=]\s*['\"]?(?!placeholder|example|redacted)[A-Za-z0-9_./+\-=]{12,}"
)
FORBIDDEN_SQL_RE = re.compile(
    r"(?i)\b(insert|update|delete|replace|alter|drop|create|attach|detach|pragma|vacuum|reindex|analyze|load_extension)\b"
)
ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_PLACEHOLDER_VALUES = frozenset(
    {"", "placeholder", "example", "redacted", "disabled", "not-set", "unset", "changeme"}
)


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    severity: str
    location: str
    detail: str
    owner: str


@dataclass(frozen=True, slots=True)
class AuditResult:
    findings: tuple[Finding, ...]
    files_scanned: int
    bytes_scanned: int

    @property
    def passed(self) -> bool:
        return not any(item.severity in {"CRITICAL", "HIGH"} for item in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "files_scanned": self.files_scanned,
            "bytes_scanned": self.bytes_scanned,
            "findings": [asdict(item) for item in self.findings],
        }


@dataclass(frozen=True, slots=True)
class AffiliatePolicy:
    allowed_hosts: frozenset[str]
    expected_product_id: str
    expected_sku_id: str
    evaluated_at: datetime
    official_host_evidence_sha256: str | None = None
    exact_variant_evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if not self.allowed_hosts:
            raise ValueError("allowed_hosts cannot be empty")


def _valid_evidence_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _safe_example_value(value: str) -> bool:
    normalized = value.strip().strip('"\'')
    if normalized.casefold() in SAFE_PLACEHOLDER_VALUES:
        return True
    try:
        parsed = urlparse(normalized)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme not in {"http", "https"} or not host:
            return False
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return False
        return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".invalid")
    except ValueError:
        return False


def _validate_env_example(raw: bytes, *, location: str, owner: str) -> list[Finding]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [Finding("ENV_EXAMPLE_INVALID_UTF8", "CRITICAL", location, "Example env must be UTF-8.", owner)]
    if len(raw) > 16_384:
        return [Finding("ENV_EXAMPLE_TOO_LARGE", "CRITICAL", location, "Example env exceeds 16 KiB.", owner)]
    findings: list[Finding] = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped or stripped.startswith("export "):
            findings.append(Finding("ENV_EXAMPLE_MALFORMED", "CRITICAL", f"{location}:{number}", "Expected KEY=VALUE without shell syntax.", owner))
            continue
        key, value = stripped.split("=", 1)
        if ENV_KEY_RE.fullmatch(key) is None or key in seen:
            findings.append(Finding("ENV_EXAMPLE_KEY_INVALID", "CRITICAL", f"{location}:{number}", "Key is invalid or duplicated.", owner))
        seen.add(key)
        if not _safe_example_value(value):
            findings.append(Finding("ENV_EXAMPLE_VALUE_NOT_INERT", "CRITICAL", f"{location}:{number}", "Only empty/explicit placeholders, loopback URLs, or .invalid URLs are allowed.", owner))
    return findings


def _inside(root: Path, child: Path) -> bool:
    return child == root or root in child.parents


def _scan_bytes(
    raw: bytes,
    *,
    location: str,
    sentinels: Sequence[bytes],
    owner: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for sentinel in sentinels:
        if not sentinel:
            raise ValueError("empty sentinel is not allowed")
        if sentinel in raw:
            findings.append(
                Finding(
                    "SECRET_SENTINEL_EXPOSED",
                    "CRITICAL",
                    location,
                    "A caller-supplied synthetic secret sentinel is present in a browser/review artifact.",
                    owner,
                )
            )
    if SECRET_ASSIGNMENT_RE.search(raw):
        findings.append(
            Finding(
                "SECRET_LIKE_ASSIGNMENT",
                "HIGH",
                location,
                "Secret-like assignment found; redact and rotate if this is not a fixture.",
                owner,
            )
        )
    return findings


def _path_findings(name: str, *, owner: str) -> list[Finding]:
    path = PurePosixPath(name.replace("\\", "/"))
    basename = path.name.casefold()
    findings: list[Finding] = []
    if basename in SENSITIVE_NAMES or (basename.startswith(".env.") and basename != ".env.example"):
        findings.append(
            Finding("SENSITIVE_FILENAME", "CRITICAL", name, "Sensitive file must not enter an artifact.", owner)
        )
    if Path(basename).suffix.casefold() in SENSITIVE_SUFFIXES:
        findings.append(
            Finding("SENSITIVE_FILE_TYPE", "CRITICAL", name, "Private-key/Registry file type is forbidden.", owner)
        )
    if any(part.casefold() in {"__pycache__", ".git", ".venv", "node_modules"} for part in path.parts):
        findings.append(
            Finding("CACHE_OR_ENVIRONMENT_CONTENT", "HIGH", name, "Cache, VCS or environment content is forbidden.", owner)
        )
    return findings


def audit_tree(
    target: str | Path,
    *,
    allowed_root: str | Path,
    sentinels: Iterable[bytes] = (),
    owner: str = "A",
    max_file_bytes: int = 20_000_000,
) -> AuditResult:
    root = Path(allowed_root).resolve(strict=True)
    path = Path(target).resolve(strict=True)
    if not _inside(root, path):
        raise ValueError("AUDIT_TARGET_OUTSIDE_ALLOWED_ROOT")
    if path.is_symlink():
        raise ValueError("AUDIT_TARGET_SYMLINK_DENIED")
    findings: list[Finding] = []
    files_scanned = 0
    bytes_scanned = 0
    sentinel_tuple = tuple(sentinels)
    candidates = [path] if path.is_file() else sorted(path.rglob("*"))
    for item in candidates:
        if item.is_symlink():
            findings.append(Finding("SYMLINK_DENIED", "HIGH", str(item), "Symlink artifact entry denied.", owner))
            continue
        if not item.is_file():
            continue
        relative = item.relative_to(root).as_posix()
        findings.extend(_path_findings(relative, owner=owner))
        size = item.stat().st_size
        if size > max_file_bytes:
            findings.append(
                Finding("FILE_SCAN_LIMIT", "HIGH", relative, f"File exceeds scan limit: {size} bytes.", owner)
            )
            continue
        raw = item.read_bytes()
        files_scanned += 1
        bytes_scanned += len(raw)
        findings.extend(_scan_bytes(raw, location=relative, sentinels=sentinel_tuple, owner=owner))
        if item.name.casefold() == ".env.example":
            findings.extend(_validate_env_example(raw, location=relative, owner=owner))
    return AuditResult(tuple(findings), files_scanned, bytes_scanned)


def _safe_zip_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return bool(normalized) and "\\" not in name and not normalized.startswith("/") and not path.is_absolute() and ".." not in path.parts and not (len(normalized) > 1 and normalized[1] == ":")


def audit_zip(
    target: str | Path,
    *,
    sentinels: Iterable[bytes] = (),
    owner: str = "A",
    max_total_bytes: int = 200_000_000,
) -> AuditResult:
    path = Path(target)
    if not path.is_file() or path.is_symlink():
        raise ValueError("ZIP_NOT_REGULAR_FILE")
    findings: list[Finding] = []
    seen: set[str] = set()
    bytes_scanned = 0
    files_scanned = 0
    sentinel_tuple = tuple(sentinels)
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                name = info.filename
                key = name.replace("\\", "/").casefold()
                if not _safe_zip_name(name):
                    findings.append(Finding("UNSAFE_ZIP_PATH", "CRITICAL", name, "Unsafe ZIP path.", owner))
                if key in seen:
                    findings.append(Finding("DUPLICATE_ZIP_PATH", "HIGH", name, "Case-fold duplicate path.", owner))
                seen.add(key)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    findings.append(Finding("ZIP_SYMLINK_DENIED", "CRITICAL", name, "Symlink ZIP entry denied.", owner))
                if info.flag_bits & 0x1:
                    findings.append(Finding("ENCRYPTED_ZIP_ENTRY", "HIGH", name, "Encrypted entry cannot be audited.", owner))
                if info.is_dir():
                    continue
                findings.extend(_path_findings(name, owner=owner))
                bytes_scanned += info.file_size
                if bytes_scanned > max_total_bytes:
                    findings.append(
                        Finding("ZIP_SCAN_LIMIT", "HIGH", str(path), "Uncompressed ZIP scan limit exceeded.", owner)
                    )
                    break
                try:
                    raw = archive.read(info)
                except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    findings.append(
                        Finding("ZIP_READ_OR_CRC_FAILURE", "CRITICAL", name, type(exc).__name__, owner)
                    )
                    continue
                files_scanned += 1
                findings.extend(_scan_bytes(raw, location=name, sentinels=sentinel_tuple, owner=owner))
                if PurePosixPath(name.replace("\\", "/")).name.casefold() == ".env.example":
                    findings.extend(_validate_env_example(raw, location=name, owner=owner))
            bad = archive.testzip()
            if bad is not None:
                findings.append(Finding("ZIP_CRC_FAILURE", "CRITICAL", bad, "CRC verification failed.", owner))
    except zipfile.BadZipFile:
        findings.append(Finding("INVALID_ZIP", "CRITICAL", str(path), "Invalid ZIP structure.", owner))
    return AuditResult(tuple(findings), files_scanned, bytes_scanned)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_search_response(payload: dict[str, Any]) -> tuple[str, ...]:
    errors: list[str] = []
    if payload.get("schema_version") != WEB_SCHEMA:
        errors.append("SCHEMA_VERSION_INVALID")
    if payload.get("data_source_status") != "USER_RECORDED_ONLY":
        errors.append("DATA_SOURCE_STATUS_INVALID")
    if not isinstance(payload.get("items"), list):
        return tuple(errors + ["ITEMS_NOT_ARRAY"])
    required = {
        "id",
        "title",
        "variant_signature",
        "last_observed_price_twd",
        "last_observed_at",
        "observed_days",
        "shipping_status",
        "price_basis",
        "thumbnail",
    }
    for index, item in enumerate(payload["items"]):
        prefix = f"ITEM_{index}"
        if not isinstance(item, dict):
            errors.append(f"{prefix}_NOT_OBJECT")
            continue
        missing = required - set(item)
        errors.extend(f"{prefix}_MISSING_{name.upper()}" for name in sorted(missing))
        price = item.get("last_observed_price_twd")
        if price is not None and (not _is_int(price) or price < 0):
            errors.append(f"{prefix}_PRICE_INVALID")
        if price == 0 and item.get("zero_price_provenance") != "VERIFIED_COMPLETE_COST":
            errors.append(f"{prefix}_FORGED_OR_UNPROVEN_ZERO")
        if item.get("shipping_status") not in {"UNKNOWN", "FREE", "PAID", "INCLUDED"}:
            errors.append(f"{prefix}_SHIPPING_STATUS_INVALID")
        if item.get("price_basis") != "GENERAL_OBSERVED":
            errors.append(f"{prefix}_PRICE_BASIS_INVALID")
        if item.get("source_type") == "SYNTHETIC":
            errors.append(f"{prefix}_SYNTHETIC_LEAK")
        if not item.get("variant_signature"):
            errors.append(f"{prefix}_VARIANT_SIGNATURE_MISSING")
    return tuple(errors)


def validate_product_detail(payload: dict[str, Any], *, expected_product_id: str) -> tuple[str, ...]:
    errors: list[str] = []
    if payload.get("schema_version") != WEB_SCHEMA:
        errors.append("SCHEMA_VERSION_INVALID")
    product = payload.get("product")
    if not isinstance(product, dict) or product.get("id") != expected_product_id:
        errors.append("PRODUCT_ID_MISMATCH")
        return tuple(errors)
    product_basis = product.get("price_basis")
    offers = payload.get("offers")
    if not isinstance(offers, list) or not offers:
        errors.append("OFFERS_MISSING")
    else:
        seen_skus: set[str] = set()
        for offer in offers:
            sku = offer.get("sku_id") if isinstance(offer, dict) else None
            if not sku:
                errors.append("OFFER_SKU_MISSING")
            elif sku in seen_skus:
                errors.append("DUPLICATE_SKU_OFFER")
            else:
                seen_skus.add(sku)
            if not isinstance(offer, dict) or offer.get("price_basis") != product_basis:
                errors.append("SKU_PRICE_BASIS_MISMATCH")
    history = payload.get("history")
    if not isinstance(history, list):
        errors.append("HISTORY_NOT_ARRAY")
    else:
        for row in history:
            if not isinstance(row, dict) or row.get("source_type") not in PUBLIC_SOURCE_TYPES:
                errors.append("FIXTURE_OR_UNAPPROVED_SOURCE_LEAK")
            if not _is_int(row.get("price_twd")) or row.get("price_twd", -1) < 0:
                errors.append("HISTORY_PRICE_INVALID")
            if isinstance(row, dict) and row.get("sku_id") not in (None, product.get("sku_id")):
                errors.append("HISTORY_SKU_MISMATCH")
            if isinstance(row, dict) and row.get("price_basis") not in (None, product_basis):
                errors.append("HISTORY_PRICE_BASIS_MISMATCH")
    if "上市以來最低價" in json.dumps(payload, ensure_ascii=False):
        errors.append("UNBOUNDED_LOWEST_PRICE_CLAIM")
    return tuple(dict.fromkeys(errors))


def _validate_click_url(url: str, allowed_hosts: frozenset[str]) -> tuple[str, ...]:
    errors: list[str] = []
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https":
        errors.append("AFFILIATE_URL_NOT_HTTPS")
    if host not in {item.casefold() for item in allowed_hosts}:
        errors.append("AFFILIATE_HOST_NOT_ALLOWED")
    if parsed.username or parsed.password:
        errors.append("AFFILIATE_URL_USERINFO_DENIED")
    try:
        port = parsed.port
    except ValueError:
        errors.append("AFFILIATE_URL_PORT_INVALID")
    else:
        if port not in (None, 443):
            errors.append("AFFILIATE_URL_PORT_DENIED")
    query_keys = {key.casefold() for key in parse_qs(parsed.query, keep_blank_values=True)}
    if query_keys & REDIRECT_QUERY_KEYS:
        errors.append("OPEN_REDIRECT_PARAMETER_DENIED")
    return tuple(errors)


def validate_affiliate(payload: dict[str, Any], policy: AffiliatePolicy) -> tuple[str, ...]:
    errors: list[str] = []
    state = payload.get("state")
    if state not in AFFILIATE_STATES:
        return ("AFFILIATE_STATE_INVALID",)
    click_url = payload.get("click_url")
    verified_match = payload.get("verified_product_match") is True
    if state in NONCLICKABLE_AFFILIATE_STATES:
        if click_url is not None:
            errors.append("NONVERIFIED_STATE_HAS_CLICK_URL")
        if verified_match:
            errors.append("NONVERIFIED_STATE_CLAIMS_MATCH")
        return tuple(errors)
    if payload.get("provider_status") != "VERIFIED":
        errors.append("AFFILIATE_PROVIDER_NOT_VERIFIED")
    if not _valid_evidence_sha256(policy.official_host_evidence_sha256):
        errors.append("OFFICIAL_HOST_EVIDENCE_MISSING")
    if not _valid_evidence_sha256(policy.exact_variant_evidence_sha256):
        errors.append("EXACT_VARIANT_EVIDENCE_MISSING")
    if payload.get("provider_market") != "TW":
        errors.append("AFFILIATE_MARKET_NOT_TW")
    if not isinstance(payload.get("provider_id"), str) or not payload.get("provider_id"):
        errors.append("AFFILIATE_PROVIDER_ID_MISSING")
    if payload.get("disclosure_present") is not True:
        errors.append("AFFILIATE_DISCLOSURE_MISSING")
    if payload.get("link_source") != "OFFICIAL_PROVIDER":
        errors.append("AFFILIATE_LINK_SOURCE_UNVERIFIED")
    if payload.get("bound_product_id") != policy.expected_product_id:
        errors.append("AFFILIATE_PRODUCT_MISMATCH")
    if payload.get("bound_sku_id") != policy.expected_sku_id:
        errors.append("AFFILIATE_SKU_MISMATCH")
    if not verified_match:
        errors.append("AFFILIATE_PRODUCT_MATCH_FALSE")
    raw_expiry = payload.get("expires_at")
    try:
        expires_at = datetime.fromisoformat(raw_expiry) if isinstance(raw_expiry, str) else None
    except ValueError:
        expires_at = None
    if expires_at is None or expires_at.tzinfo is None or expires_at.utcoffset() is None:
        errors.append("AFFILIATE_EXPIRY_INVALID")
    elif policy.evaluated_at >= expires_at:
        errors.append("AFFILIATE_LINK_EXPIRED")
    raw_verified = payload.get("verified_at")
    try:
        verified_at = datetime.fromisoformat(raw_verified) if isinstance(raw_verified, str) else None
    except ValueError:
        verified_at = None
    if verified_at is None or verified_at.tzinfo is None or verified_at.utcoffset() is None:
        errors.append("AFFILIATE_VERIFIED_AT_INVALID")
    elif policy.evaluated_at < verified_at:
        errors.append("AFFILIATE_CLOCK_ROLLBACK")
    if not isinstance(click_url, str) or not click_url:
        errors.append("AFFILIATE_CLICK_URL_MISSING")
    else:
        errors.extend(_validate_click_url(click_url, policy.allowed_hosts))
    return tuple(dict.fromkeys(errors))


def open_readonly_database(path: str | Path, *, allowed_root: str | Path) -> sqlite3.Connection:
    root = Path(allowed_root).resolve(strict=True)
    raw_target = Path(path)
    if raw_target.is_symlink():
        raise ValueError("SQLITE_PATH_SYMLINK_DENIED")
    target = raw_target.resolve(strict=True)
    if not _inside(root, target):
        raise ValueError("SQLITE_PATH_OUTSIDE_ALLOWED_ROOT")
    if not target.is_file():
        raise ValueError("SQLITE_PATH_NOT_REGULAR_FILE")
    if target.suffix.casefold() not in {".sqlite", ".sqlite3", ".db"}:
        raise ValueError("SQLITE_SUFFIX_INVALID")
    uri = f"file:{quote(str(target), safe='/:')}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def execute_readonly(
    connection: sqlite3.Connection,
    sql: str,
    parameters: Sequence[Any] = (),
    *,
    max_rows: int = 1000,
) -> list[dict[str, Any]]:
    stripped = sql.strip()
    if not stripped.casefold().startswith("select "):
        raise ValueError("SQL_NOT_SELECT")
    if ";" in stripped or "--" in stripped or "/*" in stripped or FORBIDDEN_SQL_RE.search(stripped):
        raise ValueError("SQL_UNSAFE_TOKEN")
    if not 1 <= max_rows <= 10_000:
        raise ValueError("SQL_ROW_LIMIT_INVALID")
    cursor = connection.execute(stripped, tuple(parameters))
    rows = cursor.fetchmany(max_rows + 1)
    if len(rows) > max_rows:
        raise ValueError("SQL_ROW_LIMIT_EXCEEDED")
    return [dict(row) for row in rows]
