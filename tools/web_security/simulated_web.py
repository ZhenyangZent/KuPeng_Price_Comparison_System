from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlencode

from .audit import AffiliatePolicy, validate_affiliate, validate_search_response


def build_search_path(term: str, *, page: int = 1, limit: int = 20) -> str:
    if not 1 <= page:
        raise ValueError("page must be positive")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be 1..100")
    return "/api/v1/products?" + urlencode({"q": term, "page": page, "limit": limit})


def render_title(title: str) -> str:
    return f'<span class="product-title">{html.escape(title, quote=True)}</span>'


def render_affiliate_cta(payload: dict[str, Any], policy: AffiliatePolicy) -> str:
    errors = validate_affiliate(payload, policy)
    if payload.get("state") != "VERIFIED" or errors:
        return '<button type="button" disabled>推薦連結暫不可用</button>'
    href = html.escape(str(payload["click_url"]), quote=True)
    return (
        f'<a class="affiliate-cta" href="{href}" target="_blank" '
        'rel="noopener noreferrer sponsored">前往官方商品頁</a>'
    )


@dataclass(frozen=True, slots=True)
class SimulatedProductService:
    items: tuple[dict[str, Any], ...]

    @classmethod
    def from_items(cls, items: Iterable[dict[str, Any]]) -> "SimulatedProductService":
        return cls(tuple(dict(item) for item in items))

    def search(self, term: str, *, page: int = 1, limit: int = 20) -> dict[str, Any]:
        lowered = term.casefold()
        public = [
            dict(item)
            for item in self.items
            if item.get("source_type") != "SYNTHETIC"
            and lowered in str(item.get("title", "")).casefold()
        ]
        offset = (page - 1) * limit
        payload = {
            "schema_version": "CDH-WEB-CONTRACT-V1",
            "items": public[offset : offset + limit],
            "page": page,
            "limit": limit,
            "total": len(public),
            "data_source_status": "USER_RECORDED_ONLY",
        }
        errors = validate_search_response(payload)
        if errors:
            raise ValueError("SIMULATED_FIXTURE_INVALID:" + ",".join(errors))
        return payload
