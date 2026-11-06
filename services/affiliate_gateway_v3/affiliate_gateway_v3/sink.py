"""Sanitized in-memory audit sink used by F03 tests and local integration."""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from .models import AdapterResult, ExactIdentity


def _hash(value: str | None) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def build_event(
    *,
    identity: ExactIdentity | None,
    result: AdapterResult | None,
    state: str,
    cta_enabled: bool,
    reasons: tuple[str, ...],
    evaluated_at: datetime,
    cache_status: str,
) -> dict[str, Any]:
    url = {
        "present": bool(result and result.verified_destination),
        "scheme": None,
        "host": None,
        "path_sha256": None,
        "query_redacted": False,
        "parse_error": False,
    }
    if result and result.verified_destination:
        try:
            parsed = urlsplit(result.verified_destination)
            url.update(
                {
                    "scheme": parsed.scheme,
                    "host": parsed.hostname,
                    "path_sha256": _hash(parsed.path),
                    "query_redacted": bool(parsed.query),
                }
            )
        except ValueError:
            url["parse_error"] = True
    return {
        "schema": "CDH-AFFILIATE-GATEWAY-AUDIT-V1",
        "evaluated_at": evaluated_at.isoformat(),
        "state": state,
        "cta_enabled": cta_enabled,
        "reason_codes": list(reasons),
        "cache_status": cache_status,
        "canonical_product_id_sha256": _hash(identity.canonical_product_id if identity else None),
        "provider_product_id_sha256": _hash(identity.provider_product_id if identity else None),
        "variant_id_sha256": _hash(identity.variant_id if identity else None),
        "seller_id_sha256": _hash(identity.seller_id if identity else None),
        "original_url_sha256": _hash(identity.original_url if identity else None),
        "verified_destination": url,
        "evidence_id_count": len(result.official_evidence_ids) if result else 0,
    }


class MockSink:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self._events.append(copy.deepcopy(event))

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(self._events))
