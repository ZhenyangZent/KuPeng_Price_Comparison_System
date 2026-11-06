from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from a01_app.gui import MainWindow
from a01_app.i02_preview import PreviewResult


APP = QApplication.instance() or QApplication([])
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = PROJECT_ROOT / "experiments" / "I02" / "test_runs"


def wait_until(predicate, timeout_ms: int = 2000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    APP.processEvents()
    return bool(predicate())


class FakeService:
    def __init__(self, workspace: Path, *, delay: float = 0.0, failure: str | None = None, dry_run: bool = False) -> None:
        self.workspace = workspace
        self.delay = delay
        self.failure = failure
        self.dry_run = dry_run
        self.run_count = 0
        self.second_count = 0

    def run_cycle(self, *, dry_run: bool = False):
        self.run_count += 1
        time.sleep(self.delay)
        if self.failure:
            raise RuntimeError(self.failure)
        if dry_run or self.dry_run:
            return PreviewResult("DRY_RUN", "no receipt", "DRY_RUN", str(self.workspace), None, None, None, None, 1, False)
        return PreviewResult("READY", "synthetic ready", "ISOLATED_WRITE", str(self.workspace), 1, 0, 0, 0, 1, True)

    def add_second_sample(self):
        self.second_count += 1
        time.sleep(self.delay)
        if self.failure:
            raise RuntimeError(self.failure)
        return "submission_22222222-2222-4222-8222-222222222222.json"


class I02GuiTests(unittest.TestCase):
    def make_window(self, service: FakeService):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="i02-gui-", dir=TEST_ROOT)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        window = MainWindow(
            inbox=root / "inbox",
            snapshot_path=root / "snapshots/latest.json",
            receipt_path=root / "receipts/latest.json",
            state_dir=root / "state",
            i02_service=service,
        )
        self.addCleanup(window.close)
        window.show()
        self.assertTrue(wait_until(lambda: "讀取" not in window.home_values["同步狀態"].text()))
        return window

    def test_existing_four_tabs_are_preserved_with_isolated_preview_panel(self):
        service = FakeService(Path("experiments/I02/fake"))
        window = self.make_window(service)
        self.assertEqual(window.tabs.count(), 4)
        self.assertEqual(window.tabs.tabText(3), "離線測試與設定")
        self.assertIn("experiments", window.i02_values["隔離工作區"].text())

    def test_worker_is_nonblocking_and_repeated_trigger_is_refused(self):
        service = FakeService(Path("experiments/I02/fake"), delay=0.3)
        window = self.make_window(service)
        ticks = {"count": 0}
        timer = QTimer(); timer.setInterval(20); timer.timeout.connect(lambda: ticks.__setitem__("count", ticks["count"] + 1)); timer.start()
        self.addCleanup(timer.stop)
        self.assertTrue(window.start_i02_sync(dry_run=False))
        self.assertFalse(window.start_i02_sync(dry_run=False))
        self.assertFalse(window.i02_sync_button.isEnabled())
        loop = QEventLoop(); QTimer.singleShot(150, loop.quit); loop.exec()
        self.assertGreater(ticks["count"], 2)
        self.assertTrue(wait_until(lambda: not window._i02_busy))
        self.assertEqual(service.run_count, 1)
        self.assertEqual(window.i02_values["執行狀態"].text(), "READY")

    def test_dry_run_never_renders_ready_counts(self):
        service = FakeService(Path("experiments/I02/fake"))
        window = self.make_window(service)
        window.start_i02_sync(dry_run=True)
        self.assertTrue(wait_until(lambda: not window._i02_busy))
        self.assertEqual(window.i02_values["執行狀態"].text(), "DRY_RUN")
        self.assertEqual(window.i02_values["已匯入"].text(), "未發布回執")

    def test_worker_failure_is_visible_and_counts_unknown(self):
        service = FakeService(Path("experiments/I02/fake"), failure="injected interruption")
        window = self.make_window(service)
        window.start_i02_sync(dry_run=False)
        self.assertTrue(wait_until(lambda: not window._i02_busy))
        self.assertEqual(window.i02_values["執行狀態"].text(), "FAILED")
        self.assertIn("injected interruption", window.i02_values["說明"].text())
        self.assertEqual(window.i02_values["已匯入"].text(), "狀態未知")

    def test_add_second_marks_pending_without_false_ready(self):
        service = FakeService(Path("experiments/I02/fake"))
        window = self.make_window(service)
        window.add_i02_second_sample()
        self.assertTrue(wait_until(lambda: not window._i02_busy))
        self.assertEqual(window.i02_values["執行狀態"].text(), "PENDING")
        self.assertIn("尚未同步", window.i02_values["說明"].text())
        self.assertEqual(service.second_count, 1)

    def test_i02_panel_does_not_overwrite_home_status(self):
        service = FakeService(Path("experiments/I02/fake"))
        window = self.make_window(service)
        before = window.home_values["同步狀態"].text()
        window.start_i02_sync(dry_run=False)
        self.assertTrue(wait_until(lambda: not window._i02_busy))
        self.assertEqual(window.home_values["同步狀態"].text(), before)


if __name__ == "__main__":
    unittest.main()
