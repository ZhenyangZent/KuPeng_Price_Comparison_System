from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from .models import (
    CostResult,
    Decision,
    EventStatus,
    Observation,
    PurchaseScenario,
    canonical_digest,
    require_aware,
    strict_int,
)
from .policy import verify_decision_approval

SCHEMA_VERSION = 5


class IdempotencyConflict(ValueError):
    """A reused request id has a different canonical payload."""


class ObservationConflict(ValueError):
    """A reused observation id has different source data."""


class DecisionBindingError(ValueError):
    """A decision cannot be bound to the supplied scenario/current state."""


class StaleCurrentState(ValueError):
    """An older source observation attempted to replace newer current state."""


class CurrentStateConflict(ValueError):
    """The same source observation time carried a conflicting state payload."""


class StalePolicyState(ValueError):
    """An older policy revision attempted to replace newer user configuration."""


class PolicyStateConflict(ValueError):
    """The same policy revision time carried conflicting configuration."""


class PolicyEpochConflict(ValueError):
    """A caller attempted a policy update from an unexpected epoch."""


@dataclass(frozen=True, slots=True)
class CurrentState:
    scenario_scope: str
    offer_key: str
    context_id: str
    quantity: int
    membership_context: str
    eligibility_profile_version: str
    coupon_plan_id: str | None
    price_basis: str
    purchase_channel: str
    payment_method: str
    quote_fingerprint: str
    semantic_fingerprint: str
    total_minor: int
    stock: str
    eligibility_state: str
    source_enabled: bool
    notifications_enabled: bool
    evidence_id: str
    rule_version: str
    observed_at: datetime
    received_at: datetime
    expires_at: datetime
    availability_version: str = "availability-v1"

    def __post_init__(self) -> None:
        strict_int(self.quantity, "quantity", minimum=1)
        strict_int(self.total_minor, "total_minor")
        for field_name in ("observed_at", "received_at", "expires_at"):
            require_aware(getattr(self, field_name), field_name)
        if self.expires_at <= self.observed_at:
            raise ValueError("current state must expire after observation")
        if self.received_at < self.observed_at:
            raise ValueError("current state cannot be received before its source observation")
        required = (
            "scenario_scope",
            "offer_key",
            "context_id",
            "membership_context",
            "eligibility_profile_version",
            "price_basis",
            "purchase_channel",
            "payment_method",
            "quote_fingerprint",
            "semantic_fingerprint",
            "stock",
            "eligibility_state",
            "evidence_id",
            "rule_version",
            "availability_version",
        )
        if any(not getattr(self, field_name) for field_name in required):
            raise ValueError("current state contains an empty required binding")

    @property
    def scenario_key(self) -> str:
        return self.scenario_scope

    @property
    def fingerprint(self) -> str:
        return self.quote_fingerprint

    @classmethod
    def verified_from(
        cls,
        scenario: PurchaseScenario,
        cost: CostResult,
        *,
        now: datetime,
        expires_at: datetime,
        stock: str = "IN_STOCK",
        eligibility_state: str = "ELIGIBLE",
        source_enabled: bool = True,
        notifications_enabled: bool = True,
        evidence_id: str = "SYNTHETIC-CURRENT-STATE",
        rule_version: str = "current-state-v3",
        availability_version: str = "availability-v1",
    ) -> "CurrentState":
        require_aware(now, "now")
        require_aware(expires_at, "expires_at")
        if (
            not cost.complete
            or cost.total_minor is None
            or cost.scenario_scope != scenario.scope_key
            or cost.price_basis != scenario.price_basis
            or not cost.quote_fingerprint
            or not cost.semantic_fingerprint
            or cost.evidence_expires_at is None
        ):
            raise DecisionBindingError("cost is incomplete or not bound to scenario")
        effective_expiry = min(expires_at, cost.evidence_expires_at)
        if effective_expiry <= now:
            raise DecisionBindingError("cost evidence is already expired")
        return cls(
            scenario_scope=scenario.scope_key,
            offer_key=scenario.offer.key,
            context_id=scenario.context_id,
            quantity=scenario.quantity,
            membership_context=scenario.membership_context,
            eligibility_profile_version=scenario.eligibility_profile_version,
            coupon_plan_id=scenario.coupon_plan_id,
            price_basis=scenario.price_basis,
            purchase_channel=scenario.purchase_channel,
            payment_method=scenario.payment_method,
            quote_fingerprint=cost.quote_fingerprint,
            semantic_fingerprint=cost.semantic_fingerprint,
            total_minor=cost.total_minor,
            stock=stock,
            eligibility_state=eligibility_state,
            source_enabled=source_enabled,
            notifications_enabled=notifications_enabled,
            evidence_id=evidence_id,
            rule_version=rule_version,
            observed_at=now,
            received_at=now,
            expires_at=effective_expiry,
            availability_version=availability_version,
        )


class DeliverySink(Protocol):
    def deliver(self, payload: dict[str, object]) -> None: ...


class AmbiguousDelivery(RuntimeError):
    """The sink may have received the notification but acknowledgement was lost."""


class MockSink:
    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.deliveries: list[dict[str, object]] = []

    def deliver(self, payload: dict[str, object]) -> None:
        if self.mode == "ambiguous":
            raise AmbiguousDelivery("mock acknowledgement lost")
        if self.mode == "fail":
            raise RuntimeError("mock delivery failure")
        self.deliveries.append(payload)


class EventStore:
    """SQLite event/outbox store with identity-bound state and two-phase delivery."""

    _ACTIVE_TABLES = (
        "current_state",
        "price_observations",
        "daily_price_stats",
        "user_notification_policy",
        "scenario_notification_policy",
        "deal_events",
        "notification_outbox",
    )

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._write_lock = threading.RLock()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
        row = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        return row is not None

    @staticmethod
    def _create_v5(connection: sqlite3.Connection) -> None:
        statements = (
            """CREATE TABLE current_state (
                scenario_scope TEXT PRIMARY KEY, offer_key TEXT NOT NULL, context_id TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0), membership_context TEXT NOT NULL,
                eligibility_profile_version TEXT NOT NULL, coupon_plan_id TEXT, price_basis TEXT NOT NULL,
                purchase_channel TEXT NOT NULL, payment_method TEXT NOT NULL, quote_fingerprint TEXT NOT NULL,
                semantic_fingerprint TEXT NOT NULL,
                total_minor INTEGER NOT NULL CHECK(total_minor >= 0), stock TEXT NOT NULL,
                eligibility_state TEXT NOT NULL, source_enabled INTEGER NOT NULL,
                notifications_enabled INTEGER NOT NULL, evidence_id TEXT NOT NULL, rule_version TEXT NOT NULL,
                observed_at TEXT NOT NULL, received_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                availability_version TEXT NOT NULL, updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE price_observations (
                observation_id TEXT PRIMARY KEY, payload_fingerprint TEXT NOT NULL, series_key TEXT NOT NULL,
                offer_key TEXT NOT NULL, context_id TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0),
                price_type TEXT NOT NULL, unit_minor INTEGER NOT NULL CHECK(unit_minor >= 0),
                membership_context TEXT NOT NULL, eligibility_profile_version TEXT NOT NULL,
                coupon_plan_id TEXT, purchase_channel TEXT NOT NULL, payment_method TEXT NOT NULL,
                source_id TEXT NOT NULL, source_published_at TEXT, observed_at TEXT NOT NULL,
                received_at TEXT, valid INTEGER NOT NULL, parser_version TEXT NOT NULL
            )""",
            "CREATE INDEX idx_price_observations_series_time_v4 ON price_observations(series_key, observed_at)",
            """CREATE TABLE daily_price_stats (
                series_key TEXT NOT NULL, local_day TEXT NOT NULL,
                median_unit_minor INTEGER NOT NULL CHECK(median_unit_minor >= 0),
                sample_count INTEGER NOT NULL CHECK(sample_count > 0), calculation_version TEXT NOT NULL,
                PRIMARY KEY(series_key, local_day, calculation_version)
            )""",
            """CREATE TABLE user_notification_policy (
                policy_scope TEXT PRIMARY KEY, epoch INTEGER NOT NULL CHECK(epoch > 0),
                notifications_enabled INTEGER NOT NULL, source_allowed INTEGER NOT NULL,
                membership_context TEXT NOT NULL, eligibility_profile_version TEXT NOT NULL,
                updated_at TEXT NOT NULL, revision_id TEXT NOT NULL
            )""",
            """CREATE TABLE scenario_notification_policy (
                scenario_scope TEXT PRIMARY KEY, policy_scope TEXT NOT NULL,
                epoch INTEGER NOT NULL CHECK(epoch > 0), enabled INTEGER NOT NULL,
                target_total_minor INTEGER CHECK(target_total_minor >= 0),
                updated_at TEXT NOT NULL, revision_id TEXT NOT NULL
            )""",
            """CREATE TABLE deal_events (
                event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, request_fingerprint TEXT NOT NULL,
                caller_dedupe_key TEXT, semantic_key TEXT NOT NULL UNIQUE, scenario_scope TEXT NOT NULL,
                user_policy_scope TEXT NOT NULL, user_policy_epoch INTEGER NOT NULL CHECK(user_policy_epoch > 0),
                scenario_policy_epoch INTEGER NOT NULL CHECK(scenario_policy_epoch > 0),
                offer_key TEXT NOT NULL, context_id TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0),
                membership_context TEXT NOT NULL, eligibility_profile_version TEXT NOT NULL,
                coupon_plan_id TEXT, price_basis TEXT NOT NULL, purchase_channel TEXT NOT NULL,
                payment_method TEXT NOT NULL, expected_quote_fingerprint TEXT NOT NULL,
                expected_semantic_fingerprint TEXT NOT NULL,
                decision_fingerprint TEXT NOT NULL, decision_reason TEXT NOT NULL,
                policy_evidence_json TEXT NOT NULL, policy_evidence_fingerprint TEXT NOT NULL,
                approval_seal TEXT NOT NULL,
                total_minor INTEGER NOT NULL CHECK(total_minor >= 0), availability_version TEXT NOT NULL,
                target_total_minor INTEGER CHECK(target_total_minor >= 0),
                state_rule_version TEXT NOT NULL, policy_version TEXT NOT NULL,
                status TEXT NOT NULL, expires_at TEXT NOT NULL,
                claim_token TEXT, claim_until TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE notification_outbox (
                outbox_id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE REFERENCES deal_events(event_id),
                status TEXT NOT NULL, payload_json TEXT NOT NULL, last_error TEXT, updated_at TEXT NOT NULL
            )""",
        )
        for statement in statements:
            connection.execute(statement)

    def _migrate(self) -> None:
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
                )
                row = connection.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
                version = None if row is None else row["version"]
                if version is not None and int(version) > SCHEMA_VERSION:
                    raise RuntimeError(f"database schema {version} is newer than supported {SCHEMA_VERSION}")
                if version == SCHEMA_VERSION:
                    connection.commit()
                    return

                archive_version = 1 if version in (None, 1) else int(version)
                for table in self._ACTIVE_TABLES:
                    if self._table_exists(connection, table):
                        archive = f"{table}_v{archive_version}_archive"
                        if self._table_exists(connection, archive):
                            raise RuntimeError(f"migration archive already exists: {archive}")
                        connection.execute(f'ALTER TABLE "{table}" RENAME TO "{archive}"')
                self._create_v5(connection)
                connection.execute(
                    "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def schema_version(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
            return int(row["version"])

    def archived_v1_tables(self) -> tuple[str, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_v1_archive' ORDER BY name"
            ).fetchall()
            return tuple(str(row["name"]) for row in rows)

    def archived_v2_tables(self) -> tuple[str, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_v2_archive' ORDER BY name"
            ).fetchall()
            return tuple(str(row["name"]) for row in rows)

    def archived_v3_tables(self) -> tuple[str, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_v3_archive' ORDER BY name"
            ).fetchall()
            return tuple(str(row["name"]) for row in rows)

    def archived_v4_tables(self) -> tuple[str, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_v4_archive' ORDER BY name"
            ).fetchall()
            return tuple(str(row["name"]) for row in rows)

    @staticmethod
    def _policy_rows(
        connection: sqlite3.Connection, scenario: PurchaseScenario
    ) -> tuple[sqlite3.Row | None, sqlite3.Row | None]:
        user = connection.execute(
            "SELECT * FROM user_notification_policy WHERE policy_scope=?",
            (scenario.user_policy_scope_key,),
        ).fetchone()
        scenario_policy = connection.execute(
            "SELECT * FROM scenario_notification_policy WHERE scenario_scope=?",
            (scenario.scope_key,),
        ).fetchone()
        return user, scenario_policy

    @staticmethod
    def _ensure_policy_rows(
        connection: sqlite3.Connection, scenario: PurchaseScenario, timestamp: datetime
    ) -> tuple[sqlite3.Row, sqlite3.Row]:
        user, scenario_policy = EventStore._policy_rows(connection, scenario)
        if user is None:
            connection.execute(
                "INSERT INTO user_notification_policy VALUES (?, 1, 1, 1, ?, ?, ?, ?)",
                (
                    scenario.user_policy_scope_key,
                    scenario.membership_context,
                    scenario.eligibility_profile_version,
                    timestamp.isoformat(),
                    "bootstrap-from-verified-scenario",
                ),
            )
        if scenario_policy is None:
            connection.execute(
                "INSERT INTO scenario_notification_policy VALUES (?, ?, 1, 1, ?, ?, ?)",
                (
                    scenario.scope_key,
                    scenario.user_policy_scope_key,
                    scenario.target_total_minor,
                    timestamp.isoformat(),
                    "bootstrap-from-verified-scenario",
                ),
            )
        user, scenario_policy = EventStore._policy_rows(connection, scenario)
        assert user is not None and scenario_policy is not None
        return user, scenario_policy

    @staticmethod
    def _supersede_policy_events(
        connection: sqlite3.Connection,
        where_sql: str,
        parameters: tuple[object, ...],
        timestamp: datetime,
        reason: str,
    ) -> int:
        rows = connection.execute(
            f"SELECT event_id FROM deal_events WHERE ({where_sql}) AND status IN (?, ?)",
            (*parameters, EventStatus.QUEUED, EventStatus.IN_FLIGHT),
        ).fetchall()
        for row in rows:
            EventStore._set_status(
                connection,
                str(row["event_id"]),
                EventStatus.SUPERSEDED,
                reason,
                timestamp,
            )
        return len(rows)

    def update_user_policy(
        self,
        scenario: PurchaseScenario,
        *,
        notifications_enabled: bool,
        source_allowed: bool,
        membership_context: str,
        eligibility_profile_version: str,
        revision_id: str,
        now: datetime,
        expected_epoch: int | None = None,
    ) -> int:
        """Persist user/source policy independently from product observations."""
        require_aware(now, "now")
        if not revision_id or not membership_context or not eligibility_profile_version:
            raise ValueError("policy revision and eligibility bindings are required")
        if expected_epoch is not None:
            strict_int(expected_epoch, "expected_epoch", minimum=1)
        desired = (
            int(notifications_enabled),
            int(source_allowed),
            membership_context,
            eligibility_profile_version,
        )
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT * FROM user_notification_policy WHERE policy_scope=?",
                    (scenario.user_policy_scope_key,),
                ).fetchone()
                if existing is None:
                    if expected_epoch is not None:
                        raise PolicyEpochConflict("user policy does not yet have an epoch")
                    epoch = 1
                    connection.execute(
                        "INSERT INTO user_notification_policy VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            scenario.user_policy_scope_key,
                            epoch,
                            *desired,
                            now.isoformat(),
                            revision_id,
                        ),
                    )
                else:
                    epoch = int(existing["epoch"])
                    if expected_epoch is not None and epoch != expected_epoch:
                        raise PolicyEpochConflict("user policy epoch changed")
                    existing_time = datetime.fromisoformat(existing["updated_at"])
                    existing_values = (
                        existing["notifications_enabled"],
                        existing["source_allowed"],
                        existing["membership_context"],
                        existing["eligibility_profile_version"],
                    )
                    if now < existing_time:
                        raise StalePolicyState("user policy revision is older than stored policy")
                    if now == existing_time:
                        if existing_values == desired and existing["revision_id"] == revision_id:
                            connection.rollback()
                            return epoch
                        raise PolicyStateConflict("conflicting user policy at identical revision time")
                    material_change = existing_values != desired
                    if material_change:
                        epoch += 1
                    connection.execute(
                        """UPDATE user_notification_policy SET epoch=?, notifications_enabled=?,
                        source_allowed=?, membership_context=?, eligibility_profile_version=?,
                        updated_at=?, revision_id=? WHERE policy_scope=?""",
                        (
                            epoch,
                            *desired,
                            now.isoformat(),
                            revision_id,
                            scenario.user_policy_scope_key,
                        ),
                    )
                    if material_change:
                        self._supersede_policy_events(
                            connection,
                            "user_policy_scope=? AND user_policy_epoch<>?",
                            (scenario.user_policy_scope_key, epoch),
                            now,
                            "USER_POLICY_EPOCH_CHANGED",
                        )
                connection.commit()
                return epoch
            except Exception:
                connection.rollback()
                raise

    def update_scenario_policy(
        self,
        scenario: PurchaseScenario,
        *,
        target_total_minor: int | None,
        enabled: bool,
        revision_id: str,
        now: datetime,
        expected_epoch: int | None = None,
    ) -> int:
        """Persist per-scenario target/enabled state on its own monotonic clock."""
        require_aware(now, "now")
        if target_total_minor is not None:
            strict_int(target_total_minor, "target_total_minor")
        if not revision_id:
            raise ValueError("policy revision is required")
        if expected_epoch is not None:
            strict_int(expected_epoch, "expected_epoch", minimum=1)
        desired = (scenario.user_policy_scope_key, int(enabled), target_total_minor)
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT * FROM scenario_notification_policy WHERE scenario_scope=?",
                    (scenario.scope_key,),
                ).fetchone()
                if existing is None:
                    if expected_epoch is not None:
                        raise PolicyEpochConflict("scenario policy does not yet have an epoch")
                    epoch = 1
                    connection.execute(
                        "INSERT INTO scenario_notification_policy VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            scenario.scope_key,
                            scenario.user_policy_scope_key,
                            epoch,
                            int(enabled),
                            target_total_minor,
                            now.isoformat(),
                            revision_id,
                        ),
                    )
                else:
                    epoch = int(existing["epoch"])
                    if expected_epoch is not None and epoch != expected_epoch:
                        raise PolicyEpochConflict("scenario policy epoch changed")
                    existing_time = datetime.fromisoformat(existing["updated_at"])
                    existing_values = (
                        existing["policy_scope"],
                        existing["enabled"],
                        existing["target_total_minor"],
                    )
                    if now < existing_time:
                        raise StalePolicyState("scenario policy revision is older than stored policy")
                    if now == existing_time:
                        if existing_values == desired and existing["revision_id"] == revision_id:
                            connection.rollback()
                            return epoch
                        raise PolicyStateConflict("conflicting scenario policy at identical revision time")
                    material_change = existing_values != desired
                    if material_change:
                        epoch += 1
                    connection.execute(
                        """UPDATE scenario_notification_policy SET policy_scope=?, epoch=?, enabled=?,
                        target_total_minor=?, updated_at=?, revision_id=? WHERE scenario_scope=?""",
                        (
                            scenario.user_policy_scope_key,
                            epoch,
                            int(enabled),
                            target_total_minor,
                            now.isoformat(),
                            revision_id,
                            scenario.scope_key,
                        ),
                    )
                    if material_change:
                        self._supersede_policy_events(
                            connection,
                            "scenario_scope=? AND scenario_policy_epoch<>?",
                            (scenario.scope_key, epoch),
                            now,
                            "SCENARIO_POLICY_EPOCH_CHANGED",
                        )
                connection.commit()
                return epoch
            except Exception:
                connection.rollback()
                raise

    def policy_snapshot(self, scenario: PurchaseScenario) -> dict[str, object]:
        with self._connection() as connection:
            user, scenario_policy = self._policy_rows(connection, scenario)
            if user is None or scenario_policy is None:
                raise KeyError(scenario.scope_key)
            return {"user": dict(user), "scenario": dict(scenario_policy)}

    def set_current_state(self, state: CurrentState, *, now: datetime | None = None) -> bool:
        timestamp = now or datetime.now(timezone.utc)
        require_aware(timestamp, "now")
        column_names = (
            "scenario_scope", "offer_key", "context_id", "quantity", "membership_context",
            "eligibility_profile_version", "coupon_plan_id", "price_basis", "purchase_channel",
            "payment_method", "quote_fingerprint", "semantic_fingerprint", "total_minor", "stock",
            "eligibility_state", "source_enabled", "notifications_enabled", "evidence_id", "rule_version",
            "observed_at", "received_at", "expires_at", "availability_version",
        )
        payload_values = (
            state.scenario_scope,
            state.offer_key,
            state.context_id,
            state.quantity,
            state.membership_context,
            state.eligibility_profile_version,
            state.coupon_plan_id,
            state.price_basis,
            state.purchase_channel,
            state.payment_method,
            state.quote_fingerprint,
            state.semantic_fingerprint,
            state.total_minor,
            state.stock,
            state.eligibility_state,
            int(state.source_enabled),
            int(state.notifications_enabled),
            state.evidence_id,
            state.rule_version,
            state.observed_at.isoformat(),
            state.received_at.isoformat(),
            state.expires_at.isoformat(),
            state.availability_version,
        )
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self._current_state_row(connection, state.scenario_scope)
                if existing is not None:
                    existing_observed_at = datetime.fromisoformat(existing["observed_at"])
                    if state.observed_at < existing_observed_at:
                        raise StaleCurrentState("current state update is older than the stored source observation")
                    existing_payload = tuple(existing[name] for name in column_names)
                    if state.observed_at == existing_observed_at:
                        if existing_payload == payload_values:
                            connection.rollback()
                            return False
                        raise CurrentStateConflict("conflicting current state at identical source observation time")
                    assignments = ", ".join(f"{name}=?" for name in column_names[1:])
                    connection.execute(
                        f"UPDATE current_state SET {assignments}, updated_at=? WHERE scenario_scope=?",
                        (*payload_values[1:], timestamp.isoformat(), state.scenario_scope),
                    )
                else:
                    columns = (*column_names, "updated_at")
                    connection.execute(
                        f"INSERT INTO current_state ({','.join(columns)}) "
                        f"VALUES ({','.join('?' for _ in columns)})",
                        (*payload_values, timestamp.isoformat()),
                    )
                connection.commit()
                return True
            except Exception:
                connection.rollback()
                raise

    def record_observation(self, observation_id: str, observation: Observation) -> bool:
        if not observation_id:
            raise ValueError("observation_id is required")
        fingerprint = observation.payload_fingerprint
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT payload_fingerprint FROM price_observations WHERE observation_id=?", (observation_id,)
                ).fetchone()
                if existing is not None:
                    connection.rollback()
                    if existing["payload_fingerprint"] != fingerprint:
                        raise ObservationConflict("observation id reused with divergent payload")
                    return False
                connection.execute(
                    """INSERT INTO price_observations (
                        observation_id, payload_fingerprint, series_key, offer_key, context_id, quantity, price_type,
                        unit_minor, membership_context, eligibility_profile_version, coupon_plan_id, purchase_channel,
                        payment_method, source_id, source_published_at, observed_at, received_at, valid, parser_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        observation_id,
                        fingerprint,
                        observation.series_key,
                        observation.offer_key,
                        observation.context_id,
                        observation.quantity,
                        observation.price_type,
                        observation.unit_minor,
                        observation.membership_context,
                        observation.eligibility_profile_version,
                        observation.coupon_plan_id,
                        observation.purchase_channel,
                        observation.payment_method,
                        observation.source_id,
                        None if observation.source_published_at is None else observation.source_published_at.isoformat(),
                        observation.observed_at.isoformat(),
                        None if observation.received_at is None else observation.received_at.isoformat(),
                        int(observation.valid),
                        observation.parser_version,
                    ),
                )
                connection.commit()
                return True
            except Exception:
                connection.rollback()
                raise

    def observation_record(self, observation_id: str) -> dict[str, object]:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM price_observations WHERE observation_id=?", (observation_id,)).fetchone()
            if row is None:
                raise KeyError(observation_id)
            return dict(row)

    def upsert_daily_stat(
        self,
        *,
        series_key: str,
        local_day: str,
        median_unit_minor: int,
        sample_count: int,
        calculation_version: str = "history-v3.0-c01-r04.5",
    ) -> None:
        strict_int(median_unit_minor, "median_unit_minor")
        strict_int(sample_count, "sample_count", minimum=1)
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """INSERT INTO daily_price_stats VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(series_key, local_day, calculation_version) DO UPDATE SET
                    median_unit_minor=excluded.median_unit_minor, sample_count=excluded.sample_count""",
                    (series_key, local_day, median_unit_minor, sample_count, calculation_version),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _state_is_valid(row: sqlite3.Row, check_time: datetime) -> bool:
        return bool(
            row["state_semantic_fingerprint"] is not None
            and row["state_scenario_scope"] == row["scenario_scope"]
            and row["state_offer_key"] == row["offer_key"]
            and row["state_context_id"] == row["context_id"]
            and row["state_quantity"] == row["quantity"]
            and row["state_membership_context"] == row["membership_context"]
            and row["state_eligibility_profile_version"] == row["eligibility_profile_version"]
            and row["state_coupon_plan_id"] == row["coupon_plan_id"]
            and row["state_price_basis"] == row["price_basis"]
            and row["state_purchase_channel"] == row["purchase_channel"]
            and row["state_payment_method"] == row["payment_method"]
            and row["state_semantic_fingerprint"] == row["expected_semantic_fingerprint"]
            and row["state_total_minor"] <= row["total_minor"]
            and row["state_availability_version"] == row["availability_version"]
            and row["current_state_rule_version"] == row["state_rule_version"]
            and row["state_stock"] == "IN_STOCK"
            and row["state_eligibility_state"] == "ELIGIBLE"
            and row["state_source_enabled"]
            and row["state_notifications_enabled"]
            and row["state_evidence_id"]
            and row["current_state_rule_version"]
            and row["user_policy_epoch"] == row["current_user_policy_epoch"]
            and row["scenario_policy_epoch"] == row["current_scenario_policy_epoch"]
            and row["current_notifications_enabled"]
            and row["current_source_allowed"]
            and row["current_scenario_enabled"]
            and row["current_policy_membership_context"] == row["membership_context"]
            and row["current_policy_profile_version"] == row["eligibility_profile_version"]
            and row["current_target_total_minor"] == row["target_total_minor"]
            and check_time >= datetime.fromisoformat(row["state_observed_at"])
            and check_time < datetime.fromisoformat(row["state_expires_at"])
        )

    @staticmethod
    def _event_state_query() -> str:
        return """SELECT e.*, o.payload_json,
            s.scenario_scope AS state_scenario_scope, s.offer_key AS state_offer_key,
            s.context_id AS state_context_id, s.quantity AS state_quantity,
            s.membership_context AS state_membership_context,
            s.eligibility_profile_version AS state_eligibility_profile_version,
            s.coupon_plan_id AS state_coupon_plan_id, s.price_basis AS state_price_basis,
            s.purchase_channel AS state_purchase_channel, s.payment_method AS state_payment_method,
            s.quote_fingerprint AS state_quote_fingerprint,
            s.semantic_fingerprint AS state_semantic_fingerprint, s.total_minor AS state_total_minor,
            s.stock AS state_stock, s.eligibility_state AS state_eligibility_state,
            s.source_enabled AS state_source_enabled, s.notifications_enabled AS state_notifications_enabled,
            s.evidence_id AS state_evidence_id, s.rule_version AS current_state_rule_version,
            s.observed_at AS state_observed_at, s.expires_at AS state_expires_at,
            s.availability_version AS state_availability_version,
            u.epoch AS current_user_policy_epoch,
            u.notifications_enabled AS current_notifications_enabled,
            u.source_allowed AS current_source_allowed,
            u.membership_context AS current_policy_membership_context,
            u.eligibility_profile_version AS current_policy_profile_version,
            p.epoch AS current_scenario_policy_epoch,
            p.enabled AS current_scenario_enabled,
            p.target_total_minor AS current_target_total_minor
            FROM deal_events e JOIN notification_outbox o ON o.event_id=e.event_id
            LEFT JOIN current_state s ON s.scenario_scope=e.scenario_scope
            LEFT JOIN user_notification_policy u ON u.policy_scope=e.user_policy_scope
            LEFT JOIN scenario_notification_policy p ON p.scenario_scope=e.scenario_scope
            WHERE e.event_id=?"""

    def _current_state_row(self, connection: sqlite3.Connection, scenario_scope: str) -> sqlite3.Row | None:
        return connection.execute("SELECT * FROM current_state WHERE scenario_scope=?", (scenario_scope,)).fetchone()

    @staticmethod
    def _validate_enqueue_bindings(
        scenario: PurchaseScenario,
        decision: Decision,
        state: sqlite3.Row | None,
        user_policy: sqlite3.Row,
        scenario_policy: sqlite3.Row,
        expected_fingerprint: str,
        now: datetime,
        expires_at: datetime,
    ) -> None:
        if not decision.notify or decision.total_minor is None:
            raise DecisionBindingError("only complete notifying decisions can be enqueued")
        if (
            decision.scenario_scope != scenario.scope_key
            or not decision.cost_fingerprint
            or decision.cost_fingerprint != expected_fingerprint
            or not decision.decision_fingerprint
            or decision.decision_fingerprint != decision.computed_fingerprint
            or decision.evaluated_at is None
            or decision.valid_until is None
            or decision.evaluated_at > now
            or now >= decision.valid_until
            or expires_at > decision.valid_until
            or not verify_decision_approval(decision)
        ):
            raise DecisionBindingError("decision identity or validity binding failed")
        if state is None:
            raise DecisionBindingError("current state is missing")
        expected = {
            "scenario_scope": scenario.scope_key,
            "offer_key": scenario.offer.key,
            "context_id": scenario.context_id,
            "quantity": scenario.quantity,
            "membership_context": scenario.membership_context,
            "eligibility_profile_version": scenario.eligibility_profile_version,
            "coupon_plan_id": scenario.coupon_plan_id,
            "price_basis": scenario.price_basis,
            "purchase_channel": scenario.purchase_channel,
            "payment_method": scenario.payment_method,
            "quote_fingerprint": expected_fingerprint,
        }
        if any(state[field_name] != value for field_name, value in expected.items()):
            raise DecisionBindingError("current state belongs to a different scenario or quote")
        if (
            state["total_minor"] > decision.total_minor
            or not state["semantic_fingerprint"]
            or not state["availability_version"]
            or not state["rule_version"]
            or state["stock"] != "IN_STOCK"
            or state["eligibility_state"] != "ELIGIBLE"
            or not state["source_enabled"]
            or not state["notifications_enabled"]
            or now < datetime.fromisoformat(state["observed_at"])
            or now >= datetime.fromisoformat(state["expires_at"])
        ):
            raise DecisionBindingError("current state is unavailable, stale, or more expensive")
        if (
            user_policy["policy_scope"] != scenario.user_policy_scope_key
            or not user_policy["notifications_enabled"]
            or not user_policy["source_allowed"]
            or user_policy["membership_context"] != scenario.membership_context
            or user_policy["eligibility_profile_version"] != scenario.eligibility_profile_version
            or scenario_policy["scenario_scope"] != scenario.scope_key
            or scenario_policy["policy_scope"] != scenario.user_policy_scope_key
            or not scenario_policy["enabled"]
            or scenario_policy["target_total_minor"] != scenario.target_total_minor
        ):
            raise DecisionBindingError("notification policy is disabled or belongs to a different configuration")

    def enqueue(
        self,
        scenario: PurchaseScenario,
        decision: Decision,
        *,
        request_id: str,
        dedupe_key: str,
        expected_fingerprint: str,
        expires_at: datetime,
        now: datetime | None = None,
        inject_failure: bool = False,
    ) -> tuple[str, bool]:
        if not request_id:
            raise ValueError("request_id is required")
        require_aware(expires_at, "expires_at")
        created = now or datetime.now(timezone.utc)
        require_aware(created, "now")
        if expires_at <= created:
            raise ValueError("event must expire after creation")

        event_id = str(uuid.uuid4())
        outbox_id = str(uuid.uuid4())
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                state = self._current_state_row(connection, scenario.scope_key)
                user_policy, scenario_policy = self._ensure_policy_rows(connection, scenario, created)
                effective_expiry = expires_at
                if decision.valid_until is not None:
                    effective_expiry = min(effective_expiry, decision.valid_until)
                if state is not None:
                    effective_expiry = min(effective_expiry, datetime.fromisoformat(state["expires_at"]))
                if effective_expiry <= created:
                    raise DecisionBindingError("event dependencies are already expired")
                self._validate_enqueue_bindings(
                    scenario,
                    decision,
                    state,
                    user_policy,
                    scenario_policy,
                    expected_fingerprint,
                    created,
                    effective_expiry,
                )
                assert state is not None
                request_fingerprint = canonical_digest(
                    "event-request",
                    {
                        "scenario_scope": scenario.scope_key,
                        "decision_fingerprint": decision.decision_fingerprint,
                        "expected_quote_fingerprint": expected_fingerprint,
                        "total_minor": decision.total_minor,
                        "expires_at": effective_expiry.isoformat(),
                        "user_policy_epoch": user_policy["epoch"],
                        "scenario_policy_epoch": scenario_policy["epoch"],
                    },
                )
                semantic_key = canonical_digest(
                    "notification-semantic",
                    {
                        "scenario_scope": scenario.scope_key,
                        "semantic_fingerprint": state["semantic_fingerprint"],
                        "total_minor": decision.total_minor,
                        "availability_version": state["availability_version"],
                        "state_rule_version": state["rule_version"],
                        "user_policy_epoch": user_policy["epoch"],
                        "scenario_policy_epoch": scenario_policy["epoch"],
                        "reason_class": (
                            "USER_TARGET" if decision.primary_reason == "TARGET_REACHED" else "DEAL_POLICY"
                        ),
                    },
                )
                existing_request = connection.execute(
                    "SELECT event_id, request_fingerprint FROM deal_events WHERE request_id=?", (request_id,)
                ).fetchone()
                if existing_request is not None:
                    connection.rollback()
                    if existing_request["request_fingerprint"] != request_fingerprint:
                        raise IdempotencyConflict("request id reused with divergent payload")
                    return str(existing_request["event_id"]), False
                existing_semantic = connection.execute(
                    "SELECT event_id FROM deal_events WHERE semantic_key=?", (semantic_key,)
                ).fetchone()
                if existing_semantic is not None:
                    connection.rollback()
                    return str(existing_semantic["event_id"]), False

                payload = {
                    "event_id": event_id,
                    "scenario_scope": scenario.scope_key,
                    "offer_key": scenario.offer.key,
                    "context_id": scenario.context_id,
                    "quantity": scenario.quantity,
                    "membership_context": scenario.membership_context,
                    "eligibility_profile_version": scenario.eligibility_profile_version,
                    "coupon_plan_id": scenario.coupon_plan_id,
                    "price_basis": scenario.price_basis,
                    "reason": decision.primary_reason,
                    "total_minor": decision.total_minor,
                    "semantic_fingerprint": state["semantic_fingerprint"],
                    "availability_version": state["availability_version"],
                    "state_rule_version": state["rule_version"],
                    "user_policy_scope": scenario.user_policy_scope_key,
                    "user_policy_epoch": user_policy["epoch"],
                    "scenario_policy_epoch": scenario_policy["epoch"],
                    "policy_evidence_fingerprint": decision.policy_evidence_fingerprint,
                    "target_total_minor": scenario.target_total_minor,
                    "observed_not_checkout_confirmed": True,
                    "delivery_kind": "MOCK_ONLY",
                }
                event_columns = (
                    "event_id", "request_id", "request_fingerprint", "caller_dedupe_key", "semantic_key",
                    "scenario_scope", "user_policy_scope", "user_policy_epoch", "scenario_policy_epoch",
                    "offer_key", "context_id", "quantity", "membership_context",
                    "eligibility_profile_version", "coupon_plan_id", "price_basis", "purchase_channel",
                    "payment_method", "expected_quote_fingerprint", "expected_semantic_fingerprint",
                    "decision_fingerprint", "decision_reason", "total_minor", "availability_version",
                    "policy_evidence_json", "policy_evidence_fingerprint", "approval_seal",
                    "target_total_minor",
                    "state_rule_version", "policy_version", "status", "expires_at", "claim_token",
                    "claim_until", "created_at", "updated_at",
                )
                event_values = (
                    event_id, request_id, request_fingerprint, dedupe_key, semantic_key,
                    scenario.scope_key, scenario.user_policy_scope_key, user_policy["epoch"],
                    scenario_policy["epoch"], scenario.offer.key, scenario.context_id, scenario.quantity,
                    scenario.membership_context, scenario.eligibility_profile_version, scenario.coupon_plan_id,
                    scenario.price_basis, scenario.purchase_channel, scenario.payment_method,
                    expected_fingerprint, state["semantic_fingerprint"], decision.decision_fingerprint,
                    decision.primary_reason, decision.total_minor, state["availability_version"],
                    decision.policy_evidence_json, decision.policy_evidence_fingerprint, decision.approval_seal,
                    scenario.target_total_minor,
                    state["rule_version"], decision.policy_version, EventStatus.QUEUED,
                    effective_expiry.isoformat(), None, None, created.isoformat(), created.isoformat(),
                )
                connection.execute(
                    f"INSERT INTO deal_events ({','.join(event_columns)}) "
                    f"VALUES ({','.join('?' for _ in event_columns)})",
                    event_values,
                )
                if inject_failure:
                    raise sqlite3.OperationalError("injected transaction failure")
                connection.execute(
                    "INSERT INTO notification_outbox VALUES (?, ?, ?, ?, NULL, ?)",
                    (
                        outbox_id,
                        event_id,
                        EventStatus.QUEUED,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        created.isoformat(),
                    ),
                )
                connection.commit()
                return event_id, True
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _set_status(
        connection: sqlite3.Connection,
        event_id: str,
        status: EventStatus,
        error: str | None,
        timestamp: datetime,
        *,
        claim_token: str | None = None,
        claim_until: datetime | None = None,
    ) -> None:
        connection.execute(
            "UPDATE deal_events SET status=?, claim_token=?, claim_until=?, updated_at=? WHERE event_id=?",
            (
                status,
                claim_token,
                None if claim_until is None else claim_until.isoformat(),
                timestamp.isoformat(),
                event_id,
            ),
        )
        connection.execute(
            "UPDATE notification_outbox SET status=?, last_error=?, updated_at=? WHERE event_id=?",
            (status, error, timestamp.isoformat(), event_id),
        )

    def deliver(self, event_id: str, sink: DeliverySink, *, now: datetime | None = None) -> EventStatus:
        check_time = now or datetime.now(timezone.utc)
        require_aware(check_time, "now")
        claim_token = str(uuid.uuid4())
        claim_until = check_time + timedelta(seconds=30)

        # Phase one validates and claims under a short transaction.
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(self._event_state_query(), (event_id,)).fetchone()
                if row is None:
                    raise KeyError(event_id)
                status = EventStatus(row["status"])
                if status == EventStatus.IN_FLIGHT:
                    current_claim_until = datetime.fromisoformat(row["claim_until"])
                    if check_time < current_claim_until:
                        connection.rollback()
                        return EventStatus.IN_FLIGHT
                elif status != EventStatus.QUEUED:
                    connection.rollback()
                    return status
                if check_time >= datetime.fromisoformat(row["expires_at"]):
                    self._set_status(connection, event_id, EventStatus.EXPIRED, "EVENT_EXPIRED", check_time)
                    connection.commit()
                    return EventStatus.EXPIRED
                if not self._state_is_valid(row, check_time):
                    self._set_status(
                        connection,
                        event_id,
                        EventStatus.SUPERSEDED,
                        "PRE_DELIVERY_REVALIDATION_FAILED",
                        check_time,
                    )
                    connection.commit()
                    return EventStatus.SUPERSEDED
                payload = json.loads(row["payload_json"])
                self._set_status(
                    connection,
                    event_id,
                    EventStatus.IN_FLIGHT,
                    None,
                    check_time,
                    claim_token=claim_token,
                    claim_until=claim_until,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        # The external callback is intentionally outside both SQLite and process write locks.
        delivery_error: Exception | None = None
        ambiguous = False
        try:
            sink.deliver(payload)
        except AmbiguousDelivery as exc:
            delivery_error = exc
            ambiguous = True
        except Exception as exc:  # noqa: BLE001 - sink failures are persisted, not propagated
            delivery_error = exc

        finalize_time = now or datetime.now(timezone.utc)
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(self._event_state_query(), (event_id,)).fetchone()
                if row is None:
                    raise KeyError(event_id)
                if row["status"] != EventStatus.IN_FLIGHT or row["claim_token"] != claim_token:
                    connection.rollback()
                    return EventStatus(row["status"])
                if ambiguous:
                    final = EventStatus.DELIVERY_UNKNOWN
                    error = str(delivery_error)
                elif delivery_error is not None:
                    final = EventStatus.FAILED
                    error = str(delivery_error)
                elif not self._state_is_valid(row, finalize_time):
                    final = EventStatus.DELIVERY_UNKNOWN
                    error = "POST_DELIVERY_STATE_CHANGED"
                else:
                    final = EventStatus.DELIVERED
                    error = None
                self._set_status(connection, event_id, final, error, finalize_time)
                connection.commit()
                return final
            except Exception:
                connection.rollback()
                raise

    def counts(self) -> dict[str, int]:
        with self._connection() as connection:
            return {
                "events": int(connection.execute("SELECT COUNT(*) FROM deal_events").fetchone()[0]),
                "outbox": int(connection.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0]),
            }

    def history_counts(self) -> dict[str, int]:
        with self._connection() as connection:
            return {
                "raw_observations": int(connection.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0]),
                "daily_stats": int(connection.execute("SELECT COUNT(*) FROM daily_price_stats").fetchone()[0]),
            }

    def event_status(self, event_id: str) -> EventStatus:
        with self._connection() as connection:
            row = connection.execute("SELECT status FROM deal_events WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise KeyError(event_id)
            return EventStatus(row["status"])
