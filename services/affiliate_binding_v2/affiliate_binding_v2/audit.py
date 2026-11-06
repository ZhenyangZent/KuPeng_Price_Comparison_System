"""Build a query-redacted, identity-pseudonymized binding audit summary."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from .models import CanonicalIdentity, ProviderDecision


def _digest(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_audit_summary(
    *,
    identity: CanonicalIdentity | None,
    provider: ProviderDecision | None,
    state: str,
    ui_cta_state: str,
    reasons: tuple[str, ...],
    evaluated_at: datetime,
) -> dict[str, Any]:
    url_meta: dict[str, Any] = {
        "present": bool(provider and provider.click_url),
        "scheme": None,
        "host": None,
        "path_sha256": None,
        "query_redacted": False,
        "parse_error": False,
    }
    if provider and provider.click_url:
        try:
            parsed = urlsplit(provider.click_url)
            url_meta.update(
                {
                    "scheme": parsed.scheme,
                    "host": parsed.hostname,
                    "path_sha256": _digest(parsed.path),
                    "query_redacted": bool(parsed.query),
                }
            )
        except ValueError:
            url_meta["parse_error"] = True
    return {
        "schema": "CDH-AFFILIATE-BINDING-AUDIT-V1",
        "evaluated_at": evaluated_at.isoformat(),
        "decision_state": state,
        "ui_cta_state": ui_cta_state,
        "reason_codes": list(reasons),
        "canonical_product_id_sha256": _digest(identity.canonical_product_id if identity else None),
        "provider_product_id_sha256": _digest(identity.provider_product_id if identity else None),
        "variant_id_sha256": _digest(identity.variant_id if identity else None),
        "seller_id_sha256": _digest(identity.seller_id if identity else None),
        "url": url_meta,
        "evidence_id_count": len(provider.evidence_ids) if provider else 0,
    }
