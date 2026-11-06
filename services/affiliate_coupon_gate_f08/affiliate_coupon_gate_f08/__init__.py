"""F08 non-activating affiliate CTA contract."""

from .contract import (
    ContractError,
    identity_from_b11_product,
    parse_authority,
    parse_coupon_context,
    parse_destination,
    parse_evidence,
    parse_identity,
    parse_intent,
)
from .models import CtaDecision, ProductIdentity
from .release_gate import B11_SHA256, F07_SHA256, ReleaseGateError, verify_release
from .verifier import AffiliateCtaVerifierF08

__all__ = [
    "AffiliateCtaVerifierF08", "B11_SHA256", "ContractError", "CtaDecision", "F07_SHA256",
    "ProductIdentity", "ReleaseGateError", "identity_from_b11_product", "parse_authority", "parse_coupon_context",
    "parse_destination", "parse_evidence", "parse_identity", "parse_intent", "verify_release",
]
