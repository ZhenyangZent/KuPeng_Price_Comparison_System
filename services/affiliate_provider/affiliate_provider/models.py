"""Stable DTOs for the offline affiliate provider boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


RESPONSE_SCHEMA_VERSION = "CDH-AFFILIATE-RESPONSE-V1"
MAX_ID_LENGTH = 256


def _identity_error(field: str, value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return f"{field.upper()}_MISSING"
    if value != value.strip():
        return f"{field.upper()}_WHITESPACE"
    if len(value) > MAX_ID_LENGTH:
        return f"{field.upper()}_TOO_LONG"
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        return f"{field.upper()}_CONTROL_CHARACTER"
    return None


@dataclass(frozen=True, slots=True)
class ProductIdentity:
    """The minimum exact identity required before an affiliate CTA can exist."""

    product_id: str
    variant_id: str
    seller_id: str

    def errors(self) -> tuple[str, ...]:
        errors = (
            _identity_error("product_id", self.product_id),
            _identity_error("variant_id", self.variant_id),
            _identity_error("seller_id", self.seller_id),
        )
        return tuple(error for error in errors if error is not None)


@dataclass(frozen=True, slots=True)
class AffiliateResponse:
    """Flattened DTO compatible with the current web security contract."""

    state: str
    click_url: None
    verified_product_match: bool
    provider_status: str
    link_source: None
    provider_id: str
    market: str
    contract_as_of: str
    bound_product_id: str | None
    bound_variant_id: str | None
    bound_seller_id: str | None
    bound_sku_id: str | None
    generated_at: None
    expires_at: None
    disclosure_text: None
    cta_enabled: bool
    error_code: str
    evidence_ids: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    gates: dict[str, bool]
    schema_version: str = RESPONSE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence_ids"] = list(self.evidence_ids)
        value["rejection_reasons"] = list(self.rejection_reasons)
        return value
