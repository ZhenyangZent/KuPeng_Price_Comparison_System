"""Independent I01 review regressions. Synthetic only; never contacts Firefox, Registry or network."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from tests.i01.test_adapter_pipeline import NOW, MutableClock, observation, fixture
from cdh_integration.pipeline import SyntheticIntegrationPipeline
from cdh_core.persistence import MockSink
from cdh_core.models import EventStatus


class I01OrchestratorAdditionalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = MutableClock()
        self.pipe = SyntheticIntegrationPipeline(candidate_database=Path(self.temp.name)/'candidates.db', event_database=Path(self.temp.name)/'events.db', clock=self.clock)
        self.raw = observation(price_minor=500)
        self.fx = fixture(self.raw,target_total_minor=500)

    def tearDown(self): self.temp.cleanup()

    def _queue_then_revoke(self,*,enabled=True,source_allowed=True,membership=None,profile=None):
        r=self.pipe.process(self.raw,self.fx)
        self.assertEqual(r.status,'QUEUED')
        self.pipe.revoke_user_policy(r.scenario,notifications_enabled=enabled,source_allowed=source_allowed,membership_context=membership or r.scenario.membership_context,eligibility_profile_version=profile or r.scenario.eligibility_profile_version,revision_id='audit-policy-revocation',now=NOW+timedelta(seconds=1))
        self.clock.value=NOW+timedelta(seconds=2)
        return r

    def test_A01_notification_disable_not_undone_by_replayed_fixture(self):
        r=self._queue_then_revoke(enabled=False)
        try:self.pipe.process(self.raw,self.fx,request_id='audit-distinct-request')
        except Exception:pass
        user=self.pipe.events.policy_snapshot(r.scenario)['user']
        self.assertEqual(user['notifications_enabled'],0,'Old qualification observation must not re-enable user notifications')
        self.assertEqual(self.pipe.events.event_status(r.event_id),EventStatus.SUPERSEDED)

    def test_A02_source_revocation_not_undone_by_replayed_fixture(self):
        r=self._queue_then_revoke(source_allowed=False)
        try:self.pipe.process(self.raw,self.fx,request_id='audit-distinct-request')
        except Exception:pass
        user=self.pipe.events.policy_snapshot(r.scenario)['user']
        self.assertEqual(user['source_allowed'],0,'Old qualification observation must not re-authorize a source')

    def test_A03_membership_change_not_undone_by_replayed_fixture(self):
        r=self._queue_then_revoke(membership='NON_WOW_SYNTHETIC',profile='ELIGIBILITY-SYNTH-v2')
        try:self.pipe.process(self.raw,self.fx,request_id='audit-distinct-request')
        except Exception:pass
        user=self.pipe.events.policy_snapshot(r.scenario)['user']
        self.assertEqual(user['membership_context'],'NON_WOW_SYNTHETIC','Stale fixture must not revert membership')
        self.assertEqual(user['eligibility_profile_version'],'ELIGIBILITY-SYNTH-v2')

    def test_A04_target_change_not_undone_by_replayed_fixture(self):
        original=self.pipe.process(self.raw,self.fx)
        self.pipe.events.update_scenario_policy(original.scenario,target_total_minor=100,enabled=True,revision_id='audit-target-100',now=NOW+timedelta(seconds=1))
        self.clock.value=NOW+timedelta(seconds=2)
        try:self.pipe.process(self.raw,self.fx,request_id='audit-distinct-request')
        except Exception:pass
        snapshot=self.pipe.events.policy_snapshot(original.scenario)
        self.assertEqual(snapshot['scenario']['target_total_minor'],100,'Replaying old fixture must not reset explicit user target price')

    def test_A05_failed_replay_must_not_mutate_policy_before_idempotency_error(self):
        original=self._queue_then_revoke(enabled=False)
        try:self.pipe.process(self.raw,self.fx) # original request ID again
        except Exception:pass
        user=self.pipe.events.policy_snapshot(original.scenario)['user']
        self.assertEqual(user['notifications_enabled'],0,'A failed request must not alter persisted policy')

    def test_A06_pipeline_delivery_must_reject_any_non_mock_sink(self):
        original=self.pipe.process(self.raw,self.fx)
        class ExternalSinkProbe:
            def __init__(self):self.received=[]
            def deliver(self,payload):self.received.append(payload)
        external=ExternalSinkProbe()
        try:self.pipe.deliver(original.event_id,external,now=NOW)
        except (TypeError,ValueError):pass
        self.assertEqual(external.received,[],'Offline-only pipeline must not call arbitrary external delivery callbacks')

    def test_A07_unqualified_replay_must_not_erase_verified_candidate_status(self):
        original=self.pipe.process(self.raw,self.fx)
        self.assertEqual(original.status,'QUEUED')
        record_before=self.pipe.ledger.get(original.source_payload_sha256)
        self.pipe.process(self.raw,None)
        record_after=self.pipe.ledger.get(original.source_payload_sha256)
        self.assertEqual(record_after['status'],record_before['status'],'Missing fixture on re-read must not erase prior qualification status')

    def test_A08_multi_quantity_price_basis_must_be_explicit(self):
        # B01 has a price_minor field but no quantity or per-unit/aggregate price-basis field.
        # Before promoting to a full order quote for q=2, the integration must carry explicit proof.
        raw=observation(price_minor=500)
        assumed_full_order_quote=fixture(raw,quantity=2,minimum_quantity=2)
        result=self.pipe.process(raw,assumed_full_order_quote)
        self.assertNotEqual(result.status,'QUEUED','Source price semantics are unproven for q>1; must not treat the $5 page amount as $5 for 2 items')

    def test_P01_original_valid_fixture_still_queues_and_mocks(self):
        first=self.pipe.process(self.raw,self.fx)
        self.assertEqual(first.status,'QUEUED')
        sink=MockSink()
        self.assertEqual(self.pipe.deliver(first.event_id,sink,now=NOW),EventStatus.DELIVERED)
        self.assertEqual(len(sink.deliveries),1)

    def test_P02_missing_fixture_never_enqueues(self):
        first=self.pipe.process(self.raw,None)
        self.assertEqual(first.status,'WAITING_EVIDENCE')
        self.assertEqual(self.pipe.events.counts(),{'events':0,'outbox':0})

    def test_P03_source_revocation_blocks_previously_queued_delivery_without_replay(self):
        r=self._queue_then_revoke(source_allowed=False)
        sink=MockSink()
        self.assertEqual(self.pipe.deliver(r.event_id,sink,now=NOW+timedelta(seconds=2)),EventStatus.SUPERSEDED)
        self.assertEqual(sink.deliveries,[])

if __name__=='__main__':unittest.main(verbosity=2)
