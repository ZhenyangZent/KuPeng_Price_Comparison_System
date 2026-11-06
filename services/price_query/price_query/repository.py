from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo


SCHEMA_VERSION_V1 = "CDH-WEB-CONTRACT-V1"
SCHEMA_VERSION_V2 = "CDH-WEB-CONTRACT-V2"
SCHEMA_VERSION = SCHEMA_VERSION_V2
DATA_SOURCE_STATUS = "USER_RECORDED_ONLY"
SYNTHETIC_SOURCE_STATUS = "SYNTHETIC_FIXTURE_ONLY"
DATA_CLASSIFICATION = "USER_RECORDED"
SYNTHETIC_CLASSIFICATION = "SYNTHETIC_DEMO_ONLY"
TAIPEI = ZoneInfo("Asia/Taipei")
ALLOWED_SOURCE_TYPES = frozenset({"USER_ENTERED", "USER_FILE"})
REQUIRED_COLUMNS = frozenset(
    {
        "observation_id",
        "submission_id",
        "observed_at_utc",
        "source_id",
        "source_kind",
        "product_title",
        "product_id",
        "variant_id",
        "seller_id",
        "displayed_price_twd",
        "price_basis",
        "minimum_purchase_quantity",
        "shipping_status",
        "stock_status",
        "is_synthetic",
    }
)


class RepositoryError(RuntimeError):
    """Fail-closed database, schema, or identity error."""


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise RepositoryError("observed_at_utc must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RepositoryError("observed_at_utc is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RepositoryError("observed_at_utc must include timezone")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


@dataclass(frozen=True, slots=True)
class Observation:
    submission_id: str
    observed_at: datetime
    source_id: str | None
    source_kind: str
    title: str
    product_id: str | None
    variant_id: str | None
    seller_id: str | None
    price_twd: int
    source_price_basis: str
    minimum_purchase_quantity: int | None
    shipping_status: str
    stock_status: str


class _Product:
    def __init__(self, identity: dict[str, object], complete: bool, key: str) -> None:
        self.identity = identity
        self.complete = complete
        self.key = key
        self.rows: list[Observation] = []

    def add(self, row: Observation) -> None:
        self.rows.append(row)

    @property
    def sorted_rows(self) -> list[Observation]:
        return sorted(self.rows, key=lambda item: (item.observed_at, item.submission_id))

    def _window_days(self, as_of: datetime, days: int) -> int:
        event_day = as_of.astimezone(TAIPEI).date()
        start = event_day - timedelta(days=days)
        values = {
            row.observed_at.astimezone(TAIPEI).date()
            for row in self.rows
            if start <= row.observed_at.astimezone(TAIPEI).date() < event_day
        }
        return len(values)

    def matches(self, term: str) -> bool:
        if not term:
            return True
        latest = self.sorted_rows[-1]
        searchable = (
            latest.title,
            self.identity["product_id"],
            self.identity["variant_id"],
            self.identity["seller_id"],
            self.identity["price_basis"],
            self.summary_variant_signature(),
        )
        return term in " ".join(str(value) for value in searchable if value is not None).casefold()

    def summary_variant_signature(self) -> str:
        variant = self.identity["variant_id"]
        minimum = self.identity["minimum_purchase_quantity"]
        return (
            f"variant:{variant}|min_qty:{minimum}"
            if self.complete
            else f"UNRESOLVED:{self.key[2:14]}"
        )

    @staticmethod
    def _coverage_status(sample_days: int, window_days: int) -> str:
        if sample_days == 0:
            return "NONE"
        if sample_days < min(7, window_days):
            return "LOW"
        if sample_days < window_days:
            return "PARTIAL"
        return "COMPLETE"

    def summary(self, as_of: datetime) -> dict[str, object]:
        rows = self.sorted_rows
        latest = rows[-1]
        observed_days = len({row.observed_at.astimezone(TAIPEI).date() for row in rows})
        m7, m30, m90 = (self._window_days(as_of, days) for days in (7, 30, 90))
        flags = {"PRICE_IS_USER_OBSERVED_NOT_CHECKOUT_TOTAL"}
        if not self.complete:
            flags.add("IDENTITY_INCOMPLETE")
        if latest.shipping_status == "UNKNOWN":
            flags.add("SHIPPING_UNKNOWN")
        if latest.stock_status == "UNKNOWN":
            flags.add("STOCK_UNKNOWN")
        if m30 < 7:
            flags.add("M30_LOW_COVERAGE")
        if as_of - latest.observed_at > timedelta(days=7):
            flags.add("STALE_LAST_OBSERVATION")
        variant_signature = self.summary_variant_signature()
        return {
            "id": self.key,
            "title": latest.title,
            "variant_signature": variant_signature,
            "last_observed_price_twd": latest.price_twd,
            "last_observed_at": _utc_text(latest.observed_at),
            "observed_days": observed_days,
            "sample_days_m7": m7,
            "sample_days_m30": m30,
            "sample_days_m90": m90,
            "coverage": {
                "basis": "COMPLETED_CALENDAR_DAYS",
                "timezone": "Asia/Taipei",
                "m7": {"sample_days": m7, "status": self._coverage_status(m7, 7)},
                "m30": {"sample_days": m30, "status": self._coverage_status(m30, 30)},
                "m90": {"sample_days": m90, "status": self._coverage_status(m90, 90)},
            },
            "shipping_status": latest.shipping_status,
            "price_basis": "GENERAL_OBSERVED",
            "source_price_basis": self.identity["price_basis"],
            "identity_state": "EXACT" if self.complete else "INCOMPLETE",
            "quality_flags": sorted(flags),
            "thumbnail": None,
        }

    def detail(self, as_of: datetime) -> dict[str, object]:
        rows = self.sorted_rows
        summary = self.summary(as_of)
        offer = {
            "offer_id": f"o_{self.key[2:]}",
            "seller_id": self.identity["seller_id"],
            "sku_id": self.identity["variant_id"],
            "product_id": self.identity["product_id"],
            "minimum_purchase_quantity": self.identity["minimum_purchase_quantity"],
            "item_condition": "UNKNOWN",
            "item_condition_source": "NOT_RECORDED",
            "price_basis": "GENERAL_OBSERVED",
            "source_price_basis": self.identity["price_basis"],
            "identity_state": "EXACT" if self.complete else "INCOMPLETE",
        }
        history = [
            {
                "observed_at": _utc_text(row.observed_at),
                "price_twd": row.price_twd,
                "source_type": row.source_kind,
                "source_id": row.source_id,
            }
            for row in rows
        ]
        return {
            "product": summary,
            "offers": [offer],
            "history": history,
            "observation_period_min_twd": min(row.price_twd for row in rows),
            "observation_period_label": "觀測期間最低價",
            "affiliate": {
                "state": "UNCONFIGURED",
                "click_url": None,
                "verified_product_match": False,
                "bound_product_id": None,
            },
        }


class ReadonlyPriceRepository:
    """Read a manually prepared SQLite copy without migration or write access."""

    def __init__(
        self,
        database_copy: Path,
        *,
        allowed_root: Path,
        clock: Callable[[], datetime] | None = None,
        data_classification: str = DATA_CLASSIFICATION,
    ) -> None:
        raw_database = database_copy.absolute()
        raw_allowed_root = allowed_root.absolute()
        if _is_reparse(raw_allowed_root):
            raise RepositoryError("allowed fixture root must not be a link or reparse point")
        if _is_reparse(raw_database):
            raise RepositoryError("database copy must not be a link or reparse point")
        self.database = raw_database.resolve()
        self.allowed_root = raw_allowed_root.resolve()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if data_classification not in {DATA_CLASSIFICATION, SYNTHETIC_CLASSIFICATION}:
            raise RepositoryError("unsupported data classification")
        self.data_classification = data_classification
        self.data_source_status = (
            DATA_SOURCE_STATUS
            if data_classification == DATA_CLASSIFICATION
            else SYNTHETIC_SOURCE_STATUS
        )
        if not self.allowed_root.is_dir() or _is_reparse(self.allowed_root):
            raise RepositoryError("allowed fixture root must be a normal directory")
        if not self.database.is_relative_to(self.allowed_root):
            raise RepositoryError("database copy must stay below the allowed fixture root")
        relative_database = raw_database.relative_to(raw_allowed_root)
        current = raw_allowed_root
        for component in relative_database.parts:
            current = current / component
            if _is_reparse(current):
                raise RepositoryError("database path must not traverse a link or reparse point")
        if not self.database.is_file():
            raise RepositoryError("database copy must be a normal file")

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RepositoryError("clock must return a timezone-aware datetime")
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
            raise RepositoryError(f"cannot open database copy read-only: {exc}") from exc

    @staticmethod
    def _verify_schema(connection: sqlite3.Connection) -> None:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "observations" not in tables:
            raise RepositoryError("observations table is required")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(observations)")}
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise RepositoryError(f"observations schema missing: {','.join(missing)}")

    @staticmethod
    def _identity(row: sqlite3.Row) -> tuple[dict[str, object], bool, str]:
        identity: dict[str, object] = {
            "product_id": row["product_id"],
            "variant_id": row["variant_id"],
            "seller_id": row["seller_id"],
            "price_basis": row["price_basis"],
            "minimum_purchase_quantity": row["minimum_purchase_quantity"],
        }
        complete = all(value is not None and value != "" for value in identity.values())
        payload: object = identity if complete else {"submission_id": row["submission_id"], "known": identity}
        return identity, complete, f"p_{_digest({'identity': payload, 'complete': complete})}"

    def _products(self) -> tuple[datetime, list[_Product]]:
        as_of = self._now()
        connection = self._connect()
        products: dict[str, _Product] = {}
        seen_submissions: set[str] = set()
        try:
            self._verify_schema(connection)
            source_filter = (
                "source_kind IN ('USER_ENTERED','USER_FILE') AND is_synthetic=0"
                if self.data_classification == DATA_CLASSIFICATION
                else "source_kind='SYNTHETIC' AND is_synthetic=1"
            )
            cursor = connection.execute(
                f"""SELECT observation_id, submission_id, observed_at_utc, source_id, source_kind,
                product_title, product_id, variant_id, seller_id, displayed_price_twd,
                price_basis, minimum_purchase_quantity, shipping_status, stock_status, is_synthetic
                FROM observations
                WHERE {source_filter}
                ORDER BY observation_id"""
            )
            for row in cursor:
                submission = str(row["submission_id"])
                if submission in seen_submissions:
                    continue
                seen_submissions.add(submission)
                try:
                    observed = _parse_utc(row["observed_at_utc"])
                except RepositoryError:
                    continue
                if observed >= as_of:
                    continue
                price = row["displayed_price_twd"]
                if isinstance(price, bool) or not isinstance(price, int) or price < 0:
                    continue
                identity, complete, key = self._identity(row)
                product = products.setdefault(key, _Product(identity, complete, key))
                product.add(
                    Observation(
                        submission_id=submission,
                        observed_at=observed,
                        source_id=row["source_id"],
                        source_kind=row["source_kind"],
                        title=row["product_title"],
                        product_id=row["product_id"],
                        variant_id=row["variant_id"],
                        seller_id=row["seller_id"],
                        price_twd=price,
                        source_price_basis=row["price_basis"],
                        minimum_purchase_quantity=row["minimum_purchase_quantity"],
                        shipping_status=row["shipping_status"],
                        stock_status=row["stock_status"],
                    )
                )
        except sqlite3.Error as exc:
            raise RepositoryError(f"read-only query failed: {exc}") from exc
        finally:
            connection.close()
        return as_of, [product for _, product in sorted(products.items()) if product.rows]

    def _envelope(self, schema_version: str) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": schema_version,
            "data_source_status": self.data_source_status,
            "data_classification": self.data_classification,
        }
        if schema_version == SCHEMA_VERSION_V2:
            value["contract_compatibility"] = [SCHEMA_VERSION_V1]
        return value

    def search(
        self,
        query: str,
        *,
        page: int,
        limit: int,
        schema_version: str = SCHEMA_VERSION_V2,
    ) -> dict[str, object]:
        as_of, products = self._products()
        term = query.casefold().strip()
        summaries = [product.summary(as_of) for product in products if product.matches(term)]
        summaries.sort(key=lambda item: (str(item["title"]).casefold(), str(item["id"])))
        total = len(summaries)
        start = (page - 1) * limit
        return {
            **self._envelope(schema_version),
            "items": summaries[start : start + limit],
            "page": page,
            "limit": limit,
            "total": total,
        }

    def detail(
        self,
        product_id: str,
        *,
        schema_version: str = SCHEMA_VERSION_V2,
    ) -> dict[str, object] | None:
        as_of, products = self._products()
        for product in products:
            if product.key == product_id:
                return {**self._envelope(schema_version), **product.detail(as_of)}
        return None

    def affiliate(
        self,
        product_id: str,
        *,
        schema_version: str = SCHEMA_VERSION_V2,
    ) -> dict[str, object] | None:
        detail = self.detail(product_id, schema_version=schema_version)
        if detail is None:
            return None
        base = {**self._envelope(schema_version), "product_id": product_id}
        if schema_version == SCHEMA_VERSION_V1:
            return {**base, **detail["affiliate"]}
        return {**base, "affiliate": detail["affiliate"]}
