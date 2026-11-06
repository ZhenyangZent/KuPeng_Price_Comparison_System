from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "d01"))

from cdh_d01.database import connect, migrate
from cdh_d01.ingest import ingest_json_bytes
from cdh_d01.sync import (
    CapacityError,
    ConcurrentSyncError,
    SingleWriterLock,
    SyncError,
    SyncPaths,
    UnsafePathError,
    run_sync,
)


def utc_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def payload(*, submission_id: str | None = None, price: int = 5) -> dict[str, object]:
    stamp = utc_text()
    return {
        "schema_version": "CDH-EXCHANGE-1",
        "submission_id": submission_id or str(uuid.uuid4()),
        "record_type": "USER_PRICE_OBSERVATION",
        "created_at_utc": stamp,
        "observed_at_utc": stamp,
        "source": {
            "source_kind": "USER_ENTERED",
            "permission_scope": "USER_PROVIDED_ONLY",
            "url": "https://www.tw.coupang.com/vp/products/123?itemId=9",
            "note": "synthetic D02 test input",
        },
        "offer": {
            "platform": "TW_COUPANG",
            "product_title": "D02 合成測試商品",
            "product_id": None,
            "variant_id": None,
            "seller_id": None,
            "displayed_price_twd": price,
            "price_basis": "DISPLAYED_UNKNOWN",
            "minimum_purchase_quantity": None,
            "shipping_status": "UNKNOWN",
            "shipping_fee_twd": None,
            "stock_status": "UNKNOWN",
            "coupon_status": "UNKNOWN",
            "account_eligibility_status": "UNKNOWN",
            "mandatory_fee_status": "UNKNOWN",
            "notes": "",
        },
        "is_synthetic": False,
    }


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode(
        "utf-8"
    )


class D02SyncCase(unittest.TestCase):
    def setUp(self) -> None:
        temp_root = ROOT / "review" / "D02" / "test_tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.root = Path(self.temp.name).resolve()
        self.paths = SyncPaths.for_root(self.root)
        conn = connect(self.paths.database)
        try:
            migrate(conn)
        finally:
            conn.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def put(self, value: dict[str, object], *, filename_id: str | None = None) -> Path:
        self.paths.inbox.mkdir(parents=True, exist_ok=True)
        identifier = filename_id or str(value["submission_id"])
        path = self.paths.inbox / f"submission_{identifier}.json"
        path.write_bytes(encoded(value))
        return path

    def db_value(self, sql: str):
        conn = sqlite3.connect(self.paths.database)
        try:
            return conn.execute(sql).fetchone()[0]
        finally:
            conn.close()

    def receipt(self) -> dict[str, object]:
        return json.loads((self.paths.receipts / "latest.json").read_text(encoding="utf-8"))

    def test_no_input_publishes_exact_empty_receipt_and_snapshot(self):
        result = run_sync(self.paths)
        self.assertEqual(result.cutoff_file_count, 0)
        self.assertEqual(result.entries, ())
        receipt = self.receipt()
        self.assertEqual(
            set(receipt),
            {"receipt_version", "exchange_version", "generated_at_utc", "source_status", "snapshot_sha256", "entries"},
        )
        self.assertEqual(receipt["entries"], [])
        self.assertEqual(receipt["source_status"], "SOURCE_BLOCKED")
        self.assertEqual(
            receipt["snapshot_sha256"],
            hashlib.sha256((self.paths.snapshots / "latest.json").read_bytes()).hexdigest(),
        )

    def test_one_valid_a01_style_price_imports_once(self):
        value = payload(price=19)
        path = self.put(value)
        result = run_sync(self.paths)
        self.assertEqual(result.entries[0].status, "IMPORTED")
        self.assertEqual(result.entries[0].file_sha256, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM observations"), 1)
        self.assertEqual(self.db_value("SELECT displayed_price_twd FROM observations"), 19)

    def test_zero_price_remains_unverified_with_unknown_qualification_fields(self):
        self.put(payload(price=0))
        run_sync(self.paths)
        conn = sqlite3.connect(self.paths.database)
        try:
            row = conn.execute(
                """SELECT displayed_price_twd,qualification_state,shipping_status,shipping_fee_twd,
                coupon_status,account_eligibility_status,mandatory_fee_status FROM observations"""
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, (0, "UNVERIFIED", "UNKNOWN", None, "UNKNOWN", "UNKNOWN", "UNKNOWN"))

    def test_malformed_file_is_quarantined_and_cached(self):
        identifier = str(uuid.uuid4())
        self.paths.inbox.mkdir(parents=True)
        path = self.paths.inbox / f"submission_{identifier}.json"
        path.write_bytes(b"{bad")
        first = run_sync(self.paths)
        attempts = self.db_value("SELECT COUNT(*) FROM ingest_attempts")
        second = run_sync(self.paths)
        self.assertEqual(first.entries[0].status, "QUARANTINED")
        self.assertEqual(first.entries[0].reason_code, "MALFORMED_JSON")
        self.assertEqual(second.entries[0].status, "QUARANTINED")
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM ingest_attempts"), attempts)
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM quarantine"), 1)

    def test_exact_replay_is_noop_without_attempt_log_growth(self):
        self.put(payload())
        first = run_sync(self.paths)
        attempt_count = self.db_value("SELECT COUNT(*) FROM ingest_attempts")
        second = run_sync(self.paths)
        self.assertEqual(first.entries[0].status, "IMPORTED")
        self.assertEqual(second.entries[0].status, "DUPLICATE_NOOP")
        self.assertEqual(second.entries[0].reason_code, "IDENTICAL_REPLAY")
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM ingest_attempts"), attempt_count)
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM observations"), 1)
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM sync_file_outcomes"), 1)

    def test_changed_file_with_same_submission_id_is_conflict(self):
        identifier = str(uuid.uuid4())
        path = self.put(payload(submission_id=identifier, price=5))
        run_sync(self.paths)
        path.write_bytes(encoded(payload(submission_id=identifier, price=6)))
        result = run_sync(self.paths)
        self.assertEqual(result.entries[0].status, "QUARANTINED")
        self.assertEqual(result.entries[0].reason_code, "SUBMISSION_ID_CONFLICT")
        self.assertEqual(self.db_value("SELECT displayed_price_twd FROM observations"), 5)
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM observations"), 1)

    def test_file_added_after_cutoff_waits_until_next_cycle(self):
        first = payload(price=1)
        second = payload(price=2)
        self.put(first)

        def add_second() -> None:
            self.put(second)

        initial = run_sync(self.paths, _after_cutoff=add_second)
        self.assertEqual([entry.filename for entry in initial.entries], [f"submission_{first['submission_id']}.json"])
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM observations"), 1)
        followup = run_sync(self.paths)
        self.assertEqual(len(followup.entries), 2)
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM observations"), 2)

    def test_recovery_after_database_commit_before_snapshot(self):
        self.put(payload())
        with self.assertRaisesRegex(SyncError, "after database commit"):
            run_sync(self.paths, _fault="AFTER_DATABASE_COMMIT")
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM observations"), 1)
        attempts = self.db_value("SELECT COUNT(*) FROM ingest_attempts")
        self.assertFalse((self.paths.snapshots / "latest.json").exists())
        self.assertFalse((self.paths.receipts / "latest.json").exists())
        recovered = run_sync(self.paths)
        self.assertEqual(recovered.entries[0].status, "DUPLICATE_NOOP")
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM ingest_attempts"), attempts)
        self.assertTrue((self.paths.receipts / "latest.json").is_file())

    def test_recovery_after_snapshot_before_receipt(self):
        self.put(payload())
        with self.assertRaisesRegex(SyncError, "after snapshot"):
            run_sync(self.paths, _fault="AFTER_SNAPSHOT")
        snapshot = self.paths.snapshots / "latest.json"
        self.assertTrue(snapshot.is_file())
        self.assertFalse((self.paths.receipts / "latest.json").exists())
        attempts = self.db_value("SELECT COUNT(*) FROM ingest_attempts")
        recovered = run_sync(self.paths)
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM observations"), 1)
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM ingest_attempts"), attempts)
        self.assertEqual(self.receipt()["snapshot_sha256"], hashlib.sha256(snapshot.read_bytes()).hexdigest())
        self.assertFalse(recovered.snapshot_written)

    def test_repeat_sync_reuses_unchanged_snapshot(self):
        self.put(payload())
        first = run_sync(self.paths)
        snapshot_count = len(list(self.paths.snapshots.glob("snapshot_*.json")))
        second = run_sync(self.paths)
        self.assertTrue(first.snapshot_written)
        self.assertFalse(second.snapshot_written)
        self.assertEqual(len(list(self.paths.snapshots.glob("snapshot_*.json"))), snapshot_count)
        self.assertEqual(first.snapshot_sha256, second.snapshot_sha256)

    def test_readers_never_observe_partial_snapshot_or_receipt(self):
        run_sync(self.paths)
        errors: list[Exception] = []
        reads: list[int] = []
        stop = threading.Event()

        def reader() -> None:
            while not stop.is_set():
                for path in (self.paths.snapshots / "latest.json", self.paths.receipts / "latest.json"):
                    try:
                        json.loads(path.read_text(encoding="utf-8"))
                        reads.append(1)
                    except PermissionError:
                        continue
                    except Exception as exc:  # pragma: no cover - asserted below
                        errors.append(exc)
                        stop.set()
                        return

        thread = threading.Thread(target=reader)
        thread.start()
        try:
            for index in range(8):
                self.put(payload(price=index))
                run_sync(self.paths)
        finally:
            stop.set()
            thread.join()
        self.assertEqual(errors, [])
        self.assertGreater(len(reads), 0)

    def test_single_writer_lock_refuses_concurrent_cycle(self):
        with SingleWriterLock(self.paths.lock):
            with self.assertRaises(ConcurrentSyncError):
                run_sync(self.paths)
        self.assertFalse((self.paths.receipts / "latest.json").exists())

    def test_dry_run_changes_no_database_or_exchange_outputs(self):
        self.put(payload())
        before = hashlib.sha256(self.paths.database.read_bytes()).hexdigest()
        result = run_sync(self.paths, dry_run=True)
        after = hashlib.sha256(self.paths.database.read_bytes()).hexdigest()
        self.assertTrue(result.dry_run)
        self.assertEqual(result.entries[0].status, "IMPORTED")
        self.assertEqual(before, after)
        self.assertFalse(self.paths.lock.exists())
        self.assertFalse(self.paths.snapshots.exists())
        self.assertFalse(self.paths.receipts.exists())
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM observations"), 0)

    def test_symlink_or_reparse_entry_is_rejected_without_receipt(self):
        value = payload()
        target = self.put(value)
        with mock.patch("cdh_d01.sync._is_reparse_or_symlink", side_effect=lambda path: Path(path) == target):
            with self.assertRaises(UnsafePathError):
                run_sync(self.paths)
        self.assertFalse((self.paths.receipts / "latest.json").exists())

    def test_real_symlink_is_rejected_when_platform_allows_creation(self):
        self.paths.inbox.mkdir(parents=True)
        source = self.root / "source.json"
        value = payload()
        source.write_bytes(encoded(value))
        link = self.paths.inbox / f"submission_{value['submission_id']}.json"
        try:
            os.symlink(source, link)
        except OSError:
            self.skipTest("platform policy does not allow unprivileged symlink creation")
        with self.assertRaises(UnsafePathError):
            run_sync(self.paths)

    def test_wrong_paths_are_rejected(self):
        wrong = SyncPaths(
            root=self.paths.root,
            database=self.paths.database,
            inbox=self.root / "wrong-inbox",
            snapshots=self.paths.snapshots,
            receipts=self.paths.receipts,
            lock=self.paths.lock,
        )
        with self.assertRaisesRegex(UnsafePathError, "wrong inbox path"):
            run_sync(wrong, dry_run=True)

    def test_capacity_excess_fails_closed_without_receipt(self):
        self.put(payload())
        self.put(payload())
        with mock.patch("cdh_d01.sync.MAX_RECEIPT_ENTRIES", 1):
            with self.assertRaises(CapacityError):
                run_sync(self.paths)
        self.assertFalse((self.paths.receipts / "latest.json").exists())
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM observations"), 0)

    def test_changed_during_read_is_retry_needed_and_not_imported(self):
        value = payload()
        path = self.put(value)
        data = path.read_bytes()
        with mock.patch("cdh_d01.sync._stable_read", return_value=(data, False)):
            result = run_sync(self.paths)
        self.assertEqual(result.entries[0].status, "RETRY_NEEDED")
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM observations"), 0)
        self.assertEqual(self.receipt()["entries"][0]["status"], "RETRY_NEEDED")

    def test_filename_payload_mismatch_is_quarantined(self):
        value = payload()
        self.put(value, filename_id=str(uuid.uuid4()))
        result = run_sync(self.paths)
        self.assertEqual(result.entries[0].status, "QUARANTINED")
        self.assertEqual(result.entries[0].reason_code, "FILENAME_SUBMISSION_ID_MISMATCH")
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM observations"), 0)

    def test_unapproved_feed_stays_quarantined_and_source_blocked(self):
        value = payload()
        value["source"]["source_kind"] = "APPROVED_FEED"
        value["source"]["permission_scope"] = "APPROVED"
        value["source"]["source_id"] = "coupang_tw_public"
        self.put(value)
        result = run_sync(self.paths)
        self.assertEqual(result.entries[0].reason_code, "SOURCE_OPERATION_NOT_APPROVED")
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM observations"), 0)
        self.assertEqual(self.receipt()["source_status"], "SOURCE_BLOCKED")
        self.assertEqual(self.db_value("SELECT COUNT(*) FROM source_permissions WHERE status='APPROVED'"), 0)

    def test_receipt_and_snapshot_versions_are_collision_safe_and_bounded(self):
        for index in range(5):
            self.put(payload(price=index))
            run_sync(self.paths)
        receipts = list(self.paths.receipts.glob("receipt_*.json"))
        snapshots = list(self.paths.snapshots.glob("snapshot_*.json"))
        self.assertEqual(len({path.name.casefold() for path in receipts}), len(receipts))
        self.assertEqual(len({path.name.casefold() for path in snapshots}), len(snapshots))
        with mock.patch("cdh_d01.sync.MAX_VERSIONED_RECEIPTS", 2), mock.patch(
            "cdh_d01.sync.MAX_VERSIONED_SNAPSHOTS", 2
        ):
            self.put(payload(price=99))
            run_sync(self.paths)
        self.assertLessEqual(len(list(self.paths.receipts.glob("receipt_*.json"))), 2)
        self.assertLessEqual(len(list(self.paths.snapshots.glob("snapshot_*.json"))), 2)

    def test_legacy_ingest_api_still_commits_by_default(self):
        conn = connect(self.root / "legacy.sqlite3")
        try:
            migrate(conn)
            result = ingest_json_bytes(conn, encoded(payload()), source_path="synthetic.json")
            self.assertEqual(result.status, "IMPORTED")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1)
        finally:
            conn.close()

    def test_source_contains_no_external_collection_or_scheduler_clients(self):
        runtime_files = list((ROOT / "apps" / "d01").rglob("*.py")) + [ROOT / "scripts" / "d02" / "d02_sync.py"]
        source = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files).lower()
        for forbidden in (
            "import requests",
            "urllib.request",
            "selenium",
            "playwright",
            "webbrowser",
            "winreg",
            "schtasks",
            "scheduledtask",
            "firefox profile",
        ):
            self.assertNotIn(forbidden, source)
        launchers = "\n".join(
            path.read_text(encoding="utf-8", errors="replace").lower()
            for path in (ROOT / "scripts" / "d02").glob("run_local_sync.*")
        )
        for forbidden in ("schtasks", "register-scheduledtask", "new-service", "sc.exe create"):
            self.assertNotIn(forbidden, launchers)

    def test_documented_receipt_example_is_hash_bound_to_fixtures(self):
        submission = ROOT / "tests/d02/fixtures/submission_11111111-1111-4111-8111-111111111111.json"
        snapshot = ROOT / "docs/D02/examples/snapshot_example.json"
        receipt = json.loads((ROOT / "docs/D02/examples/receipt_example.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["entries"][0]["file_sha256"], hashlib.sha256(submission.read_bytes()).hexdigest())
        self.assertEqual(receipt["snapshot_sha256"], hashlib.sha256(snapshot.read_bytes()).hexdigest())
        self.assertEqual(receipt["entries"][0]["status"], "IMPORTED")
        self.assertEqual(receipt["source_status"], "SOURCE_BLOCKED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
