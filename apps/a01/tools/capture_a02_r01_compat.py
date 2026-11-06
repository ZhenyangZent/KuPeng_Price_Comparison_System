from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from a01_app.gui import MainWindow


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Visible A02 R01 duplicate-receipt compatibility proof")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("screenshot", type=Path)
    args = parser.parse_args()
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.screenshot.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=args.evidence.parent) as temporary:
        root = Path(temporary)
        inbox = root / "inbox"
        inbox.mkdir()
        snapshot_path = root / "snapshots/latest.json"
        snapshot_path.parent.mkdir()
        receipt_path = root / "receipts/latest.json"
        receipt_path.parent.mkdir()
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        snapshot = {
            "schema_version": "CDH-EXCHANGE-1",
            "snapshot_generated_at_utc": now,
            "source": "D01_LOCAL_LEDGER",
            "counts": {"total_entries": 0, "real_observations": 0, "synthetic_observations": 0, "unverified_leads": 0},
            "items": [],
            "source_status": {"live_coupang_discovery": "SOURCE_BLOCKED", "permission_checked_at_utc": None},
        }
        snapshot_bytes = canonical(snapshot)
        snapshot_path.write_bytes(snapshot_bytes)
        definitions = [
            ("11111111-1111-4111-8111-111111111111", "DUPLICATE_NOOP", "IDENTICAL_REPLAY"),
            ("22222222-2222-4222-8222-222222222222", "IMPORTED", None),
        ]
        entries = []
        for uuid_text, status, reason in definitions:
            path = inbox / f"submission_{uuid_text}.json"
            path.write_bytes(canonical({"synthetic_fixture": True, "uuid": uuid_text}))
            entries.append(
                {
                    "filename": path.name,
                    "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "status": status,
                    "reason_code": reason,
                }
            )
        receipt_path.write_bytes(
            canonical(
                {
                    "receipt_version": "CDH-D01-RECEIPT-1",
                    "exchange_version": "CDH-EXCHANGE-1",
                    "generated_at_utc": now,
                    "source_status": "SOURCE_BLOCKED",
                    "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
                    "entries": entries,
                }
            )
        )

        app = QApplication.instance() or QApplication([])
        window = MainWindow(inbox=inbox, snapshot_path=snapshot_path, receipt_path=receipt_path, state_dir=root / "state")
        clicks = {"count": 0}
        window.refresh_button.clicked.connect(lambda: clicks.__setitem__("count", clicks["count"] + 1))
        window.show()
        QTimer.singleShot(400, window.refresh_button.click)

        def record() -> None:
            window.grab().save(str(args.screenshot), "PNG")
            observed = {
                "test": "A02_R01_VISIBLE_DUPLICATE_RECEIPT_COMPATIBILITY",
                "visible": window.isVisible(),
                "native_win_id_nonzero": int(window.winId()) != 0,
                "refresh_click_signal_count": clicks["count"],
                "sync_status_text": window.home_values["同步狀態"].text(),
                "imported_text": window.home_values["已匯入"].text(),
                "pending_text": window.home_values["待處理"].text(),
                "source_status_text": window.home_values["來源權限"].text(),
            }
            observed["result"] = (
                "PASS"
                if observed["visible"]
                and observed["native_win_id_nonzero"]
                and observed["refresh_click_signal_count"] == 1
                and observed["imported_text"] == "2"
                and observed["pending_text"] == "0"
                and observed["source_status_text"] == "SOURCE_BLOCKED"
                else "FAIL"
            )
            args.evidence.write_text(json.dumps(observed, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            app.quit()

        QTimer.singleShot(1700, record)
        exit_code = app.exec()
    if exit_code != 0:
        return exit_code
    result = json.loads(args.evidence.read_text(encoding="utf-8"))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
