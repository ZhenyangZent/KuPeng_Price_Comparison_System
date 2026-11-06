from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import canonical_json


class DeliveryError(RuntimeError):
    pass


class TemporaryDeliveryError(DeliveryError):
    pass


class RealDeliveryDisabled(DeliveryError):
    pass


@dataclass(frozen=True, slots=True)
class SinkReceipt:
    receipt_id: str
    duplicate: bool = False


class MockSink:
    """Deterministic, idempotent, in-memory sink for synthetic tests only."""

    def __init__(self, *, failures_before_success: int = 0) -> None:
        self.failures_remaining = failures_before_success
        self.calls = 0
        self.deliveries: dict[str, dict[str, Any]] = {}

    def deliver(self, event_id: str, payload: dict[str, Any]) -> SinkReceipt:
        self.calls += 1
        if event_id in self.deliveries:
            return SinkReceipt(f"mock:{event_id}", duplicate=True)
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise TemporaryDeliveryError("SYNTHETIC_TRANSIENT_FAILURE")
        self.deliveries[event_id] = payload
        return SinkReceipt(f"mock:{event_id}")


class LocalSyntheticJsonlSink:
    """Append-only local event log constrained to an explicit synthetic root."""

    def __init__(self, path: str | Path, *, synthetic_root: str | Path) -> None:
        self.path = Path(path).resolve()
        root = Path(synthetic_root).resolve()
        if self.path != root and root not in self.path.parents:
            raise ValueError("LOCAL_SINK_PATH_OUTSIDE_SYNTHETIC_ROOT")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._seen.add(str(json.loads(line)["event_id"]))

    def deliver(self, event_id: str, payload: dict[str, Any]) -> SinkReceipt:
        if event_id in self._seen:
            return SinkReceipt(f"jsonl:{event_id}", duplicate=True)
        record = {"event_id": event_id, "payload": payload, "synthetic": True}
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(record) + "\n")
            handle.flush()
        self._seen.add(event_id)
        return SinkReceipt(f"jsonl:{event_id}")


class WindowsToastSinkInterface:
    def deliver(self, event_id: str, payload: dict[str, Any]) -> SinkReceipt:
        raise RealDeliveryDisabled("WINDOWS_TOAST_INTERFACE_ONLY")


class TelegramSinkInterface:
    def deliver(self, event_id: str, payload: dict[str, Any]) -> SinkReceipt:
        raise RealDeliveryDisabled("TELEGRAM_INTERFACE_ONLY")
