from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
sys.path.insert(0, str(APP_ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from a01_app.d03_client import D03Client
from a01_app.gui import MainWindow
from a01_app.i02_preview import PreviewResult
from a01_app.importers import import_csv


class EvidenceI02:
    workspace = PROJECT_ROOT / "experiments/I02/frozen-not-operated"
    def run_cycle(self, *, dry_run=False):
        return PreviewResult("DRY_RUN", "not used by A03 evidence", "DRY_RUN", str(self.workspace), None, None, None, None, 0, False)
    def add_second_sample(self):
        return "not-used.json"


def file_identity(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"exists": False, "bytes": None, "sha256": None}
    return {"exists": True, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("top_screenshot", type=Path)
    parser.add_argument("sync_screenshot", type=Path)
    parser.add_argument("history_screenshot", type=Path)
    parser.add_argument("--hold-ms", type=int, default=30000)
    args = parser.parse_args()
    for path in (args.evidence, args.top_screenshot, args.sync_screenshot, args.history_screenshot):
        path.parent.mkdir(parents=True, exist_ok=True)

    allowed = (PROJECT_ROOT / "experiments/A03").resolve()
    workspace = (allowed / "windows_gui_evidence").resolve()
    if not inside(workspace, allowed) or workspace == allowed:
        raise SystemExit("unsafe A03 workspace")
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    inbox = workspace / "data/exchange/inbox"
    snapshot = workspace / "data/exchange/snapshots/latest.json"
    receipt = workspace / "data/exchange/receipts/latest.json"
    state_dir = workspace / "state"
    csv_path = workspace / "selected_user_file.csv"
    csv_path.write_text(
        "product_title,displayed_price_twd,observed_at_utc,url,variant_id\n"
        "A03 CSV 商品,19,2026-11-04T09:00:00Z,,CSV-SKU\n",
        encoding="utf-8",
    )
    production_db = PROJECT_ROOT / "data/d01/observations.sqlite3"
    database_before = file_identity(production_db)
    d03 = D03Client(PROJECT_ROOT)

    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        inbox=inbox, snapshot_path=snapshot, receipt_path=receipt, state_dir=state_dir,
        i02_service=EvidenceI02(), d03_client=d03,
    )
    window.tabs.setCurrentIndex(1); window.show()
    heartbeat = {"count": 0}; heart = QTimer(); heart.setInterval(25); heart.timeout.connect(lambda: heartbeat.__setitem__("count", heartbeat["count"] + 1)); heart.start()
    state = {"phase": 0, "first_result": "", "import_result": "", "replay_result": "", "restart_rows": 0}

    def begin_manual() -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        window.manual_title.setText("A03 手動零元商品")
        window.manual_price.setText("0")
        window.manual_observed.setText(now)
        window.manual_variant.setText("MANUAL-SKU")
        window.manual_notes.setText("Windows GUI isolated evidence")
        window.submit_manual()

    def advance() -> None:
        phase = state["phase"]
        if phase == 0 and "等待本地同步" in window.manual_result.toPlainText():
            state["first_result"] = window.manual_result.toPlainText(); state["phase"] = 1
            window._run(lambda: import_csv(csv_path, inbox), window._local_file_done, window._show_error)
        elif phase == 1 and "IMPORTED" in window.manual_result.toPlainText():
            state["import_result"] = window.manual_result.toPlainText(); state["phase"] = 2
            window._run(lambda: import_csv(csv_path, inbox), window._local_file_done, window._show_error)
        elif phase == 2 and "DUPLICATE_NOOP" in window.manual_result.toPlainText():
            state["replay_result"] = window.manual_result.toPlainText(); state["phase"] = 3
            window.render_history(); window.manual_scroll.verticalScrollBar().setValue(0)
            QTimer.singleShot(100, capture_top)

    def capture_top() -> None:
        window.grab().save(str(args.top_screenshot), "PNG")
        window.manual_scroll.verticalScrollBar().setValue(window.manual_scroll.verticalScrollBar().maximum())
        QTimer.singleShot(100, capture_sync)

    def capture_sync() -> None:
        window.grab().save(str(args.sync_screenshot), "PNG")
        window.tabs.setCurrentIndex(2); window.render_history()
        QTimer.singleShot(100, capture_history)

    def capture_history() -> None:
        window.grab().save(str(args.history_screenshot), "PNG")
        state["phase"] = 4
        window.close()
        restart()

    def restart() -> None:
        second = MainWindow(
            inbox=inbox, snapshot_path=snapshot, receipt_path=receipt, state_dir=state_dir,
            i02_service=EvidenceI02(), d03_client=d03,
        )
        state["second_window"] = second
        second.tabs.setCurrentIndex(2); second.show(); second.render_history()
        state["restart_rows"] = second.history_table.rowCount()
        files = sorted(inbox.glob("submission_*.json"))
        records = [json.loads(path.read_text(encoding="utf-8")) for path in files]
        database_after = file_identity(production_db)
        expected_d03_state = "AVAILABLE_NOT_CHECKED" if d03.available else "WAITING_FOR_D03"
        expected_controls = (
            second.d03_status_button.isEnabled()
            and second.d03_preflight_button.isEnabled()
            and second.d03_dry_run_button.isEnabled()
            and not second.d03_execute_button.isEnabled()
        ) if d03.available else (
            not second.d03_status_button.isEnabled()
            and not second.d03_preflight_button.isEnabled()
            and not second.d03_dry_run_button.isEnabled()
            and not second.d03_execute_button.isEnabled()
        )
        result = {
            "task_id": "CDH-A03-USABLE-LOCAL-GUI-001",
            "visible": second.isVisible(),
            "native_win_id_nonzero": int(second.winId()) != 0,
            "heartbeat_count": heartbeat["count"],
            "workspace": str(workspace),
            "formal_database_before": database_before,
            "formal_database_after": database_after,
            "formal_database_unchanged": database_before == database_after,
            "submission_count": len(files),
            "source_kinds": sorted(record["source"]["source_kind"] for record in records),
            "zero_record": any(record["offer"]["displayed_price_twd"] == 0 and record["offer"]["shipping_status"] == "UNKNOWN" and record["offer"]["shipping_fee_twd"] is None for record in records),
            "duplicate_replay": "DUPLICATE_NOOP" in state["replay_result"],
            "restart_history_rows": state["restart_rows"],
            "d03_available": d03.available,
            "d03_state": second.d03_values["執行狀態"].text(),
            "d03_control_gate": expected_controls,
            "d03_execute_disabled": not second.d03_execute_button.isEnabled(),
            "dry_run_state": "NOT_RUN_PROTECTED_D03" if d03.available else "WAITING_FOR_D03",
            "source_status": second.d03_values["來源狀態"].text(),
        }
        result["result"] = "PASS" if (
            result["formal_database_unchanged"] and result["submission_count"] == 2
            and result["source_kinds"] == ["USER_ENTERED", "USER_FILE"] and result["zero_record"]
            and result["duplicate_replay"] and result["restart_history_rows"] == 2
            and result["d03_state"] == expected_d03_state and result["d03_control_gate"]
            and result["source_status"] == "SOURCE_BLOCKED" and result["native_win_id_nonzero"]
        ) else "FAIL"
        args.evidence.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        second.tabs.setCurrentIndex(1); second.manual_scroll.verticalScrollBar().setValue(second.manual_scroll.verticalScrollBar().maximum())
        QTimer.singleShot(max(500, args.hold_ms), app.quit)

    monitor = QTimer(); monitor.setInterval(30); monitor.timeout.connect(advance); monitor.start()
    QTimer.singleShot(250, begin_manual)
    QTimer.singleShot(max(15000, args.hold_ms + 15000), app.quit)
    code = app.exec(); monitor.stop(); heart.stop()
    if code != 0 or not args.evidence.is_file():
        return code or 2
    return 0 if json.loads(args.evidence.read_text(encoding="utf-8"))["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
