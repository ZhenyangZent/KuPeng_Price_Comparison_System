"""Offline, fail-closed Taiwan affiliate provider shell."""

from .contract import ContractError, ProviderContract, load_provider_contract
from .models import AffiliateResponse, ProductIdentity
from .policy import (
    AffiliateCandidate,
    CandidatePolicy,
    REQUIRED_VERIFIED_CAPABILITIES,
    validate_candidate,
)
from .provider import AffiliateProvider, PendingTwAffiliateProvider

__all__ = [
    "AffiliateCandidate",
    "AffiliateProvider",
    "AffiliateResponse",
    "CandidatePolicy",
    "ContractError",
    "PendingTwAffiliateProvider",
    "ProductIdentity",
    "ProviderContract",
    "REQUIRED_VERIFIED_CAPABILITIES",
    "load_provider_contract",
    "validate_candidate",
]
