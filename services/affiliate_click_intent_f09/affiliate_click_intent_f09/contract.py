"""Strict synthetic A11/B11 and review-evidence parsers for F09."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, unquote, urlsplit

from .models import AccountEvidence, ProductIdentity, ProductSnapshot, ReferenceCandidate, VariantEvidence


PRODUCT_FIELDS = frozenset(
    {
        "series_key", "title", "series_identity", "data_classification", "source_id", "observed_at",
        "base_price_twd", "before_coupon_price_twd", "coupon", "confirmed_coupon_price_twd",
        "possible_coupon_price_twd", "display_price_twd", "display_basis", "minimum_purchase_quantity",
        "minimum_item_spend_twd", "shipping_status", "required_total_twd", "source_permission", "quality_flags",
    }
)
IDENTITY_FIELDS = frozenset({"platform", "product_id", "sku_id", "seller_id", "condition", "package_signature"})
COUPON_FIELDS = frozenset(
    {
        "coupon_id", "status", "discount_twd", "discount_scope", "already_included_in_base",
        "eligibility_profile", "valid_from", "valid_until", "scope_evidence",
        "pre_coupon_comparison_source", "evaluation_reasons",
    }
)
SOURCE_FIELDS = frozenset({"allowed", "state", "reason"})
VARIANT_FIELDS = frozenset(
    {
        "schema_version", "classification", "market", "platform", "product_id", "sku_id", "variant_id",
        "seller_id", "condition", "package_signature", "issued_at", "expires_at", "revoked_at",
    }
)
ACCOUNT_FIELDS = frozenset(
    {"schema_version", "classification", "state", "account_reference_sha256", "issued_at", "expires_at", "revoked_at"}
)
REFERENCE_FIELDS = frozenset({"kind", "url"})
COUPON_STATUSES = frozenset({"CONFIRMED_APPLICABLE", "CLAIM_REQUIRED", "UNVERIFIED", "INELIGIBLE", "EXPIRED", "UNKNOWN", "NONE"})
DISPLAY_BASES = frozenset({"CONFIRMED_COUPON", "BASE_PRICE", "PRICE_UNAVAILABLE"})
DISCOUNT_SCOPES = frozenset({"UNIT", "ORDER_TOTAL", "NONE"})
REDIRECT_KEYS = frozenset({"redirect", "redirect_url", "url", "next", "return", "return_url", "continue", "destination", "target", "callback"})
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _exact(value: object, fields: frozenset[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractError(code, f"exact fields required: {sorted(fields)}")
    return value


def _text(value: object, name: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 256:
        raise ContractError(f"{name.upper()}_INVALID", f"{name} must be a bounded non-empty string")
    if "://" in value or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ContractError(f"{name.upper()}_INVALID", f"{name} contains URL or control data")
    return value


def _integer(value: object, name: str, *, nullable: bool = False) -> int | None:
    if nullable and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{name.upper()}_INVALID", f"{name} must be a non-negative integer")
    return value


def _time(value: object, name: str, *, nullable: bool = False) -> datetime | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContractError(f"{name.upper()}_INVALID", f"{name} must use canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError(f"{name.upper()}_INVALID", f"{name} must be ISO-8601") from exc
    return parsed.astimezone(timezone.utc)


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ContractError(f"{name.upper()}_INVALID", f"{name} must be lowercase SHA-256")
    return value


def _binding(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identity(raw: object, *, variant_id: str | None = None) -> ProductIdentity:
    data = _exact(raw, IDENTITY_FIELDS, "IDENTITY_STRUCTURE_INVALID")
    identity = ProductIdentity(
        market="TW",
        platform=_text(data["platform"], "platform") or "",
        product_id=_text(data["product_id"], "product_id") or "",
        sku_id=_text(data["sku_id"], "sku_id") or "",
        variant_id=variant_id,
        seller_id=_text(data["seller_id"], "seller_id") or "",
        condition=_text(data["condition"], "condition") or "",
        package_signature=_text(data["package_signature"], "package_signature") or "",
    )
    if identity.platform != "COUPANG_TW":
        raise ContractError("PLATFORM_INVALID", "COUPANG_TW required")
    return identity


def parse_product(value: object) -> ProductSnapshot:
    data = _exact(value, PRODUCT_FIELDS, "PRODUCT_STRUCTURE_INVALID")
    if data["data_classification"] != "SYNTHETIC_FIXTURE":
        raise ContractError("DATA_CLASSIFICATION_INVALID", "synthetic A11/B11 input required")
    coupon = _exact(data["coupon"], COUPON_FIELDS, "COUPON_STRUCTURE_INVALID")
    source = _exact(data["source_permission"], SOURCE_FIELDS, "SOURCE_STRUCTURE_INVALID")
    if coupon["status"] not in COUPON_STATUSES:
        raise ContractError("COUPON_STATUS_INVALID", "unknown coupon status")
    if coupon["discount_scope"] not in DISCOUNT_SCOPES:
        raise ContractError("COUPON_DISCOUNT_SCOPE_INVALID", "unknown discount scope")
    if not isinstance(coupon["already_included_in_base"], bool):
        raise ContractError("COUPON_ALREADY_INCLUDED_INVALID", "already_included_in_base must be boolean")
    _text(coupon["coupon_id"], "coupon_id", nullable=True)
    _integer(coupon["discount_twd"], "discount_twd", nullable=True)
    _text(coupon["eligibility_profile"], "eligibility_profile", nullable=True)
    _time(coupon["valid_from"], "coupon_valid_from", nullable=True)
    _time(coupon["valid_until"], "coupon_valid_until", nullable=True)
    _text(coupon["scope_evidence"], "scope_evidence", nullable=True)
    _text(coupon["pre_coupon_comparison_source"], "pre_coupon_comparison_source", nullable=True)
    reasons = coupon["evaluation_reasons"]
    if not isinstance(reasons, list) or any(not isinstance(item, str) or not item for item in reasons) or len(reasons) != len(set(reasons)):
        raise ContractError("COUPON_EVALUATION_REASONS_INVALID", "coupon reasons must be unique non-empty strings")
    if data["display_basis"] not in DISPLAY_BASES:
        raise ContractError("DISPLAY_BASIS_INVALID", "unknown display basis")
    if not isinstance(source["allowed"], bool):
        raise ContractError("SOURCE_ALLOWED_INVALID", "source allowed must be boolean")
    if not isinstance(data["quality_flags"], list) or any(not isinstance(item, str) for item in data["quality_flags"]) or len(data["quality_flags"]) != len(set(data["quality_flags"])):
        raise ContractError("QUALITY_FLAGS_INVALID", "quality flags must be strings")
    _text(data["title"], "title")
    _text(data["source_id"], "source_id", nullable=True)
    _time(data["observed_at"], "observed_at", nullable=True)
    for field in (
        "base_price_twd", "before_coupon_price_twd", "confirmed_coupon_price_twd", "possible_coupon_price_twd",
        "display_price_twd", "minimum_item_spend_twd", "required_total_twd",
    ):
        _integer(data[field], field, nullable=True)
    _text(data["shipping_status"], "shipping_status")
    quantity = _integer(data["minimum_purchase_quantity"], "minimum_purchase_quantity")
    if quantity is None or quantity < 1:
        raise ContractError("MINIMUM_PURCHASE_QUANTITY_INVALID", "minimum quantity must be at least one")
    return ProductSnapshot(
        series_key=_text(data["series_key"], "series_key") or "",
        identity=_identity(data["series_identity"]),
        coupon_id=_text(coupon["coupon_id"], "coupon_id", nullable=True),
        coupon_status=str(coupon["status"]),
        coupon_valid_from=_time(coupon["valid_from"], "coupon_valid_from", nullable=True),
        coupon_valid_until=_time(coupon["valid_until"], "coupon_valid_until", nullable=True),
        base_price_twd=_integer(data["base_price_twd"], "base_price_twd", nullable=True),
        display_price_twd=_integer(data["display_price_twd"], "display_price_twd", nullable=True),
        display_basis=str(data["display_basis"]),
        source_allowed=source["allowed"],
        source_state=_text(source["state"], "source_state") or "",
        source_reason=_text(source["reason"], "source_reason") or "",
        coupon_binding_sha256=_binding(coupon),
        price_binding_sha256=_binding(
            {
                field: data[field]
                for field in (
                    "base_price_twd", "before_coupon_price_twd", "confirmed_coupon_price_twd",
                    "possible_coupon_price_twd", "display_price_twd", "display_basis",
                    "minimum_purchase_quantity", "minimum_item_spend_twd", "shipping_status", "required_total_twd",
                )
            }
        ),
        source_binding_sha256=_binding(source),
    )


def parse_variant_evidence(value: object) -> VariantEvidence:
    data = _exact(value, VARIANT_FIELDS, "VARIANT_EVIDENCE_STRUCTURE_INVALID")
    if data["schema_version"] != "CDH-F09-VARIANT-EVIDENCE-1" or data["classification"] != "CONTRACT_FIXTURE_TEST_ONLY":
        raise ContractError("VARIANT_EVIDENCE_CLASSIFICATION_INVALID", "test-only F09 evidence required")
    market = _text(data["market"], "market")
    platform = _text(data["platform"], "platform")
    if market != "TW" or platform != "COUPANG_TW":
        raise ContractError("VARIANT_EVIDENCE_MARKET_INVALID", "TW / COUPANG_TW required")
    identity = ProductIdentity(
        market="TW",
        platform="COUPANG_TW",
        product_id=_text(data["product_id"], "product_id") or "",
        sku_id=_text(data["sku_id"], "sku_id") or "",
        variant_id=_text(data["variant_id"], "variant_id"),
        seller_id=_text(data["seller_id"], "seller_id") or "",
        condition=_text(data["condition"], "condition") or "",
        package_signature=_text(data["package_signature"], "package_signature") or "",
    )
    return VariantEvidence(
        classification=str(data["classification"]), identity=identity,
        issued_at=_time(data["issued_at"], "issued_at"), expires_at=_time(data["expires_at"], "expires_at"),
        revoked_at=_time(data["revoked_at"], "revoked_at", nullable=True),
    )


def parse_account_evidence(value: object) -> AccountEvidence:
    data = _exact(value, ACCOUNT_FIELDS, "ACCOUNT_EVIDENCE_STRUCTURE_INVALID")
    if data["schema_version"] != "CDH-F09-ACCOUNT-EVIDENCE-1" or data["classification"] != "CONTRACT_FIXTURE_TEST_ONLY":
        raise ContractError("ACCOUNT_EVIDENCE_CLASSIFICATION_INVALID", "test-only F09 evidence required")
    state = _text(data["state"], "account_state")
    if state not in {"ACTIVE", "DISABLED"}:
        raise ContractError("ACCOUNT_STATE_INVALID", "ACTIVE or DISABLED required")
    return AccountEvidence(
        classification=str(data["classification"]), state=state,
        account_reference_sha256=_sha(data["account_reference_sha256"], "account_reference_sha256"),
        issued_at=_time(data["issued_at"], "issued_at"), expires_at=_time(data["expires_at"], "expires_at"),
        revoked_at=_time(data["revoked_at"], "revoked_at", nullable=True),
    )


def _host(value: str) -> str:
    if not value or value != value.lower() or value != value.strip() or len(value) > 253:
        raise ContractError("HOST_INVALID", "host must be bounded lowercase ASCII")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ContractError("UNICODE_HOST_REJECTED", "Unicode hostnames are rejected") from exc
    if any(label.startswith("xn--") for label in value.split(".")):
        raise ContractError("PUNYCODE_HOST_REJECTED", "punycode hostnames are rejected")
    if "*" in value or value.startswith(".") or value.endswith(".") or ".." in value:
        raise ContractError("HOST_INVALID", "wildcard or malformed host rejected")
    if not value.endswith(".invalid"):
        raise ContractError("NON_SYNTHETIC_HOST_REJECTED", "F09 accepts synthetic .invalid references only")
    return value


def parse_reference(value: object) -> ReferenceCandidate:
    data = _exact(value, REFERENCE_FIELDS, "REFERENCE_STRUCTURE_INVALID")
    kind = data["kind"]
    if kind not in {"GENERAL_PRODUCT_PAGE", "AFFILIATE_CANDIDATE"}:
        raise ContractError("REFERENCE_KIND_INVALID", "reference kind is invalid")
    url = data["url"]
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise ContractError("REFERENCE_URL_INVALID", "bounded URL required")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ContractError("REFERENCE_URL_INVALID", "HTTPS URL without credentials or custom port required")
    host = _host(parsed.hostname)
    if parsed.fragment:
        raise ContractError("REFERENCE_FRAGMENT_REJECTED", "fragments are rejected")
    raw_path = parsed.path or "/"
    if unquote(raw_path) != raw_path or "\\" in raw_path or ".." in raw_path or "//" in raw_path:
        raise ContractError("REFERENCE_PATH_AMBIGUOUS", "ambiguous paths are rejected")
    keys = [key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)]
    if len(keys) != len(set(keys)):
        raise ContractError("REFERENCE_QUERY_DUPLICATE", "duplicate query keys are rejected")
    if set(keys) & REDIRECT_KEYS:
        raise ContractError("OPEN_REDIRECT_PARAMETER_REJECTED", "redirect-like parameters are rejected")
    return ReferenceCandidate(kind=str(kind), host=host)

