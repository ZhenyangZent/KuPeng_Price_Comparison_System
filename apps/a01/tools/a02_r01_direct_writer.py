from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/a01"))
sys.path.insert(0, str(ROOT / "apps/d01"))

from a01_app.exchange import build_submission, safe_write_submission
from a01_app.receipt import receipt_status
from cdh_d01.database import connect, migrate
from cdh_d01.sync import SyncPaths, run_sync


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _status(paths: SyncPaths) -> dict[str, object]:
    value = receipt_status(paths.receipts / "latest.json", paths.snapshots / "latest.json", paths.inbox)
    return {
        "state": value.state,
        "imported_count": value.imported_count,
        "pending_count": value.pending_count,
        "quarantined_count": value.quarantined_count,
    }


def _sync(paths: SyncPaths) -> dict[str, object]:
    result = run_sync(paths)
    return {
        "entries": [
            {"filename": item.filename, "status": item.status, "reason_code": item.reason_code}
            for item in result.entries
        ],
        "a02_status": _status(paths),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="A02 writer -> unmodified D02 -> A02 receipt compatibility proof")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    allowed = (ROOT / "review/A02/R01").resolve()
    workspace = args.workspace.resolve()
    output = args.output.resolve()
    if not _inside(workspace, allowed) or not _inside(output, allowed):
        raise SystemExit("workspace and output must stay under review/A02/R01")
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    output.parent.mkdir(parents=True, exist_ok=True)

    paths = SyncPaths.for_root(workspace)
    connection = connect(paths.database)
    migrate(connection)
    connection.close()

    now = datetime.now(timezone.utc)
    first = build_submission(
        product_title="A02 R01 synthetic first",
        displayed_price_twd=5,
        observed_at=now,
        created_at=now,
        is_synthetic=True,
    )
    first_path, first_hash = safe_write_submission(paths.inbox, first)
    cycles = [_sync(paths), _sync(paths)]

    second = build_submission(
        product_title="A02 R01 synthetic second",
        displayed_price_twd=7,
        observed_at=now,
        created_at=now,
        is_synthetic=True,
    )
    second_path, second_hash = safe_write_submission(paths.inbox, second)
    cycles.extend([_sync(paths), _sync(paths)])

    connection = sqlite3.connect(paths.database)
    rows = connection.execute(
        "SELECT displayed_price_twd, qualification_state, shipping_status, shipping_fee_twd "
        "FROM observations ORDER BY displayed_price_twd"
    ).fetchall()
    connection.close()

    expected = [
        ("IMPORTED", None, "READY", 1, 0),
        ("DUPLICATE_NOOP", "IDENTICAL_REPLAY", "READY", 1, 0),
    ]
    for index, (status, reason, state, imported, pending) in enumerate(expected):
        entry = cycles[index]["entries"][0]
        actual_status = cycles[index]["a02_status"]
        assert (entry["status"], entry["reason_code"]) == (status, reason)
        assert (actual_status["state"], actual_status["imported_count"], actual_status["pending_count"]) == (
            state,
            imported,
            pending,
        )
    for cycle in cycles[2:]:
        status = cycle["a02_status"]
        assert (status["state"], status["imported_count"], status["pending_count"]) == ("READY", 2, 0)
    assert rows == [(5, "UNVERIFIED", "UNKNOWN", None), (7, "UNVERIFIED", "UNKNOWN", None)]

    result = {
        "task_id": "CDH-A02-RECEIPT-COMPAT-REWORK-002",
        "workspace": str(workspace),
        "a02_writer_files": [
            {"filename": first_path.name, "sha256": first_hash},
            {"filename": second_path.name, "sha256": second_hash},
        ],
        "cycles": cycles,
        "database_observations": [
            {
                "displayed_price_twd": row[0],
                "qualification_state": row[1],
                "shipping_status": row[2],
                "shipping_fee_twd": row[3],
            }
            for row in rows
        ],
        "result": "PASS",
    }
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
