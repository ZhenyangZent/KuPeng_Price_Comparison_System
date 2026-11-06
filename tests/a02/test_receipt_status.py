from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from a01_app.receipt import ReceiptError, receipt_status, validate_receipt


NOW = datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc)
UUID1 = "11111111-1111-4111-8111-111111111111"
UUID2 = "22222222-2222-4222-8222-222222222222"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReceiptFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.inbox = root / "inbox"
        self.snapshot = root / "snapshots/latest.json"
        self.receipt = root / "receipts/latest.json"
        self.inbox.mkdir(parents=True)
        self.snapshot.parent.mkdir(parents=True)
        self.receipt.parent.mkdir(parents=True)
        self.snapshot_bytes = json.dumps({
            "schema_version": "CDH-EXCHANGE-1",
            "snapshot_generated_at_utc": "2026-11-03T00:29:00Z",
            "source": "D01_LOCAL_LEDGER",
            "counts": {"total_entries": 0, "real_observations": 0, "synthetic_observations": 0, "unverified_leads": 0},
            "items": [],
            "source_status": {"live_coupang_discovery": "SOURCE_BLOCKED", "permission_checked_at_utc": None},
        }, separators=(",", ":")).encode("utf-8") + b"\n"
        self.snapshot.write_bytes(self.snapshot_bytes)

    def put(self, uuid_text: str = UUID1, data: bytes = b'{"synthetic":"submission"}\n') -> Path:
        path = self.inbox / f"submission_{uuid_text}.json"
        path.write_bytes(data)
        return path

    def document(self, entries: list[dict] | None = None, generated: str = "2026-11-03T00:30:00Z") -> dict:
        return {
            "receipt_version": "CDH-D01-RECEIPT-1",
            "exchange_version": "CDH-EXCHANGE-1",
            "generated_at_utc": generated,
            "source_status": "SOURCE_BLOCKED",
            "snapshot_sha256": digest(self.snapshot_bytes),
            "entries": entries or [],
        }

    def entry(self, path: Path, status: str = "IMPORTED", reason_code=None) -> dict:
        return {"filename": path.name, "file_sha256": digest(path.read_bytes()), "status": status, "reason_code": reason_code}

    def write_receipt(self, value: dict) -> None:
        self.receipt.write_text(json.dumps(value), encoding="utf-8")


class ReceiptStatusTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return ReceiptFixture(Path(temporary.name))

    def test_processed_file_that_remains_in_inbox_is_not_pending(self):
        fx = self.fixture(); path = fx.put(); fx.write_receipt(fx.document([fx.entry(path, "IMPORTED")]))
        result = receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW)
        self.assertEqual(result.state, "READY")
        self.assertEqual((result.raw_inbox_count, result.imported_count, result.pending_count), (1, 1, 0))

    def test_duplicate_noop_is_processed_when_hash_matches(self):
        fx = self.fixture(); path = fx.put(); fx.write_receipt(fx.document([fx.entry(path, "DUPLICATE_NOOP")]))
        result = receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW)
        self.assertEqual((result.imported_count, result.pending_count), (1, 0))

    def test_duplicate_noop_identical_replay_is_processed_when_hash_matches(self):
        fx = self.fixture(); path = fx.put(); fx.write_receipt(fx.document([fx.entry(path, "DUPLICATE_NOOP", "IDENTICAL_REPLAY")]))
        result = receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW)
        self.assertEqual((result.state, result.imported_count, result.pending_count), ("READY", 1, 0))

    def test_duplicate_noop_unknown_reason_is_rejected(self):
        fx = self.fixture(); path = fx.put(); entry = fx.entry(path, "DUPLICATE_NOOP", "SUSPICIOUS")
        with self.assertRaises(ReceiptError): validate_receipt(fx.document([entry]), now=NOW)

    def test_imported_identical_replay_reason_is_rejected(self):
        fx = self.fixture(); path = fx.put(); entry = fx.entry(path, "IMPORTED", "IDENTICAL_REPLAY")
        with self.assertRaises(ReceiptError): validate_receipt(fx.document([entry]), now=NOW)

    def test_mixed_import_and_exact_replay_counts_all_processed(self):
        fx = self.fixture(); first = fx.put(); second = fx.put(UUID2, b'{"second":true}\n')
        fx.write_receipt(fx.document([
            fx.entry(first, "DUPLICATE_NOOP", "IDENTICAL_REPLAY"),
            fx.entry(second, "IMPORTED"),
        ]))
        result = receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW)
        self.assertEqual((result.state, result.imported_count, result.pending_count), ("READY", 2, 0))

    def test_new_late_file_is_pending_until_next_receipt(self):
        fx = self.fixture(); first = fx.put(); fx.write_receipt(fx.document([fx.entry(first)])); fx.put(UUID2, b'{"later":true}\n')
        result = receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW)
        self.assertEqual((result.raw_inbox_count, result.imported_count, result.pending_count), (2, 1, 1))

    def test_changed_file_hash_returns_to_pending(self):
        fx = self.fixture(); path = fx.put(); receipt = fx.document([fx.entry(path)]); path.write_bytes(b'{"changed":true}\n'); fx.write_receipt(receipt)
        result = receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW)
        self.assertEqual((result.imported_count, result.pending_count), (0, 1))

    def test_quarantined_is_error_not_imported(self):
        fx = self.fixture(); path = fx.put(); fx.write_receipt(fx.document([fx.entry(path, "QUARANTINED", "INVALID_SCHEMA")]))
        result = receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW)
        self.assertEqual((result.imported_count, result.pending_count, result.quarantined_count), (0, 0, 1))

    def test_retry_needed_remains_pending(self):
        fx = self.fixture(); path = fx.put(); fx.write_receipt(fx.document([fx.entry(path, "RETRY_NEEDED", "LOCKED")]))
        result = receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW)
        self.assertEqual((result.pending_count, result.retry_count), (1, 1))

    def test_no_d01_receipt_is_not_false_zero(self):
        fx = self.fixture(); fx.put()
        result = receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW)
        self.assertEqual(result.state, "NO_RECEIPT")
        self.assertFalse(result.counts_known)
        self.assertEqual(result.raw_inbox_count, 1)

    def test_no_d01_install_and_empty_inbox_is_still_unknown(self):
        fx = self.fixture()
        result = receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW)
        self.assertEqual(result.state, "NO_RECEIPT")
        self.assertIsNone(result.pending_count)

    def test_snapshot_hash_mismatch_is_syncing_not_complete(self):
        fx = self.fixture(); path = fx.put(); fx.write_receipt(fx.document([fx.entry(path)])); fx.snapshot.write_bytes(b'{"newer":true}\n')
        result = receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW)
        self.assertEqual(result.state, "SYNCING")
        self.assertFalse(result.counts_known)

    def test_invalid_snapshot_with_matching_hash_is_syncing(self):
        fx = self.fixture(); path = fx.put(); fx.snapshot_bytes = b'{"broken":true}\n'; fx.snapshot.write_bytes(fx.snapshot_bytes); fx.write_receipt(fx.document([fx.entry(path)]))
        result = receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW)
        self.assertEqual(result.state, "SYNCING")
        self.assertFalse(result.counts_known)

    def test_missing_snapshot_is_syncing(self):
        fx = self.fixture(); path = fx.put(); fx.write_receipt(fx.document([fx.entry(path)])); fx.snapshot.unlink()
        self.assertEqual(receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW).state, "SYNCING")

    def test_stale_receipt_is_explicit(self):
        fx = self.fixture(); path = fx.put(); fx.write_receipt(fx.document([fx.entry(path)], "2026-10-30T00:00:00Z"))
        result = receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW)
        self.assertEqual(result.state, "STALE"); self.assertTrue(result.receipt_stale)

    def test_invalid_snapshot_hash_is_rejected(self):
        fx = self.fixture(); value = fx.document(); value["snapshot_sha256"] = "x" * 64
        with self.assertRaises(ReceiptError): validate_receipt(value, now=NOW)

    def test_path_traversal_filename_is_rejected(self):
        fx = self.fixture(); value = fx.document([{"filename":"../submission_11111111-1111-4111-8111-111111111111.json","file_sha256":"0"*64,"status":"IMPORTED","reason_code":None}])
        with self.assertRaises(ReceiptError): validate_receipt(value, now=NOW)

    def test_duplicate_entries_are_rejected(self):
        fx = self.fixture(); path = fx.put(); entry = fx.entry(path)
        with self.assertRaises(ReceiptError): validate_receipt(fx.document([entry, dict(entry)]), now=NOW)

    def test_case_variant_filename_is_rejected(self):
        fx = self.fixture(); path = fx.put(); entry = fx.entry(path); entry["filename"] = entry["filename"].upper()
        with self.assertRaises(ReceiptError): validate_receipt(fx.document([entry]), now=NOW)

    def test_unknown_status_is_rejected(self):
        fx = self.fixture(); path = fx.put(); entry = fx.entry(path); entry["status"] = "COMPLETE"
        with self.assertRaises(ReceiptError): validate_receipt(fx.document([entry]), now=NOW)

    def test_future_schema_is_unknown(self):
        fx = self.fixture(); value = fx.document(); value["receipt_version"] = "CDH-D01-RECEIPT-2"; fx.write_receipt(value)
        self.assertEqual(receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW).state, "UNKNOWN")

    def test_receipt_entry_missing_current_file_is_unknown(self):
        fx = self.fixture(); path = fx.put(); entry = fx.entry(path); path.unlink(); fx.write_receipt(fx.document([entry]))
        self.assertEqual(receipt_status(fx.receipt, fx.snapshot, fx.inbox, now=NOW).state, "UNKNOWN")

    def test_receipt_never_upgrades_product_qualification(self):
        fx = self.fixture(); path = fx.put(); entry = fx.entry(path)
        self.assertEqual(set(entry), {"filename", "file_sha256", "status", "reason_code"})

    def test_processed_status_cannot_hide_reason_code(self):
        fx = self.fixture(); path = fx.put(); entry = fx.entry(path, "IMPORTED", "SUSPICIOUS")
        with self.assertRaises(ReceiptError): validate_receipt(fx.document([entry]), now=NOW)
