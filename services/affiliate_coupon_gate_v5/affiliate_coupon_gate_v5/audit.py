"""Redacted F05 audit sink."""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime
from typing import Any

from .models import SeriesIdentity


def _hash(value: str | None) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def build_event(
    *,
    identity: SeriesIdentity,
    source_id: str,
    coupon_id: str,
    eligibility_profile: str | None,
    affiliate_envelope_id: str | None,
    display_price_twd: int | None,
    display_basis: str,
    coupon_applied: bool,
    cta_enabled: bool,
    reasons: tuple[str, ...],
    evaluated_at: datetime,
) -> dict[str, Any]:
    return {
        "schema": "CDH-AFFILIATE-COUPON-GATE-AUDIT-V1",
        "evaluated_at": evaluated_at.isoformat(),
        "binding_sha256": identity.binding_sha256,
        "source_id_sha256": _hash(source_id),
        "coupon_id_sha256": _hash(coupon_id),
        "eligibility_profile_sha256": _hash(eligibility_profile),
        "affiliate_envelope_id": affiliate_envelope_id,
        "display_price_twd": display_price_twd,
        "display_basis": display_basis,
        "coupon_applied": coupon_applied,
        "cta_enabled": cta_enabled,
        "reason_codes": list(reasons),
    }


class MockSink:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self._events.append(copy.deepcopy(event))

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(self._events))
