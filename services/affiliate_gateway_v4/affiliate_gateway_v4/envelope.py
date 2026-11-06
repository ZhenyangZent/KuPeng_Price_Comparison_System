"""HMAC-authenticated candidate envelope; keys are injected, never loaded from environment."""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .canonical import canonical_json
from .models import TrustClaims, identifier_errors


SCHEMA = "CDH-AFFILIATE-TRUST-ENVELOPE-CANDIDATE-1"
TYPE = "CDH-AFFILIATE-TRUST"
TOP_FIELDS = frozenset({"schema_version", "protected", "claims", "signature"})
PROTECTED_FIELDS = frozenset({"alg", "kid", "typ"})
CLAIM_FIELDS = frozenset(
    {
        "issuer", "audience", "fixture_class", "provider_id", "market", "canonical_product_id",
        "provider_product_id", "sku_id", "seller_id", "original_url_sha256", "verified_destination",
        "issued_at", "expires_at", "official_evidence_ids", "revocation_event_id", "revocation_status",
        "revocation_checked_at", "disclosure_text", "nonce",
    }
)


class EnvelopeError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True, slots=True)
class EnvelopeKey:
    secret: bytes = field(repr=False)
    permitted_fixture_classes: frozenset[str]


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_signature(value: object) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        raise EnvelopeError("SIGNATURE_ENCODING_INVALID", "unpadded base64url signature required")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise EnvelopeError("SIGNATURE_ENCODING_INVALID", "signature is not base64url") from exc
    if len(decoded) != hashlib.sha256().digest_size:
        raise EnvelopeError("SIGNATURE_LENGTH_INVALID", "HS256 signature must be 32 bytes")
    return decoded


def _datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise EnvelopeError(f"{field.upper()}_INVALID", f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EnvelopeError(f"{field.upper()}_INVALID", f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EnvelopeError(f"{field.upper()}_INVALID", f"{field} must include timezone")
    return parsed


class TrustEnvelopeCodec:
    def __init__(self, keys: dict[str, EnvelopeKey]) -> None:
        if not keys:
            raise ValueError("at least one injected backend key is required")
        for key_id, material in keys.items():
            if (
                identifier_errors("key_id", key_id)
                or not isinstance(material, EnvelopeKey)
                or not isinstance(material.secret, bytes)
                or len(material.secret) < 32
                or not material.permitted_fixture_classes
                or not material.permitted_fixture_classes.issubset({"CONTRACT_FIXTURE_TEST_ONLY", "OFFICIAL_RUNTIME"})
            ):
                raise ValueError("key IDs, 32-byte secrets and explicit permitted fixture classes are required")
        self._keys = dict(keys)

    @staticmethod
    def _signed_bytes(protected: dict[str, Any], claims: dict[str, Any]) -> bytes:
        return canonical_json({"protected": protected, "claims": claims})

    def sign(self, claims: TrustClaims, *, key_id: str) -> dict[str, Any]:
        try:
            material = self._keys[key_id]
        except KeyError as exc:
            raise EnvelopeError("KEY_ID_UNKNOWN", "key ID is not registered") from exc
        if claims.fixture_class not in material.permitted_fixture_classes:
            raise EnvelopeError("KEY_PURPOSE_MISMATCH", "key is not authorized for this fixture class")
        protected = {"alg": "HS256", "kid": key_id, "typ": TYPE}
        wire_claims = claims.to_wire()
        signature = hmac.new(material.secret, self._signed_bytes(protected, wire_claims), hashlib.sha256).digest()
        return {"schema_version": SCHEMA, "protected": protected, "claims": wire_claims, "signature": _b64url(signature)}

    def verify(self, value: object) -> tuple[TrustClaims, str, str]:
        if not isinstance(value, dict) or set(value) != TOP_FIELDS:
            raise EnvelopeError("ENVELOPE_STRUCTURE_INVALID", "exact envelope field set required")
        if value.get("schema_version") != SCHEMA:
            raise EnvelopeError("ENVELOPE_SCHEMA_INVALID", "candidate envelope schema required")
        protected = value.get("protected")
        claims = value.get("claims")
        if not isinstance(protected, dict) or set(protected) != PROTECTED_FIELDS:
            raise EnvelopeError("PROTECTED_STRUCTURE_INVALID", "exact protected header required")
        if protected.get("alg") != "HS256" or protected.get("typ") != TYPE:
            raise EnvelopeError("PROTECTED_HEADER_INVALID", "algorithm or type is invalid")
        key_id = protected.get("kid")
        if identifier_errors("key_id", key_id):
            raise EnvelopeError("KEY_ID_INVALID", "key ID is invalid")
        try:
            material = self._keys[key_id]
        except KeyError as exc:
            raise EnvelopeError("KEY_ID_UNKNOWN", "key ID is not registered") from exc
        if not isinstance(claims, dict) or set(claims) != CLAIM_FIELDS:
            raise EnvelopeError("CLAIMS_STRUCTURE_INVALID", "exact claims field set required")
        received = _decode_signature(value.get("signature"))
        expected = hmac.new(material.secret, self._signed_bytes(protected, claims), hashlib.sha256).digest()
        if not hmac.compare_digest(received, expected):
            raise EnvelopeError("SIGNATURE_INVALID", "envelope authentication failed")
        if claims.get("fixture_class") not in material.permitted_fixture_classes:
            raise EnvelopeError("KEY_PURPOSE_MISMATCH", "key is not authorized for this fixture class")
        evidence = claims.get("official_evidence_ids")
        if (
            not isinstance(evidence, list)
            or any(not isinstance(item, str) or not item for item in evidence)
            or evidence != sorted(set(evidence))
        ):
            raise EnvelopeError("EVIDENCE_IDS_INVALID", "evidence IDs must be sorted unique strings")
        for name in (
            "issuer", "audience", "fixture_class", "provider_id", "market", "canonical_product_id",
            "provider_product_id", "sku_id", "seller_id", "revocation_event_id", "revocation_status",
            "disclosure_text", "nonce",
        ):
            errors = identifier_errors(name, claims.get(name))
            if errors:
                raise EnvelopeError(errors[0], f"invalid claim: {name}")
        digest = claims.get("original_url_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise EnvelopeError("ORIGINAL_URL_SHA256_INVALID", "lowercase SHA-256 required")
        destination = claims.get("verified_destination")
        if not isinstance(destination, str) or not destination:
            raise EnvelopeError("VERIFIED_DESTINATION_INVALID", "verified destination is required")
        parsed = TrustClaims(
            issuer=claims["issuer"], audience=claims["audience"], fixture_class=claims["fixture_class"],
            provider_id=claims["provider_id"], market=claims["market"],
            canonical_product_id=claims["canonical_product_id"], provider_product_id=claims["provider_product_id"],
            sku_id=claims["sku_id"], seller_id=claims["seller_id"], original_url_sha256=digest,
            verified_destination=destination, issued_at=_datetime(claims.get("issued_at"), "issued_at"),
            expires_at=_datetime(claims.get("expires_at"), "expires_at"),
            official_evidence_ids=tuple(evidence), revocation_event_id=claims["revocation_event_id"],
            revocation_status=claims["revocation_status"],
            revocation_checked_at=_datetime(claims.get("revocation_checked_at"), "revocation_checked_at"),
            disclosure_text=claims["disclosure_text"], nonce=claims["nonce"],
        )
        envelope_id = hashlib.sha256(canonical_json(value)).hexdigest()
        return parsed, key_id, envelope_id
