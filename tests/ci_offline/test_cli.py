from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from tools.ci_offline.check_project import main, output_path_allowed
from tools.ci_offline.runner import ExitCode


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = PROJECT_ROOT / "reports" / "G02" / "test_tmp"


class CliBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT, ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_output_path_policy_accepts_only_g02_roots(self) -> None:
        self.assertTrue(output_path_allowed(self.root, self.root / "reports" / "G02" / "run"))
        self.assertTrue(output_path_allowed(self.root, self.root / "review" / "G02" / "run"))
        self.assertFalse(output_path_allowed(self.root, self.root / "reports" / "B07"))

    def test_cli_rejects_outside_output_before_creation(self) -> None:
        outside = self.root / "reports" / "B07" / "forbidden"
        with redirect_stderr(StringIO()):
            code = main(["--project-root", str(self.root), "--output-dir", str(outside), "--suite", "g02_self"])
        self.assertEqual(code, int(ExitCode.USAGE_ERROR))
        self.assertFalse(outside.exists())

    def test_python_runner_contains_no_dependency_install_command(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8").lower()
            for path in sorted((PROJECT_ROOT / "tools" / "ci_offline").glob("*.py"))
        )
        self.assertNotIn("npm install", source)
        self.assertNotIn("pip install", source)
        self.assertNotIn("npx ", source)


if __name__ == "__main__":
    unittest.main()
