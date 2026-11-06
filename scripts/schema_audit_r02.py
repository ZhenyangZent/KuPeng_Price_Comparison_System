from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from cdh_core.persistence import EventStore, SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / "review" / "R02" / "tmp"


def main() -> None:
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
        database = Path(directory) / "schema-audit.sqlite3"
        store = EventStore(database)
        actual_version = store.schema_version()
        with closing(sqlite3.connect(database)) as connection:
            tables = sorted(
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            )
            columns = {
                table: [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
                for table in tables
            }
            foreign_key_violations = list(connection.execute("PRAGMA foreign_key_check"))

    required = {
        "current_state": {"semantic_fingerprint", "observed_at", "availability_version", "rule_version"},
        "deal_events": {
            "expected_semantic_fingerprint",
            "availability_version",
            "state_rule_version",
            "semantic_key",
        },
        "notification_outbox": {"event_id", "status", "payload_json"},
    }
    missing = {
        table: sorted(expected - set(columns.get(table, [])))
        for table, expected in required.items()
        if expected - set(columns.get(table, []))
    }
    result = {
        "schema_version_expected": SCHEMA_VERSION,
        "schema_version_actual": actual_version,
        "tables": tables,
        "columns": columns,
        "required_column_missing": missing,
        "foreign_key_violations": foreign_key_violations,
        "status": "PASS"
        if actual_version == SCHEMA_VERSION and not missing and not foreign_key_violations
        else "FAIL",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
