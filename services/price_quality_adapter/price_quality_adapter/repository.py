from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median_low
from threading import RLock
from typing import Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

ADAPTER_CONTRACT = "CDH-PRICE-QUALITY-ADAPTER-V3"
WIRE_CONTRACT = "CDH-WEB-CONTRACT-V2"
B07_CONTRACT = "CDH-PRICE-QUALITY-READMODEL-1"
TAIPEI = ZoneInfo("Asia/Taipei")
ACTIVE_PERMISSIONS = {"ACTIVE_USER_COPY", "ACTIVE_SYNTHETIC_FIXTURE"}
CLASSIFICATIONS = {"USER_AUTHORIZED_COPY", "SYNTHETIC_FIXTURE"}
SAFE_PRICE_BASES = {"CURRENT_ITEM_PRICE", "DISPLAYED_UNKNOWN"}
REQUIRED_TABLES = {"adapter_schema", "snapshot_metadata", "series", "observations"}
MAX_HISTORY_ITEMS = 500
MAX_METRICS_CACHE_ITEMS = 256


class AdapterError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AdapterError("timestamp must use canonical UTC Z form")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AdapterError("invalid UTC timestamp") from exc
    if result.utcoffset() != timedelta(0):
        raise AdapterError("timestamp must be UTC")
    return result.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(path.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except (AttributeError, FileNotFoundError, OSError):
        return path.is_symlink()


@dataclass(frozen=True)
class SnapshotMetadata:
    snapshot_id: str
    data_classification: str
    source_permission_state: str
    generated_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    source_database_sha256: str
    source_report_sha256: str


class PriceQualityRepository:
    """Consumes a SHA-bound local SQLite snapshot without ever opening it writable."""

    def __init__(
        self,
        database: Path,
        *,
        authority_file: Path,
        allowed_root: Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        raw_root = allowed_root.absolute()
        raw_db = database.absolute()
        raw_auth = authority_file.absolute()
        if _is_reparse(raw_root) or _is_reparse(raw_db) or _is_reparse(raw_auth):
            raise AdapterError("links and reparse points are not allowed")
        self.allowed_root = raw_root.resolve()
        self.database = raw_db.resolve()
        self.authority_file = raw_auth.resolve()
        if not self.allowed_root.is_dir():
            raise AdapterError("allowed root must be a directory")
        for candidate in (self.database, self.authority_file):
            if not candidate.is_relative_to(self.allowed_root) or not candidate.is_file():
                raise AdapterError("database and authority must be normal files below allowed root")
            current = self.allowed_root
            for component in candidate.relative_to(self.allowed_root).parts:
                current /= component
                if _is_reparse(current):
                    raise AdapterError("path must not traverse a link or reparse point")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.database_sha256 = _sha256(self.database)
        self._authority = self._load_authority()
        self._metadata = self._load_metadata()
        self.data_version = f'"{self.database_sha256}:{self._metadata.snapshot_id}"'
        self._metrics_cache: OrderedDict[tuple[str, str, str], dict[str, object]] = OrderedDict()
        self._cache_lock = RLock()
        self._cache_hits = 0
        self._cache_misses = 0

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise AdapterError("clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    def _load_authority(self) -> dict[str, object]:
        try:
            value = json.loads(self.authority_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AdapterError("invalid authority sidecar") from exc
        expected = {
            "schema_version",
            "database_sha256",
            "data_classification",
            "contains_private_data",
            "authorized_use",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise AdapterError("authority sidecar fields must match the exact schema")
        if value["schema_version"] != "CDH-B08-SNAPSHOT-AUTHORITY-1":
            raise AdapterError("unsupported authority schema")
        if value["database_sha256"] != self.database_sha256:
            raise AdapterError("authority database SHA-256 mismatch")
        if value["data_classification"] not in CLASSIFICATIONS:
            raise AdapterError("unsupported data classification")
        if value["contains_private_data"] is not False:
            raise AdapterError("private data snapshots are refused")
        if value["authorized_use"] != "OFFLINE_LOCAL_READONLY_B08_ONLY":
            raise AdapterError("authority use mismatch")
        return value

    def _connect(self) -> sqlite3.Connection:
        encoded = quote(self.database.as_posix(), safe="/:")
        try:
            connection = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True, timeout=2.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=2000")
            return connection
        except sqlite3.Error as exc:
            raise AdapterError(f"cannot open snapshot read-only: {exc}") from exc

    @staticmethod
    def _verify_schema(connection: sqlite3.Connection) -> None:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED_TABLES.issubset(tables):
            raise AdapterError("adapter snapshot schema is incomplete")
        row = connection.execute("SELECT version FROM adapter_schema").fetchone()
        if row is None or row[0] != 1:
            raise AdapterError("unsupported adapter schema version")
        check = connection.execute("PRAGMA quick_check").fetchone()
        if check is None or check[0] != "ok":
            raise AdapterError("SQLite quick_check failed")

    def _load_metadata(self) -> SnapshotMetadata:
        connection = self._connect()
        try:
            self._verify_schema(connection)
            rows = connection.execute("SELECT * FROM snapshot_metadata").fetchall()
            if len(rows) != 1:
                raise AdapterError("snapshot_metadata must contain exactly one row")
            row = rows[0]
            if row["b07_contract"] != B07_CONTRACT or row["wire_contract"] != WIRE_CONTRACT:
                raise AdapterError("snapshot contract mismatch")
            classification = row["data_classification"]
            if classification != self._authority["data_classification"]:
                raise AdapterError("authority and snapshot classification mismatch")
            mixed = connection.execute(
                "SELECT COUNT(DISTINCT data_classification) FROM observations"
            ).fetchone()[0]
            mismatch = connection.execute(
                "SELECT COUNT(*) FROM observations WHERE data_classification<>?",
                (classification,),
            ).fetchone()[0]
            if mixed > 1 or mismatch:
                raise AdapterError("mixed or mismatched data classifications are refused")
            return SnapshotMetadata(
                snapshot_id=row["snapshot_id"],
                data_classification=classification,
                source_permission_state=row["source_permission_state"],
                generated_at=_parse_utc(row["generated_at_utc"]),
                expires_at=_parse_utc(row["expires_at_utc"]) if row["expires_at_utc"] else None,
                revoked_at=_parse_utc(row["revoked_at_utc"]) if row["revoked_at_utc"] else None,
                source_database_sha256=row["source_database_sha256"],
                source_report_sha256=row["source_report_sha256"],
            )
        except sqlite3.Error as exc:
            raise AdapterError(f"snapshot validation failed: {exc}") from exc
        finally:
            connection.close()

    def _permission(self, now: datetime) -> tuple[bool, str]:
        state = self._metadata.source_permission_state
        if self._metadata.revoked_at is not None or state == "REVOKED":
            return False, "SOURCE_PERMISSION_REVOKED"
        if state not in ACTIVE_PERMISSIONS:
            return False, "SOURCE_PERMISSION_NOT_ACTIVE"
        expected = (
            "ACTIVE_SYNTHETIC_FIXTURE"
            if self.classification == "SYNTHETIC_FIXTURE"
            else "ACTIVE_USER_COPY"
        )
        if state != expected:
            return False, "SOURCE_PERMISSION_CLASSIFICATION_MISMATCH"
        if self._metadata.expires_at is not None and now >= self._metadata.expires_at:
            return False, "SOURCE_PERMISSION_EXPIRED"
        return True, "SOURCE_PERMISSION_ACTIVE"

    @property
    def classification(self) -> str:
        return self._metadata.data_classification

    def _envelope(self) -> dict[str, object]:
        synthetic = self.classification == "SYNTHETIC_FIXTURE"
        return {
            "schema_version": WIRE_CONTRACT,
            "data_source_status": "SYNTHETIC_FIXTURE_ONLY" if synthetic else "USER_RECORDED_ONLY",
            "data_classification": "SYNTHETIC_DEMO_ONLY" if synthetic else "USER_RECORDED",
            "contract_compatibility": ["CDH-WEB-CONTRACT-V1"],
        }

    @staticmethod
    def _coverage_status(sample_days: int, window: int) -> str:
        if sample_days == 0:
            return "NONE"
        if sample_days < min(7, window):
            return "LOW"
        if sample_days < window:
            return "PARTIAL"
        return "COMPLETE"

    def _series(self, connection: sqlite3.Connection, key: str) -> sqlite3.Row | None:
        return connection.execute("SELECT * FROM series WHERE series_key=?", (key,)).fetchone()

    def _eligibility(self, row: sqlite3.Row, now: datetime) -> tuple[bool, list[str]]:
        allowed, reason = self._permission(now)
        reasons: list[str] = [] if allowed else [reason]
        required = (
            "product_id", "seller_id", "variant_id", "spec_signature", "minimum_purchase_quantity",
            "package_signature", "item_condition", "price_basis",
        )
        if row["identity_state"] != "EXACT" or row["exact_match_claim_allowed"] != 1:
            reasons.append("IDENTITY_NOT_EXACT")
        if any(row[name] is None or row[name] == "" for name in required):
            reasons.append("IDENTITY_DIMENSION_MISSING")
        if row["price_basis"] not in SAFE_PRICE_BASES:
            reasons.append("PRICE_BASIS_CONDITIONAL_OR_UNSUPPORTED")
        if row["data_classification"] != self.classification:
            reasons.append("DATA_CLASSIFICATION_MISMATCH")
        return not reasons, sorted(set(reasons))

    def _daily(self, connection: sqlite3.Connection, key: str, now: datetime) -> tuple[list[dict[str, object]], int]:
        today = now.astimezone(TAIPEI).date()
        expected_synthetic = 1 if self.classification == "SYNTHETIC_FIXTURE" else 0
        allowed_sources = (
            {"SYNTHETIC"}
            if self.classification == "SYNTHETIC_FIXTURE"
            else {"USER_ENTERED", "USER_FILE"}
        )
        cursor = connection.execute(
            "SELECT observed_at_utc,taipei_date,price_twd,source_type,source_id,is_synthetic "
            "FROM observations WHERE series_key=? AND data_classification=? "
            "AND observed_at_utc<? ORDER BY observed_at_utc",
            (key, self.classification, _utc_text(now)),
        )
        hourly: dict[str, tuple[datetime, int]] = {}
        raw_count = 0
        for item in cursor:
            try:
                observed = _parse_utc(item["observed_at_utc"])
                local_date = observed.astimezone(TAIPEI).date()
                stored_date = date.fromisoformat(item["taipei_date"])
            except (AdapterError, ValueError, TypeError):
                continue
            price = item["price_twd"]
            if (
                local_date != stored_date
                or local_date >= today
                or isinstance(price, bool)
                or not isinstance(price, int)
                or price < 0
                or item["is_synthetic"] != expected_synthetic
                or item["source_type"] not in allowed_sources
                or not item["source_id"]
            ):
                continue
            raw_count += 1
            hour = observed.strftime("%Y-%m-%dT%H")
            hourly.setdefault(hour, (observed, price))
        by_day: dict[date, list[int]] = defaultdict(list)
        for observed, price in hourly.values():
            by_day[observed.astimezone(TAIPEI).date()].append(price)
        daily = [
            {"taipei_date": day.isoformat(), "daily_median_twd": int(median_low(values)), "sample_count": len(values)}
            for day, values in sorted(by_day.items())
        ]
        return daily, raw_count

    def _metrics_uncached(self, connection: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> dict[str, object]:
        daily, valid_raw_count = self._daily(connection, row["series_key"], now)
        today = now.astimezone(TAIPEI).date()
        windows: dict[str, dict[str, object]] = {}
        for days in (7, 30, 90):
            start = today - timedelta(days=days)
            count = sum(start <= date.fromisoformat(item["taipei_date"]) < today for item in daily)
            windows[f"m{days}"] = {
                "sample_days": count,
                "missing_days": days - count,
                "coverage_ratio": round(count / days, 6),
                "status": self._coverage_status(count, days),
            }
        latest = daily[-1] if daily else None
        latest_date = date.fromisoformat(latest["taipei_date"]) if latest else None
        freshness_days = (today - latest_date).days if latest_date else None
        eligible, reasons = self._eligibility(row, now)
        prior = daily[:-1]
        period_low = min((item["daily_median_twd"] for item in daily), default=None)
        prior_low = min((item["daily_median_twd"] for item in prior), default=None)
        new_low = bool(
            eligible and latest and prior_low is not None and windows["m30"]["sample_days"] >= 7
            and freshness_days is not None and freshness_days <= 7
            and latest["daily_median_twd"] < prior_low
        )
        if not eligible:
            new_low_reason = reasons[0]
        elif not latest:
            new_low_reason = "NO_COMPLETED_DAY_OBSERVATION"
        elif not prior:
            new_low_reason = "FIRST_OBSERVATION_HAS_NO_PRIOR_BASELINE"
        elif windows["m30"]["sample_days"] < 7:
            new_low_reason = "M30_EVIDENCE_BELOW_7_DAYS"
        elif freshness_days is None or freshness_days > 7:
            new_low_reason = "LATEST_OBSERVATION_STALE"
        elif new_low:
            new_low_reason = "VALID_NEW_PERIOD_LOW"
        else:
            new_low_reason = "LATEST_PRICE_NOT_BELOW_PRIOR_LOW"
        return {
            "daily": daily,
            "valid_raw_observation_count": valid_raw_count,
            "windows": windows,
            "latest_completed_day": latest,
            "freshness_days": freshness_days,
            "period_low_twd": period_low if eligible else None,
            "new_low_valid": new_low,
            "new_low_reason": new_low_reason,
            "eligible": eligible,
            "incompatibility_reasons": reasons,
        }

    def _metrics(self, connection: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> dict[str, object]:
        permission_reason = self._permission(now)[1]
        key = (str(row["series_key"]), now.strftime("%Y-%m-%dT%H:%M"), permission_reason)
        with self._cache_lock:
            cached = self._metrics_cache.get(key)
            if cached is not None:
                self._metrics_cache.move_to_end(key)
                self._cache_hits += 1
                return cached
        computed = self._metrics_uncached(connection, row, now)
        with self._cache_lock:
            existing = self._metrics_cache.get(key)
            if existing is not None:
                self._metrics_cache.move_to_end(key)
                self._cache_hits += 1
                return existing
            self._metrics_cache[key] = computed
            self._cache_misses += 1
            while len(self._metrics_cache) > MAX_METRICS_CACHE_ITEMS:
                self._metrics_cache.popitem(last=False)
        return computed

    def cache_info(self) -> dict[str, int]:
        with self._cache_lock:
            return {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "size": len(self._metrics_cache),
                "max_size": MAX_METRICS_CACHE_ITEMS,
            }

    def _visible_history(
        self,
        connection: sqlite3.Connection,
        key: str,
        now: datetime,
        *,
        limit: int,
    ) -> list[dict[str, object]]:
        if limit < 1 or limit > MAX_HISTORY_ITEMS:
            raise AdapterError(f"history_limit must be between 1 and {MAX_HISTORY_ITEMS}")
        today = now.astimezone(TAIPEI).date()
        expected_synthetic = 1 if self.classification == "SYNTHETIC_FIXTURE" else 0
        cursor = connection.execute(
            "SELECT observed_at_utc,taipei_date,price_twd,source_type,source_id,is_synthetic "
            "FROM observations WHERE series_key=? AND data_classification=? "
            "AND is_synthetic=? AND price_twd IS NOT NULL AND price_twd>=0 "
            "AND observed_at_utc<? AND taipei_date<? ORDER BY observed_at_utc DESC",
            (
                key,
                self.classification,
                expected_synthetic,
                _utc_text(now),
                today.isoformat(),
            ),
        )
        history: list[dict[str, object]] = []
        allowed_sources = (
            {"SYNTHETIC"}
            if self.classification == "SYNTHETIC_FIXTURE"
            else {"USER_ENTERED", "USER_FILE"}
        )
        for item in cursor:
            try:
                observed = _parse_utc(item["observed_at_utc"])
                stored_date = date.fromisoformat(item["taipei_date"])
            except (AdapterError, TypeError, ValueError):
                continue
            price = item["price_twd"]
            if (
                observed >= now
                or observed.astimezone(TAIPEI).date() != stored_date
                or stored_date >= today
                or isinstance(price, bool)
                or not isinstance(price, int)
                or price < 0
                or item["source_type"] not in allowed_sources
                or not item["source_id"]
            ):
                continue
            history.append(
                {
                    "observed_at": item["observed_at_utc"],
                    "price_twd": price,
                    "source_type": item["source_type"],
                    "source_id": item["source_id"],
                }
            )
            if len(history) == limit:
                break
        history.reverse()
        return history

    def _summary(self, connection: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> dict[str, object]:
        metrics = self._metrics(connection, row, now)
        latest = metrics["latest_completed_day"]
        flags = set(json.loads(row["quality_flags_json"]))
        flags.update(metrics["incompatibility_reasons"])
        if row["shipping_status"] == "UNKNOWN":
            flags.add("SHIPPING_UNKNOWN")
        if metrics["windows"]["m30"]["sample_days"] < 7:
            flags.add("M30_LOW_COVERAGE")
        if metrics["freshness_days"] is None or metrics["freshness_days"] > 7:
            flags.add("STALE_OR_MISSING_LAST_OBSERVATION")
        if metrics["eligible"]:
            flags.add("PRICE_IS_OBSERVED_NOT_CHECKOUT_TOTAL")
        observed_at = None
        if latest:
            observed_at = connection.execute(
                "SELECT MAX(observed_at_utc) FROM observations WHERE series_key=? AND taipei_date=?",
                (row["series_key"], latest["taipei_date"]),
            ).fetchone()[0]
        return {
            "id": row["series_key"],
            "title": row["title"],
            "variant_signature": (
                f"variant:{row['variant_id']}|min_qty:{row['minimum_purchase_quantity']}"
                if row["identity_state"] == "EXACT" else f"UNRESOLVED:{row['series_key'][:12]}"
            ),
            "last_observed_price_twd": latest["daily_median_twd"] if latest and metrics["eligible"] else None,
            "last_observed_at": observed_at if latest and metrics["eligible"] else None,
            "observed_days": len(metrics["daily"]),
            "sample_days_m7": metrics["windows"]["m7"]["sample_days"],
            "sample_days_m30": metrics["windows"]["m30"]["sample_days"],
            "sample_days_m90": metrics["windows"]["m90"]["sample_days"],
            "coverage": {"basis": "COMPLETED_CALENDAR_DAYS", "timezone": "Asia/Taipei", **metrics["windows"]},
            "shipping_status": row["shipping_status"],
            "price_basis": "GENERAL_OBSERVED" if metrics["eligible"] else "UNAVAILABLE",
            "source_price_basis": row["price_basis"],
            "identity_state": row["identity_state"],
            "quality_flags": sorted(flags),
            "thumbnail": None,
        }

    def search(self, query: str, *, page: int, limit: int) -> dict[str, object]:
        if page < 1 or limit < 1 or limit > 100:
            raise AdapterError("pagination outside allowed bounds")
        now = self._now()
        connection = self._connect()
        try:
            self._verify_schema(connection)
            term = f"%{query.strip().casefold()}%"
            total = connection.execute(
                "SELECT COUNT(*) FROM series WHERE lower(title) LIKE ? OR lower(product_id) LIKE ?",
                (term, term),
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM series WHERE lower(title) LIKE ? OR lower(product_id) LIKE ? "
                "ORDER BY lower(title),series_key LIMIT ? OFFSET ?",
                (term, term, limit, (page - 1) * limit),
            ).fetchall()
            return {**self._envelope(), "items": [self._summary(connection, row, now) for row in rows], "page": page, "limit": limit, "total": total}
        finally:
            connection.close()

    def detail(self, key: str, *, history_limit: int = MAX_HISTORY_ITEMS) -> dict[str, object] | None:
        now = self._now()
        connection = self._connect()
        try:
            self._verify_schema(connection)
            row = self._series(connection, key)
            if row is None:
                return None
            metrics = self._metrics(connection, row, now)
            summary = self._summary(connection, row, now)
            history: list[dict[str, object]] = []
            if metrics["eligible"]:
                history = self._visible_history(connection, key, now, limit=history_limit)
            offer = {
                "offer_id": f"o_{key}", "seller_id": row["seller_id"], "sku_id": row["variant_id"],
                "product_id": row["product_id"], "minimum_purchase_quantity": row["minimum_purchase_quantity"],
                "item_condition": "UNKNOWN", "item_condition_source": "NOT_RECORDED",
                "price_basis": "GENERAL_OBSERVED" if metrics["eligible"] else "UNAVAILABLE",
                "source_price_basis": row["price_basis"], "identity_state": row["identity_state"],
            }
            return {
                **self._envelope(), "product": summary, "offers": [offer], "history": history,
                "observation_period_min_twd": min(
                    (item["price_twd"] for item in history), default=None
                ),
                "observation_period_label": "觀測期間最低價",
                "affiliate": {"state": "UNCONFIGURED", "click_url": None, "verified_product_match": False, "bound_product_id": None},
            }
        finally:
            connection.close()

    def affiliate(self, key: str) -> dict[str, object] | None:
        connection = self._connect()
        try:
            if self._series(connection, key) is None:
                return None
        finally:
            connection.close()
        return {
            **self._envelope(), "product_id": key,
            "affiliate": {"state": "UNCONFIGURED", "click_url": None, "verified_product_match": False, "bound_product_id": None},
        }

    def quality(self, key: str) -> dict[str, object] | None:
        now = self._now()
        connection = self._connect()
        try:
            self._verify_schema(connection)
            row = self._series(connection, key)
            if row is None:
                return None
            metrics = self._metrics(connection, row, now)
            allowed, permission_reason = self._permission(now)
            total = connection.execute("SELECT COUNT(*) FROM observations WHERE series_key=?", (key,)).fetchone()[0]
            return {
                "schema_version": ADAPTER_CONTRACT,
                "wire_contract": WIRE_CONTRACT,
                "source_readmodel_contract": B07_CONTRACT,
                "series_key": key,
                "identity": {
                    "product_id": row["product_id"], "seller_id": row["seller_id"], "variant_id": row["variant_id"],
                    "spec_signature": row["spec_signature"],
                    "minimum_purchase_quantity": row["minimum_purchase_quantity"], "package_signature": row["package_signature"],
                    "item_condition": row["item_condition"], "price_basis": row["price_basis"], "state": row["identity_state"],
                },
                "coverage": {"basis": "COMPLETED_CALENDAR_DAYS", "timezone": "Asia/Taipei", **metrics["windows"]},
                "source_permission": {"allowed": allowed, "state": self._metadata.source_permission_state, "reason": permission_reason},
                "source_freshness": {"latest_completed_day": metrics["latest_completed_day"], "freshness_days": metrics["freshness_days"]},
                "period_low_twd": metrics["period_low_twd"],
                "period_low_label": "觀測期間最低價",
                "new_low_valid": metrics["new_low_valid"],
                "new_low_reason": metrics["new_low_reason"],
                "raw_observation_count": total,
                "valid_observation_count": metrics["valid_raw_observation_count"],
                "daily_sample_count": len(metrics["daily"]),
                "history_page_limit": 500,
                "history_truncated": total > 500,
                "data_version": self.data_version,
                "incompatibility_reasons": metrics["incompatibility_reasons"],
            }
        finally:
            connection.close()
