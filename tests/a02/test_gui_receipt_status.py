from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from a01_app.gui import MainWindow
from a01_app.receipt import SyncStatus


class GuiReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.inbox = self.root / "inbox"
        self.snapshot = self.root / "snapshots/latest.json"
        self.receipt = self.root / "receipts/latest.json"
        self.state = self.root / "state"

    def tearDown(self):
        self.temporary.cleanup()

    def test_home_has_separate_receipt_status_controls(self):
        window = MainWindow(inbox=self.inbox, snapshot_path=self.snapshot, receipt_path=self.receipt, state_dir=self.state)
        self.assertEqual(window.tabs.count(), 4)
        self.assertIn("同步狀態", window.home_values)
        self.assertIn("原始收件檔", window.home_values)
        self.assertIn("已匯入", window.home_values)
        self.assertIn("待處理", window.home_values)
        self.assertIn("隔離錯誤", window.home_values)
        window.close()

    def test_missing_receipt_renders_unknown_not_zero(self):
        window = MainWindow(inbox=self.inbox, snapshot_path=self.snapshot, receipt_path=self.receipt, state_dir=self.state)
        window._render_sync_status(SyncStatus("NO_RECEIPT", "D01 尚無回執／資料仍在同步", 0))
        self.assertEqual(window.home_values["待處理"].text(), "狀態未知")
        self.assertIn("不等於待處理", window.home_values["原始收件檔"].text())
        window.close()

    def test_ready_status_renders_each_count(self):
        window = MainWindow(inbox=self.inbox, snapshot_path=self.snapshot, receipt_path=self.receipt, state_dir=self.state)
        window._render_sync_status(SyncStatus("READY", "已讀取 D01 回執", 4, 2, 1, 1, 1))
        self.assertEqual(window.home_values["已匯入"].text(), "2")
        self.assertEqual(window.home_values["待處理"].text(), "1")
        self.assertEqual(window.home_values["隔離錯誤"].text(), "1")
        window.close()

    def test_refresh_control_responds_without_d01_install(self):
        window = MainWindow(inbox=self.inbox, snapshot_path=self.snapshot, receipt_path=self.receipt, state_dir=self.state)
        window.refresh_button.click()
        loop = QEventLoop(); QTimer.singleShot(500, loop.quit); loop.exec()
        self.assertIn("尚無回執", window.home_values["同步狀態"].text())
        self.assertEqual(window.home_values["待處理"].text(), "狀態未知")
        window.close()

    def test_watchlist_scope_is_visibly_preview_only(self):
        window = MainWindow(inbox=self.inbox, snapshot_path=self.snapshot, receipt_path=self.receipt, state_dir=self.state)
        window.watchlists.add("Synthetic", "10")
        window.refresh_watchlist()
        self.assertIn("不是 C01 通知", window.watch_table.item(0, 2).text())
        window.close()
