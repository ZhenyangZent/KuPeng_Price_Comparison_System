from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from cdh_core.models import Decision, EventStatus, PurchaseScenario, canonical_digest
from cdh_core.persistence import (
    CurrentState,
    CurrentStateConflict,
    DecisionBindingError,
    EventStore,
    IdempotencyConflict,
    MockSink,
    StaleCurrentState,
)
from cdh_core.policy import decide
from cdh_core.pricing import calculate_total

from .adapter import IntegrationValidationError, QualificationFixture, SyntheticObservation
from .storage import CandidateLedger


@dataclass(frozen=True, slots=True)
class IntegrationResult:
    source_payload_sha256: str | None
    status: str
    reasons: tuple[str, ...]
    synthetic_only: bool = True
    fixture_id: str | None = None
    fixture_sha256: str | None = None
    scenario: PurchaseScenario | None = None
    decision: Decision | None = None
    event_id: str | None = None
    event_created: bool = False
    observation_created: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "scope": "SYNTHETIC_ONLY",
            "source_payload_sha256": self.source_payload_sha256,
            "status": self.status,
            "reasons": list(self.reasons),
            "fixture_id": self.fixture_id,
            "fixture_sha256": self.fixture_sha256,
            "scenario_scope": None if self.scenario is None else self.scenario.scope_key,
            "decision_notify": None if self.decision is None else self.decision.notify,
            "decision_reason": None if self.decision is None else self.decision.primary_reason,
            "decision_fingerprint": None if self.decision is None else self.decision.decision_fingerprint,
            "event_id": self.event_id,
            "event_created": self.event_created,
            "observation_created": self.observation_created,
        }


class SyntheticIntegrationPipeline:
    def __init__(
        self,
        *,
        candidate_database: str | Path,
        event_database: str | Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.ledger = CandidateLedger(candidate_database)
        self.events = EventStore(event_database)

    def process(
        self,
        payload: object,
        fixture_payload: object | None = None,
        *,
        request_id: str | None = None,
    ) -> IntegrationResult:
        if request_id is not None and (not isinstance(request_id, str) or not request_id):
            raise ValueError("request_id must be non-empty text when supplied")
        now = self.clock()
        try:
            observation = SyntheticObservation.parse(payload)
        except IntegrationValidationError as exc:
            return IntegrationResult(None, "REJECTED", (exc.code,))

        if fixture_payload is None:
            result = IntegrationResult(
                observation.source_payload_sha256,
                "WAITING_EVIDENCE",
                ("QUALIFICATION_FIXTURE_REQUIRED",),
            )
            self._record(observation, result, now, attempt_only=True)
            return result

        try:
            fixture = QualificationFixture.parse(fixture_payload)
            bundle = fixture.bind(observation, now)
        except IntegrationValidationError as exc:
            fixture_id = fixture_payload.get("fixture_id") if isinstance(fixture_payload, dict) else None
            result = IntegrationResult(
                observation.source_payload_sha256,
                "BLOCKED",
                (exc.code,),
                fixture_id=fixture_id if isinstance(fixture_id, str) else None,
            )
            self._record(observation, result, now)
            return result

        observation_id = f"i01:{observation.source_payload_sha256}"
        cost = calculate_total(bundle.scenario, bundle.pricing)
        decision = decide(bundle.scenario, cost, bundle.baseline, bundle.policy)
        fixture_id = str(fixture.raw["fixture_id"])
        if not cost.complete:
            result = IntegrationResult(
                observation.source_payload_sha256,
                "BLOCKED",
                tuple(cost.reason_codes) or ("COST_INCOMPLETE",),
                fixture_id=fixture_id,
                fixture_sha256=fixture.fixture_sha256,
                scenario=bundle.scenario,
                decision=decision,
            )
            self._record(observation, result, now)
            return result

        effective_request_id = request_id or f"i01-request:{observation.source_payload_sha256}:{fixture.fixture_sha256}"
        request_fingerprint = canonical_digest(
            "i01-integration-request-v2",
            {
                "source_payload_sha256": observation.source_payload_sha256,
                "fixture_sha256": fixture.fixture_sha256,
                "scenario_scope": bundle.scenario.scope_key,
            },
        )
        existing_request = self.ledger.request_binding(effective_request_id)
        if existing_request is not None:
            if existing_request["request_fingerprint"] != request_fingerprint:
                result = IntegrationResult(
                    observation.source_payload_sha256,
                    "BLOCKED",
                    ("IDEMPOTENCY_CONFLICT",),
                    fixture_id=fixture_id,
                    fixture_sha256=fixture.fixture_sha256,
                    scenario=bundle.scenario,
                    decision=decision,
                )
            else:
                event_id = str(existing_request["event_id"])
                event_status = self.events.event_status(event_id)
                result = IntegrationResult(
                    observation.source_payload_sha256,
                    "QUEUED" if event_status == EventStatus.QUEUED else "BLOCKED",
                    (
                        decision.primary_reason
                        if event_status == EventStatus.QUEUED
                        else f"IDEMPOTENT_EVENT_{event_status.value}"
                    ,),
                    fixture_id=fixture_id,
                    fixture_sha256=fixture.fixture_sha256,
                    scenario=bundle.scenario,
                    decision=decision,
                    event_id=event_id,
                    event_created=False,
                    observation_created=False,
                )
            self._record(observation, result, now)
            return result

        observation_created = self.events.record_observation(observation_id, bundle.core_observation)

        current_state = CurrentState.verified_from(
            bundle.scenario,
            cost,
            now=observation.observed_at,
            expires_at=bundle.policy.evidence_expires_at,
            stock=str(bundle.fixture.raw["stock_state"]),
            eligibility_state=str(bundle.fixture.raw["eligibility_state"]),
            source_enabled=bool(bundle.fixture.raw["source_allowed"]),
            notifications_enabled=bool(bundle.fixture.raw["notifications_enabled"]),
            evidence_id=f"I01-CURRENT:{observation.source_payload_sha256}:{fixture.fixture_sha256}",
            rule_version="i01-current-state-v1",
            availability_version=str(bundle.fixture.raw["availability_version"]),
        )
        try:
            self.events.set_current_state(current_state, now=now)
        except (StaleCurrentState, CurrentStateConflict) as exc:
            reason = "STALE_SOURCE_OBSERVATION" if isinstance(exc, StaleCurrentState) else "CURRENT_STATE_CONFLICT"
            result = IntegrationResult(
                observation.source_payload_sha256,
                "BLOCKED",
                (reason,),
                fixture_id=fixture_id,
                fixture_sha256=fixture.fixture_sha256,
                scenario=bundle.scenario,
                decision=decision,
                observation_created=observation_created,
            )
            self._record(observation, result, now)
            return result

        if not decision.notify:
            result = IntegrationResult(
                observation.source_payload_sha256,
                "FILTERED",
                (decision.primary_reason,),
                fixture_id=fixture_id,
                fixture_sha256=fixture.fixture_sha256,
                scenario=bundle.scenario,
                decision=decision,
                observation_created=observation_created,
            )
            self._record(observation, result, now)
            return result

        try:
            event_id, created = self.events.enqueue(
                bundle.scenario,
                decision,
                request_id=effective_request_id,
                dedupe_key=f"i01-dedupe:{bundle.scenario.scope_key}",
                expected_fingerprint=cost.quote_fingerprint or "",
                expires_at=decision.valid_until,
                now=now,
            )
        except (DecisionBindingError, IdempotencyConflict) as exc:
            reason = "IDEMPOTENCY_CONFLICT" if isinstance(exc, IdempotencyConflict) else "AUTHORITATIVE_POLICY_BLOCKED"
            result = IntegrationResult(
                observation.source_payload_sha256,
                "BLOCKED",
                (reason,),
                fixture_id=fixture_id,
                fixture_sha256=fixture.fixture_sha256,
                scenario=bundle.scenario,
                decision=decision,
                observation_created=observation_created,
            )
            self._record(observation, result, now)
            return result
        self.ledger.record_request_binding(
            request_id=effective_request_id,
            request_fingerprint=request_fingerprint,
            source_payload_sha256=observation.source_payload_sha256,
            fixture_sha256=fixture.fixture_sha256,
            event_id=event_id,
            now=now,
        )
        result = IntegrationResult(
            observation.source_payload_sha256,
            "QUEUED",
            (decision.primary_reason,),
            fixture_id=fixture_id,
            fixture_sha256=fixture.fixture_sha256,
            scenario=bundle.scenario,
            decision=decision,
            event_id=event_id,
            event_created=created,
            observation_created=observation_created,
        )
        self._record(observation, result, now)
        return result

    def revoke_user_policy(
        self,
        scenario: PurchaseScenario,
        *,
        notifications_enabled: bool,
        source_allowed: bool,
        membership_context: str,
        eligibility_profile_version: str,
        revision_id: str,
        now: datetime,
    ) -> int:
        return self.events.update_user_policy(
            scenario,
            notifications_enabled=notifications_enabled,
            source_allowed=source_allowed,
            membership_context=membership_context,
            eligibility_profile_version=eligibility_profile_version,
            revision_id=revision_id,
            now=now,
        )

    def update_scenario_policy(
        self,
        scenario: PurchaseScenario,
        *,
        target_total_minor: int | None,
        enabled: bool,
        revision_id: str,
        now: datetime,
    ) -> int:
        """Apply an explicit user-side scenario policy command, never observation data."""
        return self.events.update_scenario_policy(
            scenario,
            target_total_minor=target_total_minor,
            enabled=enabled,
            revision_id=revision_id,
            now=now,
        )

    def deliver(self, event_id: str, sink: MockSink, *, now: datetime) -> EventStatus:
        if type(sink) is not MockSink:
            raise TypeError("I01 delivery is restricted to the exact offline MockSink implementation")
        return self.events.deliver(event_id, sink, now=now)

    def _record(
        self,
        observation: SyntheticObservation,
        result: IntegrationResult,
        now: datetime,
        *,
        attempt_only: bool = False,
    ) -> None:
        self.ledger.update(
            observation,
            status=result.status,
            reasons=result.reasons,
            now=now,
            fixture_id=result.fixture_id,
            fixture_sha256=result.fixture_sha256,
            scenario_scope=None if result.scenario is None else result.scenario.scope_key,
            decision_reason=None if result.decision is None else result.decision.primary_reason,
            event_id=result.event_id,
            attempt_only=attempt_only,
        )

