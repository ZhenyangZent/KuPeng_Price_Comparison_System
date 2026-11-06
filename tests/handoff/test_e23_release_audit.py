from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/orchestrator_handoff/e23_release_audit.py"
sys.path.insert(0, str(MODULE_PATH.parent))
spec = importlib.util.spec_from_file_location("e23_release_audit", MODULE_PATH)
assert spec and spec.loader
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)


class E23ReleaseAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        project_root = MODULE_PATH.parents[2]
        temp_base = project_root / "experiments/E23/audit_test_tmp"
        temp_base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_base)
        if not Path(self.temp.name).resolve().is_relative_to(temp_base.resolve()):
            raise RuntimeError("test temporary path escaped project root")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "review/releases").mkdir(parents=True)

    def make_zip(self, name: str, members: dict[str, bytes]) -> tuple[Path, dict]:
        path = self.root / "review/releases" / name
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for member, data in members.items():
                z.writestr(member, data)
        row = {"filename": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        return path, row

    def test_private_member_blocks_without_opening_member_content(self) -> None:
        _, row = self.make_zip("private.zip", {"private/history.sqlite3": b"PRIVATE_DATA_MARKER"})
        with mock.patch.object(audit_module, "ROOT", self.root), mock.patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("member content opened")):
            result = audit_module.audit(row)
        self.assertEqual(result["status"], "BLOCKED_FOR_UPLOAD")
        self.assertIn("SENSITIVE_MEMBER_PATH", result["reasons"])
        self.assertEqual(result["content_checked_count"], 0)
        self.assertEqual(result["crc"], "NOT_RUN")

    def test_nested_zip_blocks_without_opening_payload(self) -> None:
        _, row = self.make_zip("nested.zip", {"bundle/upstream.zip": b"NESTED_MARKER"})
        with mock.patch.object(audit_module, "ROOT", self.root), mock.patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("nested payload opened")):
            result = audit_module.audit(row)
        self.assertIn("NESTED_ZIP", result["reasons"])
        self.assertEqual(result["content_checked_count"], 0)

    def test_text_with_credential_pattern_is_blocked(self) -> None:
        _, row = self.make_zip("pattern.zip", {"notes.txt": b"ghp_" + b"A" * 35})
        with mock.patch.object(audit_module, "ROOT", self.root):
            result = audit_module.audit(row)
        self.assertIn("CREDENTIAL_PATTERN", result["reasons"])
        self.assertEqual(result["status"], "BLOCKED_FOR_UPLOAD")

    def test_clean_text_manifest_is_eligible(self) -> None:
        data = b"offline synthetic documentation\n"
        manifest = {"files": [{"path": "notes.txt", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}]}
        _, row = self.make_zip("clean.zip", {"notes.txt": data, "MANIFEST.json": json.dumps(manifest).encode()})
        with mock.patch.object(audit_module, "ROOT", self.root):
            result = audit_module.audit(row)
        self.assertEqual(result["status"], "ELIGIBLE_FOR_PUBLICATION_REVIEW")
        self.assertEqual(result["crc"], "PASS")
        self.assertEqual(result["manifest"], "PASS")


if __name__ == "__main__":
    unittest.main()
