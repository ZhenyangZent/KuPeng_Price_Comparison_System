from __future__ import annotations

import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from n01_alerts.models import OutboxStatus, RequestConflict, StateConflict, StaleState
from n01_alerts.service import NotificationService
from n01_alerts.sinks import LocalSyntheticJsonlSink, MockSink, WindowsToastSinkInterface

from tests.n01.helpers import NOW, candidate, cleanup, state, workspace


class ServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace()
        self.service = NotificationService(self.root / "outbox.sqlite3")

    def tearDown(self) -> None:
        cleanup(self.root)

    def submit(self, item=None, latest=None, *, now=None):
        item = item or candidate()
        latest = latest or state(item)
        return self.service.submit(item, latest, now=now or NOW + timedelta(minutes=1))


class IdempotencyEpisodeTests(ServiceTestCase):
    def test_same_request_is_idempotent_across_restart(self) -> None:
        first = self.submit()
        reopened = NotificationService(self.root / "outbox.sqlite3")
        second = reopened.submit(candidate(), state(candidate()), now=NOW + timedelta(minutes=2))
        self.assertEqual(first.event_id, second.event_id)
        self.assertFalse(second.created)
        self.assertEqual(len(reopened.store.rows()), 1)

    def test_request_id_conflict_is_explicit(self) -> None:
        self.submit()
        changed = candidate(
            total_minor=400,
            subtotal_minor=400,
            source_revision=2,
            observed_at=NOW + timedelta(minutes=1),
            expires_at=NOW + timedelta(days=3, minutes=1),
        )
        with self.assertRaises(RequestConflict):
            self.submit(changed, state(changed), now=NOW + timedelta(minutes=2))

    def test_price_rebound_then_drop_creates_new_episode(self) -> None:
        first = self.submit()
        self.assertEqual(first.episode, 1)
        self.service.observe_rebound(
            candidate().scenario_scope,
            observed_at=NOW + timedelta(hours=1),
            total_minor=1200,
        )
        dropped = candidate(
            request_id="req-episode-2",
            source_revision=2,
            observed_at=NOW + timedelta(hours=2),
            expires_at=NOW + timedelta(days=3, hours=2),
        )
        second = self.submit(dropped, state(dropped), now=NOW + timedelta(hours=2, minutes=1))
        self.assertEqual(second.episode, 2)
        self.assertNotEqual(first.event_id, second.event_id)

    def test_frequent_lower_prices_dedupe_only_same_semantic(self) -> None:
        first = self.submit()
        lower = candidate(
            request_id="req-lower",
            total_minor=400,
            subtotal_minor=400,
            source_revision=2,
            observed_at=NOW + timedelta(minutes=10),
            expires_at=NOW + timedelta(days=3),
            cost_semantic_fingerprint="cost-lower",
        )
        second = self.submit(lower, state(lower), now=NOW + timedelta(minutes=11))
        self.assertNotEqual(first.event_id, second.event_id)
        self.assertEqual(second.episode, 1)

    def test_concurrent_same_submit_creates_one_event(self) -> None:
        item = candidate()

        def work(_):
            local = NotificationService(self.root / "outbox.sqlite3")
            return local.submit(item, state(item), now=NOW + timedelta(minutes=1)).event_id

        with ThreadPoolExecutor(max_workers=8) as pool:
            event_ids = list(pool.map(work, range(16)))
        self.assertEqual(len(set(event_ids)), 1)
        self.assertEqual(len(self.service.store.rows()), 1)


class StateAndRevocationTests(ServiceTestCase):
    def test_data_time_rollback_and_equal_conflict_rejected(self) -> None:
        item = candidate()
        self.submit(item, state(item))
        with self.assertRaises(StaleState):
            self.service.update_latest_state(
                state(item, observed_at=NOW - timedelta(seconds=1), expires_at=NOW + timedelta(days=1)),
                now=NOW + timedelta(minutes=2),
            )
        with self.assertRaises(StateConflict):
            self.service.update_latest_state(
                state(item, stock="OUT_OF_STOCK"),
                now=NOW + timedelta(minutes=2),
            )

    def test_membership_change_revokes_pending(self) -> None:
        result = self.submit()
        changed = state(
            candidate(),
            membership_context="NON_WOW",
            policy_epoch=2,
            observed_at=NOW + timedelta(minutes=5),
            expires_at=NOW + timedelta(days=3, minutes=5),
            revision_id="membership-2",
        )
        self.service.update_latest_state(changed, now=NOW + timedelta(minutes=5))
        row = self.service.store.row(result.event_id)
        self.assertEqual(row["status"], OutboxStatus.REVOKED)
        self.assertIn("MEMBERSHIP_CHANGED", row["revoked_reason"])

    def test_notification_disable_and_policy_epoch_revoke(self) -> None:
        result = self.submit()
        changed = state(
            candidate(),
            notifications_enabled=False,
            policy_epoch=2,
            observed_at=NOW + timedelta(minutes=5),
            expires_at=NOW + timedelta(days=3, minutes=5),
            revision_id="disabled-2",
        )
        self.service.update_latest_state(changed, now=NOW + timedelta(minutes=5))
        self.assertEqual(self.service.store.row(result.event_id)["status"], OutboxStatus.REVOKED)

    def test_explicit_revoke_is_idempotent(self) -> None:
        result = self.submit()
        self.assertTrue(self.service.revoke(result.event_id, reason="OPERATOR_REVOKED", now=NOW + timedelta(minutes=2)))
        self.assertFalse(self.service.revoke(result.event_id, reason="OPERATOR_REVOKED", now=NOW + timedelta(minutes=3)))

    def test_source_offline_is_filtered_before_enqueue(self) -> None:
        item = candidate()
        result = self.submit(item, state(item, source_available=False))
        self.assertEqual(result.status, "FILTERED")
        self.assertIn("SOURCE_OFFLINE", result.gate.reasons)
        self.assertEqual(self.service.store.rows(), [])


class DispatchRetryTests(ServiceTestCase):
    def test_mock_delivery_and_restart_readback(self) -> None:
        submitted = self.submit()
        sink = MockSink()
        result = self.service.dispatch_one(sink, worker_id="w1", now=NOW + timedelta(minutes=2))
        self.assertEqual(result.status, "DELIVERED")
        reopened = NotificationService(self.root / "outbox.sqlite3")
        self.assertEqual(reopened.store.row(submitted.event_id)["status"], OutboxStatus.DELIVERED)
        self.assertEqual(len(sink.deliveries), 1)

    def test_two_transient_retries_then_success(self) -> None:
        submitted = self.submit()
        sink = MockSink(failures_before_success=2)
        statuses = []
        for offset in (2, 10, 20):
            statuses.append(
                self.service.dispatch_one(
                    sink,
                    worker_id="w2",
                    now=NOW + timedelta(minutes=offset),
                ).status
            )
        self.assertEqual(statuses, ["RETRY", "RETRY", "DELIVERED"])
        self.assertEqual(len(self.service.store.attempts(submitted.event_id)), 3)

    def test_ten_transient_retries_then_success(self) -> None:
        item = candidate(expires_at=NOW + timedelta(days=30))
        submitted = self.submit(item, state(item))
        sink = MockSink(failures_before_success=10)
        statuses = []
        for attempt in range(11):
            statuses.append(
                self.service.dispatch_one(
                    sink,
                    worker_id="w10",
                    now=NOW + timedelta(hours=attempt + 1),
                ).status
            )
        self.assertEqual(statuses.count("RETRY"), 10)
        self.assertEqual(statuses[-1], "DELIVERED")
        self.assertEqual(len(self.service.store.attempts(submitted.event_id)), 11)

    def test_message_expiry_prevents_delivery(self) -> None:
        item = candidate(expires_at=NOW + timedelta(minutes=2))
        submitted = self.submit(item, state(item), now=NOW + timedelta(minutes=1))
        result = self.service.dispatch_one(MockSink(), worker_id="wx", now=NOW + timedelta(minutes=3))
        self.assertEqual(result.status, "IDLE")
        self.assertEqual(self.service.store.row(submitted.event_id)["status"], OutboxStatus.EXPIRED)

    def test_stale_lease_is_recovered_after_restart(self) -> None:
        submitted = self.submit()
        claimed = self.service.store.claim(worker_id="crashed", now=NOW + timedelta(minutes=2), lease_seconds=1)
        self.assertEqual(claimed["event_id"], submitted.event_id)
        reopened = NotificationService(self.root / "outbox.sqlite3")
        result = reopened.dispatch_one(MockSink(), worker_id="recovery", now=NOW + timedelta(minutes=3))
        self.assertEqual(result.status, "DELIVERED")

    def test_unauthorized_sink_is_rejected(self) -> None:
        self.submit()
        with self.assertRaisesRegex(TypeError, "N01_SINK_NOT_AUTHORIZED"):
            self.service.dispatch_one(WindowsToastSinkInterface(), worker_id="bad", now=NOW + timedelta(minutes=2))

    def test_local_jsonl_sink_is_idempotent_and_rooted(self) -> None:
        submitted = self.submit()
        sink = LocalSyntheticJsonlSink(self.root / "logs/events.jsonl", synthetic_root=self.root)
        result = self.service.dispatch_one(sink, worker_id="jsonl", now=NOW + timedelta(minutes=2))
        self.assertEqual(result.status, "DELIVERED")
        line = json.loads((self.root / "logs/events.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(line["event_id"], submitted.event_id)
        self.assertTrue(line["synthetic"])
        with self.assertRaisesRegex(ValueError, "OUTSIDE_SYNTHETIC_ROOT"):
            LocalSyntheticJsonlSink(self.root.parent / "escape.jsonl", synthetic_root=self.root)


class DigestAndObservabilityTests(ServiceTestCase):
    def test_daily_digest_reuses_gate_and_blocks_changed_state(self) -> None:
        item = candidate()
        self.submit(item, state(item))
        digest = self.service.daily_digest(NOW.astimezone().date(), now=NOW + timedelta(minutes=2))
        # Host timezone is not authoritative; the contract explicitly uses Taipei.
        if not digest["items"]:
            digest = self.service.daily_digest(
                NOW.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Taipei")).date(),
                now=NOW + timedelta(minutes=2),
            )
        self.assertEqual(len(digest["items"]), 1)
        changed = state(
            item,
            source_available=False,
            source_revision=2,
            observed_at=NOW + timedelta(minutes=3),
            expires_at=NOW + timedelta(days=3, minutes=3),
            revision_id="offline-2",
        )
        self.service.update_latest_state(changed, now=NOW + timedelta(minutes=3))
        digest = self.service.daily_digest(
            NOW.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Taipei")).date(),
            now=NOW + timedelta(minutes=4),
        )
        self.assertEqual(len(digest["items"]), 0)
        self.assertIn("SOURCE_OFFLINE", digest["blocked"][0]["gate_reasons"])

    def test_cross_day_digest_separates_taipei_days(self) -> None:
        first = candidate(observed_at=NOW, expires_at=NOW + timedelta(days=4))
        self.submit(first, state(first), now=NOW + timedelta(minutes=1))
        second_time = NOW + timedelta(days=1)
        second = candidate(
            request_id="day-2",
            source_revision=2,
            observed_at=second_time,
            expires_at=second_time + timedelta(days=3),
            cost_semantic_fingerprint="day-2-cost",
            total_minor=400,
            subtotal_minor=400,
        )
        self.submit(second, state(second), now=second_time + timedelta(minutes=1))
        from zoneinfo import ZoneInfo

        day1 = (NOW + timedelta(minutes=1)).astimezone(ZoneInfo("Asia/Taipei")).date()
        day2 = (second_time + timedelta(minutes=1)).astimezone(ZoneInfo("Asia/Taipei")).date()
        self.assertEqual(len(self.service.daily_digest(day1, now=second_time + timedelta(minutes=2))["blocked"]), 1)
        self.assertEqual(len(self.service.daily_digest(day2, now=second_time + timedelta(minutes=2))["items"]), 1)

    def test_stats_report_attempts_retries_filters_and_no_real_delivery(self) -> None:
        self.submit()
        self.service.dispatch_one(MockSink(failures_before_success=1), worker_id="stats", now=NOW + timedelta(minutes=2))
        blocked = candidate(request_id="blocked", source_revision=2, observed_at=NOW + timedelta(minutes=3))
        self.submit(blocked, state(blocked, source_available=False), now=NOW + timedelta(minutes=4))
        stats = self.service.stats()
        self.assertEqual(stats["attempt_count"], 1)
        self.assertEqual(stats["retry_count"], 1)
        self.assertEqual(stats["filtered_count"], 1)
        self.assertFalse(stats["external_exactly_once_claimed"])
        self.assertEqual(stats["real_delivery_count"], 0)

    def test_source_has_no_network_registry_or_real_notification_imports(self) -> None:
        forbidden = ("import requests", "import urllib", "import socket", "import winreg", "from winrt", "plyer")
        for path in Path("apps/n01").rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} in {path}")


if __name__ == "__main__":
    unittest.main()
