from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CONFIRMED = "CONFIRMED_APPLICABLE"
ALLOWED_STATUSES = {CONFIRMED, "CLAIM_REQUIRED", "UNVERIFIED", "INELIGIBLE", "EXPIRED", "UNKNOWN", "NONE"}
IDENTITY_FIELDS = ("platform", "product_id", "sku_id", "seller_id", "condition", "package_signature")


class ContractError(ValueError):
    pass


def _time(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContractError(f"{field} must be canonical UTC Z")
    try: result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc: raise ContractError(f"{field} invalid") from exc
    return result.astimezone(timezone.utc)


def _price(value: object, field: str, *, nullable: bool = True) -> int | None:
    if value is None and nullable: return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0: raise ContractError(f"{field} must be non-negative integer or null")
    return value


def _identity(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(IDENTITY_FIELDS): raise ContractError("series_identity fields mismatch")
    if any(not isinstance(value[key], str) or not value[key] for key in IDENTITY_FIELDS): raise ContractError("series_identity incomplete")
    return {key: value[key] for key in IDENTITY_FIELDS}


@dataclass(frozen=True)
class Resolution:
    display_price_twd: int | None
    display_basis: str
    confirmed_coupon_price_twd: int | None
    possible_coupon_price_twd: int | None
    base_price_twd: int | None
    required_total_twd: int | None
    coupon_applied: bool
    reason: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def resolve(payload: dict, *, now: datetime, mode: str = "TEST_ONLY") -> Resolution:
    if payload.get("schema_version") != "CDH-COUPON-PRICE-V4": raise ContractError("schema_version mismatch")
    identity = _identity(payload.get("series_identity"))
    classification = payload.get("data_classification")
    if classification not in {"SYNTHETIC_FIXTURE", "USER_AUTHORIZED_COPY"}: raise ContractError("classification not authorized")
    if classification == "SYNTHETIC_FIXTURE" and mode != "TEST_ONLY": raise ContractError("synthetic fixture forbidden outside TEST_ONLY")
    source_id = payload.get("source_id")
    if not isinstance(source_id, str) or not source_id: raise ContractError("source_id required")
    observed = _time(payload.get("observed_at"), "observed_at")
    if observed > now: raise ContractError("future observation forbidden")
    base = _price(payload.get("base_price_twd"), "base_price_twd")
    possible = _price(payload.get("possible_coupon_price_twd"), "possible_coupon_price_twd")
    coupon = payload.get("coupon")
    if not isinstance(coupon, dict): raise ContractError("coupon object required")
    status = coupon.get("status")
    if status not in ALLOWED_STATUSES: raise ContractError("coupon status invalid")
    quantity = payload.get("quantity", 1)
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1: raise ContractError("quantity invalid")
    scope = coupon.get("discount_scope", "UNIT")
    if scope not in {"UNIT", "ORDER"}: raise ContractError("discount_scope invalid")
    discount = _price(coupon.get("discount_twd"), "coupon.discount_twd")
    included = coupon.get("already_included_in_base")
    if not isinstance(included, bool): raise ContractError("already_included_in_base must be boolean")
    coupon_identity = coupon.get("series_identity", identity)
    identity_match = isinstance(coupon_identity, dict) and all(coupon_identity.get(key) == identity[key] for key in IDENTITY_FIELDS)
    eligible_evidence = all(isinstance(coupon.get(key), str) and coupon.get(key) for key in ("coupon_id", "eligibility_profile", "scope_evidence"))
    active = False
    if status == CONFIRMED:
        valid_from, valid_until = _time(coupon.get("valid_from"), "coupon.valid_from"), _time(coupon.get("valid_until"), "coupon.valid_until")
        active = valid_from <= now <= valid_until
    confirmed = status == CONFIRMED and active and eligible_evidence and identity_match and base is not None and discount is not None
    required_total: int | None = None
    confirmed_price: int | None = None
    reason = "BASE_PRICE"
    applied = False
    if confirmed:
        if included:
            confirmed_price = base
            reason = "COUPON_ALREADY_INCLUDED_NO_SECOND_DISCOUNT"
        elif scope == "UNIT":
            if discount > base: raise ContractError("discount exceeds base; zero must not be fabricated")
            confirmed_price = base - discount; applied = True; reason = "CONFIRMED_UNIT_COUPON"
        else:
            subtotal = base * quantity
            if discount > subtotal or (subtotal - discount) % quantity: raise ContractError("order discount cannot produce exact unit price")
            confirmed_price = (subtotal - discount) // quantity; applied = True; reason = "CONFIRMED_ORDER_COUPON"
    declared_confirmed = _price(payload.get("confirmed_coupon_price_twd"), "confirmed_coupon_price_twd")
    if declared_confirmed != confirmed_price: raise ContractError("declared confirmed coupon price mismatch")
    display = confirmed_price if confirmed_price is not None else base
    basis = "CONFIRMED_COUPON" if confirmed_price is not None else "BASE" if base is not None else "UNKNOWN"
    shipping = payload.get("shipping_status")
    if shipping not in {"FREE", "PAID", "UNKNOWN"}: raise ContractError("shipping_status invalid")
    if display is not None and shipping == "FREE": required_total = display * quantity
    declared_total = _price(payload.get("required_total_twd"), "required_total_twd")
    if declared_total != required_total: raise ContractError("required_total mismatch")
    if payload.get("display_price_twd") != display or payload.get("display_basis") != basis: raise ContractError("declared display mismatch")
    return Resolution(display, basis, confirmed_price, possible, base, required_total, applied, reason)


class CouponHistoryStore:
    """Synthetic/test-only SQLite recorder with separate before/confirmed-after series."""

    def __init__(self, path: Path) -> None:
        self.path = path
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS history(kind TEXT NOT NULL, observed_at TEXT NOT NULL, price_twd INTEGER NOT NULL, identity_json TEXT NOT NULL, coupon_json TEXT, eligibility_profile TEXT, source_id TEXT NOT NULL)")
            connection.commit()
        finally: connection.close()

    def record(self, payload: dict, resolution: Resolution) -> None:
        rows = []
        common = (payload["observed_at"], json.dumps(payload["series_identity"], sort_keys=True), payload["source_id"])
        if resolution.base_price_twd is not None: rows.append(("BEFORE_COUPON", resolution.base_price_twd, None, None))
        if resolution.confirmed_coupon_price_twd is not None:
            rows.append(("CONFIRMED_AFTER_COUPON", resolution.confirmed_coupon_price_twd, json.dumps(payload["coupon"], sort_keys=True), payload["coupon"]["eligibility_profile"]))
        connection = sqlite3.connect(self.path)
        try:
            for kind, price, coupon, eligibility in rows:
                connection.execute("INSERT INTO history VALUES(?,?,?,?,?,?,?)", (kind, common[0], price, common[1], coupon, eligibility, common[2]))
            connection.commit()
        finally: connection.close()

    def read(self, kind: str) -> list[dict]:
        if kind not in {"BEFORE_COUPON", "CONFIRMED_AFTER_COUPON"}: raise ContractError("history kind invalid")
        connection = sqlite3.connect(self.path)
        try:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute("SELECT * FROM history WHERE kind=? ORDER BY observed_at", (kind,))]
        finally: connection.close()


def base_payload() -> dict:
    identity = {"platform": "COUPANG_TW", "product_id": "SYN-P-1", "sku_id": "SYN-SKU-1", "seller_id": "SYN-SELLER-1", "condition": "NEW", "package_signature": "1x100ml"}
    return {
        "schema_version": "CDH-COUPON-PRICE-V4", "series_identity": identity, "data_classification": "SYNTHETIC_FIXTURE",
        "source_id": "SYN-SOURCE-1", "observed_at": "2026-11-05T00:00:00Z", "base_price_twd": 99,
        "coupon": {"coupon_id": "SYN-COUPON-1", "status": CONFIRMED, "discount_twd": 50, "already_included_in_base": False, "eligibility_profile": "SYN-ELIGIBLE-PROFILE", "valid_from": "2026-11-01T00:00:00Z", "valid_until": "2026-11-30T23:59:59Z", "scope_evidence": "SYN-TEST-EVIDENCE", "series_identity": identity.copy(), "discount_scope": "UNIT"},
        "confirmed_coupon_price_twd": 49, "possible_coupon_price_twd": None, "display_price_twd": 49,
        "display_basis": "CONFIRMED_COUPON", "shipping_status": "UNKNOWN", "required_total_twd": None,
        "history": {"before_coupon": [], "confirmed_after_coupon": []},
    }
