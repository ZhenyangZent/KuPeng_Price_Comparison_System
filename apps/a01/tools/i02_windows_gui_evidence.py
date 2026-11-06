from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
sys.path.insert(0, str(APP_ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from a01_app.gui import MainWindow
from a01_app.i02_preview import SyntheticSyncPreview


def inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Visible I02 Windows four-cycle GUI evidence")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("screenshot", type=Path)
    args = parser.parse_args()
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.screenshot.parent.mkdir(parents=True, exist_ok=True)

    allowed = (PROJECT_ROOT / "experiments/I02").resolve()
    workspace = (allowed / "windows_gui_evidence").resolve()
    if not inside(workspace, allowed) or workspace == allowed:
        raise SystemExit("unsafe I02 evidence workspace")
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)

    service = SyntheticSyncPreview(root=PROJECT_ROOT, workspace=workspace / "sync_workspace")
    home = workspace / "home_empty"
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        inbox=home / "inbox",
        snapshot_path=home / "snapshots/latest.json",
        receipt_path=home / "receipts/latest.json",
        state_dir=home / "state",
        i02_service=service,
    )
    window.tabs.setCurrentIndex(3)
    window.show()
    heartbeat = {"count": 0}
    heart_timer = QTimer()
    heart_timer.setInterval(25)
    heart_timer.timeout.connect(lambda: heartbeat.__setitem__("count", heartbeat["count"] + 1))
    heart_timer.start()
    phases: list[dict[str, object]] = []
    state = {"phase": 0, "duplicate_refused": False, "buttons_disabled": False}

    def capture(label: str) -> None:
        phases.append(
            {
                "label": label,
                "state": window.i02_values["執行狀態"].text(),
                "mode": window.i02_values["執行模式"].text(),
                "imported": window.i02_values["已匯入"].text(),
                "pending": window.i02_values["待處理"].text(),
                "quarantined": window.i02_values["隔離錯誤"].text(),
                "detail": window.i02_values["說明"].text(),
            }
        )

    def begin() -> None:
        accepted = window.start_i02_sync(dry_run=False)
        state["buttons_disabled"] = not window.i02_sync_button.isEnabled()
        state["duplicate_refused"] = accepted and not window.start_i02_sync(dry_run=False)

    def advance() -> None:
        if window._i02_busy:
            return
        phase = state["phase"]
        if phase == 0 and window.i02_values["執行狀態"].text() == "READY":
            capture("FIRST_IMPORT")
            state["phase"] = 1
            window.start_i02_sync(dry_run=False)
        elif phase == 1 and window.i02_values["執行狀態"].text() == "READY":
            capture("IDENTICAL_REPLAY")
            state["phase"] = 2
            window.add_i02_second_sample()
        elif phase == 2 and window.i02_values["執行狀態"].text() == "PENDING":
            capture("SECOND_SAMPLE_PENDING")
            state["phase"] = 3
            window.start_i02_sync(dry_run=False)
        elif phase == 3 and window.i02_values["執行狀態"].text() == "READY":
            capture("SECOND_IMPORT")
            state["phase"] = 4
            window.start_i02_sync(dry_run=False)
        elif phase == 4 and window.i02_values["執行狀態"].text() == "READY":
            capture("TWO_ITEM_REPLAY")
            state["phase"] = 5
            window.grab().save(str(args.screenshot), "PNG")
            service.export_workspace_summary(workspace / "WORKSPACE_SUMMARY.json")
            expected = [
                ("FIRST_IMPORT", "READY", "1", "0"),
                ("IDENTICAL_REPLAY", "READY", "1", "0"),
                ("SECOND_SAMPLE_PENDING", "PENDING", "狀態未知（待同步）", "狀態未知（待同步）"),
                ("SECOND_IMPORT", "READY", "2", "0"),
                ("TWO_ITEM_REPLAY", "READY", "2", "0"),
            ]
            observed = [(row["label"], row["state"], row["imported"], row["pending"]) for row in phases]
            result = {
                "task_id": "CDH-I02-LOCAL-SYNC-PREVIEW-001",
                "visible": window.isVisible(),
                "native_win_id_nonzero": int(window.winId()) != 0,
                "heartbeat_count": heartbeat["count"],
                "buttons_disabled_while_running": state["buttons_disabled"],
                "duplicate_trigger_refused": state["duplicate_refused"],
                "tab_count": window.tabs.count(),
                "source_status": "SOURCE_BLOCKED",
                "workspace": str(service.workspace),
                "phases": phases,
                "result": "PASS" if observed == expected and heartbeat["count"] > 5 and state["buttons_disabled"] and state["duplicate_refused"] else "FAIL",
            }
            args.evidence.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            app.quit()

    monitor = QTimer()
    monitor.setInterval(30)
    monitor.timeout.connect(advance)
    monitor.start()
    QTimer.singleShot(300, begin)
    QTimer.singleShot(15000, lambda: app.quit() if state["phase"] < 5 else None)
    exit_code = app.exec()
    monitor.stop(); heart_timer.stop()
    if exit_code != 0 or not args.evidence.is_file():
        return exit_code or 2
    return 0 if json.loads(args.evidence.read_text(encoding="utf-8"))["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

