from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

from a01_app.d03_client import D03Reply
from a01_app.gui import MainWindow
from a01_app.i02_preview import PreviewResult


APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = ROOT / "experiments/A04/test_tmp"
PLAN = "c" * 64


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate(): return True
        time.sleep(0.01)
    APP.processEvents(); return bool(predicate())


def response(command, result="READY", *, plan_id=None, expires=True):
    now = datetime.now(timezone.utc)
    data = {
        "contract": "CDH-LOCAL-MANUAL-SYNC-1", "command": command, "result": result,
        "source_status": "SOURCE_BLOCKED", "data_scope": "USER_PROVIDED_LOCAL_ONLY", "plan_id": plan_id,
        "database_kind": "USER_LOCAL", "dry_run": command == "dry-run",
        "counts": {"scanned": 2, "imported": 1 if command == "execute" else 0, "duplicate": 1, "quarantined": 0, "pending": 0},
        "receipt": {"state": "READY", "sha256": "1" * 64}, "snapshot": {"state": "READY", "sha256": "2" * 64},
        "backup": {"state": "VERIFIED" if command == "execute" else "NOT_REQUIRED", "path": "synthetic.sqlite3", "sha256": "3" * 64 if command == "execute" else None},
        "preview": [{"filename": "submission_synthetic.json", "status": "IMPORTED", "reason_code": None}],
        "errors": [], "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    return D03Reply(command, result, plan_id, data["counts"], now, data, now + timedelta(minutes=10) if plan_id and expires else None)


class FakeI02:
    workspace = Path("experiments/A04/fake_i02")
    def run_cycle(self, *, dry_run=False):
        return PreviewResult("DRY_RUN", "synthetic", "DRY_RUN", str(self.workspace), None, None, None, None, 0, False)
    def add_second_sample(self): return "second.json"


class FakeD03:
    available = True
    def __init__(self, delay=0): self.delay = delay; self.calls = []; self.cancelled = False
    def run(self, command, *, plan_id=None, operator_confirmed=False):
        self.calls.append(command); time.sleep(self.delay)
        if command == "preflight": return response(command)
        if command == "dry-run": return response(command, "NEEDS_OPERATOR_CONFIRMATION", plan_id=PLAN)
        if command == "execute": return response(command, "EXECUTED", plan_id=plan_id)
        return response(command)
    def cancel(self): self.cancelled = True; return True


class A04GuiTests(unittest.TestCase):
    def setUp(self):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="gui-", dir=TEST_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def window(self, client=None):
        window = MainWindow(inbox=self.root / "inbox", snapshot_path=self.root / "snap/latest.json", receipt_path=self.root / "receipt/latest.json", state_dir=self.root / "state", i02_service=FakeI02(), d03_client=client or FakeD03(), d04_report_path=self.root / "d04/latest.json")
        self.addCleanup(window.close); window.show(); self.assertTrue(wait_until(lambda: "讀取" not in window.home_values["同步狀態"].text()))
        return window

    def test_daily_workflow_is_visible_and_dry_run_is_gated(self):
        window = self.window()
        self.assertIn("Preflight", window.d03_values["工作流程"].text())
        self.assertFalse(window.d03_dry_run_button.isEnabled())
        self.assertFalse(window.start_d03_command("dry-run"))
        self.assertIn("Preflight", window.d03_values["說明"].text())

    def test_preflight_and_dry_run_show_preview_expiry_and_enable_confirm(self):
        window = self.window()
        self.assertTrue(window.start_d03_command("preflight")); self.assertTrue(wait_until(lambda: not window._d03_busy))
        self.assertTrue(window.start_d03_command("dry-run")); self.assertTrue(wait_until(lambda: not window._d03_busy))
        self.assertIn("submission_synthetic.json", window.d03_preview.toPlainText())
        self.assertIn("+00:00", window.d03_values["計畫失效"].text())
        self.assertTrue(window.d03_execute_button.isEnabled())

    def test_expired_plan_is_revoked_before_execute(self):
        window = self.window()
        expired = response("dry-run", "NEEDS_OPERATOR_CONFIRMATION", plan_id=PLAN)
        object.__setattr__(expired, "expires_at", datetime.now(timezone.utc) - timedelta(seconds=1))
        window._d03_preflight_ok = True; window._d03_plan_id = PLAN; window._d03_plan_reply = expired
        window._refresh_plan_clock()
        self.assertIsNone(window._d03_plan_id)
        self.assertFalse(window.d03_execute_button.isEnabled())
        self.assertIn("已到期", window.d03_values["說明"].text())

    def test_confirm_execute_auto_verifies_and_refreshes_receipt(self):
        client = FakeD03(); window = self.window(client)
        window.start_d03_command("preflight"); self.assertTrue(wait_until(lambda: not window._d03_busy))
        window.start_d03_command("dry-run"); self.assertTrue(wait_until(lambda: not window._d03_busy))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(window.confirm_d03_execute())
        self.assertTrue(wait_until(lambda: client.calls[-1] == "verify" and not window._d03_busy))
        self.assertEqual(client.calls, ["preflight", "dry-run", "execute", "verify"])
        self.assertEqual(window.d03_values["Receipt / Snapshot"].text(), "receipt=READY｜snapshot=READY")

    def test_reentry_and_cancel_are_explicit(self):
        client = FakeD03(delay=.25); window = self.window(client)
        self.assertTrue(window.start_d03_command("status")); self.assertFalse(window.start_d03_command("status"))
        self.assertTrue(window.cancel_d03_command())
        self.assertTrue(client.cancelled)
        self.assertEqual(window.d03_values["執行狀態"].text(), "CANCEL_REQUESTED")
        self.assertTrue(wait_until(lambda: not window._d03_busy))

    def test_d04_absence_is_not_reported_as_ready(self):
        window = self.window()
        self.assertEqual(window.d04_values["狀態"].text(), "NOT_ENABLED")
        self.assertEqual(window.d04_values["說明"].text(), "歷史報表尚未啟用")


if __name__ == "__main__":
    unittest.main()
