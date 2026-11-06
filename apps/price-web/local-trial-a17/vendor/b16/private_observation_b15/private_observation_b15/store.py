from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median_low
from typing import Callable


DB_SCHEMA = "CDH-B15-PRIVATE-OBSERVATION-DB-1"
WIRE_SCHEMA = "CDH-PRIVATE-PRICE-V1"
MAX_HISTORY = 500
MAX_DATABASE_BYTES = 64 * 1024 * 1024
BACKUP_NAME = re.compile(r"^before-commit-\d{8}T\d{12}Z-[0-9a-f]{32}\.sqlite3$")


class StoreError(RuntimeError):
    pass


class StoreConflict(StoreError):
    pass


def _is_reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(path.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except (AttributeError, FileNotFoundError, OSError):
        return path.is_symlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _components(path: Path):
    absolute = _absolute(path)
    current = Path(absolute.anchor)
    yield current
    for part in absolute.parts[1:]:
        current /= part
        yield current


def _identity(path: Path) -> tuple[int, int, int, int]:
    value = path.stat(follow_symlinks=False)
    return (int(value.st_dev), int(value.st_ino), int(value.st_mode), int(getattr(value, "st_file_attributes", 0)))


class ObservationStore:
    def __init__(self, data_root: Path, *, allowed_project_root: Path, database_name: str = "private_user_observations.sqlite3", clock: Callable[[], datetime] | None = None, max_backups: int = 8, max_backup_bytes: int = 256 * 1024 * 1024, max_backup_age_days: int = 30, min_backups_to_keep: int = 2) -> None:
        if not database_name or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for char in database_name) or not database_name.endswith(".sqlite3"):
            raise StoreError("database name is not allowed")
        if max_backups < 2 or min_backups_to_keep < 1 or min_backups_to_keep > max_backups or max_backup_bytes < 1 or max_backup_age_days < 1:
            raise StoreError("backup retention settings are invalid")
        self.allowed_project_root = _absolute(allowed_project_root)
        self.data_root = _absolute(data_root)
        self.database = self.data_root / database_name
        self.backup_root = self.data_root / "backups"
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_backups = max_backups
        self.max_backup_bytes = max_backup_bytes
        self.max_backup_age_days = max_backup_age_days
        self.min_backups_to_keep = min_backups_to_keep
        self._lock = threading.RLock()
        self._trusted_project_identities: dict[str, tuple[int, int, int, int]] = {}
        self._bind_project_root()
        self._validate_paths("constructor")

    def _walk_existing_no_reparse(self, target: Path, *, require_final_directory: bool = False) -> list[Path]:
        existing: list[Path] = []
        for component in _components(target):
            if not os.path.lexists(component):
                break
            if _is_reparse(component):
                raise StoreError("path component is a symlink, junction, or reparse point")
            if component != target and not component.is_dir():
                raise StoreError("path ancestor is not a directory")
            existing.append(component)
        if require_final_directory and (not target.is_dir() or _is_reparse(target)):
            raise StoreError("required directory is missing or unsafe")
        return existing

    def _bind_project_root(self) -> None:
        components = self._walk_existing_no_reparse(self.allowed_project_root, require_final_directory=True)
        if components[-1] != self.allowed_project_root:
            raise StoreError("allowed project root identity is unavailable")
        self._project_resolved = self.allowed_project_root.resolve(strict=True)
        self._trusted_project_identities = {str(path): _identity(path) for path in components}

    def _validate_paths(self, stage: str) -> None:
        del stage
        project_components = self._walk_existing_no_reparse(self.allowed_project_root, require_final_directory=True)
        for path in project_components:
            expected = self._trusted_project_identities.get(str(path))
            if expected is not None and _identity(path) != expected:
                raise StoreError("allowed project ancestor identity changed")
        if self.allowed_project_root.resolve(strict=True) != self._project_resolved:
            raise StoreError("allowed project root resolved identity changed")
        if not self.data_root.is_relative_to(self.allowed_project_root):
            raise StoreError("data root must be lexically below the allowed project root")
        self._walk_existing_no_reparse(self.data_root)
        resolved_data = self.data_root.resolve(strict=False)
        if not resolved_data.is_relative_to(self._project_resolved):
            raise StoreError("resolved data root escapes the allowed project root")
        for target in (self.database, self.backup_root):
            if not target.is_relative_to(self.data_root):
                raise StoreError("storage target escapes the controlled data root")
            self._walk_existing_no_reparse(target)
            resolved = target.resolve(strict=False)
            if not resolved.is_relative_to(self._project_resolved):
                raise StoreError("resolved storage target escapes the allowed project root")
        if self.database.exists():
            if _is_reparse(self.database) or not self.database.is_file() or self.database.stat().st_size > MAX_DATABASE_BYTES:
                raise StoreError("database file identity or size is invalid")
        if self.backup_root.exists() and (not self.backup_root.is_dir() or _is_reparse(self.backup_root)):
            raise StoreError("backup root identity is invalid")

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise StoreError("clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        self._validate_paths("before_database_open")
        if readonly:
            if not self.database.is_file():
                raise FileNotFoundError
            connection = sqlite3.connect(f"file:{self.database.as_posix()}?mode=ro", uri=True, timeout=2.0)
            connection.execute("PRAGMA query_only=ON")
        else:
            connection = sqlite3.connect(self.database, timeout=2.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=2000")
        self._validate_paths("after_database_open")
        return connection

    @staticmethod
    def _schema(connection: sqlite3.Connection) -> None:
        statements = (
        "CREATE TABLE IF NOT EXISTS b15_schema(version INTEGER NOT NULL, schema_version TEXT NOT NULL)",
        "INSERT INTO b15_schema(version,schema_version) SELECT 1,'CDH-B15-PRIVATE-OBSERVATION-DB-1' WHERE NOT EXISTS(SELECT 1 FROM b15_schema)",
        """CREATE TABLE IF NOT EXISTS observations(
          observation_id TEXT PRIMARY KEY,
          submission_id TEXT NOT NULL UNIQUE,
          fingerprint TEXT NOT NULL UNIQUE,
          series_key TEXT NOT NULL,
          title TEXT NOT NULL,
          platform TEXT NOT NULL,
          product_id TEXT NOT NULL,
          sku_id TEXT NOT NULL,
          seller_id TEXT NOT NULL,
          item_condition TEXT NOT NULL,
          package_signature TEXT NOT NULL,
          currency TEXT NOT NULL,
          observed_at_utc TEXT NOT NULL,
          taipei_date TEXT NOT NULL,
          quantity INTEGER NOT NULL CHECK(quantity>=1),
          before_coupon_price_twd INTEGER NOT NULL CHECK(before_coupon_price_twd>=0),
          confirmed_after_coupon_price_twd INTEGER,
          user_reported_coupon_price_twd INTEGER,
          coupon_status TEXT NOT NULL,
          coupon_eligibility TEXT NOT NULL,
          coupon_evidence_level TEXT NOT NULL,
          coupon_evidence_note TEXT,
          coupon_valid_from_utc TEXT,
          coupon_valid_until_utc TEXT,
          shipping_status TEXT NOT NULL,
          shipping_fee_twd INTEGER,
          mandatory_fee_twd INTEGER,
          required_total_twd INTEGER,
          user_reported_required_total_twd INTEGER,
          source_class TEXT NOT NULL,
          visibility TEXT NOT NULL,
          source_note TEXT NOT NULL,
          platform_verified INTEGER NOT NULL CHECK(platform_verified=0),
          input_sha256 TEXT NOT NULL,
          created_at_utc TEXT NOT NULL,
          is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN(0,1)),
          CHECK(confirmed_after_coupon_price_twd IS NULL),
          CHECK(source_class='USER_ENTERED'),
          CHECK(visibility='PRIVATE_LOCAL')
        )""",
        "CREATE INDEX IF NOT EXISTS idx_b15_search ON observations(product_id,sku_id,title,series_key,observed_at_utc)",
        """CREATE TABLE IF NOT EXISTS commit_audit(
          audit_id TEXT PRIMARY KEY,
          observation_id TEXT NOT NULL,
          action TEXT NOT NULL,
          occurred_at_utc TEXT NOT NULL,
          input_sha256 TEXT NOT NULL
        )""",
        )
        for statement in statements:
            connection.execute(statement)
        row = connection.execute("SELECT version,schema_version FROM b15_schema").fetchall()
        if len(row) != 1 or row[0]["version"] != 1 or row[0]["schema_version"] != DB_SCHEMA:
            raise StoreError("private database schema mismatch")

    def _existing(self, normalized: dict[str, object]) -> tuple[sqlite3.Row | None, bool]:
        if not self.database.is_file():
            return None, False
        connection = self._connect(readonly=True)
        try:
            self._schema_readonly_check(connection)
            by_submission = connection.execute("SELECT * FROM observations WHERE submission_id=?", (normalized["submission_id"],)).fetchone()
            if by_submission is not None:
                if by_submission["fingerprint"] != normalized["observation_fingerprint"]:
                    raise StoreConflict("SUBMISSION_ID_CONTENT_CONFLICT")
                return by_submission, True
            by_fingerprint = connection.execute("SELECT * FROM observations WHERE fingerprint=?", (normalized["observation_fingerprint"],)).fetchone()
            return (by_fingerprint, True) if by_fingerprint is not None else (None, False)
        finally:
            connection.close()

    @staticmethod
    def _schema_readonly_check(connection: sqlite3.Connection) -> None:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"b15_schema", "observations", "commit_audit"}.issubset(tables):
            raise StoreError("private database schema incomplete")
        row = connection.execute("SELECT version,schema_version FROM b15_schema").fetchall()
        if len(row) != 1 or row[0][0] != 1 or row[0][1] != DB_SCHEMA:
            raise StoreError("private database schema mismatch")
        check = connection.execute("PRAGMA quick_check").fetchone()
        if check is None or check[0] != "ok":
            raise StoreError("private database integrity check failed")

    def _backup(self) -> Path | None:
        if not self.database.is_file():
            return None
        self._validate_paths("before_backup")
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self._validate_paths("after_backup_directory_creation")
        stamp = self._now().strftime("%Y%m%dT%H%M%S%fZ")
        target = self.backup_root / f"before-commit-{stamp}-{uuid.uuid4().hex}.sqlite3"
        source = self._connect(readonly=True)
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
            check = destination.execute("PRAGMA integrity_check").fetchone()
            if check is None or check[0] != "ok":
                raise StoreError("backup integrity check failed")
        finally:
            source.close()
            destination.close()
        self._validate_paths("after_backup_creation")
        removed = self._cleanup_backups(newest=target)
        self._last_backup_cleanup_removed = removed
        return target

    def _backup_files(self) -> list[Path]:
        if not self.backup_root.exists():
            return []
        self._validate_paths("before_backup_inventory")
        result = []
        for path in self.backup_root.iterdir():
            if _is_reparse(path) or not path.is_file() or not BACKUP_NAME.fullmatch(path.name):
                raise StoreError("backup directory contains an unexpected or unsafe entry")
            result.append(path)
        return sorted(result, key=lambda item: (item.stat().st_mtime_ns, item.name), reverse=True)

    def _cleanup_backups(self, *, newest: Path) -> int:
        files = self._backup_files()
        mandatory = files[: self.min_backups_to_keep]
        mandatory_bytes = sum(item.stat().st_size for item in mandatory)
        if mandatory_bytes > self.max_backup_bytes:
            if newest.exists():
                newest.unlink()
            raise StoreError("backup capacity cannot preserve the minimum recovery set")
        now_timestamp = self._now().timestamp()
        keep = set(mandatory)
        total = mandatory_bytes
        for path in files[self.min_backups_to_keep:]:
            age_days = max(0.0, (now_timestamp - path.stat().st_mtime) / 86400)
            size = path.stat().st_size
            if len(keep) < self.max_backups and age_days <= self.max_backup_age_days and total + size <= self.max_backup_bytes:
                keep.add(path); total += size
        removed = 0
        for path in files:
            if path not in keep:
                path.unlink(); removed += 1
        self._validate_paths("after_backup_cleanup")
        return removed

    def commit(self, normalized: dict[str, object]) -> dict[str, object]:
        with self._lock:
            self._validate_paths("before_commit")
            existing, replay = self._existing(normalized)
            if replay and existing is not None:
                return {"observation_id": existing["observation_id"], "series_key": existing["series_key"], "idempotent_replay": True, "backup_created": False, "backup_cleanup_removed_count": 0}
            self.data_root.mkdir(parents=True, exist_ok=True)
            self._validate_paths("after_data_root_creation")
            self._last_backup_cleanup_removed = 0
            backup = self._backup()
            observation_id = "OBS-B15-" + uuid.uuid4().hex
            created = self._now().isoformat(timespec="seconds").replace("+00:00", "Z")
            identity = normalized["identity"]
            coupon = normalized["user_reported_coupon"]
            shipping = normalized["shipping"]
            source = normalized["source"]
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._schema(connection)
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
                placeholders = ",".join("?" for _ in columns)
                connection.execute(f"INSERT INTO observations({','.join(columns)}) VALUES({placeholders})", values)
                connection.execute("INSERT INTO commit_audit VALUES(?,?,?,?,?)", ("AUD-B15-" + uuid.uuid4().hex, observation_id, "COMMIT", created, normalized["input_sha256"]))
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
            self._validate_paths("after_commit")
            return {"observation_id": observation_id, "series_key": normalized["series_key"], "idempotent_replay": False, "backup_created": backup is not None, "backup_cleanup_removed_count": self._last_backup_cleanup_removed}

    def _rows(self, query: str = "", *, series_key: str | None = None) -> list[sqlite3.Row]:
        if not self.database.is_file():
            return []
        connection = self._connect(readonly=True)
        try:
            self._schema_readonly_check(connection)
            if series_key is not None:
                return connection.execute("SELECT * FROM observations WHERE series_key=? AND is_deleted=0 ORDER BY observed_at_utc,observation_id", (series_key,)).fetchall()
            term = f"%{query.casefold()}%"
            return connection.execute("SELECT * FROM observations WHERE is_deleted=0 AND (lower(title) LIKE ? OR lower(product_id) LIKE ? OR lower(sku_id) LIKE ?) ORDER BY observed_at_utc DESC,observation_id DESC", (term, term, term)).fetchall()
        finally:
            connection.close()

    @staticmethod
    def _current(row: sqlite3.Row) -> dict[str, object]:
        return {
            "series_key": row["series_key"], "title": row["title"],
            "series_identity": {"platform": row["platform"], "product_id": row["product_id"], "sku_id": row["sku_id"], "seller_id": row["seller_id"], "condition": row["item_condition"], "package_signature": row["package_signature"], "currency": row["currency"]},
            "data_classification": "PRIVATE_LOCAL_USER_ENTERED", "source_id": row["observation_id"], "observed_at": row["observed_at_utc"],
            "base_price_twd": row["before_coupon_price_twd"], "before_coupon_price_twd": row["before_coupon_price_twd"],
            "confirmed_coupon_price_twd": None, "possible_coupon_price_twd": row["user_reported_coupon_price_twd"],
            "display_price_twd": row["before_coupon_price_twd"], "display_basis": "USER_ENTERED_BEFORE_COUPON",
            "minimum_purchase_quantity": row["quantity"], "shipping_status": row["shipping_status"], "required_total_twd": row["required_total_twd"],
            "source_permission": {"allowed": True, "state": "PRIVATE_LOCAL_ONLY", "reason": "USER_EXPLICITLY_CONFIRMED_LOCAL_STORAGE"},
            "coupon_evidence": {"status": row["coupon_status"], "eligibility": row["coupon_eligibility"], "evidence_level": row["coupon_evidence_level"], "platform_verified": False},
            "quality_flags": ["PRIVATE_USER_ENTERED", "NOT_PLATFORM_VERIFIED"], "cta_enabled": False, "click_url": None,
        }

    def data_version(self) -> str:
        if not self.database.is_file():
            return '"private-empty"'
        self._validate_paths("before_data_version_hash")
        return '"private-' + _sha256(self.database) + '"'

    def search(self, query: str, *, page: int = 1, limit: int = 20) -> dict[str, object]:
        if page < 1 or limit < 1 or limit > 100 or len(query) > 200:
            raise StoreError("pagination or query outside allowed bounds")
        rows = self._rows(query)
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest.setdefault(row["series_key"], row)
        items = [self._current(row) for row in latest.values()]
        items.sort(key=lambda item: (str(item["title"]).casefold(), str(item["series_key"])))
        start = (page - 1) * limit
        return {"schema_version": WIRE_SCHEMA, "data_classification": "PRIVATE_LOCAL_USER_ENTERED", "items": items[start:start + limit], "page": page, "limit": limit, "total": len(items), "data_version": self.data_version()}

    @staticmethod
    def _daily(points: list[dict[str, object]]) -> list[dict[str, object]]:
        days: dict[str, list[int]] = defaultdict(list)
        for item in points:
            days[str(item["taipei_date"])].append(int(item["price_twd"]))
        return [{"taipei_date": day, "representative_price_twd": int(median_low(values)), "sample_count": len(values)} for day, values in sorted(days.items())]

    def detail(self, series_key: str) -> dict[str, object] | None:
        if len(series_key) != 64 or any(char not in "0123456789abcdef" for char in series_key):
            return None
        rows = self._rows(series_key=series_key)
        if not rows:
            return None
        latest = rows[-1]
        before = [{"observed_at": row["observed_at_utc"], "taipei_date": row["taipei_date"], "price_twd": row["before_coupon_price_twd"], "source_id": row["observation_id"], "series_key": series_key} for row in rows[-MAX_HISTORY:]]
        reported = [{"observed_at": row["observed_at_utc"], "taipei_date": row["taipei_date"], "price_twd": row["user_reported_coupon_price_twd"], "source_id": row["observation_id"], "series_key": series_key, "evidence_level": row["coupon_evidence_level"], "eligibility": row["coupon_eligibility"], "platform_verified": False} for row in rows[-MAX_HISTORY:] if row["user_reported_coupon_price_twd"] is not None]
        confirmed: list[dict[str, object]] = []
        return {
            "schema_version": WIRE_SCHEMA, "data_classification": "PRIVATE_LOCAL_USER_ENTERED", "product": self._current(latest),
            "history": {"before_coupon": before, "confirmed_after_coupon": confirmed, "user_reported_after_coupon": reported},
            "history_quality": {
                "before_coupon": {"raw_sample_count": len(before), "daily_representatives": self._daily(before), "truncated": len(rows) > MAX_HISTORY},
                "confirmed_after_coupon": {"raw_sample_count": 0, "daily_representatives": [], "truncated": False},
                "user_reported_after_coupon": {"raw_sample_count": len(reported), "daily_representatives": self._daily(reported), "truncated": len(reported) >= MAX_HISTORY and len(rows) > MAX_HISTORY},
            },
            "data_version": self.data_version(),
        }

    def observation_count(self) -> int:
        if not self.database.is_file():
            return 0
        connection = self._connect(readonly=True)
        try:
            self._schema_readonly_check(connection)
            return int(connection.execute("SELECT COUNT(*) FROM observations WHERE is_deleted=0").fetchone()[0])
        finally:
            connection.close()
