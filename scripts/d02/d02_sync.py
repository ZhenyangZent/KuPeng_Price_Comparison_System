from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "d01"))

from cdh_d01.sync import SyncError, SyncPaths, run_sync  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Explicit local-only D02 inbox → SQLite → snapshot → receipt synchronization"
    )
    result.add_argument(
        "--dry-run",
        action="store_true",
        help="validate a synthetic copy of current state without writing the database, snapshot, receipt, or lock",
    )
    result.add_argument("--pretty", action="store_true", help="indent JSON operator output")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = run_sync(SyncPaths.for_root(ROOT), dry_run=args.dry_run)
    except (SyncError, sqlite3.Error, OSError) as exc:
        print(
            json.dumps(
                {"status": "FAILED", "error_type": type(exc).__name__, "detail": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    output = {"status": "DRY_RUN_COMPLETE" if args.dry_run else "SYNC_COMPLETE", **result.to_dict()}
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
