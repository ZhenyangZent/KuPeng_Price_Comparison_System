from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.ci_web_g04.runner import _exit_code, _find_root, _redact, _run, _write_html


class RunnerTests(unittest.TestCase):
    def setUp(self):
        parent = Path("reports/G04/test_tmp").resolve(); parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent); self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def test_find_release_root_from_marker(self):
        marker = self.root / "PKG" / "apps" / "price-web" / "frontend"; marker.mkdir(parents=True)
        self.assertEqual(_find_root(self.root, Path("apps/price-web/frontend")), self.root / "PKG")

    def test_exit_code_prioritizes_security(self):
        self.assertEqual(_exit_code([{"status": "PASS"}], [{"passed": False}]), 4)

    def test_missing_dependency_is_not_run(self):
        result = _run("skip", ["never"], self.root, self.root / "logs", self.root, missing="node missing")
        self.assertEqual(result["status"], "NOT_RUN_DEPENDENCY"); self.assertIsNone(result["return_code"])

    def test_redaction_removes_project_path(self):
        self.assertNotIn(str(self.root), _redact(f"error at {self.root / 'x'}", self.root))

    def test_process_result_retains_actual_exit_code(self):
        import sys
        result = _run("ok", [sys.executable, "-c", "print('ok')"], self.root, self.root / "logs", self.root)
        self.assertEqual((result["status"], result["return_code"]), ("PASS", 0))

    def test_html_report_accepts_missing_crossline_result(self):
        output = self.root / "result.html"
        _write_html(output, {"profile": "baseline-defects", "crossline": None, "suites": []})
        self.assertIn("Crossline", output.read_text(encoding="utf-8"))


if __name__ == "__main__": unittest.main()
