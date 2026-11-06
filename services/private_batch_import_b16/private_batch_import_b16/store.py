from __future__ import annotations

import sqlite3
import uuid

from . import dependencies as _dependencies  # noqa: F401
from private_observation_b15.store import ObservationStore, StoreConflict


class BatchObservationStore(ObservationStore):
    def _initialize_schema_if_missing(self) -> bool:
        """Durably initialize an absent database before any observation transaction."""
        self._validate_paths("before_initial_schema_creation")
        if self.database.is_file():
            return False
        connection = self._connect()
        initialized = False
        try:
            connection.execute("BEGIN IMMEDIATE")
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables:
                connection.execute("ROLLBACK")
                self._schema_readonly_check(connection)
                return False
            self._schema(connection)
            connection.execute("COMMIT")
            initialized = True
            self._schema_readonly_check(connection)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        self._validate_paths("after_initial_schema_creation")
        return initialized

    @staticmethod
    def _classify_connection(connection: sqlite3.Connection, records: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        new_records: list[dict[str, object]] = []
        existing: list[dict[str, object]] = []
        for record in records:
            by_submission = connection.execute(
                "SELECT observation_id,fingerprint FROM observations WHERE submission_id=?",
                (record["submission_id"],),
            ).fetchone()
            if by_submission is not None:
                if by_submission["fingerprint"] != record["observation_fingerprint"]:
                    raise StoreConflict("SUBMISSION_ID_CONTENT_CONFLICT")
                existing.append(record)
                continue
            by_fingerprint = connection.execute(
                "SELECT observation_id FROM observations WHERE fingerprint=?",
                (record["observation_fingerprint"],),
            ).fetchone()
            if by_fingerprint is not None:
                existing.append(record)
            else:
                new_records.append(record)
        return new_records, existing

    def classify_batch(self, records: list[dict[str, object]]) -> dict[str, int]:
        with self._lock:
            self._validate_paths("before_batch_classification")
            if not self.database.is_file():
                return {"new_count": len(records), "existing_idempotent_count": 0}
            connection = self._connect(readonly=True)
            try:
                self._schema_readonly_check(connection)
                new_records, existing = self._classify_connection(connection, records)
            finally:
                connection.close()
            return {"new_count": len(new_records), "existing_idempotent_count": len(existing)}

    def _insert_record(self, connection: sqlite3.Connection, normalized: dict[str, object], *, batch_id: str, created: str) -> str:
        observation_id = "OBS-B16-" + uuid.uuid4().hex
        identity = normalized["identity"]
        coupon = normalized["user_reported_coupon"]
        shipping = normalized["shipping"]
        source = normalized["source"]
        columns = (
            "observation_id", "submission_id", "fingerprint", "series_key", "title", "platform", "product_id", "sku_id", "seller_id", "item_condition", "package_signature", "currency",
            "observed_at_utc", "taipei_date", "quantity", "before_coupon_price_twd", "confirmed_after_coupon_price_twd", "user_reported_coupon_price_twd",
            "coupon_status", "coupon_eligibility", "coupon_evidence_level", "coupon_evidence_note", "coupon_valid_from_utc", "coupon_valid_until_utc",
            "shipping_status", "shipping_fee_twd", "mandatory_fee_twd", "required_total_twd", "user_reported_required_total_twd",
            "source_class", "visibility", "source_note", "platform_verified", "input_sha256", "created_at_utc", "is_deleted",
        )
        values = (
            observation_id, normalized["submission_id"], normalized["observation_fingerprint"], normalized["series_key"], normalized["title"],
            identity["platform"], identity["product_id"], identity["sku_id"], identity["seller_id"], identity["condition"], identity["package_signature"], identity["currency"],
            normalized["observed_at"], normalized["taipei_date"], normalized["quantity"], normalized["before_coupon_price_twd"], None, coupon["price_twd"],
            coupon["status"], coupon["eligibility"], coupon["evidence_level"], coupon["evidence_note"], coupon["valid_from"], coupon["valid_until"],
            shipping["status"], shipping["shipping_fee_twd"], shipping["mandatory_fee_twd"], normalized["required_total_twd"], normalized["user_reported_required_total_twd"],
            source["source_class"], source["visibility"], source["note"], 0, normalized["input_sha256"], created, 0,
        )
        connection.execute(
            f"INSERT INTO observations({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
            values,
        )
        connection.execute(
            "INSERT INTO commit_audit VALUES(?,?,?,?,?)",
            ("AUD-B16-" + uuid.uuid4().hex, observation_id, f"BATCH_COMMIT:{batch_id}", created, normalized["input_sha256"]),
        )
        return observation_id

    def commit_batch(self, records: list[dict[str, object]], *, file_sha256: str, duplicate_input_count: int) -> dict[str, object]:
        if not records:
            raise ValueError("batch records must not be empty")
        with self._lock:
            self._validate_paths("before_batch_commit")
            if self.database.is_file():
                preflight = self._connect(readonly=True)
                try:
                    self._schema_readonly_check(preflight)
                    preflight_new, preflight_existing = self._classify_connection(preflight, records)
                finally:
                    preflight.close()
                if not preflight_new:
                    return {
                        "batch_id": "BATCH-B16-IDEMPOTENT-" + file_sha256[:16],
                        "inserted_count": 0,
                        "existing_idempotent_count": len(preflight_existing),
                        "duplicate_input_count": duplicate_input_count,
                        "idempotent_replay": True,
                        "backup_created": False,
                        "backup_cleanup_removed_count": 0,
                    }
            self.data_root.mkdir(parents=True, exist_ok=True)
            self._validate_paths("after_batch_data_root_creation")
            self._last_backup_cleanup_removed = 0
            initialized_now = self._initialize_schema_if_missing()
            backup = None if initialized_now else self._backup()
            batch_id = "BATCH-B16-" + uuid.uuid4().hex
            created = self._now().isoformat(timespec="seconds").replace("+00:00", "Z")
            connection = self._connect()
            inserted_ids: list[str] = []
            existing_count = 0
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._schema(connection)
                new_records, existing = self._classify_connection(connection, records)
                existing_count = len(existing)
                for record in new_records:
                    inserted_ids.append(self._insert_record(connection, record, batch_id=batch_id, created=created))
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
            self._validate_paths("after_batch_commit")
            return {
                "batch_id": batch_id,
                "inserted_count": len(inserted_ids),
                "existing_idempotent_count": existing_count,
                "duplicate_input_count": duplicate_input_count,
                "idempotent_replay": len(inserted_ids) == 0,
                "backup_created": backup is not None,
                "backup_cleanup_removed_count": self._last_backup_cleanup_removed,
                "observation_ids": inserted_ids,
            }

