from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = PROJECT_ROOT / "scripts/orchestrator_handoff"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import project_file_index

LOCAL_TEMP = PROJECT_ROOT / "experiments/E02/index_test_tmp"
LOCAL_TEMP.mkdir(parents=True, exist_ok=True)


class ProjectFileIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=LOCAL_TEMP)
        self.root = Path(self.temp.name) / "酷澎比價系統"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_sensitive_file_is_metadata_only_and_not_hashed(self) -> None:
        secret = self.root / ".env"
        secret.write_text("DO_NOT_READ=this-is-synthetic", encoding="utf-8")
        records, warnings = project_file_index.collect(self.root)
        self.assertEqual(warnings, [])
        record = next(item for item in records if item[0] == ".env")
        self.assertEqual(record[4], "SKIPPED_SECRET")
        self.assertEqual(record[5], "SENSITIVE_NAME_ONLY")

    def test_review_zip_is_hashed_without_extracting(self) -> None:
        path = self.root / "review/releases/CDH_E02_001_REVIEW.zip"
        path.parent.mkdir(parents=True)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("README.txt", "synthetic")
        records, _ = project_file_index.collect(self.root)
        record = next(item for item in records if item[0].endswith(path.name))
        self.assertEqual(record[4], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_write_once_and_refuse_overwrite(self) -> None:
        (self.root / "README.md").write_text("synthetic", encoding="utf-8")
        self.assertEqual(
            project_file_index.main(["--project-root", str(self.root), "--write"]), 0
        )
        output = self.root / "docs/HANDOFF/PROJECT_FILE_INDEX.csv"
        with output.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 1)
        with self.assertRaises(RuntimeError):
            project_file_index.main(["--project-root", str(self.root), "--write"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
