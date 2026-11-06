from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from a01_app.gui import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="Visible Windows control-response smoke test")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("screenshot", type=Path)
    args = parser.parse_args()
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.screenshot.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    clicks = {"count": 0}
    window.refresh_button.clicked.connect(lambda: clicks.__setitem__("count", clicks["count"] + 1))
    window.show()

    def click_refresh() -> None:
        window.refresh_button.click()

    def record_and_close() -> None:
        window.grab().save(str(args.screenshot), "PNG")
        evidence = {
            "test": "A02_VISIBLE_WINDOWS_REFRESH_CONTROL",
            "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "visible": window.isVisible(),
            "native_win_id_nonzero": int(window.winId()) != 0,
            "tab_count": window.tabs.count(),
            "refresh_button_enabled": window.refresh_button.isEnabled(),
            "refresh_click_signal_count": clicks["count"],
            "sync_status_text": window.home_values["同步狀態"].text(),
            "pending_text": window.home_values["待處理"].text(),
            "source_status_text": window.home_values["來源權限"].text(),
            "result": "PASS" if window.isVisible() and int(window.winId()) != 0 and clicks["count"] == 1 and window.home_values["同步狀態"].text() != "讀取本機回執中…" else "FAIL",
        }
        args.evidence.write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        app.quit()

    QTimer.singleShot(500, click_refresh)
    QTimer.singleShot(1800, record_and_close)
    result = app.exec()
    if result != 0:
        return result
    saved = json.loads(args.evidence.read_text(encoding="utf-8"))
    return 0 if saved["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
