from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .adapter import SyntheticObservation, canonical_json


class CandidateLedger:
    """Namespaced raw-candidate ledger; it never changes the frozen C01 schema."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS i01_candidates (
                    source_payload_sha256 TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason_codes_json TEXT NOT NULL,
                    fixture_id TEXT,
                    fixture_sha256 TEXT,
                    scenario_scope TEXT,
                    decision_reason TEXT,
                    event_id TEXT,
                    updated_at TEXT NOT NULL,
                    latest_attempt_status TEXT NOT NULL,
                    latest_attempt_reason_codes_json TEXT NOT NULL,
                    latest_attempt_at TEXT NOT NULL
                )"""
            )
            existing_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(i01_candidates)").fetchall()
            }
            migrations = {
                "latest_attempt_status": "TEXT NOT NULL DEFAULT 'UNKNOWN'",
                "latest_attempt_reason_codes_json": "TEXT NOT NULL DEFAULT '[]'",
                "latest_attempt_at": "TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00'",
            }
            for column, declaration in migrations.items():
                if column not in existing_columns:
                    connection.execute(f"ALTER TABLE i01_candidates ADD COLUMN {column} {declaration}")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS i01_candidate_attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_payload_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason_codes_json TEXT NOT NULL,
                    fixture_id TEXT,
                    fixture_sha256 TEXT,
                    scenario_scope TEXT,
                    decision_reason TEXT,
                    event_id TEXT,
                    attempted_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS i01_request_bindings (
                    request_id TEXT PRIMARY KEY,
                    request_fingerprint TEXT NOT NULL,
                    source_payload_sha256 TEXT NOT NULL,
                    fixture_sha256 TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update(
        self,
        observation: SyntheticObservation,
        *,
        status: str,
        reasons: tuple[str, ...],
        now: datetime,
        fixture_id: str | None = None,
        fixture_sha256: str | None = None,
        scenario_scope: str | None = None,
        decision_reason: str | None = None,
        event_id: str | None = None,
        attempt_only: bool = False,
    ) -> None:
        reasons_json = json.dumps(list(reasons), ensure_ascii=False)
        with self._connection() as connection:
            values = (
                observation.source_payload_sha256,
                canonical_json(observation.raw_payload),
                observation.observed_at.isoformat(),
                status,
                reasons_json,
                fixture_id,
                fixture_sha256,
                scenario_scope,
                decision_reason,
                event_id,
                now.isoformat(),
                status,
                reasons_json,
                now.isoformat(),
            )
            columns = (
                "source_payload_sha256,payload_json,observed_at,status,reason_codes_json,"
                "fixture_id,fixture_sha256,scenario_scope,decision_reason,event_id,updated_at,"
                "latest_attempt_status,latest_attempt_reason_codes_json,latest_attempt_at"
            )
            if attempt_only:
                connection.execute(
                    f"""INSERT INTO i01_candidates ({columns}) VALUES ({','.join('?' for _ in values)})
                    ON CONFLICT(source_payload_sha256) DO UPDATE SET
                        latest_attempt_status=excluded.latest_attempt_status,
                        latest_attempt_reason_codes_json=excluded.latest_attempt_reason_codes_json,
                        latest_attempt_at=excluded.latest_attempt_at""",
                    values,
                )
            else:
                connection.execute(
                    f"""INSERT INTO i01_candidates ({columns}) VALUES ({','.join('?' for _ in values)})
                    ON CONFLICT(source_payload_sha256) DO UPDATE SET
                        status=excluded.status,
                        reason_codes_json=excluded.reason_codes_json,
                        fixture_id=excluded.fixture_id,
                        fixture_sha256=excluded.fixture_sha256,
                        scenario_scope=excluded.scenario_scope,
                        decision_reason=excluded.decision_reason,
                        event_id=COALESCE(excluded.event_id, i01_candidates.event_id),
                        updated_at=excluded.updated_at,
                        latest_attempt_status=excluded.latest_attempt_status,
                        latest_attempt_reason_codes_json=excluded.latest_attempt_reason_codes_json,
                        latest_attempt_at=excluded.latest_attempt_at""",
                    values,
                )
            connection.execute(
                """INSERT INTO i01_candidate_attempts (
                    source_payload_sha256,status,reason_codes_json,fixture_id,fixture_sha256,
                    scenario_scope,decision_reason,event_id,attempted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    observation.source_payload_sha256,
                    status,
                    reasons_json,
                    fixture_id,
                    fixture_sha256,
                    scenario_scope,
                    decision_reason,
                    event_id,
                    now.isoformat(),
                ),
            )

    def get(self, source_payload_sha256: str) -> dict[str, object]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM i01_candidates WHERE source_payload_sha256=?", (source_payload_sha256,)
            ).fetchone()
        if row is None:
            raise KeyError(source_payload_sha256)
        return dict(row)

    def count(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM i01_candidates").fetchone()[0])

    def attempts(self, source_payload_sha256: str) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM i01_candidate_attempts WHERE source_payload_sha256=? ORDER BY attempt_id",
                (source_payload_sha256,),
            ).fetchall()
        return [dict(row) for row in rows]

    def request_binding(self, request_id: str) -> dict[str, object] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM i01_request_bindings WHERE request_id=?", (request_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def record_request_binding(
        self,
        *,
        request_id: str,
        request_fingerprint: str,
        source_payload_sha256: str,
        fixture_sha256: str,
        event_id: str,
        now: datetime,
    ) -> None:
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT * FROM i01_request_bindings WHERE request_id=?", (request_id,)
            ).fetchone()
            if existing is not None:
                if (
                    existing["request_fingerprint"] != request_fingerprint
                    or existing["event_id"] != event_id
                ):
                    raise ValueError("I01_REQUEST_BINDING_CONFLICT")
                return
            connection.execute(
                "INSERT INTO i01_request_bindings VALUES (?, ?, ?, ?, ?, ?)",
                (
                    request_id,
                    request_fingerprint,
                    source_payload_sha256,
                    fixture_sha256,
                    event_id,
                    now.isoformat(),
                ),
            )

