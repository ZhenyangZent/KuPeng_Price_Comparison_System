"""Offline, default-disabled affiliate gateway V3."""

from .cache import VerifiedLinkCache
from .contracts import ContractError, load_c04_readiness, parse_b06_affiliate_response
from .gateway import AffiliateGatewayV3
from .models import (
    AdapterResult,
    AuthoritySnapshot,
    CapabilityState,
    ExactIdentity,
    GatewayDecision,
    LinkRequest,
)
from .provider import DisabledProviderAdapter, ProviderAdapter, SyntheticMockProviderAdapter
from .sink import MockSink

__all__ = [
    "AdapterResult",
    "AffiliateGatewayV3",
    "AuthoritySnapshot",
    "CapabilityState",
    "ContractError",
    "DisabledProviderAdapter",
    "ExactIdentity",
    "GatewayDecision",
    "LinkRequest",
    "MockSink",
    "ProviderAdapter",
    "SyntheticMockProviderAdapter",
    "VerifiedLinkCache",
    "load_c04_readiness",
    "parse_b06_affiliate_response",
]
