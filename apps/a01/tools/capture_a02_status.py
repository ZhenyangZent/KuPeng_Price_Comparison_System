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
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as temporary:
        root = Path(temporary)
        inbox = root / "inbox"; inbox.mkdir()
        snapshot_path = root / "snapshots/latest.json"; snapshot_path.parent.mkdir()
        receipt_path = root / "receipts/latest.json"; receipt_path.parent.mkdir()
        state_dir = root / "state"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        snapshot = {
            "schema_version": "CDH-EXCHANGE-1", "snapshot_generated_at_utc": now, "source": "D01_LOCAL_LEDGER",
            "counts": {"total_entries": 0, "real_observations": 0, "synthetic_observations": 0, "unverified_leads": 0},
            "items": [], "source_status": {"live_coupang_discovery": "SOURCE_BLOCKED", "permission_checked_at_utc": None},
        }
        snapshot_bytes = canonical(snapshot); snapshot_path.write_bytes(snapshot_bytes)
        definitions = [
            ("11111111-1111-4111-8111-111111111111", "IMPORTED", None),
            ("22222222-2222-4222-8222-222222222222", "RETRY_NEEDED", "NEXT_CYCLE"),
            ("33333333-3333-4333-8333-333333333333", "QUARANTINED", "INVALID_SCHEMA"),
        ]
        entries = []
        for uuid_text, status, reason in definitions:
            path = inbox / f"submission_{uuid_text}.json"
            path.write_bytes(canonical({"synthetic_fixture": True, "uuid": uuid_text}))
            entries.append({"filename": path.name, "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "status": status, "reason_code": reason})
        receipt = {
            "receipt_version": "CDH-D01-RECEIPT-1", "exchange_version": "CDH-EXCHANGE-1", "generated_at_utc": now,
            "source_status": "SOURCE_BLOCKED", "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(), "entries": entries,
        }
        receipt_path.write_bytes(canonical(receipt))
        app = QApplication.instance() or QApplication([])
        window = MainWindow(inbox=inbox, snapshot_path=snapshot_path, receipt_path=receipt_path, state_dir=state_dir)
        window.show()
        QTimer.singleShot(1200, lambda: window.grab().save(str(args.output), "PNG"))
        QTimer.singleShot(1500, app.quit)
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
