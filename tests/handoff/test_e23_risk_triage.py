from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/orchestrator_handoff/e23_risk_triage.py"
spec = importlib.util.spec_from_file_location("e23_risk_triage", MODULE_PATH)
assert spec and spec.loader
triage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(triage)


class E23RiskTriageTests(unittest.TestCase):
    def setUp(self) -> None:
        base = MODULE_PATH.parents[2] / "experiments/E23/triage_test_tmp"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "review/releases").mkdir(parents=True)

    def test_private_database_original_excluded_without_opening_payload(self) -> None:
        path = self.root / "review/releases/private.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("fixtures/private.sqlite3", b"DO_NOT_READ")
        item = {"filename": path.name, "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "reasons": ["SENSITIVE_MEMBER_PATH"]}
        with mock.patch.object(triage, "ROOT", self.root), mock.patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("payload opened")):
            result = triage.classify(item)
        self.assertEqual(result["decision"], "ORIGINAL_EXCLUDE_DERIVATIVE_ONLY")
        self.assertEqual(result["payload_open_count"], 0)

    def test_image_is_review_candidate_not_automatically_publishable(self) -> None:
        path = self.root / "review/releases/image.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("synthetic/screenshot.png", b"PNG_TEST_DATA")
        item = {"filename": path.name, "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "reasons": ["NON_TEXT_MEMBER_REVIEW_REQUIRED"]}
        with mock.patch.object(triage, "ROOT", self.root):
            result = triage.classify(item)
        self.assertEqual(result["decision"], "DEEP_CONTENT_AND_PROVENANCE_REVIEW")
        self.assertEqual(result["payload_open_count"], 0)


if __name__ == "__main__":
    unittest.main()
