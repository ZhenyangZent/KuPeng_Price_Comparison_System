from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .parser import BatchValidationError


@dataclass
class BatchClaim:
    preview_id: str
    claim_id: str
    records: list[dict[str, object]]
    file_sha256: str
    duplicate_input_count: int


@dataclass
class _PendingBatch:
    expires_at: float
    token: str
    records: list[dict[str, object]]
    file_sha256: str
    size: int
    duplicate_input_count: int
    state: str = "AVAILABLE"
    claim_id: str | None = None


class PendingBatches:
    def __init__(self, *, ttl_seconds: int = 600, max_items: int = 16, max_total_bytes: int = 8 * 1024 * 1024, clock: Callable[[], float] | None = None) -> None:
        if ttl_seconds < 1 or max_items < 1 or max_total_bytes < 1024:
            raise ValueError("pending batch limits are invalid")
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self.max_total_bytes = max_total_bytes
        self.clock = clock or time.monotonic
        self._items: dict[str, _PendingBatch] = {}
        self._lock = threading.Lock()

    def _cleanup_locked(self) -> int:
        now = self.clock()
        expired = [key for key, value in self._items.items() if value.state != "IN_FLIGHT" and value.expires_at < now]
        for key in expired:
            self._items.pop(key, None)
        return len(expired)

    def create(self, records: list[dict[str, object]], file_sha256: str, duplicate_input_count: int) -> tuple[str, str, int]:
        size = len(json.dumps(records, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        preview_id = secrets.token_urlsafe(24)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._cleanup_locked()
            total = sum(item.size for item in self._items.values())
            if len(self._items) >= self.max_items or total + size > self.max_total_bytes:
                raise BatchValidationError("BATCH_PREVIEW_CAPACITY_EXCEEDED")
            self._items[preview_id] = _PendingBatch(
                expires_at=self.clock() + self.ttl_seconds,
                token=token,
                records=records,
                file_sha256=file_sha256,
                size=size,
                duplicate_input_count=duplicate_input_count,
            )
        return preview_id, token, self.ttl_seconds

    def claim(self, preview_id: object, token: object) -> BatchClaim:
        if not isinstance(preview_id, str) or not isinstance(token, str):
            raise BatchValidationError("CONFIRMATION_TOKEN_INVALID")
        with self._lock:
            self._cleanup_locked()
            value = self._items.get(preview_id)
            if value is None or not secrets.compare_digest(value.token, token):
                raise BatchValidationError("CONFIRMATION_TOKEN_INVALID_OR_EXPIRED")
            if value.state == "IN_FLIGHT":
                raise BatchValidationError("CONFIRMATION_ALREADY_IN_PROGRESS")
            if value.expires_at < self.clock():
                self._items.pop(preview_id, None)
                raise BatchValidationError("CONFIRMATION_TOKEN_INVALID_OR_EXPIRED")
            if value.state == "FAILED":
                raise BatchValidationError("CONFIRMATION_FAILED_NEW_PREVIEW_REQUIRED")
            if value.state != "AVAILABLE":
                raise BatchValidationError("CONFIRMATION_TOKEN_INVALID_OR_EXPIRED")
            claim_id = secrets.token_urlsafe(24)
            value.state = "IN_FLIGHT"
            value.claim_id = claim_id
            return BatchClaim(
                preview_id=preview_id,
                claim_id=claim_id,
                records=value.records,
                file_sha256=value.file_sha256,
                duplicate_input_count=value.duplicate_input_count,
            )

    def complete(self, claim: BatchClaim) -> None:
        with self._lock:
            value = self._items.get(claim.preview_id)
            if value is None or value.state != "IN_FLIGHT" or value.claim_id != claim.claim_id:
                raise RuntimeError("pending batch claim state changed unexpectedly")
            self._items.pop(claim.preview_id, None)

    def fail(self, claim: BatchClaim) -> None:
        with self._lock:
            value = self._items.get(claim.preview_id)
            if value is None or value.state != "IN_FLIGHT" or value.claim_id != claim.claim_id:
                raise RuntimeError("pending batch claim state changed unexpectedly")
            value.state = "FAILED"
            value.claim_id = None
            value.records = []
            value.size = 0

    def retained_count(self) -> int:
        with self._lock:
            self._cleanup_locked()
            return len(self._items)

