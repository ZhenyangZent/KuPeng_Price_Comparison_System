"""Pure read-only binding between B06 V2, C03 evidence, and F01 provider state."""

from .binding import AffiliateBindingV2
from .contracts import (
    ContractError,
    load_c03_capability_snapshot,
    load_f01_provider_snapshot,
    parse_b06_affiliate_response,
)
from .models import (
    B06AffiliateResponse,
    BindingOutcome,
    CanonicalIdentity,
    CapabilitySnapshot,
    ProviderDecision,
)

__all__ = [
    "AffiliateBindingV2",
    "B06AffiliateResponse",
    "BindingOutcome",
    "CanonicalIdentity",
    "CapabilitySnapshot",
    "ContractError",
    "ProviderDecision",
    "load_c03_capability_snapshot",
    "load_f01_provider_snapshot",
    "parse_b06_affiliate_response",
]
