from __future__ import annotations

import json
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from a01_app.i02_preview import PreviewError, SyntheticSyncPreview, load_frozen_d02


ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = ROOT / "experiments" / "I02" / "test_runs"


class I02PreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="i02-", dir=TEST_ROOT)
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.service = SyntheticSyncPreview(root=ROOT, workspace=self.workspace)

    def test_four_cycle_import_replay_second_and_replay(self):
        first = self.service.run_cycle()
        replay = self.service.run_cycle()
        self.service.add_second_sample()
        second = self.service.run_cycle()
        second_replay = self.service.run_cycle()
        self.assertEqual((first.state, first.imported_count, first.pending_count), ("READY", 1, 0))
        self.assertEqual((replay.state, replay.imported_count, replay.pending_count), ("READY", 1, 0))
        self.assertEqual((second.state, second.imported_count, second.pending_count), ("READY", 2, 0))
        self.assertEqual((second_replay.state, second_replay.imported_count, second_replay.pending_count), ("READY", 2, 0))

    def test_dry_run_never_claims_ready_or_publishes_receipt(self):
        result = self.service.run_cycle(dry_run=True)
        self.assertEqual(result.state, "DRY_RUN")
        self.assertFalse(result.receipt_published)
        self.assertIsNone(result.imported_count)
        self.assertFalse((self.workspace / "data/exchange/receipts/latest.json").exists())

    def test_dry_run_after_real_receipt_is_still_labeled_dry_run(self):
        self.service.run_cycle()
        receipt = self.workspace / "data/exchange/receipts/latest.json"
        snapshot = self.workspace / "data/exchange/snapshots/latest.json"
        before = tuple(hashlib.sha256(path.read_bytes()).hexdigest() for path in (receipt, snapshot))
        result = self.service.run_cycle(dry_run=True)
        self.assertEqual((result.state, result.mode, result.receipt_published), ("DRY_RUN", "DRY_RUN", False))
        after = tuple(hashlib.sha256(path.read_bytes()).hexdigest() for path in (receipt, snapshot))
        self.assertEqual(after, before)

    def test_empty_inbox_publishes_valid_zero_receipt(self):
        result = self.service.run_cycle(seed_first=False)
        self.assertEqual((result.state, result.imported_count, result.pending_count), ("READY", 0, 0))

    def test_zero_price_stays_unverified_and_unknown_shipping(self):
        self.service.run_cycle()
        database = self.workspace / "data/d01/observations.sqlite3"
        connection = sqlite3.connect(database)
        row = connection.execute(
            "SELECT displayed_price_twd,qualification_state,shipping_status,shipping_fee_twd FROM observations"
        ).fetchone()
        connection.close()
        self.assertEqual(row, (0, "UNVERIFIED", "UNKNOWN", None))

    def test_corrupt_json_is_quarantined(self):
        _, paths = self.service.initialize()
        paths.inbox.mkdir(parents=True)
        (paths.inbox / "submission_33333333-3333-4333-8333-333333333333.json").write_bytes(b"{BROKEN")
        result = self.service.run_cycle(seed_first=False)
        self.assertEqual((result.state, result.imported_count, result.quarantined_count), ("READY", 0, 1))

    def test_changed_same_id_is_quarantined_without_new_observation(self):
        self.service.run_cycle()
        path = self.workspace / "data/exchange/inbox/submission_11111111-1111-4111-8111-111111111111.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["offer"]["displayed_price_twd"] = 8
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        result = self.service.run_cycle(seed_first=False)
        self.assertEqual((result.state, result.imported_count, result.quarantined_count), ("READY", 0, 1))
        connection = sqlite3.connect(self.workspace / "data/d01/observations.sqlite3")
        prices = connection.execute("SELECT displayed_price_twd FROM observations").fetchall()
        connection.close()
        self.assertEqual(prices, [(0,)])

    def test_restart_reads_same_isolated_state(self):
        self.service.run_cycle()
        restarted = SyntheticSyncPreview(root=ROOT, workspace=self.workspace)
        status = restarted.read_status()
        self.assertEqual((status.state, status.imported_count, status.pending_count), ("READY", 1, 0))

    def test_malformed_status_array_fails_closed_as_unknown(self):
        self.service.run_cycle()
        receipt = self.workspace / "data/exchange/receipts/latest.json"
        value = json.loads(receipt.read_text(encoding="utf-8"))
        value["entries"][0]["status"] = []
        receipt.write_text(json.dumps(value), encoding="utf-8")
        status = self.service.read_status()
        self.assertEqual(status.state, "UNKNOWN")
        self.assertIsNone(status.imported_count)

    def test_receipt_version_mismatch_fails_closed(self):
        self.service.run_cycle()
        receipt = self.workspace / "data/exchange/receipts/latest.json"
        value = json.loads(receipt.read_text(encoding="utf-8"))
        value["receipt_version"] = "CDH-D01-RECEIPT-2"
        receipt.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(self.service.read_status().state, "UNKNOWN")

    def test_snapshot_hash_mismatch_is_syncing(self):
        self.service.run_cycle()
        (self.workspace / "data/exchange/snapshots/latest.json").write_bytes(b"{}")
        status = self.service.read_status()
        self.assertEqual(status.state, "SYNCING")
        self.assertIsNone(status.imported_count)

    def test_sample_conflict_fails_closed(self):
        _, paths = self.service.initialize()
        paths.inbox.mkdir(parents=True)
        (paths.inbox / "submission_11111111-1111-4111-8111-111111111111.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(PreviewError, "SAMPLE_CONFLICT"):
            self.service.run_cycle()

    def test_production_data_workspace_is_rejected(self):
        with self.assertRaisesRegex(PreviewError, "WORKSPACE_NOT_ISOLATED"):
            SyntheticSyncPreview(root=ROOT, workspace=ROOT / "data")

    def test_workspace_root_itself_is_rejected(self):
        with self.assertRaisesRegex(PreviewError, "WORKSPACE_NOT_ISOLATED"):
            SyntheticSyncPreview(root=ROOT, workspace=ROOT / "experiments/I02")

    def test_missing_d02_is_explicit(self):
        fake_root = self.workspace / "fake_project"
        fake_root.mkdir()
        service = SyntheticSyncPreview(root=fake_root, workspace=fake_root / "experiments/I02/test")
        with self.assertRaisesRegex(PreviewError, "D02_UNAVAILABLE"):
            service.run_cycle()

    def test_version_mismatch_is_explicit(self):
        def incompatible(_root: Path):
            raise PreviewError("D02_VERSION_MISMATCH", "synthetic mismatch")

        service = SyntheticSyncPreview(root=ROOT, workspace=self.workspace, binding_loader=incompatible)
        with self.assertRaisesRegex(PreviewError, "D02_VERSION_MISMATCH"):
            service.run_cycle()

    def test_case_collision_sync_failure_is_wrapped_and_never_ready(self):
        real = load_frozen_d02(ROOT)

        class FailingBindings:
            SyncPaths = real.SyncPaths

            def initialize_database(self, path: Path) -> None:
                real.initialize_database(path)

            def run_sync(self, paths, *, dry_run: bool):
                raise RuntimeError("case-colliding inbox filename")

        service = SyntheticSyncPreview(root=ROOT, workspace=self.workspace, binding_loader=lambda _root: FailingBindings())
        with self.assertRaisesRegex(PreviewError, "D02_SYNC_FAILED"):
            service.run_cycle()

    def test_interrupted_runner_is_wrapped_and_never_ready(self):
        real = load_frozen_d02(ROOT)

        class InterruptedBindings:
            SyncPaths = real.SyncPaths

            def initialize_database(self, path: Path) -> None:
                real.initialize_database(path)

            def run_sync(self, paths, *, dry_run: bool):
                raise RuntimeError("injected interruption after snapshot before receipt")

        service = SyntheticSyncPreview(
            root=ROOT,
            workspace=self.workspace,
            binding_loader=lambda _root: InterruptedBindings(),
        )
        with self.assertRaisesRegex(PreviewError, "D02_SYNC_FAILED"):
            service.run_cycle()

    def test_frozen_d02_versions_and_source_status_match(self):
        bindings = load_frozen_d02(ROOT)
        self.assertEqual(bindings.sync_module.RECEIPT_VERSION, "CDH-D01-RECEIPT-1")
        self.assertEqual(bindings.sync_module.EXCHANGE_VERSION, "CDH-EXCHANGE-1")
        self.assertEqual(bindings.sync_module.SOURCE_STATUS, "SOURCE_BLOCKED")


if __name__ == "__main__":
    unittest.main()

