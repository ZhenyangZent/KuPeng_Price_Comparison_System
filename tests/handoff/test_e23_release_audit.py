from __future__ import annotations

import hashlib
import importlib.util
import csv
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

    def test_freeze_baseline_keeps_seven_old_checkpoints(self) -> None:
        out = self.root / "reports/E23/release_audit"
        out.mkdir(parents=True)
        prior = []
        for batch in range(7):
            rows = [{"filename": f"historical_{batch}_{i}.zip", "expected_sha256": "a" * 64}
                    for i in range(20)]
            target = out / f"batch_{batch:02d}.json"
            target.write_text(json.dumps({"batch": batch, "items": rows}), encoding="utf-8")
            prior.append(hashlib.sha256(target.read_bytes()).hexdigest())
        with mock.patch.object(audit_module, "OUT", out), mock.patch.object(audit_module, "BASELINE", out / "BASELINE_140.json"):
            frozen = audit_module.freeze_baseline()
            self.assertEqual(len(frozen["rows"]), 140)
            self.assertEqual(audit_module.freeze_baseline(), frozen)
        self.assertEqual(prior, [hashlib.sha256((out / f"batch_{i:02d}.json").read_bytes()).hexdigest()
                                 for i in range(7)])

    def test_incremental_snapshot_does_not_rewrite_old_snapshot(self) -> None:
        out = self.root / "reports/E23/release_audit"
        out.mkdir(parents=True)
        baseline = out / "BASELINE_140.json"
        baseline.write_text(json.dumps({"rows": [{"filename": "old.zip", "sha256": "a" * 64}]}), encoding="utf-8")
        ledger_dir = self.root / "docs/HANDOFF"
        ledger_dir.mkdir(parents=True)
        with (ledger_dir / "RELEASE_LEDGER.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["filename", "sha256"])
            w.writeheader()
            w.writerow({"filename": "new.zip", "sha256": "0" * 64})
        self.make_zip("new.zip", {"notes.txt": b"synthetic"})
        with mock.patch.object(audit_module, "ROOT", self.root), mock.patch.object(audit_module, "OUT", out), mock.patch.object(audit_module, "BASELINE", baseline):
            first = audit_module.capture_new()
            original = (out / "incremental_snapshot_000.json").read_bytes()
            self.assertEqual(len(first["rows"]), 1)
            self.assertEqual(first["rows"][0]["ledger_identity_gate"], "BLOCKED")
            self.assertEqual(audit_module.capture_new()["status"], "NO_NEW_RELEASES")
            self.assertEqual((out / "incremental_snapshot_000.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
