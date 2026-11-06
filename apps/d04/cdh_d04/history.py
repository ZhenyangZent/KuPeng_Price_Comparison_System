from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote
from zoneinfo import ZoneInfo


CONTRACT = "CDH-LOCAL-HISTORY-1"
TASK_ID = "CDH-D04-PRICE-HISTORY-001"
CALCULATION_VERSION = "history-v3.0-c01-r04.5-compatible-exploratory-d04-v1"
TIMEZONE_NAME = "Asia/Taipei"
TAIPEI = ZoneInfo(TIMEZONE_NAME)
ALLOWED_SOURCES = frozenset({"USER_ENTERED", "USER_FILE"})
EXPLORATORY_PRICE_BASES = frozenset({"CURRENT_ITEM_PRICE", "DISPLAYED_UNKNOWN"})
REQUIRED_COLUMNS = frozenset(
    {
        "observation_id",
        "submission_id",
        "observed_at_utc",
        "imported_at_utc",
        "source_kind",
        "product_title",
        "product_id",
        "variant_id",
        "seller_id",
        "displayed_price_twd",
        "price_basis",
        "minimum_purchase_quantity",
        "shipping_status",
        "shipping_fee_twd",
        "stock_status",
        "coupon_status",
        "account_eligibility_status",
        "mandatory_fee_status",
        "qualification_state",
        "is_synthetic",
    }
)


class HistoryError(RuntimeError):
    """Fail-closed query or schema error."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise HistoryError(f"{field} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HistoryError(f"{field} is invalid: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HistoryError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _time_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoryError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _median_floor(values: Iterable[int]) -> int | None:
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def _atomic_write(path: Path, data: bytes) -> None:
    if path.exists() and path.is_symlink():
        raise HistoryError(f"refusing symlink output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file() or path.is_symlink():
        raise HistoryError(f"normal SQLite file required: {path}")
    encoded = quote(path.resolve().as_posix(), safe="/:")
    try:
        connection = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True, timeout=2.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=2000")
    except sqlite3.Error as exc:
        raise HistoryError(f"cannot open SQLite read-only: {exc}") from exc
    return connection


def _verify_schema(connection: sqlite3.Connection) -> list[int]:
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "observations" not in tables or "schema_migrations" not in tables:
        raise HistoryError("D01 observations/schema_migrations tables are required")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(observations)").fetchall()}
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        raise HistoryError(f"D01 observations schema is missing columns: {','.join(missing)}")
    migrations = [int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
    if not migrations or migrations[0] != 1:
        raise HistoryError("unsupported or missing D01 migration history")
    return migrations


def _identity(row: sqlite3.Row) -> tuple[dict[str, object], bool, str]:
    value: dict[str, object] = {
        "platform": "TW_COUPANG",
        "product_id": row["product_id"],
        "variant_id": row["variant_id"],
        "seller_id": row["seller_id"],
        "package_signature": None,
        "package_signature_state": "UNAVAILABLE_IN_D01_SCHEMA",
        "minimum_purchase_quantity": row["minimum_purchase_quantity"],
        "price_basis": row["price_basis"],
    }
    required = (
        value["product_id"],
        value["variant_id"],
        value["seller_id"],
        value["minimum_purchase_quantity"],
        value["price_basis"],
    )
    complete = all(item is not None and item != "" for item in required)
    if complete:
        key_payload: object = value
        state = "EXACT_D01_IDENTITY"
    else:
        # A title is display-only. An incomplete row is intentionally isolated by
        # submission id so similar brand/product names can never merge a series.
        key_payload = {"pending_submission_id": row["submission_id"], "known_identity": value}
        state = "NEEDS_IDENTITY_REVIEW"
    return value, complete, _canonical_sha256({"identity_state": state, "identity": key_payload})


class _Series:
    def __init__(self, identity: dict[str, object], identity_complete: bool, series_key: str) -> None:
        self.identity = identity
        self.identity_complete = identity_complete
        self.series_key = series_key
        self.raw_observation_count = 0
        self.hourly_first: dict[datetime, tuple[datetime, int]] = {}
        self.sources: Counter[str] = Counter()
        self.flags: set[str] = set()
        self.latest_title: tuple[datetime, str] | None = None

    def add(self, row: sqlite3.Row, observed: datetime, as_of: datetime) -> None:
        self.raw_observation_count += 1
        self.sources[str(row["source_kind"])] += 1
        title = str(row["product_title"])
        if self.latest_title is None or observed >= self.latest_title[0]:
            self.latest_title = (observed, title)
        if not self.identity_complete:
            self.flags.add("IDENTITY_INCOMPLETE")
        if row["qualification_state"] != "UNVERIFIED":
            self.flags.add("UNEXPECTED_QUALIFICATION_STATE")
        if row["shipping_status"] == "UNKNOWN":
            self.flags.add("SHIPPING_UNKNOWN")
        if row["stock_status"] == "UNKNOWN":
            self.flags.add("STOCK_UNKNOWN")
        if row["coupon_status"] not in {"UNKNOWN", "NOT_APPLICABLE"}:
            self.flags.add("COUPON_CONDITIONAL_UNBOUND")
        if row["account_eligibility_status"] not in {"UNKNOWN", "NOT_APPLICABLE"}:
            self.flags.add("ACCOUNT_ELIGIBILITY_CONDITIONAL_UNBOUND")
        if row["mandatory_fee_status"] == "UNKNOWN":
            self.flags.add("MANDATORY_FEE_UNKNOWN")
        if row["price_basis"] not in EXPLORATORY_PRICE_BASES:
            self.flags.add("PRICE_BASIS_NOT_EXPLORATORY_ITEM_PRICE")
        event_day = as_of.astimezone(TAIPEI).date()
        observed_day = observed.astimezone(TAIPEI).date()
        if observed >= as_of or observed_day >= event_day:
            self.flags.add("CURRENT_OR_FUTURE_SAMPLE_EXCLUDED")
            return
        if row["stock_status"] == "OUT_OF_STOCK":
            self.flags.add("OUT_OF_STOCK_SAMPLE_EXCLUDED")
            return
        price = row["displayed_price_twd"]
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            self.flags.add("INVALID_PRICE_EXCLUDED")
            return
        hour = observed.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        if hour in self.hourly_first:
            self.flags.add("SAME_UTC_HOUR_DEDUPED")
            return
        self.hourly_first[hour] = (observed, price)

    def render(self, as_of: datetime) -> dict[str, object]:
        daily_values: dict[date, list[int]] = defaultdict(list)
        daily_latest: dict[date, datetime] = {}
        for observed, price in self.hourly_first.values():
            day = observed.astimezone(TAIPEI).date()
            daily_values[day].append(price)
            daily_latest[day] = max(daily_latest.get(day, observed), observed)
        daily_medians = {day: _median_floor(values) for day, values in daily_values.items()}
        event_day = as_of.astimezone(TAIPEI).date()

        def window(days: int) -> list[int]:
            start = event_day - timedelta(days=days)
            return [
                int(value)
                for day, value in sorted(daily_medians.items())
                if value is not None and start <= day < event_day
            ]

        w7, w30, w90 = window(7), window(30), window(90)
        eligible_times = [observed for observed, _ in self.hourly_first.values()]
        first = min(eligible_times, default=None)
        last = max(eligible_times, default=None)
        stale = last is None or as_of - last > timedelta(days=7)
        conditional = bool(
            {"COUPON_CONDITIONAL_UNBOUND", "ACCOUNT_ELIGIBILITY_CONDITIONAL_UNBOUND"} & self.flags
        )
        price_basis_allowed = self.identity["price_basis"] in EXPLORATORY_PRICE_BASES
        enough_history = len(w30) >= 7
        comparable = self.identity_complete and enough_history and not stale and price_basis_allowed and not conditional
        if not self.identity_complete:
            comparison_status = "NEEDS_IDENTITY_REVIEW"
        elif conditional:
            comparison_status = "CONDITIONAL_PRICE_UNBOUND"
        elif not price_basis_allowed:
            comparison_status = "UNSUPPORTED_PRICE_BASIS"
        elif not enough_history:
            comparison_status = "INSUFFICIENT_HISTORY"
        elif stale:
            comparison_status = "STALE_HISTORY"
        else:
            comparison_status = "READY_EXPLORATORY_ITEM_PRICE"
        if len(daily_medians) <= 1:
            self.flags.add("FIRST_OBSERVATION_NO_COMPARISON")
        if stale:
            self.flags.add("STALE_HISTORY")
        if len(w7) < 3:
            self.flags.add("M7_LOW_COVERAGE")
        if len(w30) < 7:
            self.flags.add("M30_LOW_COVERAGE")
        if len(w90) < 21:
            self.flags.add("M90_LOW_COVERAGE")
        if any(value == 0 for value in daily_medians.values() if value is not None):
            self.flags.add("ZERO_PRICE_UNVERIFIED_TOTAL")
        all_values = [int(value) for value in daily_medians.values() if value is not None]
        return {
            "series_key": self.series_key,
            "identity": self.identity,
            "identity_state": "EXACT_D01_IDENTITY" if self.identity_complete else "NEEDS_IDENTITY_REVIEW",
            "display_title": None if self.latest_title is None else self.latest_title[1],
            "title_identity_used": False,
            "raw_observation_count": self.raw_observation_count,
            "eligible_hourly_sample_count": len(self.hourly_first),
            "observation_day_count": len(daily_medians),
            "first_observed_at_utc": None if first is None else _time_text(first),
            "last_observed_at_utc": None if last is None else _time_text(last),
            "is_comparable": comparable,
            "comparison_status": comparison_status,
            "statistics_scope": "EXPLORATORY_DISPLAYED_ITEM_PRICE_NOT_CHECKOUT_TOTAL",
            "median_twd": {
                "m7": _median_floor(w7),
                "m30": _median_floor(w30),
                "m90": _median_floor(w90),
            },
            "historical_low_twd": min(all_values) if all_values else None,
            "verified_checkout_low_claim_allowed": False,
            "true_drop_claim_allowed": False,
            "window_day_counts": {"m7": len(w7), "m30": len(w30), "m90": len(w90)},
            "coverage": {
                "m7": round(len(w7) / 7, 6),
                "m30": round(len(w30) / 30, 6),
                "m90": round(len(w90) / 90, 6),
            },
            "source_counts": dict(sorted(self.sources.items())),
            "quality_flags": sorted(self.flags),
        }


class HistoryQuery:
    """Independent D01/D02 history reader that never opens SQLite read-write."""

    def __init__(self, database: Path) -> None:
        self.database = database.resolve()

    def export(self, *, as_of: datetime, generated_at: datetime | None = None) -> dict[str, object]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise HistoryError("as_of must be timezone-aware")
        as_of = as_of.astimezone(timezone.utc)
        generated = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        database_sha256 = _sha256_file(self.database)
        connection = _open_readonly(self.database)
        try:
            migrations = _verify_schema(connection)
            cursor = connection.execute(
                """SELECT observation_id, submission_id, observed_at_utc, imported_at_utc,
                source_kind, product_title, product_id, variant_id, seller_id,
                displayed_price_twd, price_basis, minimum_purchase_quantity,
                shipping_status, shipping_fee_twd, stock_status, coupon_status,
                account_eligibility_status, mandatory_fee_status, qualification_state, is_synthetic
                FROM observations
                WHERE source_kind IN ('USER_ENTERED','USER_FILE') AND is_synthetic=0
                ORDER BY observation_id"""
            )
            series: dict[str, _Series] = {}
            source_rows = 0
            invalid_time_rows = 0
            seen_submissions: set[str] = set()
            duplicate_submission_rows = 0
            while True:
                rows = cursor.fetchmany(512)
                if not rows:
                    break
                for row in rows:
                    source_rows += 1
                    submission_id = str(row["submission_id"])
                    if submission_id in seen_submissions:
                        duplicate_submission_rows += 1
                        continue
                    seen_submissions.add(submission_id)
                    try:
                        observed = _parse_timestamp(row["observed_at_utc"], "observed_at_utc")
                    except HistoryError:
                        invalid_time_rows += 1
                        continue
                    identity, complete, key = _identity(row)
                    target = series.setdefault(key, _Series(identity, complete, key))
                    target.add(row, observed, as_of)
        except sqlite3.Error as exc:
            raise HistoryError(f"read-only history query failed: {exc}") from exc
        finally:
            connection.close()
        rendered = [item.render(as_of) for _, item in sorted(series.items())]
        flag_counts: Counter[str] = Counter()
        for item in rendered:
            flag_counts.update(item["quality_flags"])
        result: dict[str, object] = {
            "contract": CONTRACT,
            "task_id": TASK_ID,
            "calculation_version": CALCULATION_VERSION,
            "timezone": TIMEZONE_NAME,
            "generated_at_utc": _time_text(generated),
            "as_of_utc": _time_text(as_of),
            "source": {
                "kind": "D01_LOCAL_SQLITE_READONLY",
                "database_sha256": database_sha256,
                "schema_migrations": migrations,
                "allowed_source_kinds": sorted(ALLOWED_SOURCES),
                "source_status": "SOURCE_BLOCKED",
            },
            "semantics": {
                "window_type": "COMPLETED_CALENDAR_DAYS_ASIA_TAIPEI",
                "hourly_deduplication": "FIRST_VALID_SAMPLE_PER_UTC_HOUR",
                "daily_aggregation": "INTEGER_MEDIAN_FLOOR",
                "window_aggregation": "MEDIAN_OF_DAILY_MEDIANS_FLOOR",
                "current_day_excluded": True,
                "product_title_is_identity": False,
                "checkout_total_verified": False,
                "free_shipping_inferred": False,
            },
            "quality": {
                "source_row_count": source_rows,
                "exported_series_count": len(rendered),
                "comparable_series_count": sum(1 for item in rendered if item["is_comparable"]),
                "needs_review_series_count": sum(1 for item in rendered if not item["is_comparable"]),
                "invalid_timestamp_row_count": invalid_time_rows,
                "duplicate_submission_row_count": duplicate_submission_rows,
                "flag_counts": dict(sorted(flag_counts.items())),
            },
            "series": rendered,
        }
        result["export_sha256"] = _canonical_sha256(result)
        return result


def export_history(database: Path, *, as_of: datetime, generated_at: datetime | None = None) -> dict[str, object]:
    return HistoryQuery(database).export(as_of=as_of, generated_at=generated_at)


def write_versioned_export(report: dict[str, object], output_dir: Path) -> tuple[Path, str]:
    data = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    stamp = str(report["generated_at_utc"]).replace("-", "").replace(":", "")
    name = f"history_{stamp}_{digest[:12]}.json"
    path = output_dir / name
    if path.exists():
        if _sha256_file(path) != digest:
            raise HistoryError(f"versioned output collision: {path}")
        return path, digest
    _atomic_write(path, data)
    return path, digest


def quality_report_markdown(report: dict[str, object]) -> str:
    quality = report["quality"]
    assert isinstance(quality, dict)
    flags = quality["flag_counts"]
    assert isinstance(flags, dict)
    lines = [
        "# D04 Local History Data Quality",
        "",
        f"CONTRACT: `{report['contract']}`",
        "",
        f"SOURCE_STATUS: `{report['source']['source_status']}`",
        "",
        f"SOURCE_ROWS: `{quality['source_row_count']}`",
        "",
        f"EXPORTED_SERIES: `{quality['exported_series_count']}`",
        "",
        f"COMPARABLE_SERIES: `{quality['comparable_series_count']}`",
        "",
        f"NEEDS_REVIEW_SERIES: `{quality['needs_review_series_count']}`",
        "",
        "使用者自報價格不是平台確認結帳價；本報告不推定免運、首購資格、優惠可用性或真正結帳總成本。",
        "",
        "## Quality flags",
        "",
    ]
    lines.extend(f"- `{name}`: {count}" for name, count in sorted(flags.items()))
    return "\n".join(lines) + "\n"

