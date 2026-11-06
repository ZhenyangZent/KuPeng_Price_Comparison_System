from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path(sys.executable)
BOOTSTRAP = "import sys; sys.path.insert(0, sys.argv.pop(1)); from a01_app.main import main; raise SystemExit(main())"


def app_command(*arguments: str) -> list[str]:
    return [str(PYTHON), "-c", BOOTSTRAP, str(ROOT / "apps/a01"), *arguments]


class GuiSafetyTests(unittest.TestCase):
    def test_t09_gui_opens_closes_and_reopens_offscreen(self):
        env = dict(os.environ); env["PYTHONPATH"] = str(ROOT / "apps/a01"); env["QT_QPA_PLATFORM"] = "offscreen"
        for _ in range(2):
            result = subprocess.run(app_command("--exit-after-ms", "250"), env=env, cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_t10_no_forbidden_runtime_integrations_in_a01_source(self):
        source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "apps/a01/a01_app").glob("*.py"))
        forbidden = ["winreg", "selenium", "playwright", "requests.get", "urllib.request", "FirefoxProfile", "QSystemTrayIcon.showMessage", "win10toast"]
        for token in forbidden:
            with self.subTest(token=token): self.assertNotIn(token, source)

    def test_screenshot_mode_produces_png(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "ui.png"
            env = dict(os.environ); env["PYTHONPATH"] = str(ROOT / "apps/a01"); env["QT_QPA_PLATFORM"] = "offscreen"
            result = subprocess.run(app_command("--screenshot", str(output)), env=env, cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr); self.assertTrue(output.is_file()); self.assertGreater(output.stat().st_size, 1000)
