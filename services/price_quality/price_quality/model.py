from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote
from zoneinfo import ZoneInfo


CONTRACT = "CDH-PRICE-QUALITY-READMODEL-1"
AUTH_SCHEMA = "CDH-PRICE-QUALITY-AUTH-1"
SCHEMA_VERSION = 1
TAIPEI = ZoneInfo("Asia/Taipei")
USER_CLASSIFICATION = "USER_AUTHORIZED_COPY"
SYNTHETIC_CLASSIFICATION = "SYNTHETIC_FIXTURE"
EXPECTED_SOURCES = {
    USER_CLASSIFICATION: frozenset({"USER_ENTERED", "USER_FILE"}),
    SYNTHETIC_CLASSIFICATION: frozenset({"SYNTHETIC"}),
}
EXPECTED_AUTHORIZATION = {
    USER_CLASSIFICATION: "USER_AUTHORIZED",
    SYNTHETIC_CLASSIFICATION: "SYNTHETIC_FIXTURE",
}
EXPECTED_SYNTHETIC = {USER_CLASSIFICATION: 0, SYNTHETIC_CLASSIFICATION: 1}
KNOWN_CONDITIONS = frozenset({"NEW", "USED", "REFURBISHED"})
REQUIRED_COLUMNS = frozenset(
    {
        "observation_id",
        "submission_id",
        "observed_at_utc",
        "source_kind",
        "source_authorization",
        "product_title",
        "product_id",
        "seller_id",
        "variant_id",
        "minimum_purchase_quantity",
        "package_signature",
        "item_condition",
        "displayed_price_twd",
        "price_basis",
        "shipping_status",
        "is_synthetic",
    }
)


class QualityError(RuntimeError):
    """Fail-closed authorization, schema, identity, or read error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _normal_child(path: Path, root: Path, label: str) -> Path:
    raw_path = path.absolute()
    raw_root = root.absolute()
    if _is_reparse(raw_root) or not raw_root.is_dir():
        raise QualityError("allowed root must be a normal directory")
    if _is_reparse(raw_path):
        raise QualityError(f"{label} must not be a link or reparse point")
    resolved_root = raw_root.resolve()
    resolved_path = raw_path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise QualityError(f"{label} must stay below the allowed root")
    current = raw_root
    for component in raw_path.relative_to(raw_root).parts:
        current = current / component
        if _is_reparse(current):
            raise QualityError(f"{label} path must not traverse a link or reparse point")
    if not resolved_path.is_file():
        raise QualityError(f"{label} must be a normal file")
    return resolved_path


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise QualityError("observed_at_utc must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QualityError("observed_at_utc is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QualityError("observed_at_utc must include a timezone")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _median_floor(values: Iterable[int]) -> int | None:
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


@dataclass(frozen=True, slots=True)
class CopyAuthorization:
    classification: str
    approved_source_kinds: frozenset[str]
    database_sha256: str

    @classmethod
    def load(cls, path: Path, database: Path, allowed_root: Path) -> "CopyAuthorization":
        authorization_path = _normal_child(path, allowed_root, "authorization descriptor")
        try:
            value = json.loads(authorization_path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError, OSError) as exc:
            raise QualityError("authorization descriptor is invalid JSON") from exc
        required = {
            "schema",
            "copy_kind",
            "database_sha256",
            "data_classification",
            "approved_source_kinds",
            "contains_private_fields",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise QualityError("authorization descriptor fields are incomplete or undeclared")
        if value["schema"] != AUTH_SCHEMA or value["copy_kind"] != "ISOLATED_READONLY_COPY":
            raise QualityError("authorization descriptor schema/copy kind is unsupported")
        classification = value["data_classification"]
        if classification not in EXPECTED_SOURCES:
            raise QualityError("authorization classification is unsupported")
        if value["contains_private_fields"] is not False:
            raise QualityError("copy declares private fields and is refused")
        sources = value["approved_source_kinds"]
        if not isinstance(sources, list) or any(not isinstance(item, str) for item in sources):
            raise QualityError("approved_source_kinds must be a string list")
        approved = frozenset(sources)
        if approved != EXPECTED_SOURCES[classification]:
            raise QualityError("approved source set does not match classification")
        actual_hash = sha256_file(database)
        if value["database_sha256"] != actual_hash:
            raise QualityError("authorization database SHA-256 does not match")
        return cls(classification, approved, actual_hash)


@dataclass(frozen=True, slots=True)
class Observation:
    submission_id: str
    observed_at: datetime
    title: str
    product_id: object
    seller_id: object
    variant_id: object
    minimum_quantity: object
    package_signature: object
    item_condition: object
    price_twd: int
    price_basis: object
    shipping_status: str
    source_kind: str


def _identity(row: sqlite3.Row) -> tuple[dict[str, object], bool, str]:
    identity: dict[str, object] = {
        "product_id": row["product_id"],
        "seller_id": row["seller_id"],
        "variant_id": row["variant_id"],
        "minimum_purchase_quantity": row["minimum_purchase_quantity"],
        "package_signature": row["package_signature"],
        "item_condition": row["item_condition"],
        "price_basis": row["price_basis"],
    }
    text_fields = (
        identity["product_id"],
        identity["seller_id"],
        identity["variant_id"],
        identity["package_signature"],
        identity["price_basis"],
    )
    text_complete = all(isinstance(item, str) and bool(item.strip()) for item in text_fields)
    quantity = identity["minimum_purchase_quantity"]
    condition = identity["item_condition"]
    complete = (
        text_complete
        and isinstance(quantity, int)
        and not isinstance(quantity, bool)
        and quantity > 0
        and condition in KNOWN_CONDITIONS
    )
    key_payload: object = identity if complete else {
        "submission_id": row["submission_id"],
        "known_identity": identity,
    }
    key = "q_" + canonical_sha256({"complete": complete, "identity": key_payload})
    return identity, complete, key


class _Series:
    def __init__(self, identity: dict[str, object], complete: bool, key: str) -> None:
        self.identity = identity
        self.complete = complete
        self.key = key
        self.raw_count = 0
        self.hourly_first: dict[datetime, Observation] = {}
        self.flags: set[str] = set()
        self.source_counts: Counter[str] = Counter()
        self.excluded_current_or_future = 0
        self.invalid_price_count = 0
        self.latest: Observation | None = None

    def add(self, observation: Observation, as_of: datetime) -> None:
        self.raw_count += 1
        self.source_counts[observation.source_kind] += 1
        if not self.complete:
            self.flags.add("IDENTITY_EVIDENCE_INCOMPLETE")
        event_day = as_of.astimezone(TAIPEI).date()
        observed_day = observation.observed_at.astimezone(TAIPEI).date()
        if observation.observed_at >= as_of or observed_day >= event_day:
            self.excluded_current_or_future += 1
            self.flags.add("CURRENT_OR_FUTURE_SAMPLE_EXCLUDED")
            return
        if observation.price_twd < 0:
            self.invalid_price_count += 1
            self.flags.add("INVALID_PRICE_EXCLUDED")
            return
        if self.latest is None or observation.observed_at >= self.latest.observed_at:
            self.latest = observation
        hour = observation.observed_at.replace(minute=0, second=0, microsecond=0)
        if hour in self.hourly_first:
            self.flags.add("SAME_UTC_HOUR_DEDUPED")
            return
        self.hourly_first[hour] = observation

    def render(self, as_of: datetime) -> dict[str, object]:
        values: dict[date, list[int]] = defaultdict(list)
        for observation in self.hourly_first.values():
            values[observation.observed_at.astimezone(TAIPEI).date()].append(observation.price_twd)
        daily = [
            {
                "taipei_date": day.isoformat(),
                "sample_count": len(prices),
                "median_twd": _median_floor(prices),
                "low_twd": min(prices),
            }
            for day, prices in sorted(values.items())
        ]
        event_day = as_of.astimezone(TAIPEI).date()

        def window(days: int) -> dict[str, object]:
            start = event_day - timedelta(days=days)
            rows = [item for item in daily if start <= date.fromisoformat(str(item["taipei_date"])) < event_day]
            medians = [int(item["median_twd"]) for item in rows]
            lows = [int(item["low_twd"]) for item in rows]
            return {
                "valid_day_count": len(rows),
                "coverage_ratio": round(len(rows) / days, 6),
                "median_of_daily_medians_twd": _median_floor(medians),
                "low_of_daily_lows_twd": min(lows) if lows else None,
            }

        eligible = sorted(self.hourly_first.values(), key=lambda item: item.observed_at)
        first = eligible[0].observed_at if eligible else None
        last = eligible[-1].observed_at if eligible else None
        age_days = None if last is None else (as_of - last).total_seconds() / 86400
        if age_days is None:
            freshness = "NO_VALID_OBSERVATION"
        elif age_days <= 2:
            freshness = "FRESH"
        elif age_days <= 7:
            freshness = "AGING"
        else:
            freshness = "STALE"
            self.flags.add("STALE_SOURCE")
        if any(item["median_twd"] == 0 for item in daily):
            self.flags.add("ZERO_PRICE_NOT_FREE_SHIPPING_OR_CHECKOUT_TOTAL")
        if self.latest is not None and self.latest.shipping_status == "UNKNOWN":
            self.flags.add("SHIPPING_UNKNOWN")
        all_lows = [int(item["low_twd"]) for item in daily]
        return {
            "series_key": self.key,
            "identity": self.identity,
            "identity_state": "EXACT_EVIDENCE" if self.complete else "NEEDS_IDENTITY_EVIDENCE",
            "exact_match_claim_allowed": self.complete,
            "display_title": None if self.latest is None else self.latest.title,
            "raw_observation_count": self.raw_count,
            "eligible_hourly_sample_count": len(eligible),
            "valid_day_count": len(daily),
            "first_observed_at_utc": None if first is None else _utc_text(first),
            "last_observed_at_utc": None if last is None else _utc_text(last),
            "source_freshness": freshness,
            "source_age_days": None if age_days is None else round(age_days, 6),
            "shipping_status": None if self.latest is None else self.latest.shipping_status,
            "period_low_twd": min(all_lows) if all_lows else None,
            "period_low_label": "觀測期間低點（非成交價）",
            "windows": {"m7": window(7), "m30": window(30), "m90": window(90)},
            "daily": daily[-90:],
            "source_counts": dict(sorted(self.source_counts.items())),
            "excluded_current_or_future_count": self.excluded_current_or_future,
            "invalid_price_count": self.invalid_price_count,
            "quality_flags": sorted(self.flags),
        }


class QualityReadModel:
    """Strict, authorized-copy-only SQLite quality reader."""

    def __init__(
        self,
        database_copy: Path,
        authorization_descriptor: Path,
        *,
        allowed_root: Path,
        clock: Callable[[], datetime] | None = None,
        fetch_size: int = 512,
    ) -> None:
        if not 1 <= fetch_size <= 4096:
            raise QualityError("fetch_size must be between 1 and 4096")
        self.database = _normal_child(database_copy, allowed_root, "database copy")
        lowered_parts = tuple(part.casefold() for part in self.database.parts)
        if len(lowered_parts) >= 3 and lowered_parts[-3:] == ("data", "d01", "observations.sqlite3"):
            raise QualityError("formal D01 database path is forbidden; use an isolated authorized copy")
        self.authorization = CopyAuthorization.load(
            authorization_descriptor,
            self.database,
            allowed_root,
        )
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.fetch_size = fetch_size

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise QualityError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

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
            raise QualityError(f"cannot open authorized copy read-only: {exc}") from exc

    @staticmethod
    def _verify_schema(connection: sqlite3.Connection) -> None:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or quick_check[0] != "ok":
            raise QualityError("SQLite quick_check failed")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"price_quality_schema", "observations"}.issubset(tables):
            raise QualityError("price_quality_schema and observations tables are required")
        versions = [row[0] for row in connection.execute("SELECT version FROM price_quality_schema")]
        if versions != [SCHEMA_VERSION]:
            raise QualityError("price-quality schema version is incompatible")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(observations)")}
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise QualityError(f"observations schema missing: {','.join(missing)}")

    def _verify_rows_authorized(self, connection: sqlite3.Connection) -> None:
        expected_authorization = EXPECTED_AUTHORIZATION[self.authorization.classification]
        expected_synthetic = EXPECTED_SYNTHETIC[self.authorization.classification]
        rows = connection.execute(
            "SELECT DISTINCT source_kind, source_authorization, is_synthetic FROM observations"
        ).fetchall()
        for row in rows:
            if (
                row["source_kind"] not in self.authorization.approved_source_kinds
                or row["source_authorization"] != expected_authorization
                or row["is_synthetic"] != expected_synthetic
            ):
                raise QualityError("mixed, unauthorized, or classification-inconsistent source rows")

    def analyze(self, *, page: int = 1, limit: int = 100) -> dict[str, object]:
        if page < 1 or not 1 <= limit <= 500:
            raise QualityError("page>=1 and 1<=limit<=500 required")
        as_of = self._now()
        connection = self._connect()
        series: dict[str, _Series] = {}
        seen_submissions: set[str] = set()
        quality: Counter[str] = Counter()
        try:
            self._verify_schema(connection)
            self._verify_rows_authorized(connection)
            cursor = connection.execute(
                """SELECT observation_id, submission_id, observed_at_utc, source_kind,
                source_authorization, product_title, product_id, seller_id, variant_id,
                minimum_purchase_quantity, package_signature, item_condition,
                displayed_price_twd, price_basis, shipping_status, is_synthetic
                FROM observations ORDER BY observation_id"""
            )
            while True:
                rows = cursor.fetchmany(self.fetch_size)
                if not rows:
                    break
                for row in rows:
                    quality["source_row_count"] += 1
                    submission_id = str(row["submission_id"])
                    if submission_id in seen_submissions:
                        quality["duplicate_submission_count"] += 1
                        continue
                    seen_submissions.add(submission_id)
                    try:
                        observed = _parse_utc(row["observed_at_utc"])
                    except QualityError:
                        quality["invalid_timestamp_count"] += 1
                        continue
                    price = row["displayed_price_twd"]
                    if isinstance(price, bool) or not isinstance(price, int):
                        quality["invalid_price_type_count"] += 1
                        continue
                    identity, complete, key = _identity(row)
                    target = series.setdefault(key, _Series(identity, complete, key))
                    target.add(
                        Observation(
                            submission_id=submission_id,
                            observed_at=observed,
                            title=str(row["product_title"]),
                            product_id=row["product_id"],
                            seller_id=row["seller_id"],
                            variant_id=row["variant_id"],
                            minimum_quantity=row["minimum_purchase_quantity"],
                            package_signature=row["package_signature"],
                            item_condition=row["item_condition"],
                            price_twd=price,
                            price_basis=row["price_basis"],
                            shipping_status=str(row["shipping_status"]),
                            source_kind=str(row["source_kind"]),
                        ),
                        as_of,
                    )
        except sqlite3.Error as exc:
            raise QualityError(f"read-only quality query failed: {exc}") from exc
        finally:
            connection.close()
        rendered = [value.render(as_of) for _, value in sorted(series.items())]
        flag_counts: Counter[str] = Counter()
        for item in rendered:
            flag_counts.update(item["quality_flags"])
        quality["series_count"] = len(rendered)
        quality["exact_series_count"] = sum(1 for item in rendered if item["exact_match_claim_allowed"])
        quality["needs_identity_evidence_count"] = sum(
            1 for item in rendered if not item["exact_match_claim_allowed"]
        )
        start = (page - 1) * limit
        result: dict[str, object] = {
            "contract": CONTRACT,
            "schema_version": SCHEMA_VERSION,
            "as_of_utc": _utc_text(as_of),
            "analysis_timezone": "Asia/Taipei",
            "data_classification": self.authorization.classification,
            "source": {
                "database_sha256": self.authorization.database_sha256,
                "copy_kind": "ISOLATED_READONLY_COPY",
                "approved_source_kinds": sorted(self.authorization.approved_source_kinds),
                "private_fields_exported": False,
            },
            "semantics": {
                "today_excluded": True,
                "daily_aggregation": "MEDIAN_FLOOR_AND_MINIMUM_AFTER_FIRST_PER_UTC_HOUR",
                "window_aggregation": "COMPLETED_TAIPEI_CALENDAR_DAYS",
                "missing_days_interpolated": False,
                "transaction_price_claimed": False,
                "free_shipping_inferred_from_zero": False,
            },
            "quality": {**dict(sorted(quality.items())), "flag_counts": dict(sorted(flag_counts.items()))},
            "pagination": {"page": page, "limit": limit, "total": len(rendered)},
            "series": rendered[start : start + limit],
            "b06_v2_compatibility": {
                "status": "READONLY_ADAPTER_REQUIRED_FOR_B08",
                "http_api_modified": False,
                "classification_can_map": True,
                "identity_partition_is_stricter": True,
                "item_condition_unknown_must_remain_unknown": True,
            },
        }
        result["report_sha256"] = canonical_sha256(result)
        return result
