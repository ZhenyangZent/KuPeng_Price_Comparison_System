from __future__ import annotations

import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from a01_app.d03_client import D03Reply
from a01_app.gui import MainWindow
from a01_app.i02_preview import PreviewResult


APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = ROOT / "experiments/A03/test_runs"


def wait_until(predicate, timeout_ms=3000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate(): return True
        time.sleep(0.01)
    APP.processEvents(); return bool(predicate())


def d03_reply(command, *, result="READY", plan_id=None, dry_run=False):
    data = {
        "contract": "CDH-LOCAL-MANUAL-SYNC-1", "command": command, "result": result,
        "source_status": "SOURCE_BLOCKED", "data_scope": "USER_PROVIDED_LOCAL_ONLY", "plan_id": plan_id,
        "database_kind": "USER_LOCAL", "dry_run": dry_run,
        "counts": {"scanned": 2, "imported": 0, "duplicate": 0, "quarantined": 0, "pending": 2},
        "receipt": {"state": "UNKNOWN", "sha256": None}, "snapshot": {"state": "UNKNOWN", "sha256": None},
        "backup": {"state": "NOT_REQUIRED", "path": None, "sha256": None}, "errors": [],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    return D03Reply(command, result, plan_id, data["counts"], datetime.now(timezone.utc), data)


class FakeI02:
    workspace = Path("experiments/I02/fake")
    def run_cycle(self, *, dry_run=False):
        return PreviewResult("DRY_RUN", "synthetic", "DRY_RUN", str(self.workspace), None, None, None, None, 0, False)
    def add_second_sample(self): return "synthetic.json"


class FakeD03:
    def __init__(self, *, available=True, delay=0.0, failure=None):
        self.available = available; self.delay = delay; self.failure = failure; self.calls = []
    def run(self, command, *, plan_id=None, operator_confirmed=False):
        self.calls.append((command, plan_id, operator_confirmed)); time.sleep(self.delay)
        if self.failure: raise RuntimeError(self.failure)
        if command == "preflight": return d03_reply(command, result="READY")
        if command == "dry-run": return d03_reply(command, result="NEEDS_OPERATOR_CONFIRMATION", plan_id="a" * 64, dry_run=True)
        if command == "execute": return d03_reply(command, result="EXECUTED", plan_id=plan_id)
        return d03_reply(command)


class A03GuiTests(unittest.TestCase):
    def setUp(self):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="a03-gui-", dir=TEST_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def window(self, client):
        window = MainWindow(
            inbox=self.root / "inbox", snapshot_path=self.root / "snapshots/latest.json",
            receipt_path=self.root / "receipts/latest.json", state_dir=self.root / "state",
            i02_service=FakeI02(), d03_client=client,
        )
        self.addCleanup(window.close); window.show()
        self.assertTrue(wait_until(lambda: "讀取" not in window.home_values["同步狀態"].text()))
        return window

    def test_four_tabs_preserved_and_manual_tab_is_explicit(self):
        window = self.window(FakeD03(available=False))
        self.assertEqual(window.tabs.count(), 4)
        self.assertEqual(window.tabs.tabText(1), "本機資料（手動）")
        self.assertIn("SOURCE_BLOCKED", window.home_values["來源權限"].text())

    def test_missing_d03_disables_all_sync_actions(self):
        window = self.window(FakeD03(available=False))
        self.assertEqual(window.d03_values["執行狀態"].text(), "WAITING_FOR_D03")
        self.assertIn("尚未完成", window.d03_values["同步元件"].text())
        self.assertFalse(window.d03_status_button.isEnabled())
        self.assertFalse(window.d03_execute_button.isEnabled())
        self.assertTrue(window.manual_submit_button.isEnabled())

    def test_manual_zero_creates_user_entered_pending_unknown(self):
        window = self.window(FakeD03(available=False))
        window.manual_title.setText("手動零元測試")
        window.manual_price.setText("0")
        window.manual_observed.setText(datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
        window.manual_variant.setText("SKU-A")
        window.submit_manual()
        self.assertTrue(wait_until(lambda: "等待本地同步" in window.manual_result.toPlainText()))
        path = next((self.root / "inbox").glob("submission_*.json"))
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["source"]["source_kind"], "USER_ENTERED")
        self.assertEqual((record["offer"]["displayed_price_twd"], record["offer"]["shipping_status"], record["offer"]["shipping_fee_twd"]), (0, "UNKNOWN", None))

    def test_preflight_then_dry_run_enables_execute(self):
        client = FakeD03()
        window = self.window(client)
        self.assertTrue(window.start_d03_command("preflight"))
        self.assertTrue(wait_until(lambda: not window._d03_busy))
        self.assertFalse(window.d03_execute_button.isEnabled())
        self.assertTrue(window.start_d03_command("dry-run"))
        self.assertTrue(wait_until(lambda: not window._d03_busy))
        self.assertEqual(window.d03_values["Plan ID"].text(), "a" * 64)
        self.assertTrue(window.d03_execute_button.isEnabled())

    def test_execute_requires_explicit_yes_and_locks_reentry(self):
        client = FakeD03(delay=0.2)
        window = self.window(client)
        window._d03_preflight_ok = True; window._d03_plan_id = "a" * 64; window.refresh_d03_availability()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(window.confirm_d03_execute())
        self.assertEqual(client.calls, [])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(window.confirm_d03_execute())
        self.assertFalse(window.confirm_d03_execute())
        self.assertFalse(window.d03_execute_button.isEnabled())
        self.assertTrue(wait_until(lambda: not window._d03_busy))
        self.assertEqual(client.calls, [("execute", "a" * 64, True)])
        self.assertEqual(window.d03_values["執行狀態"].text(), "EXECUTED")

    def test_background_d03_does_not_freeze_event_loop(self):
        window = self.window(FakeD03(delay=0.3))
        ticks = {"count": 0}; timer = QTimer(); timer.setInterval(20); timer.timeout.connect(lambda: ticks.__setitem__("count", ticks["count"] + 1)); timer.start(); self.addCleanup(timer.stop)
        self.assertTrue(window.start_d03_command("status")); self.assertFalse(window.start_d03_command("status"))
        loop = QEventLoop(); QTimer.singleShot(150, loop.quit); loop.exec()
        self.assertGreater(ticks["count"], 2)
        self.assertTrue(wait_until(lambda: not window._d03_busy))

    def test_failure_never_displays_imported_success(self):
        window = self.window(FakeD03(failure="synthetic runner failure"))
        window.start_d03_command("status")
        self.assertTrue(wait_until(lambda: not window._d03_busy))
        self.assertEqual(window.d03_values["執行狀態"].text(), "FAILED")
        self.assertEqual(window.d03_values["計數"].text(), "狀態未知")
        self.assertIn("synthetic runner failure", window.d03_values["說明"].text())

    def test_close_reopen_reads_pending_manual_history(self):
        first = self.window(FakeD03(available=False))
        first.manual_title.setText("重啟歷史")
        first.manual_price.setText("11")
        first.manual_observed.setText(datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
        first.submit_manual(); self.assertTrue(wait_until(lambda: "等待本地同步" in first.manual_result.toPlainText())); first.close()
        second = self.window(FakeD03(available=False)); second.render_history()
        self.assertEqual(second.history_table.item(0, 0).text(), "重啟歷史")
        self.assertEqual(second.history_table.item(0, 5).text(), "等待本地同步")


if __name__ == "__main__":
    unittest.main()
