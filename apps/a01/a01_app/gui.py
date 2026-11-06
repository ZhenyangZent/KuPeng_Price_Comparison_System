from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QDate, QThreadPool, Qt, QTimer
from PySide6.QtGui import QColor, QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .constants import APP_VERSION, EXCHANGE_VERSION, SOURCE_AUTHORITY_STATUS, default_d04_report, default_inbox, default_receipt, default_snapshot, default_state_dir, project_root
from .d03_client import D03Client, D03Reply, plan_is_current
from .d04_report import read_d04_report
from .display import snapshot_rows
from .exchange import build_submission, safe_write_submission
from .importers import import_csv, import_json
from .i02_preview import PreviewResult, SyntheticSyncPreview, default_i02_workspace
from .manual_history import local_history_rows
from .schema import ValidationError, parse_money_text, parse_utc
from .settings import SettingsStore
from .receipt import SyncStatus, receipt_status
from .snapshot import SnapshotCache, SnapshotResult, read_snapshot
from .watchlist import WatchlistStore
from .workers import FunctionWorker


APP_STYLE = """
QWidget { color: #202938; background: #ffffff; font-family: "Segoe UI"; font-size: 13px; }
QMainWindow { background: #f4f6fb; }
QTabWidget::pane { border: 1px solid #d9dfeb; background: white; }
QTabBar::tab { padding: 10px 18px; background: #e9edf5; }
QTabBar::tab:selected { background: white; color: #1554ad; font-weight: 600; }
QGroupBox { font-weight: 600; border: 1px solid #d9dfeb; border-radius: 7px; margin-top: 12px; padding: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #202938; }
QPushButton { background: #1769d2; color: white; border: none; border-radius: 5px; padding: 8px 14px; }
QPushButton:disabled { background: #9aa8bb; }
QLineEdit, QComboBox, QSpinBox, QDateEdit, QTextEdit { color: #202938; background: #ffffff; padding: 5px; border: 1px solid #bfc8d8; border-radius: 4px; }
QLineEdit:disabled, QComboBox:disabled { background: #eef1f6; color: #667085; }
QTableWidget { color: #202938; background: #ffffff; alternate-background-color: #f5f7fb; gridline-color: #d9dfeb; }
QHeaderView::section { color: #202938; background: #e9edf5; padding: 6px; border: 1px solid #d9dfeb; }
"""


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        inbox: Path | None = None,
        snapshot_path: Path | None = None,
        receipt_path: Path | None = None,
        state_dir: Path | None = None,
        i02_workspace: Path | None = None,
        i02_service: SyntheticSyncPreview | None = None,
        d03_client: D03Client | None = None,
        d04_report_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.inbox = inbox or default_inbox()
        self.snapshot_path = snapshot_path or default_snapshot()
        self.receipt_path = receipt_path or default_receipt()
        self.state_dir = state_dir or default_state_dir()
        self.watchlists = WatchlistStore(self.state_dir / "watchlist.json")
        self.settings = SettingsStore(self.state_dir / "settings.json")
        self.snapshot_cache = SnapshotCache()
        self.pool = QThreadPool.globalInstance()
        self._workers: list[FunctionWorker] = []
        self.i02_service = i02_service or SyntheticSyncPreview(workspace=i02_workspace or default_i02_workspace())
        self._i02_busy = False
        self.d03_client = d03_client or D03Client(project_root())
        self.d04_report_path = d04_report_path or default_d04_report()
        self._d03_busy = False
        self._d03_preflight_ok = False
        self._d03_plan_id: str | None = None
        self._d03_plan_reply: D03Reply | None = None
        self._d03_last_command: str | None = None
        self._d03_verify_after_execute = False
        self.setWindowTitle("Coupang Deal Hunter — A04 Windows 每日本機管理")
        self.resize(1240, 900)
        self.setStyleSheet(APP_STYLE)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._build_home()
        self._build_manual()
        self._build_history()
        self._build_settings()
        self._plan_timer = QTimer(self)
        self._plan_timer.setInterval(1000)
        self._plan_timer.timeout.connect(self._refresh_plan_clock)
        self._plan_timer.start()
        self.refresh_watchlist()
        self.refresh_snapshot()

    def _title(self, text: str, detail: str) -> tuple[QLabel, QLabel]:
        title = QLabel(text)
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.DemiBold))
        subtitle = QLabel(detail)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #5c6779")
        return title, subtitle

    def _build_home(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        title, subtitle = self._title("本機資料狀態", "A04 每日介面只管理使用者明確輸入的本機資料；不連線酷澎、不掃描網頁、不發送通知。")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        offline = QLabel("● SOURCE_BLOCKED｜這是手動觀測價、非成交價；未授權自動擷取，也不代表真實優惠")
        offline.setStyleSheet("background:#fff1cc;color:#7c4a00;padding:12px;border-radius:6px;font-weight:700")
        layout.addWidget(offline)
        grid = QGridLayout()
        self.home_values: dict[str, QLabel] = {}
        entries = [
            ("應用程式版本", APP_VERSION),
            ("交換契約", EXCHANGE_VERSION),
            ("來源權限", SOURCE_AUTHORITY_STATUS),
            ("D01 快照", "資料等待中"),
            ("同步狀態", "D01 尚無回執／資料仍在同步"),
            ("原始收件檔", "0（僅檔案數，不等於待處理）"),
            ("已匯入", "狀態未知"),
            ("待處理", "狀態未知"),
            ("隔離錯誤", "狀態未知"),
        ]
        for row, (name, value) in enumerate(entries):
            grid.addWidget(QLabel(name), row, 0)
            label = QLabel(value)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(label, row, 1)
            self.home_values[name] = label
        box = QGroupBox("目前狀態")
        box.setLayout(grid)
        layout.addWidget(box)
        self.refresh_button = QPushButton("重新讀取本機快照與回執")
        self.refresh_button.clicked.connect(self.refresh_snapshot)
        layout.addWidget(self.refresh_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        self.tabs.addTab(page, "首頁 / Source Health")

    def _build_manual(self) -> None:
        page = QWidget()
        outer = QVBoxLayout(page)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); self.manual_scroll = scroll
        content = QWidget(); layout = QVBoxLayout(content)
        scroll.setWidget(content); outer.addWidget(scroll)
        title, subtitle = self._title("本機資料（手動）", "USER_ENTERED／USER_FILE 只進入等待同步收件匣；所有未核實資格固定 UNKNOWN。")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        form = QFormLayout()
        self.manual_title = QLineEdit()
        self.manual_url = QLineEdit()
        self.manual_price = QLineEdit()
        self.manual_price.setPlaceholderText("實售價觀測：非負整數 TWD；空白不等於 0")
        self.manual_observed = QLineEdit(datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
        self.manual_observed.setPlaceholderText("UTC，例如 2026-11-04T10:00:00Z")
        self.manual_product = QLineEdit()
        self.manual_variant = QLineEdit()
        self.manual_seller = QLineEdit()
        self.manual_notes = QLineEdit()
        self.manual_notes.setPlaceholderText("可選規格補充；不得貼 Cookie、帳密或訂單資料")
        self.manual_quantity = QSpinBox()
        self.manual_quantity.setRange(0, 10000)
        self.manual_quantity.setSpecialValueText("UNKNOWN")
        self.manual_shipping = QComboBox(); self.manual_shipping.addItems(["UNKNOWN"]); self.manual_shipping.setEnabled(False)
        self.manual_shipping_fee = QLineEdit(); self.manual_shipping_fee.setPlaceholderText("UNKNOWN（不得補 0）"); self.manual_shipping_fee.setEnabled(False)
        self.manual_stock = QComboBox(); self.manual_stock.addItems(["UNKNOWN"]); self.manual_stock.setEnabled(False)
        self.manual_coupon = QComboBox(); self.manual_coupon.addItems(["UNKNOWN"]); self.manual_coupon.setEnabled(False)
        self.manual_eligibility = QComboBox(); self.manual_eligibility.addItems(["UNKNOWN"]); self.manual_eligibility.setEnabled(False)
        self.manual_fee = QComboBox(); self.manual_fee.addItems(["UNKNOWN"]); self.manual_fee.setEnabled(False)
        for name, widget in [
            ("商品名稱 *", self.manual_title), ("商品 URL（可選）", self.manual_url), ("實售價觀測 TWD *", self.manual_price),
            ("觀測時間 UTC *", self.manual_observed), ("商品 ID", self.manual_product), ("SKU / 規格", self.manual_variant),
            ("賣家 ID", self.manual_seller), ("規格補充", self.manual_notes),
            ("最低件數", self.manual_quantity), ("運費狀態", self.manual_shipping), ("運費 TWD", self.manual_shipping_fee),
            ("庫存狀態", self.manual_stock), ("優惠券狀態", self.manual_coupon), ("帳號資格", self.manual_eligibility), ("必要費用", self.manual_fee),
        ]:
            form.addRow(name, widget)
        form_box = QGroupBox("使用者自行觀測（非結帳驗證）")
        form_box.setLayout(form)
        layout.addWidget(form_box)
        actions = QHBoxLayout()
        submit = QPushButton("保存 USER_ENTERED（等待同步）")
        self.manual_submit_button = submit
        submit.clicked.connect(self.submit_manual)
        file_button = QPushButton("選擇本機 CSV／JSON 匯入")
        self.manual_file_button = file_button
        file_button.clicked.connect(self.choose_local_file)
        actions.addWidget(submit); actions.addWidget(file_button); actions.addStretch()
        layout.addLayout(actions)
        self.manual_result = QTextEdit(); self.manual_result.setReadOnly(True); self.manual_result.setMaximumHeight(110)
        layout.addWidget(self.manual_result)
        self._build_d03_panel(layout)
        self.tabs.addTab(page, "本機資料（手動）")

    def _build_d03_panel(self, layout: QVBoxLayout) -> None:
        warning = QLabel("SOURCE_BLOCKED｜手動觀測價不是成交價；NT$0、WOW、首購、UNKNOWN 運費都不代表免費或可購買。")
        warning.setWordWrap(True)
        warning.setStyleSheet("background:#fff1cc;color:#7c4a00;padding:10px;border-radius:6px;font-weight:700")
        layout.addWidget(warning)
        grid = QGridLayout()
        self.d03_values: dict[str, QLabel] = {}
        for row, (name, value) in enumerate((
            ("同步元件", "檢查中"),
            ("契約", "CDH-LOCAL-MANUAL-SYNC-1"),
            ("來源狀態", "SOURCE_BLOCKED"),
            ("工作流程", "1.狀態 → 2.Preflight → 3.Dry-run → 4.人工確認 → 5.Execute → 6.Verify"),
            ("執行狀態", "WAITING_FOR_D03"),
            ("計數", "狀態未知"),
            ("Plan ID", "尚無 dry-run 計畫"),
            ("計畫失效", "尚無計畫"),
            ("備份", "execute 前必須建立並驗證 SQLite backup"),
            ("Receipt / Snapshot", "尚未驗證"),
            ("最後更新", "尚未執行"),
            ("說明", "正式 SQLite 只可由使用者確認後透過 D03 執行；GUI 不直接寫 DB。"),
        )):
            grid.addWidget(QLabel(name), row, 0)
            label = QLabel(value); label.setWordWrap(True); label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(label, row, 1); self.d03_values[name] = label
        box = QGroupBox("本地同步確認（D03 固定 CLI）")
        box.setLayout(grid); layout.addWidget(box)
        actions = QHBoxLayout()
        self.d03_status_button = QPushButton("讀取狀態")
        self.d03_status_button.clicked.connect(lambda: self.start_d03_command("status"))
        self.d03_preflight_button = QPushButton("Preflight 安全檢查")
        self.d03_preflight_button.clicked.connect(lambda: self.start_d03_command("preflight"))
        self.d03_dry_run_button = QPushButton("查看 Dry-run")
        self.d03_dry_run_button.clicked.connect(lambda: self.start_d03_command("dry-run"))
        self.d03_execute_button = QPushButton("確認後開始本地同步")
        self.d03_execute_button.clicked.connect(self.confirm_d03_execute)
        self.d03_verify_button = QPushButton("Verify 回執與歷史")
        self.d03_verify_button.clicked.connect(lambda: self.start_d03_command("verify"))
        self.d03_cancel_button = QPushButton("取消目前操作")
        self.d03_cancel_button.clicked.connect(self.cancel_d03_command)
        for button in (self.d03_status_button, self.d03_preflight_button, self.d03_dry_run_button, self.d03_execute_button, self.d03_verify_button, self.d03_cancel_button):
            actions.addWidget(button)
        actions.addStretch(); layout.addLayout(actions)
        self.d03_preview = QTextEdit()
        self.d03_preview.setReadOnly(True)
        self.d03_preview.setMaximumHeight(130)
        self.d03_preview.setPlaceholderText("Dry-run 預覽會在這裡顯示每個檔案的新增、重複、隔離或待審查結果。")
        layout.addWidget(self.d03_preview)
        self.refresh_d03_availability()

    def refresh_d03_availability(self) -> None:
        available = self.d03_client.available
        self.d03_values["同步元件"].setText("D03 已就緒" if available else "本地同步元件尚未完成")
        if available and self.d03_values["執行狀態"].text() == "WAITING_FOR_D03":
            self.d03_values["執行狀態"].setText("AVAILABLE_NOT_CHECKED")
            self.d03_values["說明"].setText("D03 介面已偵測；尚未執行 status。正式 SQLite 仍只可由使用者確認後透過 D03 執行。")
        elif not available:
            self.d03_values["執行狀態"].setText("WAITING_FOR_D03")
            self.d03_values["說明"].setText("可繼續保存手動資料；同步操作停用，未發明任何成功結果。")
        idle = available and not self._d03_busy
        self.d03_status_button.setEnabled(idle)
        self.d03_preflight_button.setEnabled(idle)
        self.d03_dry_run_button.setEnabled(idle and self._d03_preflight_ok)
        self.d03_verify_button.setEnabled(idle)
        self.d03_cancel_button.setEnabled(available and self._d03_busy)
        valid_plan = self._has_current_plan()
        if self._d03_plan_id is not None and not valid_plan:
            self.d03_values["計畫失效"].setText("已到期；請重新 Preflight / Dry-run")
        self.d03_execute_button.setEnabled(idle and self._d03_preflight_ok and valid_plan)

    def _has_current_plan(self) -> bool:
        """Require expiry binding for the real client while preserving injected test doubles."""
        if self._d03_plan_id is None:
            return False
        if isinstance(self.d03_client, D03Client):
            return self._d03_plan_reply is not None and plan_is_current(self._d03_plan_reply)
        return self._d03_plan_reply is None or self._d03_plan_reply.expires_at is None or plan_is_current(self._d03_plan_reply)

    def _set_d03_busy(self, busy: bool) -> None:
        self._d03_busy = busy
        self.manual_submit_button.setEnabled(not busy)
        self.manual_file_button.setEnabled(not busy)
        self.refresh_d03_availability()

    def start_d03_command(self, command: str) -> bool:
        if self._d03_busy or not self.d03_client.available or command not in {"status", "preflight", "dry-run", "verify"}:
            return False
        if command == "dry-run" and not self._d03_preflight_ok:
            self.d03_values["說明"].setText("請先完成 Preflight，再建立 dry-run 計畫。")
            return False
        if command in {"preflight", "dry-run"}:
            self._d03_plan_id = None
            self._d03_plan_reply = None
            if command == "preflight":
                self._d03_preflight_ok = False
        self._d03_last_command = command
        self._set_d03_busy(True)
        self.d03_values["執行狀態"].setText("RUNNING")
        self.d03_values["說明"].setText(f"正在背景執行固定命令 {command}；不使用 shell 字串。")
        self._run(lambda: self.d03_client.run(command), self._d03_ready, self._d03_failed)
        return True

    def _d03_ready(self, reply: D03Reply) -> None:
        self._set_d03_busy(False)
        self.d03_values["執行狀態"].setText(reply.result)
        counts = reply.counts
        self.d03_values["計數"].setText(
            f"掃描 {counts['scanned']}｜匯入 {counts['imported']}｜重複 {counts['duplicate']}｜隔離 {counts['quarantined']}｜待處理 {counts['pending']}"
        )
        self.d03_values["最後更新"].setText(reply.generated_at.isoformat())
        receipt = reply.data.get("receipt", {})
        snapshot = reply.data.get("snapshot", {})
        self.d03_values["Receipt / Snapshot"].setText(f"receipt={receipt.get('state', 'UNKNOWN')}｜snapshot={snapshot.get('state', 'UNKNOWN')}")
        backup = reply.data.get("backup", {})
        backup_text = f"{backup.get('state', 'UNKNOWN')}"
        if backup.get("sha256"):
            backup_text += f"｜SHA-256 {backup['sha256']}"
        if backup.get("path"):
            backup_text += f"｜{backup['path']}"
        self.d03_values["備份"].setText(backup_text)
        self.d03_values["說明"].setText("已驗證 D03 單一 JSON 回覆；SOURCE_BLOCKED 維持不變。")
        if reply.command == "preflight":
            self._d03_preflight_ok = reply.result in {"READY", "NEEDS_OPERATOR_CONFIRMATION", "NO_CHANGES"}
        elif reply.command == "dry-run":
            self._d03_plan_id = reply.plan_id if reply.result in {"DRY_RUN", "NEEDS_OPERATOR_CONFIRMATION"} else None
            self._d03_plan_reply = reply if self._d03_plan_id is not None else None
            self.d03_values["計畫失效"].setText(reply.expires_at.isoformat() if reply.expires_at else "尚無計畫")
            preview = reply.data.get("preview", [])
            lines = []
            if isinstance(preview, list):
                for item in preview:
                    if isinstance(item, dict):
                        lines.append(f"{item.get('filename', 'UNKNOWN')}｜{item.get('status', 'UNKNOWN')}｜{item.get('reason_code') or '無原因碼'}")
            self.d03_preview.setPlainText("\n".join(lines) or "Dry-run 無檔案變更；不會假稱已匯入。")
        elif reply.command == "execute":
            self._d03_plan_id = None
            self._d03_plan_reply = None
            self._d03_preflight_ok = False
            self.refresh_snapshot()
            if reply.result == "EXECUTED":
                self._d03_verify_after_execute = True
                self.d03_values["說明"].setText("execute 已完成；正在準備 Verify 回執、快照與歷史。")
                QTimer.singleShot(100, self._start_verify_after_execute)
        elif reply.command == "verify":
            self._d03_verify_after_execute = False
            self.refresh_snapshot()
            self.d03_values["說明"].setText("Verify 已通過；回執、快照與歷史已重新讀取。")
        self.d03_values["Plan ID"].setText(self._d03_plan_id or "尚無可執行 dry-run 計畫")
        self.refresh_d03_availability()

    def _d03_failed(self, message: str) -> None:
        self._d03_plan_id = None
        self._d03_plan_reply = None
        self._d03_preflight_ok = False
        self._d03_verify_after_execute = False
        self._set_d03_busy(False)
        self.d03_values["執行狀態"].setText("FAILED")
        self.d03_values["計數"].setText("狀態未知")
        self.d03_values["Plan ID"].setText("已撤銷")
        self.d03_values["計畫失效"].setText("已撤銷")
        self.d03_values["說明"].setText(f"本地同步失敗：{message}")
        self.refresh_d03_availability()

    def _refresh_plan_clock(self) -> None:
        if self._d03_plan_reply is not None and not plan_is_current(self._d03_plan_reply):
            self._d03_plan_id = None
            self._d03_plan_reply = None
            self.d03_values["Plan ID"].setText("已到期")
            self.d03_values["計畫失效"].setText("已到期；請重新 Preflight / Dry-run")
            self.d03_values["說明"].setText("dry-run 計畫已到期，execute 已停用。")
            self.refresh_d03_availability()

    def _start_verify_after_execute(self) -> None:
        if self._d03_verify_after_execute and not self._d03_busy:
            self.start_d03_command("verify")

    def cancel_d03_command(self) -> bool:
        if not self._d03_busy:
            return False
        cancel = getattr(self.d03_client, "cancel", None)
        if not callable(cancel) or not cancel():
            self.d03_values["說明"].setText("取消要求未能送達；等待目前命令安全結束或逾時。")
            return False
        self.d03_values["執行狀態"].setText("CANCEL_REQUESTED")
        self.d03_values["說明"].setText("已要求終止 D03 子程序；任何計畫都不會自動執行。")
        return True

    def confirm_d03_execute(self) -> bool:
        if self._d03_busy or not self._d03_preflight_ok or not self._has_current_plan() or not self.d03_client.available:
            return False
        answer = QMessageBox.question(
            self,
            "確認本地同步",
            "僅匯入 USER_ENTERED／USER_FILE；將先驗證備份並 append-only 寫入本機 SQLite。\n"
            "不會連線酷澎、不會刪除 inbox、不會提升商品資格。\n\n"
            f"Plan ID: {self._d03_plan_id}\n\n確定開始？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        plan_id = self._d03_plan_id
        self._set_d03_busy(True)
        self.d03_values["執行狀態"].setText("RUNNING")
        self.d03_values["說明"].setText("操作者已確認；正在執行固定 D03 execute。")
        self._run(lambda: self.d03_client.run("execute", plan_id=plan_id, operator_confirmed=True), self._d03_ready, self._d03_failed)
        return True

    def _build_history(self) -> None:
        page = QWidget(); layout = QVBoxLayout(page)
        title, subtitle = self._title("追蹤清單與歷史", "目標價只屬於 A01 預覽，不是已啟用的 C01 通知；不會改寫正式政策。")
        layout.addWidget(title); layout.addWidget(subtitle)
        add = QHBoxLayout()
        self.watch_title = QLineEdit(); self.watch_title.setPlaceholderText("商品名稱")
        self.watch_target = QLineEdit(); self.watch_target.setPlaceholderText("整筆目標價 TWD")
        self.watch_url = QLineEdit(); self.watch_url.setPlaceholderText("可選商品 URL")
        button = QPushButton("加入本機追蹤"); button.clicked.connect(self.add_watch)
        add.addWidget(self.watch_title); add.addWidget(self.watch_target); add.addWidget(self.watch_url); add.addWidget(button)
        layout.addLayout(add)
        self.watch_table = QTableWidget(0, 3); self.watch_table.setHorizontalHeaderLabels(["商品", "整筆目標價", "範圍"])
        layout.addWidget(self.watch_table)
        filter_row = QHBoxLayout(); filter_row.addWidget(QLabel("觀測日期起"))
        self.date_from = QDateEdit(QDate.currentDate().addYears(-10)); self.date_from.setCalendarPopup(True)
        self.include_synthetic = QCheckBox("顯示合成資料（明確標示）"); self.include_synthetic.setChecked(True)
        refresh = QPushButton("套用篩選"); refresh.clicked.connect(self.render_history)
        filter_row.addWidget(self.date_from); filter_row.addWidget(self.include_synthetic); filter_row.addWidget(refresh); filter_row.addStretch()
        layout.addLayout(filter_row)
        self.history_table = QTableWidget(0, 8); self.history_table.setHorizontalHeaderLabels(["商品", "價格", "觀測時間", "來源", "核實狀態", "同步狀態", "資料類型", "Submission ID"])
        layout.addWidget(self.history_table)
        report_grid = QGridLayout()
        self.d04_values: dict[str, QLabel] = {}
        for row, (name, value) in enumerate((("狀態", "讀取中"), ("報表時間", "UNKNOWN"), ("筆數", "UNKNOWN"), ("說明", "歷史報表尚未啟用"))):
            report_grid.addWidget(QLabel(name), row, 0)
            label = QLabel(value); label.setWordWrap(True); label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            report_grid.addWidget(label, row, 1); self.d04_values[name] = label
        report_box = QGroupBox("D04 歷史報表（唯讀；未啟用時不偽造資料）")
        report_box.setLayout(report_grid); layout.addWidget(report_box)
        report_button = QPushButton("重新讀取 D04 報表")
        report_button.clicked.connect(self.refresh_d04_report)
        layout.addWidget(report_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.refresh_d04_report()
        self.tabs.addTab(page, "追蹤與歷史")

    def refresh_d04_report(self) -> None:
        status = read_d04_report(self.d04_report_path)
        self.d04_values["狀態"].setText(status.state)
        self.d04_values["報表時間"].setText(status.generated_at or "UNKNOWN")
        self.d04_values["筆數"].setText("UNKNOWN" if status.item_count is None else str(status.item_count))
        self.d04_values["說明"].setText(status.detail)

    def _build_settings(self) -> None:
        page = QWidget(); layout = QVBoxLayout(page)
        title, subtitle = self._title("離線測試與設定", "設定僅存於 A01 local_state；不套用正式雷達、不送出 Windows Toast。")
        layout.addWidget(title); layout.addWidget(subtitle)
        data = self.settings.load()
        self.wow_active = QCheckBox("我自行聲明 WOW 會員有效（USER_DECLARED_ACTIVE，不等於免運已確認）")
        self.wow_active.setChecked(data["wow_membership"] == "USER_DECLARED_ACTIVE")
        self.threshold = QSpinBox(); self.threshold.setRange(-1, 10_000_000); self.threshold.setSpecialValueText("不啟用例外"); self.threshold.setValue(data["o2_paid_shipping_exception_threshold_twd"] if data["o2_paid_shipping_exception_threshold_twd"] is not None else -1)
        layout.addWidget(self.wow_active)
        form = QFormLayout(); form.addRow("O1 免運優先", QLabel("啟用（未知運費仍維持未知）")); form.addRow("O2 付運費例外門檻", self.threshold); form.addRow("首購資格", QLabel("UNKNOWN"))
        box = QGroupBox("預覽政策說明"); box.setLayout(form); layout.addWidget(box)
        buttons = QHBoxLayout()
        save = QPushButton("保存 A01 預覽設定"); save.clicked.connect(self.save_settings)
        preview = QPushButton("模擬通知預覽（不傳送）"); preview.clicked.connect(self.preview_notification)
        buttons.addWidget(save); buttons.addWidget(preview); buttons.addStretch(); layout.addLayout(buttons)
        self.settings_status = QLabel(); layout.addWidget(self.settings_status)
        self._build_i02_preview(layout)
        layout.addStretch()
        self.tabs.addTab(page, "離線測試與設定")

    def _build_i02_preview(self, layout: QVBoxLayout) -> None:
        title, subtitle = self._title(
            "合成資料同步預覽",
            "只操作 experiments/I02 隔離工作區；不讀寫正式 D01 資料庫，也不代表商品可購買。",
        )
        layout.addWidget(title); layout.addWidget(subtitle)
        warning = QLabel(
            "SYNTHETIC ONLY｜未知運費不等於免運；NT$0 不代表可購買；"
            "不連線酷澎、不發送真實通知、不執行購物。"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("background:#fff1cc;color:#7c4a00;padding:12px;border-radius:6px;font-weight:700")
        layout.addWidget(warning)
        grid = QGridLayout()
        self.i02_values: dict[str, QLabel] = {}
        values = [
            ("隔離工作區", str(self.i02_service.workspace)),
            ("執行狀態", "尚未執行"),
            ("執行模式", "UNKNOWN"),
            ("已匯入", "狀態未知"),
            ("待處理", "狀態未知"),
            ("隔離錯誤", "狀態未知"),
            ("重試", "狀態未知"),
            ("說明", "按下同步才會建立隔離 SQLite；正式資料不會被操作。"),
        ]
        for row, (name, value) in enumerate(values):
            grid.addWidget(QLabel(name), row, 0)
            label = QLabel(value); label.setWordWrap(True); label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(label, row, 1); self.i02_values[name] = label
        box = QGroupBox("I02 獨立測試面板（不覆蓋首頁正式檔案狀態）"); box.setLayout(grid); layout.addWidget(box)
        actions = QHBoxLayout()
        self.i02_sync_button = QPushButton("執行隔離寫入同步")
        self.i02_sync_button.clicked.connect(lambda: self.start_i02_sync(dry_run=False))
        self.i02_dry_run_button = QPushButton("Dry-run 檢查（不發布回執）")
        self.i02_dry_run_button.clicked.connect(lambda: self.start_i02_sync(dry_run=True))
        self.i02_second_button = QPushButton("加入第二個固定合成商品")
        self.i02_second_button.clicked.connect(self.add_i02_second_sample)
        actions.addWidget(self.i02_sync_button); actions.addWidget(self.i02_dry_run_button); actions.addWidget(self.i02_second_button); actions.addStretch()
        layout.addLayout(actions)

    def _set_i02_busy(self, busy: bool) -> None:
        self._i02_busy = busy
        for button in (self.i02_sync_button, self.i02_dry_run_button, self.i02_second_button):
            button.setEnabled(not busy)

    def start_i02_sync(self, *, dry_run: bool) -> bool:
        if self._i02_busy:
            return False
        self._set_i02_busy(True)
        self.i02_values["執行狀態"].setText("RUNNING")
        self.i02_values["執行模式"].setText("DRY_RUN" if dry_run else "ISOLATED_WRITE")
        self.i02_values["說明"].setText("背景執行中；介面仍可回應，重複觸發已停用。")
        self._run(
            lambda: self.i02_service.run_cycle(dry_run=dry_run),
            self._i02_sync_ready,
            self._i02_sync_failed,
        )
        return True

    def _i02_sync_ready(self, result: PreviewResult) -> None:
        self._set_i02_busy(False)
        self.i02_values["執行狀態"].setText(result.state)
        self.i02_values["執行模式"].setText(result.mode)
        self.i02_values["說明"].setText(result.detail)
        if result.state == "DRY_RUN":
            for name in ("已匯入", "待處理", "隔離錯誤", "重試"):
                self.i02_values[name].setText("未發布回執")
            return
        for name, value in (
            ("已匯入", result.imported_count),
            ("待處理", result.pending_count),
            ("隔離錯誤", result.quarantined_count),
            ("重試", result.retry_count),
        ):
            self.i02_values[name].setText("狀態未知" if value is None else str(value))

    def _i02_sync_failed(self, message: str) -> None:
        self._set_i02_busy(False)
        self.i02_values["執行狀態"].setText("FAILED")
        self.i02_values["說明"].setText(f"同步失敗：{message}")
        for name in ("已匯入", "待處理", "隔離錯誤", "重試"):
            self.i02_values[name].setText("狀態未知")

    def add_i02_second_sample(self) -> bool:
        if self._i02_busy:
            return False
        self._set_i02_busy(True)
        self.i02_values["執行狀態"].setText("RUNNING")
        self.i02_values["說明"].setText("正在隔離工作區建立第二個固定合成檔案。")
        self._run(
            self.i02_service.add_second_sample,
            self._i02_second_ready,
            self._i02_sync_failed,
        )
        return True

    def _i02_second_ready(self, filename: str) -> None:
        self._set_i02_busy(False)
        self.i02_values["執行狀態"].setText("PENDING")
        self.i02_values["執行模式"].setText("SYNTHETIC_INPUT_ONLY")
        self.i02_values["說明"].setText(f"已建立 {filename}；尚未同步，不可顯示 READY。")
        for name in ("已匯入", "待處理", "隔離錯誤", "重試"):
            self.i02_values[name].setText("狀態未知（待同步）")

    def _run(self, function, success, failure=None) -> None:
        worker = FunctionWorker(function)
        self._workers.append(worker)
        def done(value):
            if worker in self._workers: self._workers.remove(worker)
            success(value)
        def failed(message):
            if worker in self._workers: self._workers.remove(worker)
            (failure or self._show_error)(message)
        worker.signals.succeeded.connect(done); worker.signals.failed.connect(failed)
        self.pool.start(worker)

    def refresh_snapshot(self) -> None:
        self.home_values["D01 快照"].setText("讀取中…")
        self.home_values["同步狀態"].setText("讀取本機回執中…")
        self._run(lambda: (read_snapshot(self.snapshot_path), receipt_status(self.receipt_path, self.snapshot_path, self.inbox)), self._snapshot_ready)

    def _snapshot_ready(self, combined: tuple[SnapshotResult, SyncStatus]) -> None:
        result, sync = combined
        if result.data is not None:
            self.snapshot_cache.accept(result)
        shown = self.snapshot_cache.current
        if shown and shown.generated_at:
            suffix = "（過期）" if shown.stale else ""
            self.home_values["D01 快照"].setText(shown.generated_at.isoformat() + suffix)
        else:
            self.home_values["D01 快照"].setText(result.detail)
        self._render_sync_status(sync)
        self.render_history()

    def _render_sync_status(self, sync: SyncStatus) -> None:
        self.home_values["同步狀態"].setText(sync.detail)
        self.home_values["原始收件檔"].setText(f"{sync.raw_inbox_count}（僅檔案數，不等於待處理）")
        if sync.counts_known:
            self.home_values["已匯入"].setText(str(sync.imported_count))
            self.home_values["待處理"].setText(str(sync.pending_count))
            self.home_values["隔離錯誤"].setText(str(sync.quarantined_count))
        else:
            self.home_values["已匯入"].setText("狀態未知")
            self.home_values["待處理"].setText("狀態未知")
            self.home_values["隔離錯誤"].setText("狀態未知")

    def submit_manual(self) -> None:
        try:
            price = parse_money_text(self.manual_price.text())
            observed = parse_utc(self.manual_observed.text().strip(), "observed_at_utc")
            record = build_submission(
                product_title=self.manual_title.text(), displayed_price_twd=price, observed_at=observed,
                url=self.manual_url.text().strip() or None, product_id=self.manual_product.text().strip() or None,
                variant_id=self.manual_variant.text().strip() or None, seller_id=self.manual_seller.text().strip() or None,
                minimum_purchase_quantity=self.manual_quantity.value() or None,
                shipping_status="UNKNOWN", shipping_fee_twd=None, stock_status="UNKNOWN", coupon_status="UNKNOWN",
                account_eligibility_status="UNKNOWN", mandatory_fee_status="UNKNOWN",
                notes=self.manual_notes.text().strip(), source_kind="USER_ENTERED",
            )
        except (ValueError, ValidationError) as exc:
            self.manual_result.setPlainText(f"拒絕：{exc}")
            return
        self._run(lambda: safe_write_submission(self.inbox, record), self._submitted, lambda message: self.manual_result.setPlainText(f"寫入失敗：{message}"))

    def _submitted(self, result) -> None:
        path, digest = result
        self.manual_result.setPlainText(
            f"已建立 USER_ENTERED 收件檔：{path.name}\nSHA-256: {digest}\n"
            "狀態：等待本地同步；UNVERIFIED；運費／庫存／優惠券／資格皆為 UNKNOWN。"
        )
        self.refresh_snapshot()

    def choose_local_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "選擇使用者本機 CSV／JSON", "", "本機資料 (*.csv *.json)")
        if not path:
            return
        selected = Path(path)
        loader = import_csv if selected.suffix.casefold() == ".csv" else import_json
        self._run(lambda: loader(selected, self.inbox), self._local_file_done, lambda message: self.manual_result.setPlainText(f"本機檔案匯入失敗：{message}"))

    def choose_csv(self) -> None:
        """A01 compatibility entry point; A03 UI uses choose_local_file()."""
        self.choose_local_file()

    def _local_file_done(self, results) -> None:
        self.manual_result.setPlainText("\n".join(f"第 {item.row} 筆 {item.status}: {item.detail}" for item in results))
        self.refresh_snapshot()

    def _csv_done(self, results) -> None:
        self._local_file_done(results)

    def add_watch(self) -> None:
        try:
            self.watchlists.add(self.watch_title.text(), self.watch_target.text(), self.watch_url.text().strip() or None)
            self.refresh_watchlist()
            self.watch_title.clear(); self.watch_target.clear(); self.watch_url.clear()
        except Exception as exc:
            self._show_error(str(exc))

    def refresh_watchlist(self) -> None:
        try: items = self.watchlists.list()
        except Exception as exc: self._show_error(str(exc)); items = []
        self.watch_table.setRowCount(len(items))
        for row, item in enumerate(items):
            for col, value in enumerate((item["title"], f"NT$ {item['target_total_twd']:,}", "僅 A01 預覽，不是 C01 通知")):
                self.watch_table.setItem(row, col, QTableWidgetItem(str(value)))

    def render_history(self) -> None:
        rows = local_history_rows(self.inbox, self.snapshot_cache.current, self.receipt_path)
        if not self.include_synthetic.isChecked():
            rows = [row for row in rows if row.data_type != "合成測試"]
        start = self.date_from.date().toString("yyyy-MM-dd")
        rows = [row for row in rows if row.observed_at[:10] >= start or row.observed_at == "未知"]
        self.history_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = (row.title, row.price, row.observed_at, row.source_kind, row.verification, row.sync_state, row.data_type, row.submission_id)
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if row.data_type == "合成測試": item.setForeground(QColor("#a14b00"))
                if row.sync_state in {"等待本地同步", "格式錯誤", "隔離錯誤", "待審查／等待重試", "隔離拒收"}: item.setForeground(QColor("#a14b00"))
                self.history_table.setItem(index, col, item)

    def save_settings(self) -> None:
        threshold = None if self.threshold.value() < 0 else self.threshold.value()
        try:
            data = self.settings.save(wow_active=self.wow_active.isChecked(), paid_shipping_threshold=threshold)
            self.settings_status.setText(f"已保存：WOW={data['wow_membership']}；首購仍為 UNKNOWN；未寫入 C01。")
        except Exception as exc: self._show_error(str(exc))

    def preview_notification(self) -> None:
        QMessageBox.information(self, "模擬預覽 — 不傳送", "[模擬] 商品可能符合目標價。\n運費、資格、券及必要費用未知時仍不得視為合格優惠。\n沒有呼叫 Windows Toast 或遠端服務。")

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "A04 本機管理", message)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._d03_busy:
            cancel = getattr(self.d03_client, "cancel", None)
            if callable(cancel):
                cancel()
        event.accept()


def run_app(*, screenshot: Path | None = None, screenshot_tab: int = 0, exit_after_ms: int | None = None) -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    if screenshot is not None:
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        window.tabs.setCurrentIndex(max(0, min(screenshot_tab, window.tabs.count() - 1)))
        QTimer.singleShot(800, lambda: window.grab().save(str(screenshot), "PNG"))
        QTimer.singleShot(1200, app.quit)
    elif exit_after_ms is not None:
        QTimer.singleShot(exit_after_ms, app.quit)
    return app.exec()
