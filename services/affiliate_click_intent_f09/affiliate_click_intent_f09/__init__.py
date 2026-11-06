"""F09 exact A11/B11 identity adapter with permanently inert actions."""

from .adapter import InertClickIntentAdapterF09
from .contract import ContractError, parse_account_evidence, parse_product, parse_reference, parse_variant_evidence
from .models import InertClickIntent
from .release_gate import A11_SHA256, B11_SHA256, ReleaseGateError, compare_a11_embedded_b11, verify_release

__all__ = [
    "A11_SHA256",
    "B11_SHA256",
    "ContractError",
    "InertClickIntent",
    "InertClickIntentAdapterF09",
    "ReleaseGateError",
    "compare_a11_embedded_b11",
    "parse_account_evidence",
    "parse_product",
    "parse_reference",
    "parse_variant_evidence",
    "verify_release",
]

