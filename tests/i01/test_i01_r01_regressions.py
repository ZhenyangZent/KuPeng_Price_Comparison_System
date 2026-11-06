"""I01-R01 synthetic-only security and integration regressions."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from cdh_core.models import EventStatus
from cdh_core.persistence import MockSink
from cdh_integration.pipeline import SyntheticIntegrationPipeline
from tests.i01.test_adapter_pipeline import NOW, MutableClock, fixture, observation


class I01R01RegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clock = MutableClock()
        self.pipeline = self._open()
        self.raw = observation(price_minor=500)
        self.qualified = fixture(self.raw, target_total_minor=500)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _open(self) -> SyntheticIntegrationPipeline:
        return SyntheticIntegrationPipeline(
            candidate_database=self.root / "candidates.sqlite3",
            event_database=self.root / "events.sqlite3",
            clock=self.clock,
        )

    def _disable(self, *, source_allowed: bool = True) -> object:
        first = self.pipeline.process(self.raw, self.qualified)
        self.pipeline.revoke_user_policy(
            first.scenario,
            notifications_enabled=False,
            source_allowed=source_allowed,
            membership_context=first.scenario.membership_context,
            eligibility_profile_version=first.scenario.eligibility_profile_version,
            revision_id="i01-r01-disable",
            now=NOW + timedelta(seconds=1),
        )
        self.clock.value = NOW + timedelta(seconds=2)
        return first

    def test_01_policy_revocation_survives_process_restart_and_old_fixture(self) -> None:
        first = self._disable(source_allowed=False)
        reopened = self._open()
        replay = reopened.process(self.raw, self.qualified, request_id="different-after-restart")
        snapshot = reopened.events.policy_snapshot(first.scenario)
        self.assertEqual(replay.status, "BLOCKED")
        self.assertEqual(replay.reasons, ("AUTHORITATIVE_POLICY_BLOCKED",))
        self.assertEqual(snapshot["user"]["notifications_enabled"], 0)
        self.assertEqual(snapshot["user"]["source_allowed"], 0)

    def test_02_same_request_replay_is_side_effect_free_after_policy_change(self) -> None:
        first = self._disable()
        before = self.pipeline.events.policy_snapshot(first.scenario)
        replay = self.pipeline.process(self.raw, self.qualified)
        after = self.pipeline.events.policy_snapshot(first.scenario)
        self.assertEqual(replay.status, "BLOCKED")
        self.assertEqual(replay.reasons, ("IDEMPOTENT_EVENT_SUPERSEDED",))
        self.assertEqual(before, after)

    def test_03_different_request_id_cannot_bypass_revocation(self) -> None:
        first = self._disable()
        replay = self.pipeline.process(self.raw, self.qualified, request_id="new-request-after-disable")
        self.assertEqual(replay.status, "BLOCKED")
        self.assertEqual(self.pipeline.events.counts(), {"events": 1, "outbox": 1})
        self.assertEqual(self.pipeline.events.event_status(first.event_id), EventStatus.SUPERSEDED)

    def test_04_explicit_reenable_allows_meaningful_new_observation(self) -> None:
        first = self._disable()
        self.pipeline.revoke_user_policy(
            first.scenario,
            notifications_enabled=True,
            source_allowed=True,
            membership_context=first.scenario.membership_context,
            eligibility_profile_version=first.scenario.eligibility_profile_version,
            revision_id="i01-r01-reenable",
            now=NOW + timedelta(seconds=3),
        )
        self.clock.value = NOW + timedelta(seconds=5)
        new_raw = observation(price_minor=500, observed_at=NOW + timedelta(seconds=4))
        new_fixture = fixture(
            new_raw,
            now=self.clock.value,
            target_total_minor=500,
            availability_version="availability-v2",
        )
        second = self.pipeline.process(new_raw, new_fixture, request_id="reenabled-new-observation")
        self.assertEqual(second.status, "QUEUED")
        self.assertNotEqual(second.event_id, first.event_id)

    def test_05_target_change_survives_old_fixture_and_new_request(self) -> None:
        first = self.pipeline.process(self.raw, self.qualified)
        self.pipeline.update_scenario_policy(
            first.scenario,
            target_total_minor=100,
            enabled=True,
            revision_id="i01-r01-target-100",
            now=NOW + timedelta(seconds=1),
        )
        self.clock.value = NOW + timedelta(seconds=2)
        result = self.pipeline.process(self.raw, self.qualified, request_id="target-stale-new-request")
        snapshot = self.pipeline.events.policy_snapshot(first.scenario)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(snapshot["scenario"]["target_total_minor"], 100)

    def test_06_exact_mock_sink_is_accepted_but_subclass_is_rejected(self) -> None:
        first = self.pipeline.process(self.raw, self.qualified)

        class MockSinkSubclass(MockSink):
            pass

        with self.assertRaises(TypeError):
            self.pipeline.deliver(first.event_id, MockSinkSubclass(), now=NOW)
        sink = MockSink()
        self.assertEqual(self.pipeline.deliver(first.event_id, sink, now=NOW), EventStatus.DELIVERED)
        self.assertEqual(len(sink.deliveries), 1)

    def test_07_q2_without_price_basis_fails_closed(self) -> None:
        raw = observation(price_minor=800)
        result = self.pipeline.process(raw, fixture(raw, quantity=2, minimum_quantity=2))
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reasons, ("MULTI_QUANTITY_PRICE_BASIS_UNVERIFIED",))

    def test_08_q2_mismatched_quoted_quantity_fails_closed(self) -> None:
        raw = observation(price_minor=800)
        qualified = fixture(
            raw,
            quantity=2,
            minimum_quantity=2,
            total_quote_evidence_id="I01-Q2-EVIDENCE",
        )
        qualified["quoted_quantity"] = 1
        result = self.pipeline.process(raw, qualified)
        self.assertEqual(result.reasons, ("QUOTED_QUANTITY_MISMATCH",))

    def test_09_q2_explicit_total_quote_preserves_total_and_unit(self) -> None:
        raw = observation(price_minor=800)
        qualified = fixture(
            raw,
            quantity=2,
            minimum_quantity=2,
            total_quote_evidence_id="I01-Q2-EVIDENCE",
        )
        result = self.pipeline.process(raw, qualified)
        record = self.pipeline.events.observation_record(f"i01:{result.source_payload_sha256}")
        self.assertEqual(result.status, "QUEUED")
        self.assertEqual(result.decision.total_minor, 800)
        self.assertEqual(record["unit_minor"], 400)

    def test_10_legacy_q1_remains_unambiguous_and_supported(self) -> None:
        legacy = dict(self.qualified)
        for field in ("price_basis", "quoted_quantity", "total_quote_evidence_id"):
            legacy.pop(field)
        result = self.pipeline.process(self.raw, legacy)
        self.assertEqual(result.status, "QUEUED")
        self.assertEqual(result.decision.total_minor, 500)

    def test_11_unqualified_replay_preserves_qualification_and_records_attempt(self) -> None:
        first = self.pipeline.process(self.raw, self.qualified)
        self.pipeline.process(self.raw, None)
        candidate = self.pipeline.ledger.get(first.source_payload_sha256)
        attempts = self.pipeline.ledger.attempts(first.source_payload_sha256)
        self.assertEqual(candidate["status"], "QUEUED")
        self.assertEqual(candidate["latest_attempt_status"], "WAITING_EVIDENCE")
        self.assertEqual(json.loads(candidate["latest_attempt_reason_codes_json"]), ["QUALIFICATION_FIXTURE_REQUIRED"])
        self.assertEqual([item["status"] for item in attempts], ["QUEUED", "WAITING_EVIDENCE"])

    def test_12_request_binding_survives_database_restart(self) -> None:
        first = self.pipeline.process(self.raw, self.qualified, request_id="persistent-request")
        reopened = self._open()
        second = reopened.process(self.raw, self.qualified, request_id="persistent-request")
        self.assertEqual(second.event_id, first.event_id)
        self.assertFalse(second.event_created)
        self.assertEqual(reopened.events.counts(), {"events": 1, "outbox": 1})

    def test_13_invalid_request_id_is_rejected_before_any_persistence(self) -> None:
        with self.assertRaises(ValueError):
            self.pipeline.process(self.raw, self.qualified, request_id="")
        self.assertEqual(self.pipeline.ledger.count(), 0)
        self.assertEqual(self.pipeline.events.counts(), {"events": 0, "outbox": 0})


if __name__ == "__main__":
    unittest.main(verbosity=2)
