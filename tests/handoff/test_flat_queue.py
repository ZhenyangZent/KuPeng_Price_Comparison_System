from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = PROJECT_ROOT / "scripts/orchestrator_handoff"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import handoff_batch
import flat_queue

HandoffError = handoff_batch.HandoffError
LOCAL_TEMP = PROJECT_ROOT / "experiments/E02/test_tmp"
LOCAL_TEMP.mkdir(parents=True, exist_ok=True)


def make_release(root: Path, name: str, payload: bytes | str = b"synthetic") -> Path:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    releases = root / "review/releases"
    releases.mkdir(parents=True, exist_ok=True)
    path = releases / name
    record = {
        "path": "payload/result.txt",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    manifest = {
        "schema": "CDH-TEST-REVIEW-MANIFEST-1",
        "payload_count": 1,
        "payloads": [record],
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("payload/result.txt", payload)
        archive.writestr("REVIEW_MANIFEST.json", json.dumps(manifest, sort_keys=True))
    return path


def make_status_only(
    root: Path,
    name: str,
    *,
    include_summary: bool = True,
    prefix: str = "",
    use_aliases: bool = False,
    time_field: str = "created_at",
) -> Path:
    releases = root / "review/releases"
    releases.mkdir(parents=True, exist_ok=True)
    path = releases / name
    status_payload = {
        "task_id": "CDH-E-STATUS-TEST-001",
        "workline": "E",
        "status": "PASS",
    }
    if use_aliases:
        status_payload.update({time_field: "2026-11-06T00:00:00+08:00", "dependencies": {}})
    else:
        status_payload.update({"generated_at": "2026-11-06T00:00:00+08:00", "prerequisites": []})
    status = json.dumps(
        status_payload,
        sort_keys=True,
    ).encode("utf-8")
    members = {f"{prefix}STATUS.json": status}
    if include_summary:
        members[f"{prefix}SUMMARY.md"] = b"# Result\n\nCompleted a meaningful handoff rule update.\n"
    manifest = {
        "schema": "CDH-STATUS-ONLY-MANIFEST-1",
        "payloads": [
            {
                "path": PurePosixPath(member).name,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            for member, payload in sorted(members.items())
        ],
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member, payload in members.items():
            archive.writestr(member, payload)
        archive.writestr(f"{prefix}MANIFEST.json", json.dumps(manifest, sort_keys=True))
    return path


class FlatQueueCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=LOCAL_TEMP)
        self.root = Path(self.temp.name)
        (self.root / "review/releases").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_code(self, code: str, callable_, *args, **kwargs) -> HandoffError:
        with self.assertRaises(HandoffError) as raised:
            callable_(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)
        return raised.exception


class EnqueueTests(FlatQueueCase):
    def test_status_only_is_a_first_class_delivery_artifact(self) -> None:
        name = "CDH_E_R11_001_STATUS_ONLY.zip"
        make_status_only(self.root, name)
        result = flat_queue.enqueue_releases(self.root, [name])
        self.assertEqual(result["pending_count"], 1)
        item = flat_queue.list_queue(self.root)["files"][0]
        self.assertEqual(item["artifact_type"], "status_only")
        self.assertEqual(item["status_task_id"], "CDH-E-STATUS-TEST-001")
        self.assertEqual(item["status_workline"], "E")
        self.assertEqual(item["status_value"], "PASS")

    def test_status_only_missing_required_summary_is_rejected(self) -> None:
        name = "CDH_E_R11_002_STATUS_ONLY.zip"
        make_status_only(self.root, name, include_summary=False)
        self.assert_code(
            "STATUS_ONLY_REQUIRED_FILE_MISSING",
            flat_queue.enqueue_releases,
            self.root,
            [name],
        )

    def test_status_only_single_top_level_artifact_directory_is_supported(self) -> None:
        name = "CDH_G10_H10_DIAGNOSTIC_STATUS_ONLY.zip"
        make_status_only(
            self.root,
            name,
            prefix="CDH_G10_H10_DIAGNOSTIC_STATUS_ONLY/",
            use_aliases=True,
        )
        flat_queue.enqueue_releases(self.root, [name])
        item = flat_queue.list_queue(self.root)["files"][0]
        self.assertEqual(item["artifact_type"], "status_only")
        self.assertEqual(
            item["manifest"],
            "CDH_G10_H10_DIAGNOSTIC_STATUS_ONLY/MANIFEST.json",
        )
        self.assertEqual(item["status_generated_at"], "2026-11-06T00:00:00+08:00")

    def test_status_only_created_at_utc_alias_is_supported(self) -> None:
        name = "CDH_H_R11_003_STATUS_ONLY.zip"
        make_status_only(
            self.root,
            name,
            prefix="CDH_H_R11_003_STATUS_ONLY/",
            use_aliases=True,
            time_field="created_at_utc",
        )
        flat_queue.enqueue_releases(self.root, [name])
        item = flat_queue.list_queue(self.root)["files"][0]
        self.assertEqual(item["status_generated_at"], "2026-11-06T00:00:00+08:00")

    def test_review_filename_cannot_bypass_status_only_contract(self) -> None:
        name = "CDH_E_R11_003_STATUS_ONLY.zip"
        path = make_status_only(self.root, name)
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("evidence/undeclared.txt", "not declared")
        self.assert_code(
            "STATUS_ONLY_MANIFEST_COVERAGE",
            flat_queue.enqueue_releases,
            self.root,
            [name],
        )

    def test_root_manifest_accepts_path_to_sha256_mapping(self) -> None:
        name = "CDH_B06_001_REVIEW.zip"
        path = self.root / "review/releases" / name
        payload = b"synthetic mapping manifest"
        manifest = {
            "schema": "CDH-REVIEW-MANIFEST-1",
            "input_handoff_sha256": "0" * 64,
            "payload_count": 1,
            "payloads": {
                "payload/result.txt": hashlib.sha256(payload).hexdigest(),
            },
        }
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("payload/result.txt", payload)
            archive.writestr("REVIEW_MANIFEST.json", json.dumps(manifest))
        result = flat_queue.enqueue_releases(self.root, [name])
        self.assertEqual(result["pending_count"], 1)
        listing = flat_queue.list_queue(self.root)
        self.assertEqual(listing["files"][0]["manifest_records"], 1)
        self.assertEqual(listing["files"][0]["manifest_gate"], "PASS")

    def test_release_root_manifest_wins_over_nested_input_manifest(self) -> None:
        name = "CDH_D03_WEB_001_REVIEW.zip"
        path = self.root / "review/releases" / name
        payload = b"synthetic"
        manifest = {
            "payloads": [
                {
                    "path": "payload/result.txt",
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ]
        }
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("CDH_D03_WEB_001_REVIEW/payload/result.txt", payload)
            archive.writestr(
                "CDH_D03_WEB_001_REVIEW/MANIFEST.json",
                json.dumps(manifest),
            )
            archive.writestr("CDH_D03_WEB_001_REVIEW/input_contract/MANIFEST.json", "{}")
        result = flat_queue.enqueue_releases(self.root, [name])
        self.assertEqual(result["pending_count"], 1)
        listing = flat_queue.list_queue(self.root)
        self.assertEqual(listing["files"][0]["manifest_candidate_count"], 2)
        self.assertEqual(
            listing["files"][0]["manifest"],
            "CDH_D03_WEB_001_REVIEW/MANIFEST.json",
        )

    def test_five_worklines_enqueue_in_arbitrary_order(self) -> None:
        names = [
            "CDH_A05_001_REVIEW.zip",
            "CDH_B05_001_REVIEW.zip",
            "CDH_S02_001_REVIEW.zip",
            "CDH_N02_001_REVIEW.zip",
            "CDH_E02_001_REVIEW.zip",
        ]
        for index, name in enumerate(names):
            make_release(self.root, name, f"line-{index}")
        order = [names[3], names[0], names[4], names[1], names[2]]
        for expected_count, name in enumerate(order, 1):
            result = flat_queue.enqueue_releases(self.root, [name])
            self.assertEqual(result["pending_count"], expected_count)
        listing = flat_queue.list_queue(self.root)
        self.assertEqual(listing["pending_count"], 5)
        self.assertEqual({item["name"] for item in listing["files"]}, set(names))

    def test_later_workline_is_not_blocked_by_existing_queue_item(self) -> None:
        make_release(self.root, "CDH_A05_001_REVIEW.zip", "first")
        make_release(self.root, "CDH_F01_001_REVIEW.zip", "later")
        flat_queue.enqueue_releases(self.root, ["CDH_A05_001_REVIEW.zip"])
        flat_queue.enqueue_releases(self.root, ["CDH_F01_001_REVIEW.zip"])
        self.assertEqual(flat_queue.list_queue(self.root)["pending_count"], 2)

    def test_same_name_same_hash_is_idempotent(self) -> None:
        make_release(self.root, "CDH_E02_001_REVIEW.zip")
        first = flat_queue.enqueue_releases(self.root, ["CDH_E02_001_REVIEW.zip"])
        second = flat_queue.enqueue_releases(self.root, ["CDH_E02_001_REVIEW.zip"])
        self.assertEqual(first["enqueued"][0]["status"], "ENQUEUED")
        self.assertEqual(second["enqueued"][0]["status"], "ALREADY_QUEUED")
        self.assertEqual(second["pending_count"], 1)

    def test_same_sha_replay_under_different_name_is_blocked(self) -> None:
        first = make_release(self.root, "CDH_D03_001_REVIEW.zip")
        second = self.root / "review/releases/CDH_D03_DUP_REVIEW.zip"
        shutil.copyfile(first, second)
        flat_queue.enqueue_releases(self.root, [first.name])
        self.assert_code(
            "DUPLICATE_SHA256", flat_queue.enqueue_releases, self.root, [second.name]
        )
        self.assertEqual(flat_queue.list_queue(self.root)["pending_count"], 1)

    def test_same_name_different_hash_conflict_preserves_queue_copy(self) -> None:
        source = make_release(self.root, "CDH_A05_001_REVIEW.zip", "original")
        flat_queue.enqueue_releases(self.root, [source.name])
        queue_copy = self.root / "review/00_TO_UPLOAD" / source.name
        before = handoff_batch.sha256(queue_copy)
        make_release(self.root, source.name, "corrected")
        self.assert_code(
            "QUEUE_NAME_HASH_CONFLICT", flat_queue.enqueue_releases, self.root, [source.name]
        )
        self.assertEqual(handoff_batch.sha256(queue_copy), before)

    def test_interrupted_copy_cleans_partial_and_retry_succeeds(self) -> None:
        source = make_release(self.root, "CDH_E02_001_REVIEW.zip")
        real_replace = os.replace

        def interrupt(src, dst):
            if Path(dst).name == source.name:
                raise OSError("synthetic enqueue interruption")
            return real_replace(src, dst)

        with mock.patch.object(flat_queue.os, "replace", side_effect=interrupt):
            with self.assertRaises(OSError):
                flat_queue.enqueue_releases(self.root, [source.name])
        queue = self.root / "review/00_TO_UPLOAD"
        self.assertEqual(list(queue.iterdir()), [])
        result = flat_queue.enqueue_releases(self.root, [source.name])
        self.assertEqual(result["pending_count"], 1)

    def test_concurrent_distinct_releases_are_both_queued(self) -> None:
        names = ["CDH_A05_001_REVIEW.zip", "CDH_B05_001_REVIEW.zip"]
        for name in names:
            make_release(self.root, name, name)
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda name: flat_queue.enqueue_releases(self.root, [name]), names))
        self.assertEqual(flat_queue.list_queue(self.root)["pending_count"], 2)

    def test_abandoned_lock_and_stale_partial_are_recovered(self) -> None:
        source = make_release(self.root, "CDH_E05_001_REVIEW.zip")
        locks = self.root / "review/E02/locks"
        staging = self.root / "review/E02/queue_staging"
        locks.mkdir(parents=True)
        staging.mkdir(parents=True)
        lock = locks / "flat_queue.lock"
        lock.write_text(json.dumps({"pid": 999_999_999}), encoding="ascii")
        stale_time = max(0, int(lock.stat().st_mtime) - 10)
        os.utime(lock, (stale_time, stale_time))
        partial = staging / ".CDH_E05_001_REVIEW.zip.crashed.partial"
        partial.write_bytes(b"incomplete")
        result = flat_queue.enqueue_releases(self.root, [source.name])
        self.assertTrue(result["stale_lock_recovered"])
        self.assertEqual(result["stale_partial_cleanup_count"], 1)
        self.assertFalse(partial.exists())
        self.assertEqual(result["pending_count"], 1)

    def test_queue_listing_during_staged_copy_never_sees_partial(self) -> None:
        source = make_release(self.root, "CDH_E05_001_REVIEW.zip", b"x" * 4096)
        started = threading.Event()
        resume = threading.Event()
        real_copy = shutil.copyfileobj

        def paused_copy(incoming, outgoing, length):
            started.set()
            self.assertTrue(resume.wait(timeout=5))
            return real_copy(incoming, outgoing, length)

        with mock.patch.object(flat_queue.shutil, "copyfileobj", side_effect=paused_copy):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(flat_queue.enqueue_releases, self.root, [source.name])
                self.assertTrue(started.wait(timeout=5))
                self.assertEqual(flat_queue.list_queue(self.root)["pending_count"], 0)
                resume.set()
                result = future.result(timeout=5)
        self.assertEqual(result["pending_count"], 1)


class ArchiveTests(FlatQueueCase):
    def test_exact_ack_can_archive_legacy_status_only_checkpoint(self) -> None:
        name = "CDH_A_R11_005_STATUS_ONLY.zip"
        source = self.root / "review/releases" / name
        prefix = "CDH_A_R11_005_STATUS_ONLY/"
        members = {
            f"{prefix}reports/A15/STATUS.json": b'{"status":"UI_PREWORK_READY"}',
            f"{prefix}reports/A15/TEST_RESULTS.md": b"# Tests\n\nHistorical checkpoint.\n",
        }
        manifest = {
            "schema_version": "CDH-A15-STATUS-MANIFEST-1",
            "payloads": [
                {
                    "path": member.removeprefix(prefix),
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                for member, payload in members.items()
            ],
        }
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for member, payload in members.items():
                archive.writestr(member, payload)
            archive.writestr(
                f"{prefix}SHA256_MANIFEST.json",
                json.dumps(manifest, sort_keys=True),
            )
        queue = self.root / "review/00_TO_UPLOAD"
        queue.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, queue / source.name)
        self.assert_code(
            "STATUS_ONLY_REQUIRED_FILE_MISSING",
            flat_queue.list_queue,
            self.root,
        )
        result = flat_queue.archive_queue_item(
            self.root,
            source.name,
            handoff_batch.sha256(source),
            "ACK_LEGACY_STATUS",
            True,
        )
        self.assertEqual(result["status"], "ARCHIVED")
        self.assertTrue(source.exists())

    def test_exact_ack_can_archive_centrally_audited_nested_input_bundle(self) -> None:
        source = make_release(self.root, "CDH_D04_001_REVIEW.zip")
        with zipfile.ZipFile(source, "a") as archive:
            archive.writestr("input/orchestrator_bundles/D04/input_bundle.zip", b"synthetic")
        self.assert_code(
            "NESTED_ZIP_DENIED",
            flat_queue.enqueue_releases,
            self.root,
            [source.name],
        )
        queue = self.root / "review/00_TO_UPLOAD"
        queue.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, queue / source.name)
        listing = flat_queue.list_queue(self.root)
        self.assertEqual(
            listing["files"][0]["nested_zip_gate"],
            "PRESENT_ALLOWED_FOR_EXACT_ACK_ONLY",
        )
        result = flat_queue.archive_queue_item(
            self.root,
            source.name,
            handoff_batch.sha256(source),
            "ACK_001",
            True,
            [source.name],
        )
        self.assertEqual(result["status"], "ARCHIVED")

    def test_exact_ack_can_archive_centrally_audited_synthetic_db_fixture(self) -> None:
        source = make_release(self.root, "CDH_D02_WEB_001_REVIEW.zip")
        with zipfile.ZipFile(source, "a") as archive:
            archive.writestr("tests/fixtures/observations.sqlite3", b"synthetic-not-a-real-db")
        with self.assertRaises(HandoffError):
            flat_queue.enqueue_releases(self.root, [source.name])
        queue = self.root / "review/00_TO_UPLOAD"
        queue.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, queue / source.name)
        listing = flat_queue.list_queue(self.root)
        self.assertEqual(
            listing["files"][0]["sensitive_content_gate"],
            "PRESENT_ALLOWED_FOR_EXACT_ACK_ONLY",
        )
        result = flat_queue.archive_queue_item(
            self.root,
            source.name,
            handoff_batch.sha256(source),
            "ACK_001",
            True,
            [source.name],
        )
        self.assertEqual(result["status"], "ARCHIVED")

    def test_exact_ack_can_archive_legacy_manifestless_release_with_alias(self) -> None:
        source = self.root / "review/releases/CDH_B05_001_REVIEW.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("payload/result.txt", "legacy centrally audited release")
        self.assert_code(
            "MANIFEST_COUNT_INVALID",
            flat_queue.enqueue_releases,
            self.root,
            [source.name],
        )
        queue = self.root / "review/00_TO_UPLOAD"
        queue.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, queue / source.name)
        listing = flat_queue.list_queue(self.root)
        self.assertEqual(
            listing["files"][0]["manifest_gate"],
            "MISSING_ALLOWED_FOR_EXACT_ACK_ONLY",
        )
        digest = handoff_batch.sha256(source)
        result = flat_queue.archive_queue_item(
            self.root,
            source.name,
            digest,
            "ACK_001",
            True,
            ["CDH_B05_001_REVIEW(1).zip"],
        )
        self.assertEqual(
            result["record"]["central_ack_filenames"],
            ["CDH_B05_001_REVIEW(1).zip"],
        )

    def test_partial_ack_archives_only_exact_item(self) -> None:
        first = make_release(self.root, "CDH_A05_001_REVIEW.zip", "a")
        second = make_release(self.root, "CDH_B05_001_REVIEW.zip", "b")
        flat_queue.enqueue_releases(self.root, [first.name, second.name])
        digest = handoff_batch.sha256(first)
        result = flat_queue.archive_queue_item(self.root, first.name, digest, "ACK_001", True)
        self.assertEqual(result["status"], "ARCHIVED")
        self.assertFalse((self.root / "review/00_TO_UPLOAD" / first.name).exists())
        self.assertTrue((self.root / "review/00_TO_UPLOAD" / second.name).exists())
        self.assertTrue((self.root / "review/releases" / first.name).exists())

    def test_wrong_hash_and_missing_ack_preserve_source(self) -> None:
        source = make_release(self.root, "CDH_E02_001_REVIEW.zip")
        flat_queue.enqueue_releases(self.root, [source.name])
        self.assert_code(
            "ACKNOWLEDGEMENT_REQUIRED",
            flat_queue.archive_queue_item,
            self.root,
            source.name,
            handoff_batch.sha256(source),
            "ACK_001",
            False,
        )
        self.assert_code(
            "ACK_SHA256_MISMATCH",
            flat_queue.archive_queue_item,
            self.root,
            source.name,
            "0" * 64,
            "ACK_001",
            True,
        )
        self.assertTrue((self.root / "review/00_TO_UPLOAD" / source.name).exists())

    def test_existing_destination_refuses_without_source_loss(self) -> None:
        source = make_release(self.root, "CDH_E02_001_REVIEW.zip")
        flat_queue.enqueue_releases(self.root, [source.name])
        archive = self.root / "review/90_UPLOADED_ARCHIVE/ACK_001"
        archive.mkdir(parents=True)
        shutil.copyfile(source, archive / source.name)
        self.assert_code(
            "ARCHIVE_DESTINATION_COLLISION",
            flat_queue.archive_queue_item,
            self.root,
            source.name,
            handoff_batch.sha256(source),
            "ACK_001",
            True,
        )
        self.assertTrue((self.root / "review/00_TO_UPLOAD" / source.name).exists())

    def test_completed_move_without_receipt_is_recovered(self) -> None:
        source = make_release(self.root, "CDH_E02_001_REVIEW.zip")
        flat_queue.enqueue_releases(self.root, [source.name])
        digest = handoff_batch.sha256(source)
        archive = self.root / "review/90_UPLOADED_ARCHIVE/ACK_001"
        archive.mkdir(parents=True)
        os.replace(self.root / "review/00_TO_UPLOAD" / source.name, archive / source.name)
        result = flat_queue.archive_queue_item(
            self.root, source.name, digest, "ACK_001", True
        )
        self.assertEqual(result["status"], "RECOVERED_AFTER_COMPLETED_MOVE")
        receipt = json.loads((archive / "ARCHIVE_RECEIPT.json").read_text(encoding="utf-8"))
        self.assertEqual(len(receipt["records"]), 1)
        self.assertTrue(receipt["records"][0]["recovered_after_completed_move"])

    def test_exact_ack_file_is_partial_safe_and_idempotent(self) -> None:
        first = make_release(self.root, "CDH_A07_001_REVIEW.zip", "first")
        second = make_release(self.root, "CDH_B08_001_REVIEW.zip", "second")
        flat_queue.enqueue_releases(self.root, [first.name, second.name])
        ack_file = self.root / "review/E05/acks.json"
        ack_file.parent.mkdir(parents=True)
        ack_file.write_text(
            json.dumps(
                {
                    "schema": "CDH-EXACT-ACK-1",
                    "acks": [
                        {
                            "filename": first.name,
                            "sha256": handoff_batch.sha256(first),
                            "central_ack_filenames": ["CDH_A07_001_REVIEW (1).zip"],
                        },
                        {"filename": second.name, "sha256": "0" * 64},
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = flat_queue.archive_ack_file(self.root, ack_file, "ACK_E05", True)
        self.assertEqual(result["archived_count"], 1)
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(result["pending_count"], 1)
        self.assertTrue((self.root / "review/00_TO_UPLOAD" / second.name).exists())

        ack_file.write_text(
            json.dumps(
                {
                    "schema": "CDH-EXACT-ACK-1",
                    "acks": [{"filename": first.name, "sha256": handoff_batch.sha256(first)}],
                }
            ),
            encoding="utf-8",
        )
        repeated = flat_queue.archive_ack_file(self.root, ack_file, "ACK_E05", True)
        self.assertEqual(repeated["already_archived_count"], 1)
        ledger = (self.root / "docs/HANDOFF/RECEIPT_LEDGER.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(ledger), 1)

    def test_ack_file_requires_authority_and_canonical_filename_case(self) -> None:
        ack_file = self.root / "review/E05/acks.json"
        ack_file.parent.mkdir(parents=True)
        ack_file.write_text(
            json.dumps(
                {
                    "schema": "CDH-EXACT-ACK-1",
                    "acks": [
                        {"filename": "CDH_A07_001_REVIEW.ZIP", "sha256": "0" * 64}
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.assert_code(
            "ACKNOWLEDGEMENT_REQUIRED",
            flat_queue.archive_ack_file,
            self.root,
            ack_file,
            "ACK_E05",
            False,
        )
        self.assert_code(
            "INVALID_ACK_RECORD",
            flat_queue.archive_ack_file,
            self.root,
            ack_file,
            "ACK_E05",
            True,
        )


class SafetyTests(FlatQueueCase):
    def test_placeholder_env_example_is_allowed(self) -> None:
        path = make_release(self.root, "CDH_A05_001_REVIEW.zip")
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr(
                "apps/frontend/.env.example",
                "VITE_API_BASE_URL=http://127.0.0.1:8080\nAPI_KEY=example_key\n",
            )
        result = flat_queue.enqueue_releases(self.root, [path.name])
        self.assertEqual(result["pending_count"], 1)

    def test_nonplaceholder_secret_in_env_example_is_blocked(self) -> None:
        path = make_release(self.root, "CDH_A05_001_REVIEW.zip")
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("apps/frontend/.env.example", "API_KEY=real-secret-value\n")
        self.assert_code(
            "ENV_EXAMPLE_NONPLACEHOLDER_SECRET",
            flat_queue.enqueue_releases,
            self.root,
            [path.name],
        )

    def test_ctrl_a_queue_rejects_non_zip_hidden_and_partial(self) -> None:
        queue = self.root / "review/00_TO_UPLOAD"
        queue.mkdir(parents=True)
        for name in ("notes.txt", ".hidden.zip", "file.partial"):
            with self.subTest(name=name):
                for existing in queue.iterdir():
                    existing.unlink()
                (queue / name).write_text("unsafe", encoding="utf-8")
                with self.assertRaises(HandoffError):
                    flat_queue.list_queue(self.root)

    def test_secret_database_and_nested_zip_are_blocked(self) -> None:
        cases = [".env", "private.sqlite3", "cookies.json", "nested/archive.zip"]
        for index, member in enumerate(cases):
            with self.subTest(member=member):
                name = f"CDH_E{index}X_001_REVIEW.zip"
                path = make_release(self.root, name)
                with zipfile.ZipFile(path, "a") as archive:
                    archive.writestr(member, "denied")
                with self.assertRaises(HandoffError):
                    flat_queue.enqueue_releases(self.root, [name])

    def test_manifest_hash_mismatch_is_blocked(self) -> None:
        path = make_release(self.root, "CDH_E02_001_REVIEW.zip")
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("payload/result.txt", "tampered")
        with self.assertRaises(HandoffError):
            flat_queue.enqueue_releases(self.root, [path.name])

    def test_chinese_project_path(self) -> None:
        root = self.root / "酷澎比價系統"
        (root / "review/releases").mkdir(parents=True)
        source = make_release(root, "CDH_E02_001_REVIEW.zip", "中文證據")
        flat_queue.enqueue_releases(root, [source.name])
        self.assertEqual(flat_queue.list_queue(root)["pending_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
