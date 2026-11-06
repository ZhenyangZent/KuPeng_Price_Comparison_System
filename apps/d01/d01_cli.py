from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cdh_d01.database import connect, migrate
from cdh_d01.ingest import ingest_csv_file, ingest_json_file, scan_inbox
from cdh_d01.permissions import seed_permissions, write_permission_matrix
from cdh_d01.reports import write_coverage_report
from cdh_d01.snapshot import write_snapshot


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="CDH D01 local-only data ledger")
    result.add_argument("--db", type=Path, default=Path("data/d01/observations.sqlite3"))
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("path", type=Path)
    scan = sub.add_parser("scan-inbox")
    scan.add_argument("path", type=Path, nargs="?", default=Path("data/exchange/inbox"))
    snap = sub.add_parser("snapshot")
    snap.add_argument("--output", type=Path, default=Path("data/exchange/snapshots"))
    permissions = sub.add_parser("seed-permissions")
    permissions.add_argument("--matrix", type=Path, default=Path("reports/D01/SOURCE_PERMISSION_MATRIX.csv"))
    report = sub.add_parser("coverage-report")
    report.add_argument("--output", type=Path, default=Path("reports/D01/DATA_COVERAGE_REPORT.md"))
    report.add_argument("--data-as-of", required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    conn = connect(args.db)
    try:
        migrate(conn)
        if args.command == "init-db":
            output = {"status": "INITIALIZED", "db": str(args.db)}
        elif args.command == "ingest":
            if args.path.suffix.lower() == ".csv":
                results = list(ingest_csv_file(conn, args.path))
            else:
                results = [ingest_json_file(conn, args.path)]
            output = {"results": [result.__dict__ for result in results]}
        elif args.command == "scan-inbox":
            output = {"results": [result.__dict__ for result in scan_inbox(conn, args.path)]}
        elif args.command == "snapshot":
            path, digest = write_snapshot(conn, args.output)
            output = {"status": "SNAPSHOT_WRITTEN", "path": str(path), "sha256": digest}
        elif args.command == "seed-permissions":
            inserted = seed_permissions(conn)
            write_permission_matrix(args.matrix)
            output = {"status": "PERMISSIONS_SEEDED", "inserted": inserted, "matrix": str(args.matrix)}
        elif args.command == "coverage-report":
            write_coverage_report(conn, args.output, data_as_of=args.data_as_of)
            output = {"status": "REPORT_WRITTEN", "path": str(args.output)}
        else:
            raise AssertionError(args.command)
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
