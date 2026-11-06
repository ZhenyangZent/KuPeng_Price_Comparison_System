"""F05 coupon-bound affiliate gate; pricing and CTA authority remain independent."""

from .ceiling import CeilingError, load_c06_ceiling
from .gate import AffiliateCouponGateV5
from .models import (
    AffiliateTrustInput,
    CombinedDecision,
    CouponPriceSnapshot,
    GateRequest,
    RuntimeCeiling,
    SeriesIdentity,
)
from .parser import CouponContractError, parse_coupon_snapshot
from .audit import MockSink

__all__ = [
    "AffiliateCouponGateV5",
    "AffiliateTrustInput",
    "CeilingError",
    "CombinedDecision",
    "CouponContractError",
    "CouponPriceSnapshot",
    "GateRequest",
    "MockSink",
    "RuntimeCeiling",
    "SeriesIdentity",
    "load_c06_ceiling",
    "parse_coupon_snapshot",
]
