from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.ci_offline.archive_audit import audit_review_zip, sha256_file

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = PROJECT_ROOT / "reports" / "G02" / "test_tmp"


class ArchiveAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT, ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build_zip(self, name: str, files: dict[str, bytes], *, declared: list[str] | None = None) -> Path:
        path = self.root / name
        declared = declared if declared is not None else list(files)
        payloads = [
            {"path": item, "bytes": len(files[item]), "sha256": hashlib.sha256(files[item]).hexdigest()}
            for item in declared
        ]
        manifest = json.dumps(
            {"schema": "TEST-MANIFEST-1", "payload_count": len(payloads), "payloads": payloads},
            sort_keys=True,
        ).encode()
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("CDH_TEST_REVIEW/MANIFEST.json", manifest)
            for filename, data in files.items():
                archive.writestr(f"CDH_TEST_REVIEW/{filename}", data)
        return path

    def test_valid_manifest_identity_crc_and_payload_pass(self) -> None:
        archive = self.build_zip("valid.zip", {"docs/readme.md": b"safe evidence\n"})
        expected = sha256_file(archive)
        result = audit_review_zip(archive, expected)
        self.assertTrue(result["passed"], result)
        self.assertTrue(result["crc_gate"])
        self.assertTrue(result["identity_match"])
        self.assertEqual(result["manifest_payload_count"], 1)

    def test_identity_mismatch_fails(self) -> None:
        archive = self.build_zip("identity.zip", {"result.json": b"{}"})
        result = audit_review_zip(archive, "0" * 64)
        self.assertFalse(result["passed"])
        self.assertFalse(result["identity_match"])

    def test_malicious_traversal_zip_fails_without_extraction(self) -> None:
        archive = self.build_zip("traversal.zip", {"safe.txt": b"safe"})
        with zipfile.ZipFile(archive, "a") as handle:
            handle.writestr("../escape.txt", b"do not extract")
        result = audit_review_zip(archive)
        self.assertFalse(result["passed"])
        self.assertEqual(result["unsafe_entries"][0]["reason"], "PATH_TRAVERSAL")
        self.assertFalse((self.root.parent / "escape.txt").exists())

    def test_env_name_and_fake_secret_fixture_fail(self) -> None:
        fake_key = ("AKIA" + "A1" * 8).encode()
        archive = self.build_zip("secret.zip", {".env": b"TOKEN=" + fake_key, "safe.txt": fake_key})
        result = audit_review_zip(archive)
        self.assertFalse(result["passed"])
        self.assertTrue(result["sensitive_named_entries"])
        self.assertTrue(any(item["rule"] == "AWS_ACCESS_KEY" for item in result["secret_findings"]))

    def test_manifest_hash_mismatch_and_undeclared_file_fail(self) -> None:
        archive = self.build_zip("mismatch.zip", {"declared.txt": b"one", "extra.txt": b"two"}, declared=["declared.txt"])
        result = audit_review_zip(archive)
        self.assertFalse(result["passed"])
        self.assertEqual(result["manifest_undeclared"], ["CDH_TEST_REVIEW/extra.txt"])
        with zipfile.ZipFile(archive, "a") as handle:
            handle.writestr("CDH_TEST_REVIEW/declared.txt", b"changed")
        duplicate = audit_review_zip(archive)
        self.assertFalse(duplicate["passed"])
        self.assertTrue(duplicate["duplicate_entries"])


if __name__ == "__main__":
    unittest.main()
