"""F06 strict adapter and fail-closed affiliate coupon gate."""

from .adapter import B10WireError, adapt_detail_envelope, adapt_search_envelope
from .audit import MockSink
from .gate import AffiliateCouponGateV6
from .models import (
    AffiliateTrustInput,
    CombinedDecision,
    CouponPriceSnapshot,
    GateRequest,
    RuntimeCeiling,
    SeriesIdentity,
)

__all__ = [
    "AffiliateCouponGateV6", "AffiliateTrustInput", "B10WireError", "CombinedDecision",
    "CouponPriceSnapshot", "GateRequest", "MockSink", "RuntimeCeiling", "SeriesIdentity",
    "adapt_detail_envelope", "adapt_search_envelope",
]
