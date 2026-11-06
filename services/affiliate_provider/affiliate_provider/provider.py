"""Production-safe provider interface and the current Taiwan implementation."""

from __future__ import annotations

from typing import Protocol

from .contract import ProviderContract
from .models import AffiliateResponse, ProductIdentity


FALSE_GATES = {
    "tw_capability_verified": False,
    "provider_account_eligible": False,
    "host_allowlist_verified": False,
    "exact_match_verified": False,
    "ttl_and_revocation_verified": False,
    "disclosure_verified_for_tw": False,
    "user_intent_verified": False,
}


class AffiliateProvider(Protocol):
    def resolve(self, identity: ProductIdentity, *, user_initiated: bool) -> dict[str, object]:
        """Return an affiliate DTO without opening any URL."""


class PendingTwAffiliateProvider:
    """F01 provider shell.  It cannot produce or fall back to a click URL."""

    def __init__(self, contract: ProviderContract) -> None:
        if contract.market != "TW" or contract.state != "PENDING_OFFICIAL_DOCS":
            raise ValueError("PendingTwAffiliateProvider requires the controlled pending Taiwan contract")
        self._contract = contract

    def resolve(self, identity: ProductIdentity, *, user_initiated: bool) -> dict[str, object]:
        identity_errors = identity.errors()
        reasons = ["PROVIDER_PENDING_OFFICIAL_DOCS"]
        reasons.extend(identity_errors)
        if not user_initiated:
            reasons.append("USER_INITIATED_CLICK_REQUIRED")
        response = AffiliateResponse(
            state=self._contract.state,
            click_url=None,
            verified_product_match=False,
            provider_status=self._contract.state,
            link_source=None,
            provider_id=self._contract.provider_id,
            market=self._contract.market,
            contract_as_of=self._contract.as_of,
            bound_product_id=identity.product_id if not identity_errors else None,
            bound_variant_id=identity.variant_id if not identity_errors else None,
            bound_seller_id=identity.seller_id if not identity_errors else None,
            bound_sku_id=identity.variant_id if not identity_errors else None,
            generated_at=None,
            expires_at=None,
            disclosure_text=None,
            cta_enabled=False,
            error_code=self._contract.state,
            evidence_ids=self._contract.evidence_ids,
            rejection_reasons=tuple(reasons),
            gates=dict(FALSE_GATES),
        )
        return response.to_dict()
