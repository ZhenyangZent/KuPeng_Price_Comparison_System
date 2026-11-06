from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .models import (
    LatestState,
    NotificationCandidate,
    OutboxStatus,
    RequestConflict,
    StateConflict,
    StaleState,
    canonical_json,
    digest,
    iso,
    parse_time,
    require_aware,
)


class OutboxStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS n01_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS n01_latest_state (
                    scenario_scope TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    state_fingerprint TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    policy_epoch INTEGER NOT NULL,
                    source_revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS n01_episode (
                    scenario_scope TEXT PRIMARY KEY,
                    episode INTEGER NOT NULL,
                    active INTEGER NOT NULL,
                    last_semantic_key TEXT,
                    last_total_minor INTEGER,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS n01_outbox (
                    event_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    request_fingerprint TEXT NOT NULL,
                    scenario_scope TEXT NOT NULL,
                    semantic_key TEXT NOT NULL,
                    episode INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_until TEXT,
                    delivered_at TEXT,
                    sink_receipt TEXT,
                    last_error TEXT,
                    revoked_reason TEXT,
                    UNIQUE(scenario_scope, semantic_key, episode)
                );
                CREATE TABLE IF NOT EXISTS n01_attempt (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    attempted_at TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    detail TEXT,
                    FOREIGN KEY(event_id) REFERENCES n01_outbox(event_id)
                );
                CREATE TABLE IF NOT EXISTS n01_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    scenario_scope TEXT,
                    event_id TEXT,
                    detail_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS n01_outbox_ready
                    ON n01_outbox(status, next_attempt_at, created_at);
                CREATE INDEX IF NOT EXISTS n01_outbox_scope
                    ON n01_outbox(scenario_scope, created_at);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO n01_meta(key,value) VALUES('schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        *,
        now: datetime,
        action: str,
        scenario_scope: str | None = None,
        event_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO n01_audit(occurred_at,action,scenario_scope,event_id,detail_json) VALUES(?,?,?,?,?)",
            (iso(now), action, scenario_scope, event_id, canonical_json(detail or {})),
        )

    def set_latest_state(self, state: LatestState, *, now: datetime) -> bool:
        require_aware(now, "now")
        with self.connection(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM n01_latest_state WHERE scenario_scope=?", (state.scenario_scope,)
            ).fetchone()
            if row is not None:
                existing_time = parse_time(str(row["observed_at"]))
                assert existing_time is not None
                if state.observed_at < existing_time:
                    raise StaleState("LATEST_STATE_TIME_ROLLBACK")
                if state.observed_at == existing_time:
                    if state.fingerprint == row["state_fingerprint"]:
                        return False
                    raise StateConflict("EQUAL_TIMESTAMP_STATE_CONFLICT")
                if state.policy_epoch < int(row["policy_epoch"]):
                    raise StaleState("POLICY_EPOCH_ROLLBACK")
                if state.source_revision < int(row["source_revision"]):
                    raise StaleState("SOURCE_REVISION_ROLLBACK")
            connection.execute(
                """INSERT INTO n01_latest_state(
                    scenario_scope,state_json,state_fingerprint,observed_at,
                    policy_epoch,source_revision,updated_at
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(scenario_scope) DO UPDATE SET
                    state_json=excluded.state_json,
                    state_fingerprint=excluded.state_fingerprint,
                    observed_at=excluded.observed_at,
                    policy_epoch=excluded.policy_epoch,
                    source_revision=excluded.source_revision,
                    updated_at=excluded.updated_at""",
                (
                    state.scenario_scope,
                    canonical_json(state.to_dict()),
                    state.fingerprint,
                    iso(state.observed_at),
                    state.policy_epoch,
                    state.source_revision,
                    iso(now),
                ),
            )
            revoked = connection.execute(
                """UPDATE n01_outbox
                SET status=?, revoked_reason=?, lease_owner=NULL, lease_until=NULL
                WHERE scenario_scope=? AND status IN (?,?,?) AND payload_json NOT LIKE ?""",
                (
                    OutboxStatus.REVOKED,
                    "LATEST_STATE_CHANGED",
                    state.scenario_scope,
                    OutboxStatus.PENDING,
                    OutboxStatus.RETRY,
                    OutboxStatus.IN_FLIGHT,
                    f'%"source_revision":{state.source_revision}%',
                ),
            ).rowcount
            self._audit(
                connection,
                now=now,
                action="LATEST_STATE_SET",
                scenario_scope=state.scenario_scope,
                detail={"fingerprint": state.fingerprint, "revoked_count": revoked},
            )
            return True

    def get_latest_state(self, scenario_scope: str) -> LatestState:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT state_json FROM n01_latest_state WHERE scenario_scope=?", (scenario_scope,)
            ).fetchone()
        if row is None:
            raise KeyError(scenario_scope)
        return LatestState.from_dict(json.loads(str(row["state_json"])))

    def record_filter(self, candidate: NotificationCandidate, reasons: tuple[str, ...], *, now: datetime) -> None:
        with self.connection(immediate=True) as connection:
            self._audit(
                connection,
                now=now,
                action="FILTERED",
                scenario_scope=candidate.scenario_scope,
                detail={"request_id": candidate.request_id, "reasons": list(reasons)},
            )

    def enqueue(self, candidate: NotificationCandidate, *, now: datetime) -> tuple[str, bool, int]:
        require_aware(now, "now")
        request_fingerprint = candidate.payload_fingerprint
        with self.connection(immediate=True) as connection:
            existing_request = connection.execute(
                "SELECT event_id,request_fingerprint,episode FROM n01_outbox WHERE request_id=?",
                (candidate.request_id,),
            ).fetchone()
            if existing_request is not None:
                if existing_request["request_fingerprint"] != request_fingerprint:
                    raise RequestConflict("REQUEST_ID_REUSE_WITH_DIFFERENT_PAYLOAD")
                return str(existing_request["event_id"]), False, int(existing_request["episode"])

            episode_row = connection.execute(
                "SELECT * FROM n01_episode WHERE scenario_scope=?", (candidate.scenario_scope,)
            ).fetchone()
            if episode_row is None:
                episode = 1
            elif bool(episode_row["active"]):
                episode = int(episode_row["episode"])
            else:
                episode = int(episode_row["episode"]) + 1
            event_id = digest(
                "outbox-event",
                {
                    "scenario_scope": candidate.scenario_scope,
                    "semantic_key": candidate.semantic_key,
                    "episode": episode,
                },
            )
            existing_semantic = connection.execute(
                """SELECT event_id,episode FROM n01_outbox
                WHERE scenario_scope=? AND semantic_key=? AND episode=?""",
                (candidate.scenario_scope, candidate.semantic_key, episode),
            ).fetchone()
            if existing_semantic is not None:
                return str(existing_semantic["event_id"]), False, int(existing_semantic["episode"])
            connection.execute(
                """INSERT INTO n01_outbox(
                    event_id,request_id,request_fingerprint,scenario_scope,semantic_key,episode,
                    payload_json,status,created_at,expires_at,next_attempt_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id,
                    candidate.request_id,
                    request_fingerprint,
                    candidate.scenario_scope,
                    candidate.semantic_key,
                    episode,
                    canonical_json(candidate.to_dict()),
                    OutboxStatus.PENDING,
                    iso(now),
                    iso(candidate.expires_at),
                    iso(now),
                ),
            )
            connection.execute(
                """INSERT INTO n01_episode(
                    scenario_scope,episode,active,last_semantic_key,last_total_minor,observed_at
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(scenario_scope) DO UPDATE SET
                    episode=excluded.episode,active=1,last_semantic_key=excluded.last_semantic_key,
                    last_total_minor=excluded.last_total_minor,observed_at=excluded.observed_at""",
                (
                    candidate.scenario_scope,
                    episode,
                    1,
                    candidate.semantic_key,
                    candidate.total_minor,
                    iso(candidate.observed_at),
                ),
            )
            self._audit(
                connection,
                now=now,
                action="ENQUEUED",
                scenario_scope=candidate.scenario_scope,
                event_id=event_id,
                detail={"episode": episode, "semantic_key": candidate.semantic_key},
            )
            return event_id, True, episode

    def observe_rebound(
        self,
        scenario_scope: str,
        *,
        observed_at: datetime,
        total_minor: int | None,
        reason: str,
    ) -> bool:
        require_aware(observed_at, "observed_at")
        with self.connection(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM n01_episode WHERE scenario_scope=?", (scenario_scope,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO n01_episode VALUES(?,?,?,?,?,?)",
                    (scenario_scope, 0, 0, None, total_minor, iso(observed_at)),
                )
                changed = True
            else:
                previous = parse_time(str(row["observed_at"]))
                assert previous is not None
                if observed_at < previous:
                    raise StaleState("EPISODE_TIME_ROLLBACK")
                if observed_at == previous and not bool(row["active"]):
                    return False
                connection.execute(
                    "UPDATE n01_episode SET active=0,last_total_minor=?,observed_at=? WHERE scenario_scope=?",
                    (total_minor, iso(observed_at), scenario_scope),
                )
                changed = bool(row["active"])
            self._audit(
                connection,
                now=observed_at,
                action="EPISODE_REBOUND",
                scenario_scope=scenario_scope,
                detail={"total_minor": total_minor, "reason": reason},
            )
            return changed

    def claim(self, *, worker_id: str, now: datetime, lease_seconds: int = 30) -> dict[str, Any] | None:
        require_aware(now, "now")
        lease_until = now + timedelta(seconds=lease_seconds)
        with self.connection(immediate=True) as connection:
            connection.execute(
                """UPDATE n01_outbox SET status=?,lease_owner=NULL,lease_until=NULL,last_error=?
                WHERE status=? AND lease_until<=?""",
                (OutboxStatus.RETRY, "LEASE_RECOVERED", OutboxStatus.IN_FLIGHT, iso(now)),
            )
            connection.execute(
                """UPDATE n01_outbox SET status=?,last_error=?
                WHERE status IN (?,?) AND expires_at<=?""",
                (
                    OutboxStatus.EXPIRED,
                    "MESSAGE_EXPIRED",
                    OutboxStatus.PENDING,
                    OutboxStatus.RETRY,
                    iso(now),
                ),
            )
            row = connection.execute(
                """SELECT * FROM n01_outbox
                WHERE status IN (?,?) AND next_attempt_at<=? AND expires_at>?
                ORDER BY next_attempt_at,created_at,event_id LIMIT 1""",
                (OutboxStatus.PENDING, OutboxStatus.RETRY, iso(now), iso(now)),
            ).fetchone()
            if row is None:
                return None
            updated = connection.execute(
                """UPDATE n01_outbox
                SET status=?,lease_owner=?,lease_until=?,attempts=attempts+1
                WHERE event_id=? AND status IN (?,?)""",
                (
                    OutboxStatus.IN_FLIGHT,
                    worker_id,
                    iso(lease_until),
                    row["event_id"],
                    OutboxStatus.PENDING,
                    OutboxStatus.RETRY,
                ),
            ).rowcount
            if updated != 1:
                return None
            claimed = connection.execute(
                "SELECT * FROM n01_outbox WHERE event_id=?", (row["event_id"],)
            ).fetchone()
            assert claimed is not None
            self._audit(
                connection,
                now=now,
                action="CLAIMED",
                scenario_scope=str(claimed["scenario_scope"]),
                event_id=str(claimed["event_id"]),
                detail={"worker_id": worker_id, "attempt": int(claimed["attempts"])},
            )
            return dict(claimed)

    def mark_delivered(self, event_id: str, *, worker_id: str, receipt: str, now: datetime) -> bool:
        with self.connection(immediate=True) as connection:
            row = connection.execute("SELECT * FROM n01_outbox WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise KeyError(event_id)
            if row["status"] != OutboxStatus.IN_FLIGHT or row["lease_owner"] != worker_id:
                self._audit(
                    connection,
                    now=now,
                    action="DELIVERY_POSTCHECK_REJECTED",
                    scenario_scope=str(row["scenario_scope"]),
                    event_id=event_id,
                    detail={"status": row["status"], "receipt": receipt},
                )
                return False
            connection.execute(
                """UPDATE n01_outbox SET status=?,delivered_at=?,sink_receipt=?,
                    lease_owner=NULL,lease_until=NULL,last_error=NULL WHERE event_id=?""",
                (OutboxStatus.DELIVERED, iso(now), receipt, event_id),
            )
            connection.execute(
                "INSERT INTO n01_attempt(event_id,attempt_number,attempted_at,outcome,detail) VALUES(?,?,?,?,?)",
                (event_id, int(row["attempts"]), iso(now), "DELIVERED", receipt),
            )
            return True

    def mark_failure(
        self,
        event_id: str,
        *,
        worker_id: str,
        error: str,
        now: datetime,
        max_attempts: int,
    ) -> OutboxStatus:
        with self.connection(immediate=True) as connection:
            row = connection.execute("SELECT * FROM n01_outbox WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise KeyError(event_id)
            if row["status"] != OutboxStatus.IN_FLIGHT or row["lease_owner"] != worker_id:
                return OutboxStatus(str(row["status"]))
            attempts = int(row["attempts"])
            status = OutboxStatus.DEAD if attempts >= max_attempts else OutboxStatus.RETRY
            delay = min(3600, 2 ** min(attempts, 10))
            connection.execute(
                """UPDATE n01_outbox SET status=?,next_attempt_at=?,lease_owner=NULL,
                    lease_until=NULL,last_error=? WHERE event_id=?""",
                (status, iso(now + timedelta(seconds=delay)), error, event_id),
            )
            connection.execute(
                "INSERT INTO n01_attempt(event_id,attempt_number,attempted_at,outcome,detail) VALUES(?,?,?,?,?)",
                (event_id, attempts, iso(now), status, error),
            )
            return status

    def revoke(self, event_id: str, *, reason: str, now: datetime) -> bool:
        with self.connection(immediate=True) as connection:
            row = connection.execute("SELECT * FROM n01_outbox WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise KeyError(event_id)
            if row["status"] in (
                OutboxStatus.REVOKED,
                OutboxStatus.EXPIRED,
                OutboxStatus.DEAD,
            ):
                return False
            connection.execute(
                "UPDATE n01_outbox SET status=?,revoked_reason=?,lease_owner=NULL,lease_until=NULL WHERE event_id=?",
                (OutboxStatus.REVOKED, reason, event_id),
            )
            self._audit(
                connection,
                now=now,
                action="REVOKED",
                scenario_scope=str(row["scenario_scope"]),
                event_id=event_id,
                detail={"reason": reason, "was_delivered": row["status"] == OutboxStatus.DELIVERED},
            )
            return True

    def row(self, event_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM n01_outbox WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            raise KeyError(event_id)
        return dict(row)

    def rows(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM n01_outbox ORDER BY created_at,event_id").fetchall()
        return [dict(row) for row in rows]

    def attempts(self, event_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM n01_attempt WHERE event_id=? ORDER BY attempt_id", (event_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self.connection() as connection:
            status_rows = connection.execute(
                "SELECT status,COUNT(*) count FROM n01_outbox GROUP BY status ORDER BY status"
            ).fetchall()
            attempt_count = int(connection.execute("SELECT COUNT(*) FROM n01_attempt").fetchone()[0])
            retry_count = int(
                connection.execute("SELECT COUNT(*) FROM n01_attempt WHERE outcome=?", (OutboxStatus.RETRY,)).fetchone()[0]
            )
            filter_count = int(
                connection.execute("SELECT COUNT(*) FROM n01_audit WHERE action='FILTERED'").fetchone()[0]
            )
        return {
            "by_status": {str(row["status"]): int(row["count"]) for row in status_rows},
            "attempt_count": attempt_count,
            "retry_count": retry_count,
            "filtered_count": filter_count,
            "external_exactly_once_claimed": False,
            "real_delivery_count": 0,
        }
