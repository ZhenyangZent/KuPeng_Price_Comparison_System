from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts/orchestrator_handoff/handoff_batch.py"
SPEC = importlib.util.spec_from_file_location("handoff_batch", MODULE_PATH)
assert SPEC and SPEC.loader
handoff_batch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = handoff_batch
SPEC.loader.exec_module(handoff_batch)

HandoffError = handoff_batch.HandoffError
archive_acknowledged = handoff_batch.archive_acknowledged
create_batch = handoff_batch.create_batch
inspect_zip = handoff_batch.inspect_zip
list_pending = handoff_batch.list_pending
sha256 = handoff_batch.sha256

LOCAL_TEST_TEMP = PROJECT_ROOT / "experiments/E01/test_tmp"
LOCAL_TEST_TEMP.mkdir(parents=True, exist_ok=True)


def make_release(root: Path, name: str, members: dict[str, bytes | str] | None = None) -> Path:
    releases = root / "review/releases"
    releases.mkdir(parents=True, exist_ok=True)
    path = releases / name
    members = members or {"README.txt": "synthetic fixture"}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member, data in members.items():
            archive.writestr(member, data)
    return path


def corrupt_first_member(path: Path) -> None:
    raw = bytearray(path.read_bytes())
    with zipfile.ZipFile(path, "r") as archive:
        info = archive.infolist()[0]
        offset = info.header_offset
        name_length, extra_length = struct.unpack_from("<HH", raw, offset + 26)
        data_offset = offset + 30 + name_length + extra_length
    raw[data_offset] ^= 0xFF
    path.write_bytes(raw)


class TemporaryProject(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=LOCAL_TEST_TEMP)
        self.root = Path(self.temp.name)
        (self.root / "review/releases").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_code(self, code: str, callable_, *args, **kwargs) -> HandoffError:
        with self.assertRaises(HandoffError) as raised:
            callable_(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)
        return raised.exception


class BuildAndArchiveTests(TemporaryProject):
    def test_build_list_archive_and_original_hashes_preserved(self) -> None:
        first = make_release(self.root, "CDH_A04_001_REVIEW.zip")
        second = make_release(self.root, "CDH_D04_001_REVIEW.zip", {"證據/結果.txt": "通過"})
        before = {path.name: sha256(path) for path in (first, second)}

        built = create_batch(
            self.root,
            "TEST_0001",
            ["CDH_D04_001_REVIEW.zip", "CDH_A04_001_REVIEW.zip"],
        )
        self.assertEqual(built["bundled_release_count"], 2)
        self.assertTrue(built["pending_upload"])
        pending = list_pending(self.root)
        self.assertEqual(pending["pending_count"], 1)

        batch = self.root / "review/00_TO_UPLOAD/CDH_BATCH_TEST_0001_REVIEW.zip"
        with zipfile.ZipFile(batch, "r") as archive:
            manifest = json.loads(archive.read("BATCH_MANIFEST.json"))
            self.assertEqual(manifest["schema"], "CDH-HANDOFF-BATCH-1")
            self.assertEqual(manifest["release_count"], 2)
            self.assertEqual(
                archive.namelist(),
                [
                    "BATCH_MANIFEST.json",
                    "packages/CDH_A04_001_REVIEW.zip",
                    "packages/CDH_D04_001_REVIEW.zip",
                ],
            )
            for item in manifest["files"]:
                self.assertEqual(
                    hashlib.sha256(archive.read(f"packages/{item['name']}")).hexdigest(),
                    item["sha256"],
                )

        self.assert_code(
            "ACKNOWLEDGEMENT_REQUIRED",
            archive_acknowledged,
            self.root,
            batch.name,
            built["sha256"],
            False,
        )
        self.assert_code(
            "RECEIPT_SHA256_MISMATCH",
            archive_acknowledged,
            self.root,
            batch.name,
            "0" * 64,
            True,
        )
        archived = archive_acknowledged(self.root, batch.name, built["sha256"], True)
        self.assertFalse(archived["already_archived"])
        self.assertEqual(list_pending(self.root)["pending_count"], 0)
        self.assertEqual(before, {path.name: sha256(path) for path in (first, second)})
        receipt = json.loads(
            (self.root / "review/90_UPLOADED_ARCHIVE/TEST_0001/ARCHIVE_RECEIPT.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(receipt["sha256"], built["sha256"])

    def test_archive_retry_is_idempotent(self) -> None:
        make_release(self.root, "CDH_E01_001_REVIEW.zip")
        built = create_batch(self.root, "RETRY_01", ["CDH_E01_001_REVIEW.zip"])
        name = "CDH_BATCH_RETRY_01_REVIEW.zip"
        first = archive_acknowledged(self.root, name, built["sha256"], True)
        second = archive_acknowledged(self.root, name, built["sha256"], True)
        self.assertFalse(first["already_archived"])
        self.assertTrue(second["already_archived"])
        self.assertFalse(second["recovered_receipt"])

    def test_recovers_receipt_after_completed_move(self) -> None:
        make_release(self.root, "CDH_E01_001_REVIEW.zip")
        built = create_batch(self.root, "HALFMOVE", ["CDH_E01_001_REVIEW.zip"])
        name = "CDH_BATCH_HALFMOVE_REVIEW.zip"
        destination_dir = self.root / "review/90_UPLOADED_ARCHIVE/HALFMOVE"
        destination_dir.mkdir(parents=True)
        os.replace(self.root / "review/00_TO_UPLOAD" / name, destination_dir / name)

        result = archive_acknowledged(self.root, name, built["sha256"], True)
        self.assertTrue(result["recovered_receipt"])
        receipt = json.loads((destination_dir / "ARCHIVE_RECEIPT.json").read_text(encoding="utf-8"))
        self.assertTrue(receipt["recovered_after_completed_move"])

    def test_existing_batch_and_repeated_release_are_blocked(self) -> None:
        make_release(self.root, "CDH_A04_001_REVIEW.zip")
        create_batch(self.root, "COLLIDE1", ["CDH_A04_001_REVIEW.zip"])
        self.assert_code(
            "BATCH_ALREADY_EXISTS",
            create_batch,
            self.root,
            "COLLIDE1",
            ["CDH_A04_001_REVIEW.zip"],
        )
        self.assert_code(
            "REPEATED_RELEASE_NAME",
            create_batch,
            self.root,
            "COLLIDE2",
            ["CDH_A04_001_REVIEW.zip", "CDH_A04_001_REVIEW.zip"],
        )

    def test_different_worklines_can_build_concurrently(self) -> None:
        make_release(self.root, "CDH_A04_001_REVIEW.zip")
        make_release(self.root, "CDH_N01_001_REVIEW.zip")
        jobs = [
            ("MULTI_A1", ["CDH_A04_001_REVIEW.zip"]),
            ("MULTI_N1", ["CDH_N01_001_REVIEW.zip"]),
        ]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda job: create_batch(self.root, *job), jobs))
        self.assertEqual({item["batch_id"] for item in results}, {"MULTI_A1", "MULTI_N1"})
        self.assertEqual(list_pending(self.root)["pending_count"], 2)

    def test_interrupted_replace_cleans_partial_and_retry_succeeds(self) -> None:
        make_release(self.root, "CDH_A04_001_REVIEW.zip")
        real_replace = os.replace

        def interrupt(source, destination):
            if Path(destination).name == "CDH_BATCH_INTERRUPT_REVIEW.zip":
                raise OSError("synthetic interruption")
            return real_replace(source, destination)

        with mock.patch.object(handoff_batch.os, "replace", side_effect=interrupt):
            with self.assertRaises(OSError):
                create_batch(self.root, "INTERRUPT", ["CDH_A04_001_REVIEW.zip"])
        upload = self.root / "review/00_TO_UPLOAD"
        self.assertEqual(list(upload.iterdir()), [])
        self.assertEqual(list((self.root / "experiments/E01/locks").iterdir()), [])
        result = create_batch(self.root, "INTERRUPT", ["CDH_A04_001_REVIEW.zip"])
        self.assertTrue(result["pending_upload"])


class ZipSafetyTests(TemporaryProject):
    def test_path_traversal_is_blocked(self) -> None:
        for index, member in enumerate(("../escape.txt", "/absolute.txt", "C:/drive.txt")):
            path = make_release(self.root, f"CDH_T{index}_001_REVIEW.zip", {member: "x"})
            self.assert_code("UNSAFE_ZIP_PATH", inspect_zip, path)
        # Python's Windows ZipInfo writer normalizes backslashes before writing;
        # validate the raw-name gate directly for this otherwise unwriteable case.
        self.assert_code("UNSAFE_ZIP_PATH", handoff_batch._validate_member_name, "a\\b.txt")

    def test_windows_case_duplicate_is_blocked(self) -> None:
        path = self.root / "review/releases/CDH_A04_001_REVIEW.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Evidence/Result.txt", "one")
            archive.writestr("evidence/result.TXT", "two")
        self.assert_code("DUPLICATE_ZIP_PATH", inspect_zip, path)

    def test_unicode_normalization_duplicate_is_blocked(self) -> None:
        path = self.root / "review/releases/CDH_A04_001_REVIEW.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("café.txt", "one")
            archive.writestr("cafe\u0301.txt", "two")
        self.assert_code("DUPLICATE_ZIP_PATH", inspect_zip, path)

    def test_windows_reserved_and_trailing_dot_are_blocked(self) -> None:
        for index, member in enumerate(("CON.txt", "folder/name. ")):
            path = make_release(self.root, f"CDH_W{index}_001_REVIEW.zip", {member: "x"})
            self.assert_code("WINDOWS_UNSAFE_ZIP_PATH", inspect_zip, path)

    def test_symlink_entry_is_blocked(self) -> None:
        path = self.root / "review/releases/CDH_A04_001_REVIEW.zip"
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat_mode := 0o120777) << 16
        self.assertNotEqual(stat_mode, 0)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(info, "target")
        self.assert_code("SYMLINK_ZIP_ENTRY", inspect_zip, path)

    def test_corrupted_zip_is_blocked(self) -> None:
        path = make_release(self.root, "CDH_A04_001_REVIEW.zip", {"payload.bin": b"A" * 32})
        corrupt_first_member(path)
        with self.assertRaises(HandoffError) as raised:
            inspect_zip(path)
        self.assertIn(raised.exception.code, {"INVALID_ZIP", "ZIP_CRC_FAILURE"})

    def test_sensitive_content_is_blocked(self) -> None:
        cases = {
            "formal.sqlite3": "database",
            ".venv/pyvenv.cfg": "environment",
            "secrets/access_token.txt": "token",
            "Firefox/Cookies": "cookie",
            "backup.reg": "registry",
        }
        for index, member in enumerate(cases):
            with self.subTest(member=member):
                path = make_release(self.root, f"CDH_S{index}_001_REVIEW.zip", {member: "private"})
                self.assert_code("SENSITIVE_RELEASE_CONTENT", inspect_zip, path)

    def test_sensitive_release_cannot_be_batched(self) -> None:
        make_release(self.root, "CDH_D04_001_REVIEW.zip", {"data/user.db": "not real"})
        self.assert_code(
            "SENSITIVE_RELEASE_CONTENT",
            create_batch,
            self.root,
            "DENY_DB1",
            ["CDH_D04_001_REVIEW.zip"],
        )
        self.assertTrue((self.root / "review/releases/CDH_D04_001_REVIEW.zip").exists())

    def test_utf8_members_and_chinese_project_path(self) -> None:
        chinese_root = self.root / "酷澎比價系統"
        (chinese_root / "review/releases").mkdir(parents=True)
        make_release(chinese_root, "CDH_E01_001_REVIEW.zip", {"證據/測試結果.txt": "全部通過"})
        result = create_batch(chinese_root, "UTF8_001", ["CDH_E01_001_REVIEW.zip"])
        self.assertEqual(result["bundled_release_count"], 1)


class QueuePolicyTests(TemporaryProject):
    def test_unexpected_item_in_upload_queue_fails_closed(self) -> None:
        upload = self.root / "review/00_TO_UPLOAD"
        upload.mkdir(parents=True)
        (upload / "notes.txt").write_text("not a batch", encoding="utf-8")
        self.assert_code("UNEXPECTED_UPLOAD_ENTRY", list_pending, self.root)

    def test_partial_item_in_upload_queue_fails_closed(self) -> None:
        upload = self.root / "review/00_TO_UPLOAD"
        upload.mkdir(parents=True)
        (upload / ".CDH_BATCH_TEST_REVIEW.zip.1.partial").write_text("partial")
        self.assert_code("INTERRUPTED_BUILD_ARTIFACT", list_pending, self.root)

    def test_archive_destination_collision_fails_before_move(self) -> None:
        make_release(self.root, "CDH_E01_001_REVIEW.zip")
        built = create_batch(self.root, "COLLARCH", ["CDH_E01_001_REVIEW.zip"])
        destination = self.root / "review/90_UPLOADED_ARCHIVE/COLLARCH"
        destination.mkdir(parents=True)
        (destination / "ARCHIVE_RECEIPT.json").write_text("{}", encoding="utf-8")
        name = "CDH_BATCH_COLLARCH_REVIEW.zip"
        self.assert_code(
            "ARCHIVE_COLLISION",
            archive_acknowledged,
            self.root,
            name,
            built["sha256"],
            True,
        )
        self.assertTrue((self.root / "review/00_TO_UPLOAD" / name).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
