"""Read-only F09 adapter that can never create a clickable destination."""

from __future__ import annotations

from datetime import datetime

from .contract import parse_account_evidence, parse_product, parse_reference, parse_variant_evidence
from .models import InertAction, InertClickIntent, ProductIdentity
from .release_gate import A11_SHA256, B11_SHA256


def _base_identity_equal(left: ProductIdentity, right: ProductIdentity) -> bool:
    return (
        left.market,
        left.platform,
        left.product_id,
        left.sku_id,
        left.seller_id,
        left.condition,
        left.package_signature,
    ) == (
        right.market,
        right.platform,
        right.product_id,
        right.sku_id,
        right.seller_id,
        right.condition,
        right.package_signature,
    )


class InertClickIntentAdapterF09:
    """Map exact synthetic price identity to permanently disabled actions."""

    def build(
        self,
        *,
        a11_product: object,
        b11_product: object,
        a11_release_sha256: str,
        b11_release_sha256: str,
        now: datetime,
        variant_evidence: object | None = None,
        account_evidence: object | None = None,
        general_product_reference: object | None = None,
        affiliate_reference: object | None = None,
    ) -> InertClickIntent:
        if a11_release_sha256 != A11_SHA256 or b11_release_sha256 != B11_SHA256:
            from .contract import ContractError

            raise ContractError("INPUT_RELEASE_SHA256_MISMATCH", "exact pinned A11 and B11 release SHA-256 values are required")
        a11 = parse_product(a11_product)
        b11 = parse_product(b11_product)
        if (
            a11.series_key != b11.series_key
            or not _base_identity_equal(a11.identity, b11.identity)
            or a11.coupon_binding_sha256 != b11.coupon_binding_sha256
            or a11.price_binding_sha256 != b11.price_binding_sha256
            or a11.source_binding_sha256 != b11.source_binding_sha256
        ):
            from .contract import ContractError

            raise ContractError("A11_B11_SNAPSHOT_MISMATCH", "identity, coupon, price and source snapshots must match")

        reasons: list[str] = []
        identity = b11.identity
        if variant_evidence is None:
            reasons.append("VARIANT_ID_REQUIRED")
        else:
            variant = parse_variant_evidence(variant_evidence)
            if not _base_identity_equal(identity, variant.identity):
                reasons.append("VARIANT_EVIDENCE_IDENTITY_MISMATCH")
            elif variant.revoked_at is not None:
                reasons.append("VARIANT_EVIDENCE_REVOKED")
            elif not (variant.issued_at <= now < variant.expires_at):
                reasons.append("VARIANT_EVIDENCE_EXPIRED_OR_NOT_YET_VALID")
            else:
                identity = variant.identity
            reasons.append("VARIANT_EVIDENCE_FIXTURE_ONLY")

        if b11.coupon_status == "CLAIM_REQUIRED":
            reasons.append("COUPON_CLAIM_REQUIRED")
        if b11.coupon_status != "CONFIRMED_APPLICABLE":
            reasons.append("COUPON_NOT_CONFIRMED_APPLICABLE")
        if b11.coupon_valid_from is not None and now < b11.coupon_valid_from:
            reasons.append("COUPON_NOT_YET_VALID")
        if b11.coupon_valid_until is not None and now >= b11.coupon_valid_until:
            reasons.append("COUPON_EXPIRED")
        if b11.display_price_twd == 0:
            reasons.append("ZERO_DISPLAY_PRICE_NOT_DELIVERED_COST")
        if not b11.source_allowed:
            reasons.append("SOURCE_PERMISSION_BLOCKED")
        if "REVOK" in b11.source_state.upper():
            reasons.append("SOURCE_PERMISSION_REVOKED")
        if "EXPIRED" in b11.source_state.upper():
            reasons.append("SOURCE_PERMISSION_EXPIRED")

        if account_evidence is None:
            reasons.append("OFFICIAL_TW_ACCOUNT_EVIDENCE_REQUIRED")
        else:
            account = parse_account_evidence(account_evidence)
            if account.state != "ACTIVE":
                reasons.append("ACCOUNT_EVIDENCE_DISABLED")
            if account.revoked_at is not None:
                reasons.append("ACCOUNT_EVIDENCE_REVOKED")
            if not (account.issued_at <= now < account.expires_at):
                reasons.append("ACCOUNT_EVIDENCE_EXPIRED_OR_NOT_YET_VALID")
            reasons.append("ACCOUNT_EVIDENCE_FIXTURE_ONLY")

        if general_product_reference is not None:
            reference = parse_reference(general_product_reference)
            if reference.kind != "GENERAL_PRODUCT_PAGE":
                from .contract import ContractError

                raise ContractError("GENERAL_REFERENCE_KIND_MISMATCH", "general product reference required")
            reasons.append("GENERAL_PRODUCT_PAGE_REFERENCE_UNVERIFIED")
        else:
            reasons.append("GENERAL_PRODUCT_PAGE_REFERENCE_ABSENT")
        if affiliate_reference is not None:
            reference = parse_reference(affiliate_reference)
            if reference.kind != "AFFILIATE_CANDIDATE":
                from .contract import ContractError

                raise ContractError("AFFILIATE_REFERENCE_KIND_MISMATCH", "affiliate candidate required")
            reasons.append("AFFILIATE_REFERENCE_UNVERIFIED")
        else:
            reasons.append("AFFILIATE_REFERENCE_ABSENT")

        reasons.extend(("SOURCE_AUTHORIZATION_REQUIRED", "OFFICIAL_TW_AFFILIATE_AUTHORITY_REQUIRED"))
        return InertClickIntent(
            schema_version="CDH-F09-INERT-CLICK-INTENT-1",
            state="SOURCE_AUTHORIZATION_REQUIRED",
            a11_release_sha256=A11_SHA256,
            b11_release_sha256=B11_SHA256,
            identity=identity,
            identity_binding_sha256=identity.binding_sha256,
            coupon_status=b11.coupon_status,
            source_state=b11.source_state,
            general_product_page=InertAction(
                action_kind="GENERAL_PRODUCT_PAGE",
                verification_state="UNVERIFIED_REFERENCE_ONLY",
                enabled=False,
                url=None,
            ),
            affiliate_link=InertAction(
                action_kind="VERIFIED_AFFILIATE_LINK",
                verification_state="OFFICIAL_AUTHORITY_REQUIRED",
                enabled=False,
                url=None,
            ),
            cta_enabled=False,
            click_url=None,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

