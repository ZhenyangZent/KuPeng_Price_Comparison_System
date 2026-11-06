from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median_low
from typing import Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "CDH-COUPON-PRICE-V4"
AUTHORITY_SCHEMA = "CDH-B10-COUPON-SNAPSHOT-AUTHORITY-1"
AUTHORIZED_USE = "AUTHORIZED_SYNTHETIC_OFFLINE_R06_B_ONLY"
TAIPEI = ZoneInfo("Asia/Taipei")
CONFIRMED = "CONFIRMED_APPLICABLE"
COUPON_STATUSES = {CONFIRMED, "CLAIM_REQUIRED", "UNVERIFIED", "INELIGIBLE", "EXPIRED", "UNKNOWN", "NONE"}
MAX_HISTORY_ITEMS = 500
MAX_HISTORY_SCAN = 5000


class CouponRepositoryError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _parse_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CouponRepositoryError("timestamp must use canonical UTC Z form")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CouponRepositoryError("invalid UTC timestamp") from exc
    if result.utcoffset() != timedelta(0):
        raise CouponRepositoryError("timestamp must be UTC")
    return result.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(path.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except (AttributeError, FileNotFoundError, OSError):
        return path.is_symlink()


@dataclass(frozen=True)
class Metadata:
    snapshot_id: str
    classification: str
    permission_state: str
    expires_at: datetime | None
    revoked_at: datetime | None


class CouponPriceRepository:
    """Reads an isolated coupon snapshot without mutating or inferring missing evidence."""

    def __init__(self, database: Path, *, authority_file: Path, allowed_root: Path, clock: Callable[[], datetime] | None = None) -> None:
        raw_root, raw_db, raw_auth = allowed_root.absolute(), database.absolute(), authority_file.absolute()
        if any(_is_reparse(item) for item in (raw_root, raw_db, raw_auth)):
            raise CouponRepositoryError("links and reparse points are not allowed")
        self.allowed_root, self.database, self.authority_file = raw_root.resolve(), raw_db.resolve(), raw_auth.resolve()
        if not self.allowed_root.is_dir():
            raise CouponRepositoryError("allowed root must be a directory")
        for item in (self.database, self.authority_file):
            if not item.is_relative_to(self.allowed_root) or not item.is_file():
                raise CouponRepositoryError("snapshot files must be below allowed root")
            current=self.allowed_root
            for component in item.relative_to(self.allowed_root).parts:
                current/=component
                if _is_reparse(current): raise CouponRepositoryError("snapshot path must not traverse a link or reparse point")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.database_sha256 = _sha256(self.database)
        self._authority = self._load_authority()
        self._metadata = self._load_metadata()
        self.data_version = f'"{self.database_sha256}:{self._metadata.snapshot_id}"'

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise CouponRepositoryError("clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    def _load_authority(self) -> dict[str, object]:
        try:
            value = json.loads(self.authority_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CouponRepositoryError("invalid authority sidecar") from exc
        expected = {"schema_version", "database_sha256", "data_classification", "contains_private_data", "authorized_use"}
        if not isinstance(value, dict) or set(value) != expected:
            raise CouponRepositoryError("authority fields must match exact schema")
        if value["schema_version"] != AUTHORITY_SCHEMA or value["authorized_use"] != AUTHORIZED_USE:
            raise CouponRepositoryError("authority schema or use mismatch")
        if value["database_sha256"] != self.database_sha256:
            raise CouponRepositoryError("authority database SHA-256 mismatch")
        if value["data_classification"] != "SYNTHETIC_FIXTURE" or value["contains_private_data"] is not False:
            raise CouponRepositoryError("only non-private synthetic R06 fixtures are authorized")
        return value

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(f"file:{quote(self.database.as_posix(), safe='/:')}?mode=ro", uri=True, timeout=2.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=2000")
            return connection
        except sqlite3.Error as exc:
            raise CouponRepositoryError(f"cannot open coupon snapshot read-only: {exc}") from exc

    @staticmethod
    def _verify_schema(connection: sqlite3.Connection) -> None:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"coupon_schema", "coupon_metadata", "coupon_series", "coupon_observations"}.issubset(tables):
            raise CouponRepositoryError("coupon snapshot schema is incomplete")
        version = connection.execute("SELECT version FROM coupon_schema").fetchone()
        if version is None or version[0] != 1:
            raise CouponRepositoryError("unsupported coupon schema")
        check = connection.execute("PRAGMA quick_check").fetchone()
        if check is None or check[0] != "ok":
            raise CouponRepositoryError("SQLite quick_check failed")

    def _load_metadata(self) -> Metadata:
        connection = self._connect()
        try:
            self._verify_schema(connection)
            rows = connection.execute("SELECT * FROM coupon_metadata").fetchall()
            if len(rows) != 1:
                raise CouponRepositoryError("coupon_metadata must have one row")
            row = rows[0]
            if row["schema_version"] != SCHEMA_VERSION or row["data_classification"] != self._authority["data_classification"]:
                raise CouponRepositoryError("metadata contract or classification mismatch")
            mismatch = connection.execute("SELECT COUNT(*) FROM coupon_observations WHERE data_classification<>? OR is_synthetic<>1", (row["data_classification"],)).fetchone()[0]
            series_mismatch = connection.execute("SELECT COUNT(*) FROM coupon_series WHERE data_classification<>?", (row["data_classification"],)).fetchone()[0]
            if mismatch or series_mismatch:
                raise CouponRepositoryError("mixed or non-synthetic observations are refused")
            return Metadata(row["snapshot_id"], row["data_classification"], row["source_permission_state"], _parse_utc(row["expires_at_utc"]), _parse_utc(row["revoked_at_utc"]))
        finally:
            connection.close()

    def _permission(self, now: datetime) -> tuple[bool, str]:
        if self._metadata.revoked_at is not None or self._metadata.permission_state == "REVOKED":
            return False, "SOURCE_PERMISSION_REVOKED"
        if self._metadata.permission_state != "ACTIVE_SYNTHETIC_FIXTURE":
            return False, "SOURCE_PERMISSION_NOT_ACTIVE"
        if self._metadata.expires_at is not None and now >= self._metadata.expires_at:
            return False, "SOURCE_PERMISSION_EXPIRED"
        return True, "SOURCE_PERMISSION_ACTIVE"

    @staticmethod
    def _identity(row: sqlite3.Row) -> dict[str, object]:
        return {"platform": row["platform"], "product_id": row["product_id"], "sku_id": row["sku_id"], "seller_id": row["seller_id"], "condition": row["item_condition"], "package_signature": row["package_signature"]}

    @staticmethod
    def _identity_exact(row: sqlite3.Row) -> bool:
        return row["identity_state"] == "EXACT" and all(row[name] not in (None, "") for name in ("platform", "product_id", "sku_id", "seller_id", "item_condition", "package_signature"))

    @staticmethod
    def _integer_price(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    def _base(self, observation: sqlite3.Row) -> tuple[int | None, list[str]]:
        reasons=[]
        value=observation["base_price_twd"]
        if not self._integer_price(value) or observation["base_price_basis"] != "LISTED_ELIGIBLE":
            reasons.append("BASE_PRICE_UNAVAILABLE")
            return None,reasons
        return int(value),reasons

    def _coupon_evaluation(self, series: sqlite3.Row, observation: sqlite3.Row, *, at: datetime, require_current: bool) -> tuple[int | None, int | None, list[str], int | None]:
        status=observation["coupon_status"]
        reasons=[]
        if status not in COUPON_STATUSES:
            return None,None,["COUPON_STATUS_INVALID"],None
        possible=(observation["stored_possible_coupon_price_twd"] if status in {"CLAIM_REQUIRED","UNVERIFIED","UNKNOWN"} and self._integer_price(observation["stored_possible_coupon_price_twd"]) else None)
        if status != CONFIRMED:
            return None,possible,[f"COUPON_{status}"],None
        required=("coupon_id","eligibility_profile","valid_from_utc","valid_until_utc","scope_evidence","coupon_product_id","coupon_sku_id","coupon_seller_id")
        if any(observation[name] in (None, "", "UNKNOWN") for name in required):
            return None,possible,["COUPON_EVIDENCE_INCOMPLETE"],None
        try:
            valid_from=_parse_utc(observation["valid_from_utc"]); valid_until=_parse_utc(observation["valid_until_utc"])
        except CouponRepositoryError:
            return None,possible,["COUPON_VALIDITY_INVALID"],None
        observed=_parse_utc(observation["observed_at_utc"])
        if valid_from is None or valid_until is None or valid_from > valid_until or observed is None or not (valid_from <= observed <= valid_until):
            return None,possible,["COUPON_NOT_VALID_AT_OBSERVATION"],None
        if require_current and not (valid_from <= at <= valid_until):
            return None,possible,["COUPON_NOT_CURRENTLY_VALID"],None
        if (observation["coupon_product_id"],observation["coupon_sku_id"],observation["coupon_seller_id"]) != (series["product_id"],series["sku_id"],series["seller_id"]):
            return None,possible,["COUPON_IDENTITY_MISMATCH"],None
        base,_=self._base(observation)
        confirmed=observation["stored_confirmed_coupon_price_twd"]
        discount=observation["discount_twd"]
        quantity=series["minimum_purchase_quantity"]
        if base is None or not self._integer_price(confirmed) or not self._integer_price(discount) or not isinstance(quantity,int) or quantity<1:
            return None,possible,["COUPON_PRICE_EVIDENCE_INVALID"],None
        if observation["already_included_in_base"] == 1:
            comparison=observation["pre_coupon_comparison_price_twd"]
            if confirmed != base or not self._integer_price(comparison) or comparison < base or comparison-base != discount or not observation["pre_coupon_comparison_source"]:
                return None,possible,["ALREADY_INCLUDED_EVIDENCE_INVALID"],None
            return int(confirmed),possible,[],int(confirmed)*quantity
        if observation["discount_scope"] == "UNIT":
            if discount > base or confirmed != base-discount:
                return None,possible,["UNIT_DISCOUNT_MISMATCH"],None
            return int(confirmed),possible,[],int(confirmed)*quantity
        if observation["discount_scope"] == "ORDER_TOTAL":
            order_total=base*quantity-discount
            if order_total < 0 or order_total % quantity or confirmed != order_total//quantity:
                return None,possible,["ORDER_DISCOUNT_MISMATCH"],None
            return int(confirmed),possible,[],order_total
        return None,possible,["DISCOUNT_SCOPE_INVALID"],None

    def _current(self, series: sqlite3.Row, observation: sqlite3.Row | None, now: datetime) -> dict[str, object]:
        identity=self._identity(series)
        allowed,permission_reason=self._permission(now)
        reasons=[] if allowed else [permission_reason]
        if not self._identity_exact(series): reasons.append("IDENTITY_NOT_EXACT")
        if observation is None: reasons.append("NO_OBSERVATION")
        base=None; confirmed=None; possible=None; item_spend=None
        before_coupon=None; coupon_reasons=[]
        if observation is not None and not reasons:
            try: observed=_parse_utc(observation["observed_at_utc"])
            except CouponRepositoryError: observed=None
            if observed is None or observed>now or not observation["source_id"]: reasons.append("OBSERVATION_EVIDENCE_INVALID")
        if observation is not None and not reasons:
            base,base_reasons=self._base(observation); reasons.extend(base_reasons)
            confirmed,possible,coupon_reasons,item_spend=self._coupon_evaluation(series,observation,at=now,require_current=True)
            before_coupon=(observation["pre_coupon_comparison_price_twd"] if observation["already_included_in_base"]==1 and self._integer_price(observation["pre_coupon_comparison_price_twd"]) else base)
        if confirmed is not None:
            display,display_basis=confirmed,"CONFIRMED_COUPON"
        elif base is not None:
            display,display_basis=base,"BASE_PRICE"
            item_spend=base*series["minimum_purchase_quantity"]
        else:
            display,display_basis=None,"PRICE_UNAVAILABLE"
        shipping_status=series["shipping_status"]
        required_total=None
        if display is not None and item_spend is not None and shipping_status=="KNOWN" and observation is not None and self._integer_price(observation["shipping_fee_twd"]) and self._integer_price(observation["mandatory_fee_twd"]):
            required_total=item_spend+observation["shipping_fee_twd"]+observation["mandatory_fee_twd"]
        coupon={"coupon_id":observation["coupon_id"] if observation else None,"status":observation["coupon_status"] if observation else "NONE","discount_twd":observation["discount_twd"] if observation else None,"discount_scope":observation["discount_scope"] if observation else "NONE","already_included_in_base":bool(observation["already_included_in_base"]) if observation else False,"eligibility_profile":observation["eligibility_profile"] if observation else None,"valid_from":observation["valid_from_utc"] if observation else None,"valid_until":observation["valid_until_utc"] if observation else None,"scope_evidence":observation["scope_evidence"] if observation else None,"pre_coupon_comparison_source":observation["pre_coupon_comparison_source"] if observation else None,"evaluation_reasons":coupon_reasons}
        return {"series_key":series["series_key"],"title":series["title"],"series_identity":identity,"data_classification":self._metadata.classification,"source_id":observation["source_id"] if observation else None,"observed_at":observation["observed_at_utc"] if observation else None,"base_price_twd":base,"before_coupon_price_twd":before_coupon,"coupon":coupon,"confirmed_coupon_price_twd":confirmed,"possible_coupon_price_twd":possible,"display_price_twd":display,"display_basis":display_basis,"minimum_purchase_quantity":series["minimum_purchase_quantity"],"minimum_item_spend_twd":item_spend,"shipping_status":shipping_status,"required_total_twd":required_total,"source_permission":{"allowed":allowed,"state":self._metadata.permission_state,"reason":permission_reason},"quality_flags":sorted(set(reasons+coupon_reasons))}

    def _latest(self, connection: sqlite3.Connection, key: str, now: datetime) -> sqlite3.Row | None:
        return connection.execute("SELECT * FROM coupon_observations WHERE series_key=? AND observed_at_utc<=? ORDER BY observed_at_utc DESC,observation_id DESC LIMIT 1",(key,_utc_text(now))).fetchone()

    def search(self, query: str, *, page: int=1, limit: int=20) -> dict[str, object]:
        if page<1 or limit<1 or limit>100: raise CouponRepositoryError("pagination outside allowed bounds")
        now=self._now(); connection=self._connect()
        try:
            self._verify_schema(connection); term=f"%{query.strip().casefold()}%"
            total=connection.execute("SELECT COUNT(*) FROM coupon_series WHERE lower(title) LIKE ? OR lower(product_id) LIKE ? OR lower(sku_id) LIKE ?",(term,term,term)).fetchone()[0]
            rows=connection.execute("SELECT * FROM coupon_series WHERE lower(title) LIKE ? OR lower(product_id) LIKE ? OR lower(sku_id) LIKE ? ORDER BY lower(title),series_key LIMIT ? OFFSET ?",(term,term,term,limit,(page-1)*limit)).fetchall()
            return {"schema_version":SCHEMA_VERSION,"data_classification":self._metadata.classification,"items":[self._current(row,self._latest(connection,row["series_key"],now),now) for row in rows],"page":page,"limit":limit,"total":total,"data_version":self.data_version}
        finally: connection.close()

    @staticmethod
    def _daily(history: list[dict[str, object]]) -> list[dict[str, object]]:
        days=defaultdict(list)
        for item in history:
            observed=_parse_utc(str(item["observed_at"])); days[observed.astimezone(TAIPEI).date()].append(int(item["price_twd"]))
        return [{"taipei_date":day.isoformat(),"representative_price_twd":int(median_low(values)),"sample_count":len(values)} for day,values in sorted(days.items())]

    def detail(self, key: str) -> dict[str, object] | None:
        now=self._now(); connection=self._connect()
        try:
            self._verify_schema(connection); series=connection.execute("SELECT * FROM coupon_series WHERE series_key=?",(key,)).fetchone()
            if series is None: return None
            product=self._current(series,self._latest(connection,key,now),now)
            before=[]; after=[]; scanned=0; before_overflow=False; after_overflow=False; scan_cap_hit=False
            allowed=self._permission(now)[0] and self._identity_exact(series)
            if allowed:
                cursor=connection.execute("SELECT * FROM coupon_observations WHERE series_key=? AND observed_at_utc<=? ORDER BY observed_at_utc DESC,observation_id DESC",(key,_utc_text(now)))
                for row in cursor:
                    scanned+=1
                    if scanned>MAX_HISTORY_SCAN:
                        scan_cap_hit=True; break
                    try: observed=_parse_utc(row["observed_at_utc"])
                    except CouponRepositoryError: continue
                    base,_=self._base(row)
                    before_price=row["pre_coupon_comparison_price_twd"] if row["already_included_in_base"]==1 and self._integer_price(row["pre_coupon_comparison_price_twd"]) else base
                    if before_price is not None:
                        if len(before)<MAX_HISTORY_ITEMS: before.append({"observed_at":row["observed_at_utc"],"price_twd":before_price,"source_id":row["source_id"],"comparison_source":row["pre_coupon_comparison_source"] if row["already_included_in_base"]==1 else row["source_id"],"series_key":key})
                        else: before_overflow=True
                    confirmed,_,reasons,_=self._coupon_evaluation(series,row,at=observed,require_current=False)
                    if confirmed is not None and not reasons:
                        if len(after)<MAX_HISTORY_ITEMS: after.append({"observed_at":row["observed_at_utc"],"price_twd":confirmed,"coupon_id":row["coupon_id"],"eligibility_profile":row["eligibility_profile"],"source_id":row["source_id"],"scope_evidence":row["scope_evidence"],"series_key":key})
                        else: after_overflow=True
                    if before_overflow and after_overflow: break
            before.reverse(); after.reverse()
            return {"schema_version":SCHEMA_VERSION,"data_classification":self._metadata.classification,"product":product,"history":{"before_coupon":before,"confirmed_after_coupon":after},"history_quality":{"before_coupon":{"raw_sample_count":len(before),"daily_representatives":self._daily(before),"truncated":before_overflow or scan_cap_hit},"confirmed_after_coupon":{"raw_sample_count":len(after),"daily_representatives":self._daily(after),"truncated":after_overflow or scan_cap_hit}},"data_version":self.data_version}
        finally: connection.close()
