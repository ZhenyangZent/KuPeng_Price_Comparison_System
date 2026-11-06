"""Redacted audit events; raw URLs, IDs, claims, signatures and keys are excluded."""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from .models import ExactIdentity


def _hash(value: str | None) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def build_event(
    *,
    identity: ExactIdentity,
    state: str,
    cta_enabled: bool,
    metadata_verified: bool,
    envelope_id: str | None,
    destination: str | None,
    reason_codes: tuple[str, ...],
    evaluated_at: datetime,
) -> dict[str, Any]:
    destination_summary = {"present": bool(destination), "scheme": None, "host": None, "path_sha256": None, "query_redacted": False}
    if destination:
        try:
            parsed = urlsplit(destination)
            destination_summary.update(
                {"scheme": parsed.scheme, "host": parsed.hostname, "path_sha256": _hash(parsed.path), "query_redacted": bool(parsed.query)}
            )
        except ValueError:
            destination_summary["parse_error"] = True
    return {
        "schema": "CDH-AFFILIATE-TRUST-AUDIT-V1",
        "evaluated_at": evaluated_at.isoformat(),
        "state": state,
        "cta_enabled": cta_enabled,
        "metadata_verified": metadata_verified,
        "reason_codes": list(reason_codes),
        "envelope_id": envelope_id,
        "binding_sha256": identity.binding_sha256,
        "canonical_product_id_sha256": _hash(identity.canonical_product_id),
        "sku_id_sha256": _hash(identity.sku_id),
        "seller_id_sha256": _hash(identity.seller_id),
        "original_url_sha256": identity.original_url_sha256,
        "destination": destination_summary,
    }


class MockSink:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self._events.append(copy.deepcopy(event))

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(self._events))
