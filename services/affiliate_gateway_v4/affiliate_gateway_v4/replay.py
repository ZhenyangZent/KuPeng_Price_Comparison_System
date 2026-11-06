"""Ephemeral replay guard for signed envelope nonces."""

from __future__ import annotations

import hashlib
from datetime import datetime


class InMemoryReplayGuard:
    def __init__(self) -> None:
        self._seen: dict[str, datetime] = {}

    @staticmethod
    def _key(issuer: str, key_id: str, nonce: str, binding_sha256: str) -> str:
        raw = "\x1f".join((issuer, key_id, nonce, binding_sha256))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def claim(
        self,
        *,
        issuer: str,
        key_id: str,
        nonce: str,
        binding_sha256: str,
        expires_at: datetime,
        now: datetime,
    ) -> bool:
        expired = [key for key, expiry in self._seen.items() if expiry <= now]
        for key in expired:
            self._seen.pop(key, None)
        key = self._key(issuer, key_id, nonce, binding_sha256)
        if key in self._seen:
            return False
        self._seen[key] = expires_at
        return True

    @property
    def size(self) -> int:
        return len(self._seen)
