from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.ci_web_g03.runner import _copy_tree, _run


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_parent = Path("reports/G03").resolve()
        temp_parent.mkdir(parents=True, exist_ok=True)
        self._temp = tempfile.TemporaryDirectory(dir=temp_parent)
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_copy_tree_detects_version_conflict_without_overwrite(self) -> None:
        source, target = self.root / "source", self.root / "target"
        source.mkdir(); target.mkdir()
        (source / "same.txt").write_text("incoming", encoding="utf-8")
        (target / "same.txt").write_text("existing", encoding="utf-8")
        conflicts: list[dict] = []
        _copy_tree(source, target, conflicts)
        self.assertEqual((target / "same.txt").read_text(encoding="utf-8"), "existing")
        self.assertEqual(len(conflicts), 1)

    def test_missing_dependency_is_machine_readable_and_not_launched(self) -> None:
        result = _run("skipped", ["definitely-not-run"], self.root, self.root / "logs", missing="browser missing")
        self.assertEqual(result["status"], "NOT_EXECUTED_DEPENDENCY")
        self.assertIsNone(result["return_code"])

    def test_process_exit_status_is_traceable(self) -> None:
        import sys
        result = _run("pass", [sys.executable, "-c", "print('ok')"], self.root, self.root / "logs")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["return_code"], 0)
        self.assertTrue(Path(result["stdout_log"]).is_file())


if __name__ == "__main__": unittest.main()
