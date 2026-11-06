from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .models import GateResult, LatestState, NotificationCandidate, OutboxStatus, free_shipping_gate, parse_time
from .sinks import LocalSyntheticJsonlSink, MockSink, TemporaryDeliveryError
from .store import OutboxStore


TAIPEI = ZoneInfo("Asia/Taipei")
ALLOWED_SINK_TYPES = (MockSink, LocalSyntheticJsonlSink)


@dataclass(frozen=True, slots=True)
class SubmitResult:
    status: str
    event_id: str | None
    created: bool
    episode: int | None
    gate: GateResult


@dataclass(frozen=True, slots=True)
class DispatchResult:
    status: str
    event_id: str | None = None
    detail: str | None = None


class NotificationService:
    def __init__(self, database_path: str | Path, *, max_attempts: int = 12) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.store = OutboxStore(database_path)
        self.max_attempts = max_attempts

    def update_latest_state(self, state: LatestState, *, now: datetime) -> bool:
        changed = self.store.set_latest_state(state, now=now)
        if not changed:
            return False
        for row in self.store.rows():
            if row["scenario_scope"] != state.scenario_scope:
                continue
            if row["status"] not in (OutboxStatus.PENDING, OutboxStatus.RETRY, OutboxStatus.IN_FLIGHT):
                continue
            candidate = NotificationCandidate.from_dict(json.loads(str(row["payload_json"])))
            gate = free_shipping_gate(candidate, state, now)
            if not gate.allowed:
                self.store.revoke(str(row["event_id"]), reason=";".join(gate.reasons), now=now)
        return True

    def submit(
        self,
        candidate: NotificationCandidate,
        latest_state: LatestState,
        *,
        now: datetime,
    ) -> SubmitResult:
        if latest_state.scenario_scope != candidate.scenario_scope:
            raise ValueError("STATE_SCENARIO_SCOPE_MISMATCH")
        self.update_latest_state(latest_state, now=now)
        gate = free_shipping_gate(candidate, latest_state, now)
        if not gate.allowed:
            self.store.record_filter(candidate, gate.reasons, now=now)
            return SubmitResult("FILTERED", None, False, None, gate)
        event_id, created, episode = self.store.enqueue(candidate, now=now)
        return SubmitResult("QUEUED", event_id, created, episode, gate)

    def observe_rebound(
        self,
        scenario_scope: str,
        *,
        observed_at: datetime,
        total_minor: int | None,
        reason: str = "PRICE_REBOUND",
    ) -> bool:
        return self.store.observe_rebound(
            scenario_scope,
            observed_at=observed_at,
            total_minor=total_minor,
            reason=reason,
        )

    @staticmethod
    def _payload(candidate: NotificationCandidate, gate: GateResult, event_id: str) -> dict[str, Any]:
        shipping = "FREE" if gate.free_shipping else f"TWD {candidate.shipping_minor}"
        return {
            "contract": "CDH-N01-NOTIFICATION-PAYLOAD-1",
            "event_id": event_id,
            "scenario_scope": candidate.scenario_scope,
            "offer_key": candidate.offer_key,
            "sku_id": candidate.sku_id,
            "quantity": candidate.quantity,
            "total_minor": candidate.total_minor,
            "shipping": shipping,
            "decision_reason": candidate.decision_reason,
            "display_category": gate.display_category,
            "expires_at": candidate.expires_at.isoformat(),
            "synthetic": True,
            "real_delivery_enabled": False,
        }

    def dispatch_one(
        self,
        sink: MockSink | LocalSyntheticJsonlSink,
        *,
        worker_id: str,
        now: datetime,
    ) -> DispatchResult:
        if type(sink) not in ALLOWED_SINK_TYPES:
            raise TypeError("N01_SINK_NOT_AUTHORIZED")
        row = self.store.claim(worker_id=worker_id, now=now)
        if row is None:
            return DispatchResult("IDLE")
        event_id = str(row["event_id"])
        candidate = NotificationCandidate.from_dict(json.loads(str(row["payload_json"])))
        try:
            state = self.store.get_latest_state(candidate.scenario_scope)
        except KeyError:
            self.store.revoke(event_id, reason="LATEST_STATE_MISSING", now=now)
            return DispatchResult("REVOKED", event_id, "LATEST_STATE_MISSING")
        gate = free_shipping_gate(candidate, state, now)
        if not gate.allowed:
            reason = ";".join(gate.reasons)
            self.store.revoke(event_id, reason=reason, now=now)
            return DispatchResult("REVOKED", event_id, reason)
        payload = self._payload(candidate, gate, event_id)
        try:
            receipt = sink.deliver(event_id, payload)
        except TemporaryDeliveryError as exc:
            status = self.store.mark_failure(
                event_id,
                worker_id=worker_id,
                error=str(exc),
                now=now,
                max_attempts=self.max_attempts,
            )
            return DispatchResult(str(status), event_id, str(exc))

        post_state = self.store.get_latest_state(candidate.scenario_scope)
        post_gate = free_shipping_gate(candidate, post_state, now)
        if not post_gate.allowed:
            reason = "POST_DELIVERY_STATE_CHANGED:" + ";".join(post_gate.reasons)
            self.store.revoke(event_id, reason=reason, now=now)
            return DispatchResult("DELIVERED_THEN_REVOKED", event_id, reason)
        committed = self.store.mark_delivered(
            event_id,
            worker_id=worker_id,
            receipt=receipt.receipt_id,
            now=now,
        )
        if not committed:
            return DispatchResult("DELIVERED_THEN_REVOKED", event_id, "POSTCHECK_REJECTED")
        return DispatchResult("DELIVERED", event_id, receipt.receipt_id)

    def revoke(self, event_id: str, *, reason: str, now: datetime) -> bool:
        return self.store.revoke(event_id, reason=reason, now=now)

    def daily_digest(self, local_day: date, *, now: datetime) -> dict[str, Any]:
        """Build a synthetic digest with the exact same gate as immediate delivery."""
        items: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for row in self.store.rows():
            created = parse_time(str(row["created_at"]))
            assert created is not None
            if created.astimezone(TAIPEI).date() != local_day:
                continue
            candidate = NotificationCandidate.from_dict(json.loads(str(row["payload_json"])))
            try:
                state = self.store.get_latest_state(candidate.scenario_scope)
                gate = free_shipping_gate(candidate, state, now)
            except KeyError:
                gate = GateResult(False, ("LATEST_STATE_MISSING",), "LOW_ABSOLUTE_PRICE", False)
            item = {
                "event_id": row["event_id"],
                "status": row["status"],
                "scenario_scope": candidate.scenario_scope,
                "sku_id": candidate.sku_id,
                "quantity": candidate.quantity,
                "total_minor": candidate.total_minor,
                "decision_reason": candidate.decision_reason,
                "display_category": gate.display_category,
                "free_shipping": gate.free_shipping,
            }
            if gate.allowed:
                items.append(item)
            else:
                blocked.append({**item, "gate_reasons": list(gate.reasons)})
        return {
            "contract": "CDH-N01-DAILY-DIGEST-1",
            "local_day": local_day.isoformat(),
            "timezone": "Asia/Taipei",
            "generated_at": now.isoformat(),
            "synthetic": True,
            "free_shipping_gate_version": "n01-free-shipping-gate-v1",
            "items": items,
            "blocked": blocked,
        }

    def stats(self) -> dict[str, Any]:
        return self.store.stats()
