"""F04 backend-authenticated affiliate trust envelope candidate."""

from .authority import AuthorityError, load_c05_authority
from .bridge import BridgeError, build_candidate_sidecar, preserve_v2_affiliate
from .envelope import EnvelopeError, EnvelopeKey, TrustEnvelopeCodec
from .gateway import AffiliateTrustGatewayV4
from .models import (
    AuthoritySnapshot,
    CapabilityEvidence,
    ExactIdentity,
    LinkRequest,
    TrustClaims,
    TrustDecision,
)
from .replay import InMemoryReplayGuard
from .audit import MockSink

__all__ = [
    "AffiliateTrustGatewayV4",
    "AuthorityError",
    "AuthoritySnapshot",
    "BridgeError",
    "CapabilityEvidence",
    "EnvelopeError",
    "EnvelopeKey",
    "ExactIdentity",
    "InMemoryReplayGuard",
    "LinkRequest",
    "MockSink",
    "TrustClaims",
    "TrustDecision",
    "TrustEnvelopeCodec",
    "build_candidate_sidecar",
    "load_c05_authority",
    "preserve_v2_affiliate",
]
