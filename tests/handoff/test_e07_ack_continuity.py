from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = PROJECT_ROOT / "scripts/orchestrator_handoff"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import flat_queue


LOCAL_TEMP = PROJECT_ROOT / "review/E07/test_tmp"
LOCAL_TEMP.mkdir(parents=True, exist_ok=True)


def make_release(root: Path, name: str, marker: str) -> Path:
    release = root / "review/releases" / name
    release.parent.mkdir(parents=True, exist_ok=True)
    content = marker.encode()
    manifest = {
        "payloads": [
            {
                "path": "payload/result.txt",
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ]
    }
    with zipfile.ZipFile(release, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("payload/result.txt", content)
        archive.writestr("REVIEW_MANIFEST.json", json.dumps(manifest))
    return release


class E07AckContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=LOCAL_TEMP)
        self.root = Path(self.temp.name) / "酷澎比價系統"
        (self.root / "review/releases").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_partial_batch_missing_queue_and_replay_are_safe(self) -> None:
        names = (
            "CDH_A08_001_REVIEW.zip",
            "CDH_B09_001_REVIEW.zip",
            "CDH_B09_002_REVIEW.zip",
        )
        releases = {name: make_release(self.root, name, name) for name in names}
        hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in releases.items()}
        flat_queue.enqueue_releases(self.root, list(names[:2]))
        ack_file = self.root / "review/E07/acks.json"
        ack_file.parent.mkdir(parents=True)
        ack_file.write_text(
            json.dumps(
                {
                    "schema": "CDH-EXACT-ACK-1",
                    "acks": [
                        {"filename": name, "sha256": hashes[name]}
                        for name in names
                    ],
                }
            ),
            encoding="utf-8",
        )
        first = flat_queue.archive_ack_file(self.root, ack_file, "R06_ACK", True)
        self.assertEqual(first["archived_count"], 2)
        self.assertEqual(first["failure_count"], 1)
        self.assertEqual(first["results"][2]["error"], "QUEUE_ITEM_MISSING")
        self.assertTrue(releases[names[2]].exists())
        self.assertFalse((self.root / "review/90_UPLOADED_ARCHIVE/R06_ACK" / names[2]).exists())

        replay = flat_queue.archive_ack_file(self.root, ack_file, "R06_ACK", True)
        self.assertEqual(replay["already_archived_count"], 2)
        self.assertEqual(replay["failure_count"], 1)
        ledger = (self.root / "docs/HANDOFF/RECEIPT_LEDGER.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(ledger), 2)

    def test_completed_move_is_recovered_without_release_mutation(self) -> None:
        name = "CDH_B09_002_REVIEW.zip"
        release = make_release(self.root, name, "canonical-candidate")
        digest = hashlib.sha256(release.read_bytes()).hexdigest()
        flat_queue.enqueue_releases(self.root, [name])
        archive = self.root / "review/90_UPLOADED_ARCHIVE/R06_INTERRUPTED"
        archive.mkdir(parents=True)
        os.replace(self.root / "review/00_TO_UPLOAD" / name, archive / name)
        result = flat_queue.archive_queue_item(
            self.root, name, digest, "R06_INTERRUPTED", True
        )
        self.assertEqual(result["status"], "RECOVERED_AFTER_COMPLETED_MOVE")
        self.assertEqual(hashlib.sha256(release.read_bytes()).hexdigest(), digest)

    def test_checked_in_ledger_preserves_b09_supersession(self) -> None:
        ledger = json.loads(
            (PROJECT_ROOT / "docs/HANDOFF/R05_RECEIPT_STATUS_LEDGER.json").read_text(
                encoding="utf-8"
            )
        )
        records = {record["filename"]: record for record in ledger["records"]}
        old = records["CDH_B09_001_REVIEW.zip"]
        new = records["CDH_B09_002_REVIEW.zip"]
        self.assertEqual(old["handoff_status"], "RECEIVED_SUPERSEDED")
        self.assertFalse(old["canonical_candidate"])
        self.assertTrue(old["historical_release_preserved"])
        self.assertEqual(new["handoff_status"], "RECEIVED_CANONICAL_CANDIDATE")
        self.assertTrue(new["canonical_candidate"])
        self.assertEqual(ledger["record_count"], 9)
        self.assertFalse(ledger["functional_pass_inferred_from_receipt"])

    def test_lock_recovery_uses_single_lstat_mode_without_is_file_race(self) -> None:
        path = self.root / "review/E02/locks/flat_queue.lock"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"pid": os.getpid(), "token": "active"}),
            encoding="ascii",
        )
        lock = flat_queue._QueueLock(path)
        with mock.patch.object(Path, "is_file", side_effect=AssertionError("second lookup")):
            self.assertFalse(lock._recover_abandoned_lock())

    def test_lock_release_retries_windows_sharing_violation(self) -> None:
        path = self.root / "review/E02/locks/flat_queue.lock"
        path.parent.mkdir(parents=True)
        lock = flat_queue._QueueLock(path)
        real_unlink = Path.unlink
        attempts = 0

        def flaky_unlink(candidate: Path, *args, **kwargs):
            nonlocal attempts
            if candidate == path:
                attempts += 1
                if attempts < 3:
                    raise PermissionError("synthetic Windows sharing violation")
            return real_unlink(candidate, *args, **kwargs)

        with lock:
            with mock.patch.object(Path, "unlink", autospec=True, side_effect=flaky_unlink):
                lock.__exit__(None, None, None)
        self.assertEqual(attempts, 3)
        self.assertFalse(path.exists())

    def test_directory_creation_retries_concurrent_windows_permission_error(self) -> None:
        target = self.root / "review/E02/locks"
        real_mkdir = Path.mkdir
        attempts = 0

        def flaky_mkdir(candidate: Path, *args, **kwargs):
            nonlocal attempts
            if candidate == target:
                attempts += 1
                if attempts == 1:
                    raise PermissionError("synthetic concurrent mkdir visibility race")
            return real_mkdir(candidate, *args, **kwargs)

        with mock.patch.object(Path, "mkdir", autospec=True, side_effect=flaky_mkdir):
            resolved = flat_queue._ensure_dir(self.root, "review/E02/locks")
        self.assertGreaterEqual(attempts, 2)
        self.assertTrue(resolved.is_dir())


if __name__ == "__main__":
    unittest.main()
