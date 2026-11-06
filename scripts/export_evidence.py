from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "review" / "C01" / "evidence"
DATABASE = EVIDENCE / "demo.sqlite3"


def main() -> None:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        schema_rows = connection.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
        ).fetchall()
        schema = "\n\n".join(f"-- {row['type']} {row['name']}\n{row['sql']};" for row in schema_rows) + "\n"
        (EVIDENCE / "schema.sql").write_text(schema, encoding="utf-8")

        table_names = (
            "schema_version",
            "price_observations",
            "daily_price_stats",
            "current_state",
            "deal_events",
            "notification_outbox",
        )
        summary: dict[str, object] = {"database": "synthetic demo only", "tables": {}}
        for table in table_names:
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            summary["tables"][table] = count
        (EVIDENCE / "database_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        for table in ("deal_events", "notification_outbox"):
            rows = [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            (EVIDENCE / f"{table}.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    finally:
        connection.close()
    print("EVIDENCE_EXPORT=PASS")


if __name__ == "__main__":
    main()

