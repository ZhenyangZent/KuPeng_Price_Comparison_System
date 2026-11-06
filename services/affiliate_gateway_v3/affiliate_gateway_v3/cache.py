"""Ephemeral verified-link cache keyed by exact identity and original URL hash."""

from __future__ import annotations

from datetime import datetime

from .models import AdapterResult, ExactIdentity


def _aware(value: datetime | None) -> bool:
    return value is not None and value.tzinfo is not None and value.utcoffset() is not None


class VerifiedLinkCache:
    def __init__(self) -> None:
        self._values: dict[str, AdapterResult] = {}

    def get(self, identity: ExactIdentity, *, now: datetime, max_revocation_age_seconds: int) -> AdapterResult | None:
        value = self._values.get(identity.cache_key())
        if value is None:
            return None
        if (
            value.status != "VERIFIED"
            or value.revocation_status != "ACTIVE"
            or not value.revocation_event_id
            or not _aware(value.expires_at)
            or value.expires_at <= now
            or not _aware(value.revocation_checked_at)
            or (now - value.revocation_checked_at).total_seconds() < 0
            or (now - value.revocation_checked_at).total_seconds() > max_revocation_age_seconds
        ):
            self._values.pop(identity.cache_key(), None)
            return None
        return value

    def put(self, identity: ExactIdentity, value: AdapterResult) -> bool:
        if (
            value.status != "VERIFIED"
            or value.revocation_status != "ACTIVE"
            or not value.revocation_event_id
            or not _aware(value.expires_at)
            or not _aware(value.revocation_checked_at)
        ):
            return False
        self._values[identity.cache_key()] = value
        return True

    def revoke(self, identity: ExactIdentity) -> None:
        self._values.pop(identity.cache_key(), None)

    @property
    def size(self) -> int:
        return len(self._values)
