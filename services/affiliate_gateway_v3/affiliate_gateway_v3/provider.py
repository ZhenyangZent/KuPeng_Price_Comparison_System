"""Provider interface plus offline-only adapters."""

from __future__ import annotations

from typing import Protocol

from .models import AdapterResult, LinkRequest


class ProviderAdapter(Protocol):
    def resolve(self, request: LinkRequest) -> AdapterResult:
        """Resolve without opening the original or destination URL."""


class DisabledProviderAdapter:
    def __init__(self, state: str = "SOURCE_AUTHORIZATION_REQUIRED") -> None:
        self.state = state
        self.call_count = 0

    def resolve(self, request: LinkRequest) -> AdapterResult:
        self.call_count += 1
        return AdapterResult(
            status=self.state,
            provider_id="coupang_tw_partners",
            market="TW",
            official_evidence_ids=frozenset(),
            verified_destination=None,
            generated_at=None,
            expires_at=None,
            bound_provider_product_id=None,
            bound_variant_id=None,
            bound_seller_id=None,
            disclosure_text=None,
            revocation_status="UNKNOWN",
            revocation_event_id=None,
            revocation_checked_at=None,
            generated_by_official_provider=False,
        )


class SyntheticMockProviderAdapter:
    """Deterministic in-memory adapter for `.invalid` tests only."""

    def __init__(self, results: dict[str, AdapterResult], *, failure: Exception | None = None) -> None:
        self._results = dict(results)
        self._failure = failure
        self.call_count = 0

    def resolve(self, request: LinkRequest) -> AdapterResult:
        self.call_count += 1
        if self._failure is not None:
            raise self._failure
        try:
            return self._results[request.identity.cache_key()]
        except KeyError as exc:
            raise LookupError("synthetic provider result missing") from exc
