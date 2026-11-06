from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.ci_offline.sensitive_scan import scan_allowed_sources
from tools.ci_offline.workline import check_workline_registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = PROJECT_ROOT / "reports" / "G02" / "test_tmp"


class SourceAndWorklineTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT, ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        (self.root / "tests" / "ci_offline").mkdir(parents=True)
        (self.root / "reports" / "G02").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_allowed_safe_source_passes(self) -> None:
        path = self.root / "tests" / "ci_offline" / "safe_fixture.txt"
        path.write_text("synthetic fixture only\n", encoding="utf-8")
        result = scan_allowed_sources(self.root, [Path("tests/ci_offline")])
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["scanned_file_count"], 1)

    def test_fake_key_fixture_is_detected(self) -> None:
        fake_key = "AKIA" + "Z9" * 8
        path = self.root / "tests" / "ci_offline" / "malicious_fixture.txt"
        path.write_text(f"value={fake_key}\n", encoding="utf-8")
        result = scan_allowed_sources(self.root, [Path("tests/ci_offline")])
        self.assertFalse(result["passed"])
        self.assertEqual(result["findings"][0]["rule"], "AWS_ACCESS_KEY")

    def test_root_env_request_is_rejected_without_reading(self) -> None:
        path = self.root / ".env"
        path.write_text("must-not-be-read", encoding="utf-8")
        result = scan_allowed_sources(self.root, [Path(".env")])
        self.assertFalse(result["passed"])
        self.assertEqual(result["scanned_file_count"], 0)
        self.assertEqual(result["rejected_paths"], [str(path.resolve())])

    def write_registry(self, records: list[dict]) -> Path:
        path = self.root / "reports" / "G02" / "registry.json"
        path.write_text(json.dumps({"worklines": records}), encoding="utf-8")
        return path

    def test_new_unique_workline_is_accepted(self) -> None:
        registry = self.write_registry(
            [
                {"workline": "B", "task_id": "B06", "version": "2", "source_sha256": "a" * 64},
                {"workline": "G", "task_id": "G02", "version": "1", "source_sha256": "b" * 64},
            ]
        )
        result = check_workline_registry(registry)
        self.assertTrue(result["passed"], result)

    def test_same_workline_different_identity_is_conflict(self) -> None:
        registry = self.write_registry(
            [
                {"workline": "B", "task_id": "B06", "version": "2", "source_sha256": "a" * 64},
                {"workline": "B", "task_id": "B07", "version": "3", "source_sha256": "b" * 64},
            ]
        )
        result = check_workline_registry(registry)
        self.assertFalse(result["passed"])
        self.assertEqual(result["conflicts"][0]["workline"], "B")


if __name__ == "__main__":
    unittest.main()
