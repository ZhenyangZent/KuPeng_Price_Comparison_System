from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .provenance import DefaultDenyVerifier, ProvenanceVerifier

RECORD_SCHEMA = "CDH-B12-IMPORT-RECORD-1"
REPORT_SCHEMA = "CDH-B12-DRY-RUN-REPORT-1"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 10_000
TOP_KEYS = {
    "schema_version", "record_id", "series_key", "title", "identity", "observed_at", "source",
    "base_price_twd", "coupon", "minimum_purchase_quantity", "shipping",
}
IDENTITY_KEYS = {"platform", "product_id", "sku_id", "seller_id", "condition", "package_signature"}
SOURCE_KEYS = {"source_candidate_id", "evidence_id", "evidence_scope", "data_classification"}
COUPON_KEYS = {
    "coupon_id", "status", "discount_twd", "discount_scope", "already_included_in_base",
    "eligibility_profile", "valid_from", "valid_until", "target_product_id", "target_sku_id",
    "target_seller_id", "pre_coupon_comparison_price_twd", "pre_coupon_comparison_evidence_id",
}
SHIPPING_KEYS = {"status", "shipping_fee_twd", "mandatory_fee_twd"}
COUPON_STATUSES = {"CONFIRMED_APPLICABLE", "CLAIM_REQUIRED", "UNVERIFIED", "INELIGIBLE", "EXPIRED", "UNKNOWN", "NONE"}
CSV_FIELDS = tuple(
    ["schema_version", "record_id", "series_key", "title"]
    + [f"identity.{name}" for name in ("platform", "product_id", "sku_id", "seller_id", "condition", "package_signature")]
    + ["observed_at"]
    + [f"source.{name}" for name in ("source_candidate_id", "evidence_id", "evidence_scope", "data_classification")]
    + ["base_price_twd"]
    + [f"coupon.{name}" for name in (
        "coupon_id", "status", "discount_twd", "discount_scope", "already_included_in_base",
        "eligibility_profile", "valid_from", "valid_until", "target_product_id", "target_sku_id",
        "target_seller_id", "pre_coupon_comparison_price_twd", "pre_coupon_comparison_evidence_id",
    )]
    + ["minimum_purchase_quantity"]
    + [f"shipping.{name}" for name in ("status", "shipping_fee_twd", "mandatory_fee_twd")]
)
INTEGER_CSV_FIELDS = {
    "base_price_twd", "coupon.discount_twd", "coupon.pre_coupon_comparison_price_twd",
    "minimum_purchase_quantity", "shipping.shipping_fee_twd", "shipping.mandatory_fee_twd",
}


class ImportStagingError(ValueError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(record: dict[str, object]) -> bytes:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def record_sha256(record: dict[str, object]) -> str:
    return _sha256_bytes(_canonical(record))


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return None
    return parsed.astimezone(timezone.utc)


def _integer(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _nonempty(value: object, *, maximum: int = 500) -> bool:
    return isinstance(value, str) and 0 < len(value) <= maximum


def validate_record(record: object, *, as_of: datetime) -> list[str]:
    if not isinstance(record, dict):
        return ["RECORD_NOT_OBJECT"]
    errors: list[str] = []
    if set(record) != TOP_KEYS:
        errors.append("TOP_LEVEL_FIELDS_MISMATCH")
    if record.get("schema_version") != RECORD_SCHEMA:
        errors.append("SCHEMA_VERSION_MISMATCH")
    for name in ("record_id", "series_key", "title"):
        if not _nonempty(record.get(name), maximum=500 if name == "title" else 256):
            errors.append(f"{name.upper()}_INVALID")

    identity = record.get("identity")
    if not isinstance(identity, dict) or set(identity) != IDENTITY_KEYS:
        errors.append("IDENTITY_FIELDS_MISMATCH")
    else:
        if identity.get("platform") != "COUPANG_TW":
            errors.append("PLATFORM_INVALID")
        for name in IDENTITY_KEYS - {"platform"}:
            if not _nonempty(identity.get(name), maximum=256):
                errors.append(f"IDENTITY_{name.upper()}_INVALID")

    observed = _parse_utc(record.get("observed_at"))
    if observed is None:
        errors.append("OBSERVED_AT_INVALID")
    elif observed > as_of:
        errors.append("OBSERVED_AT_FUTURE")

    source = record.get("source")
    if not isinstance(source, dict) or set(source) != SOURCE_KEYS:
        errors.append("SOURCE_FIELDS_MISMATCH")
    else:
        for name in ("source_candidate_id", "evidence_id"):
            if not _nonempty(source.get(name), maximum=256):
                errors.append(f"SOURCE_{name.upper()}_INVALID")
        if source.get("evidence_scope") != "USER_PROVIDED_FILE_IMPORT":
            errors.append("EVIDENCE_SCOPE_INVALID")
        if source.get("data_classification") not in {"SYNTHETIC_FIXTURE", "USER_PROVIDED_OBSERVATION"}:
            errors.append("DATA_CLASSIFICATION_INVALID")

    if not _integer(record.get("base_price_twd")):
        errors.append("BASE_PRICE_INVALID")
    if not _integer(record.get("minimum_purchase_quantity"), minimum=1):
        errors.append("MINIMUM_PURCHASE_QUANTITY_INVALID")

    shipping = record.get("shipping")
    if not isinstance(shipping, dict) or set(shipping) != SHIPPING_KEYS:
        errors.append("SHIPPING_FIELDS_MISMATCH")
    else:
        status = shipping.get("status")
        fee = shipping.get("shipping_fee_twd")
        mandatory = shipping.get("mandatory_fee_twd")
        if status == "KNOWN":
            if not _integer(fee) or not _integer(mandatory):
                errors.append("KNOWN_SHIPPING_FEES_INVALID")
        elif status == "UNKNOWN":
            if fee is not None or mandatory is not None:
                errors.append("UNKNOWN_SHIPPING_FEES_MUST_BE_NULL")
        else:
            errors.append("SHIPPING_STATUS_INVALID")

    coupon = record.get("coupon")
    if not isinstance(coupon, dict) or set(coupon) != COUPON_KEYS:
        errors.append("COUPON_FIELDS_MISMATCH")
        return sorted(set(errors))
    status = coupon.get("status")
    if status not in COUPON_STATUSES:
        errors.append("COUPON_STATUS_INVALID")
    if not isinstance(coupon.get("already_included_in_base"), bool):
        errors.append("ALREADY_INCLUDED_FLAG_INVALID")
    if coupon.get("discount_scope") not in {"UNIT", "ORDER_TOTAL", "NONE", "UNKNOWN"}:
        errors.append("DISCOUNT_SCOPE_INVALID")
    discount = coupon.get("discount_twd")
    if discount is not None and not _integer(discount):
        errors.append("DISCOUNT_INVALID")

    if status == "NONE":
        nullable = COUPON_KEYS - {"status", "discount_scope", "already_included_in_base"}
        if coupon.get("discount_scope") != "NONE" or coupon.get("already_included_in_base") is not False or any(coupon.get(name) is not None for name in nullable):
            errors.append("NONE_COUPON_MUST_BE_EMPTY")
    elif status == "CONFIRMED_APPLICABLE":
        required = (
            "coupon_id", "discount_twd", "eligibility_profile", "valid_from", "valid_until",
            "target_product_id", "target_sku_id", "target_seller_id",
        )
        if any(coupon.get(name) in (None, "") for name in required):
            errors.append("CONFIRMED_COUPON_EVIDENCE_INCOMPLETE")
        valid_from = _parse_utc(coupon.get("valid_from"))
        valid_until = _parse_utc(coupon.get("valid_until"))
        if valid_from is None or valid_until is None or valid_from > valid_until or observed is None or not (valid_from <= observed <= valid_until):
            errors.append("CONFIRMED_COUPON_NOT_VALID_AT_OBSERVATION")
        if isinstance(identity, dict) and (
            coupon.get("target_product_id"), coupon.get("target_sku_id"), coupon.get("target_seller_id")
        ) != (identity.get("product_id"), identity.get("sku_id"), identity.get("seller_id")):
            errors.append("CONFIRMED_COUPON_IDENTITY_MISMATCH")
        if coupon.get("discount_scope") not in {"UNIT", "ORDER_TOTAL"}:
            errors.append("CONFIRMED_DISCOUNT_SCOPE_INVALID")
        base = record.get("base_price_twd")
        quantity = record.get("minimum_purchase_quantity")
        if _integer(base) and _integer(quantity, minimum=1) and _integer(discount):
            if coupon.get("already_included_in_base") is True:
                comparison = coupon.get("pre_coupon_comparison_price_twd")
                evidence = coupon.get("pre_coupon_comparison_evidence_id")
                if not _integer(comparison) or comparison < base or comparison - base != discount or not _nonempty(evidence, maximum=256):
                    errors.append("ALREADY_INCLUDED_COMPARISON_INVALID")
            elif coupon.get("pre_coupon_comparison_price_twd") is not None or coupon.get("pre_coupon_comparison_evidence_id") is not None:
                errors.append("UNEXPECTED_PRE_COUPON_COMPARISON")
            elif coupon.get("discount_scope") == "UNIT" and discount > base:
                errors.append("UNIT_DISCOUNT_EXCEEDS_BASE")
            elif coupon.get("discount_scope") == "ORDER_TOTAL":
                total = base * quantity - discount
                if total < 0 or total % quantity:
                    errors.append("ORDER_TOTAL_DISCOUNT_NOT_UNIT_REPRESENTABLE")
    return sorted(set(errors))


def _price_preview(record: dict[str, object]) -> dict[str, object]:
    base = int(record["base_price_twd"])
    quantity = int(record["minimum_purchase_quantity"])
    coupon = record["coupon"]
    assert isinstance(coupon, dict)
    confirmed: int | None = None
    before = base
    if coupon["status"] == "CONFIRMED_APPLICABLE":
        discount = int(coupon["discount_twd"])
        if coupon["already_included_in_base"]:
            confirmed = base
            before = int(coupon["pre_coupon_comparison_price_twd"])
        elif coupon["discount_scope"] == "UNIT":
            confirmed = base - discount
        else:
            confirmed = (base * quantity - discount) // quantity
    display = confirmed if confirmed is not None else base
    item_spend = display * quantity
    shipping = record["shipping"]
    assert isinstance(shipping, dict)
    required_total = None
    if shipping["status"] == "KNOWN":
        required_total = item_spend + int(shipping["shipping_fee_twd"]) + int(shipping["mandatory_fee_twd"])
    return {
        "base_price_twd": base,
        "before_coupon_price_twd": before,
        "confirmed_coupon_price_twd": confirmed,
        "display_price_twd": display,
        "display_basis": "CONFIRMED_COUPON" if confirmed is not None else "BASE_PRICE",
        "minimum_purchase_quantity": quantity,
        "minimum_item_spend_twd": item_spend,
        "shipping_status": shipping["status"],
        "required_total_twd": required_total,
    }


def _is_reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(path.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except (AttributeError, FileNotFoundError, OSError):
        return path.is_symlink()


def safe_input_path(path: Path, allowed_root: Path) -> Path:
    raw_root = allowed_root.absolute()
    raw_path = path.absolute()
    if _is_reparse(raw_root) or _is_reparse(raw_path):
        raise ImportStagingError("links and reparse points are refused")
    if not raw_path.is_relative_to(raw_root):
        raise ImportStagingError("input must be below allowed_root")
    current = raw_root
    for part in raw_path.relative_to(raw_root).parts:
        current /= part
        if _is_reparse(current):
            raise ImportStagingError("input path must not traverse a link or reparse point")
    root = raw_root.resolve()
    target = raw_path.resolve()
    if not root.is_dir() or not target.is_file() or not target.is_relative_to(root):
        raise ImportStagingError("input must be a regular file below allowed_root")
    current = root
    for part in target.relative_to(root).parts:
        current /= part
        if _is_reparse(current):
            raise ImportStagingError("input path must not traverse a link or reparse point")
    if target.stat().st_size > MAX_INPUT_BYTES:
        raise ImportStagingError("input file exceeds 2 MiB limit")
    return target


def _csv_value(name: str, value: str) -> object:
    if value == "":
        return None
    if name in INTEGER_CSV_FIELDS:
        try:
            return int(value)
        except ValueError:
            return value
    if name == "coupon.already_included_in_base":
        if value.casefold() == "true":
            return True
        if value.casefold() == "false":
            return False
    return value


def _nested_csv(row: dict[str, str]) -> dict[str, object]:
    result: dict[str, object] = {"identity": {}, "source": {}, "coupon": {}, "shipping": {}}
    for name in CSV_FIELDS:
        value = _csv_value(name, row[name])
        if "." in name:
            group, field = name.split(".", 1)
            nested = result[group]
            assert isinstance(nested, dict)
            nested[field] = value
        else:
            result[name] = value
    return result


def load_records(path: Path, *, allowed_root: Path, input_format: str = "auto") -> tuple[list[object], str]:
    target = safe_input_path(path, allowed_root)
    raw = target.read_bytes()
    digest = _sha256_bytes(raw)
    kind = input_format
    if kind == "auto":
        kind = "csv" if target.suffix.casefold() == ".csv" else "json" if target.suffix.casefold() == ".json" else ""
    if kind not in {"csv", "json"}:
        raise ImportStagingError("input format must be csv or json")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ImportStagingError("input must be UTF-8") from exc
    if kind == "json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ImportStagingError("invalid JSON input") from exc
        if not isinstance(value, list):
            raise ImportStagingError("JSON input must be an array")
        records: list[object] = value
    else:
        reader = csv.DictReader(text.splitlines())
        if reader.fieldnames is None or tuple(reader.fieldnames) != CSV_FIELDS:
            raise ImportStagingError("CSV headers must match the exact B12 contract")
        records = [_nested_csv(row) for row in reader]
    if len(records) > MAX_RECORDS:
        raise ImportStagingError("input exceeds 10000 record limit")
    return records, digest


def dry_run(
    records: Iterable[object],
    *,
    input_sha256: str,
    as_of: datetime,
    verifier: ProvenanceVerifier | None = None,
) -> dict[str, object]:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ImportStagingError("as_of must be timezone-aware")
    now = as_of.astimezone(timezone.utc)
    active_verifier = verifier or DefaultDenyVerifier()
    outcomes: list[dict[str, object]] = []
    accepted: list[tuple[dict[str, object], str, dict[str, object]]] = []
    unique_keys: dict[tuple[str, str, str], str] = {}
    record_ids: dict[str, str] = {}
    series_identities: dict[str, bytes] = {}
    for index, raw in enumerate(records):
        errors = validate_record(raw, as_of=now)
        if not isinstance(raw, dict):
            outcomes.append({"index": index, "record_id": None, "record_sha256": None, "status": "INVALID_RECORD", "reasons": errors})
            continue
        digest = record_sha256(raw)
        record_id = raw.get("record_id") if isinstance(raw.get("record_id"), str) else None
        if errors:
            outcomes.append({"index": index, "record_id": record_id, "record_sha256": digest, "status": "INVALID_RECORD", "reasons": errors})
            continue
        source = raw["source"]
        assert isinstance(source, dict)
        key = (str(raw["series_key"]), str(raw["observed_at"]), str(source["evidence_id"]))
        prior_by_id = record_ids.get(str(record_id))
        prior_by_key = unique_keys.get(key)
        if (prior_by_id is not None and prior_by_id != digest) or (prior_by_key is not None and prior_by_key != digest):
            outcomes.append({"index": index, "record_id": record_id, "record_sha256": digest, "status": "CONFLICT", "reasons": ["DUPLICATE_KEY_DIFFERENT_CONTENT"]})
            continue
        if prior_by_id == digest or prior_by_key == digest:
            outcomes.append({"index": index, "record_id": record_id, "record_sha256": digest, "status": "NOOP_DUPLICATE", "reasons": []})
            continue
        identity = raw["identity"]
        assert isinstance(identity, dict)
        identity_bytes = _canonical(identity)
        prior_identity = series_identities.get(str(raw["series_key"]))
        if prior_identity is not None and prior_identity != identity_bytes:
            outcomes.append({"index": index, "record_id": record_id, "record_sha256": digest, "status": "CONFLICT", "reasons": ["SERIES_IDENTITY_MISMATCH"]})
            continue
        provenance = active_verifier.verify(raw, input_sha256=input_sha256, record_sha256=digest)
        if not provenance.allowed:
            outcomes.append({"index": index, "record_id": record_id, "record_sha256": digest, "status": "DENIED_PROVENANCE", "reasons": list(provenance.reasons), "verifier_id": provenance.verifier_id})
            continue
        preview = _price_preview(raw)
        unique_keys[key] = digest
        record_ids[str(record_id)] = digest
        series_identities[str(raw["series_key"])] = identity_bytes
        accepted.append((raw, digest, preview))
        outcomes.append({"index": index, "record_id": record_id, "record_sha256": digest, "status": "ACCEPTED_FOR_STAGING_PREVIEW", "reasons": list(provenance.reasons), "verifier_id": provenance.verifier_id, "price_preview": preview})

    timelines: dict[str, list[dict[str, object]]] = {}
    for record, digest, preview in sorted(accepted, key=lambda item: (str(item[0]["series_key"]), str(item[0]["observed_at"]), str(item[0]["record_id"]))):
        source = record["source"]
        identity = record["identity"]
        assert isinstance(source, dict) and isinstance(identity, dict)
        timelines.setdefault(str(record["series_key"]), []).append({
            "record_id": record["record_id"],
            "record_sha256": digest,
            "observed_at": record["observed_at"],
            "evidence_id": source["evidence_id"],
            "identity": identity,
            "before_coupon_price_twd": preview["before_coupon_price_twd"],
            "confirmed_coupon_price_twd": preview["confirmed_coupon_price_twd"],
        })
    counts = {status: sum(1 for item in outcomes if item["status"] == status) for status in (
        "ACCEPTED_FOR_STAGING_PREVIEW", "NOOP_DUPLICATE", "CONFLICT", "DENIED_PROVENANCE", "INVALID_RECORD",
    )}
    return {
        "schema_version": REPORT_SCHEMA,
        "mode": "IMMUTABLE_DRY_RUN_PREVIEW",
        "input_sha256": input_sha256,
        "as_of": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "record_count": len(outcomes),
        "counts": counts,
        "outcomes": outcomes,
        "timelines": timelines,
        "database_write_count": 0,
        "collection_authorized": False,
    }
