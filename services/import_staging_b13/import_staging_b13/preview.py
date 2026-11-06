from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .dependencies import (
    B11_RELEASE_SHA256,
    C09_RELEASE_SHA256,
    DependencyError,
    load_exact_b12,
    safe_file,
    sha256,
)

DTO_SCHEMA = "CDH-B13-DRYRUN-PREVIEW-DTO-1"
FORMULA_PREFIXES = ("=", "+", "-", "@")
SENSITIVE_VALUE = re.compile(
    r"(?:^Bearer\s+\S+|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|^[a-z][a-z0-9+.-]*://[^/@\s:]+:[^/@\s]+@)",
    re.IGNORECASE,
)


class PreviewError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _safe_text(value: object, *, maximum: int = 256) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum or SENSITIVE_VALUE.search(value):
        return None
    return value


def _csv_hazards(path: Path) -> dict[int, dict[str, object]]:
    if path.suffix.casefold() != ".csv":
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise PreviewError("CSV input must be UTF-8") from exc
    reader = csv.DictReader(text.splitlines())
    result: dict[int, dict[str, object]] = {}
    for index, row in enumerate(reader):
        fields = []
        for name, value in row.items():
            if name is None or not isinstance(value, str):
                continue
            stripped = value.lstrip()
            if stripped.startswith(FORMULA_PREFIXES):
                fields.append(name)
        reasons = []
        extra = row.get(None)
        if isinstance(extra, list) and any(value not in (None, "") for value in extra):
            reasons.append("CSV_EXTRA_COLUMN")
        if fields:
            reasons.append("CSV_FORMULA_INJECTION")
        if reasons:
            result[index] = {"formula_fields": sorted(set(fields)), "reasons": sorted(set(reasons))}
    return result


def _field_for_reason(reason: str) -> str:
    mappings = (
        (("CSV_",), "csv"),
        (("IDENTITY_", "PLATFORM_", "SERIES_IDENTITY"), "identity"),
        (("OBSERVED_", "TIMESTAMP_", "CAPTURE_"), "observed_at"),
        (("SOURCE_", "EVIDENCE_", "C09_", "RIGHTS_"), "source"),
        (("BASE_PRICE",), "base_price_twd"),
        (("MINIMUM_PURCHASE", "QUANTITY_"), "minimum_purchase_quantity"),
        (("SHIPPING_",), "shipping"),
        (("COUPON_", "DISCOUNT_", "ALREADY_INCLUDED", "UNIT_DISCOUNT", "ORDER_TOTAL"), "coupon"),
        (("DUPLICATE_", "TOP_LEVEL_", "RECORD_"), "$"),
    )
    for prefixes, field in mappings:
        if reason.startswith(prefixes):
            return field
    return "$"


def _sanitize_record(index: int, record: object, outcome: dict[str, object], csv_hazard: dict[str, object] | None) -> dict[str, object]:
    raw_sha = hashlib.sha256(_canonical(record)).hexdigest()
    reasons = list(outcome.get("reasons", []))
    formula_fields = [] if csv_hazard is None else list(csv_hazard["formula_fields"])
    if csv_hazard is not None:
        reasons.extend(str(reason) for reason in csv_hazard["reasons"])
    reasons = sorted(set(str(reason) for reason in reasons))
    error_reasons = reasons if outcome["status"] in {"INVALID_RECORD", "DENIED_PROVENANCE", "CONFLICT"} else []
    result: dict[str, object] = {
        "index": index,
        "record_id": None,
        "series_key": None,
        "observed_at": None,
        "identity": None,
        "source": None,
        "raw_record_sha256": raw_sha,
        "raw_content_included": False,
        "status": outcome["status"],
        "reasons": reasons,
        "field_errors": [{"field": _field_for_reason(reason), "code": reason} for reason in error_reasons],
        "formula_fields": formula_fields,
        "price_preview": outcome.get("price_preview"),
    }
    if not isinstance(record, dict):
        return result
    result["record_id"] = _safe_text(record.get("record_id"))
    result["series_key"] = _safe_text(record.get("series_key"))
    result["observed_at"] = _safe_text(record.get("observed_at"), maximum=64)
    identity = record.get("identity")
    if isinstance(identity, dict):
        result["identity"] = {
            name: _safe_text(identity.get(name))
            for name in ("platform", "product_id", "sku_id", "seller_id", "condition", "package_signature")
        }
    source = record.get("source")
    if isinstance(source, dict):
        result["source"] = {
            name: _safe_text(source.get(name))
            for name in ("source_candidate_id", "evidence_id", "evidence_scope", "data_classification")
        }
    return result


def _history_candidates(report: dict[str, object]) -> list[dict[str, object]]:
    timelines = report.get("timelines")
    if not isinstance(timelines, dict):
        return []
    candidates = []
    for series_key, observations in sorted(timelines.items()):
        if not isinstance(observations, list) or not observations:
            continue
        first = observations[0]
        identity = first.get("identity") if isinstance(first, dict) else None
        identity_key = hashlib.sha256(_canonical(identity)).hexdigest()
        candidates.append({
            "identity_key": identity_key,
            "series_key": series_key,
            "identity": identity,
            "observation_count": len(observations),
            "observations": observations,
        })
    return candidates


def build_preview(
    input_path: Path,
    *,
    input_root: Path,
    dependency_root: Path,
    b12_release: Path,
    c09_release: Path,
    b11_release: Path,
    as_of: datetime,
    project_root: Path,
    c09_request_bundle: Path | None = None,
) -> dict[str, object]:
    try:
        source = safe_file(input_path, allowed_root=input_root)
        b12_path = safe_file(b12_release, allowed_root=dependency_root)
        c09_path = safe_file(c09_release, allowed_root=dependency_root)
        b11_path = safe_file(b11_release, allowed_root=dependency_root)
    except DependencyError as exc:
        raise PreviewError(str(exc)) from exc
    if sha256(c09_path) != C09_RELEASE_SHA256:
        raise PreviewError("C09 release SHA-256 mismatch")
    b11_before = sha256(b11_path)
    if b11_before != B11_RELEASE_SHA256:
        raise PreviewError("B11 release SHA-256 mismatch")
    try:
        b12, dependency_evidence = load_exact_b12(b12_path, project_root=project_root)
        records, input_sha = b12.load_records(source, allowed_root=input_root, input_format="auto")
    except Exception as exc:
        raise PreviewError(f"B12 preflight failed: {exc}") from exc
    csv_hazards = _csv_hazards(source)
    prepared = []
    for index, record in enumerate(records):
        if index in csv_hazards and isinstance(record, dict):
            record = dict(record)
            record["__b13_csv_hazard__"] = csv_hazards[index]
        prepared.append(record)
    verifier = b12.DefaultDenyVerifier()
    if c09_request_bundle is not None:
        try:
            bundle = safe_file(c09_request_bundle, allowed_root=input_root)
            verifier = b12.load_verified_c09_verifier(
                bundle,
                expected_input_sha256=input_sha,
                c09_release=c09_path,
                project_root=project_root,
            )
        except Exception as exc:
            raise PreviewError(f"C09 verifier binding failed: {exc}") from exc
    try:
        report = b12.dry_run(prepared, input_sha256=input_sha, as_of=as_of, verifier=verifier)
    except Exception as exc:
        raise PreviewError(f"dry-run preview failed: {exc}") from exc
    b11_after = sha256(b11_path)
    if b11_after != b11_before:
        raise PreviewError("B11 release changed during preview")
    outcomes = report["outcomes"]
    sanitized = [
        _sanitize_record(index, record, outcomes[index], csv_hazards.get(index))
        for index, record in enumerate(records)
    ]
    counts = dict(report["counts"])
    return {
        "schema_version": DTO_SCHEMA,
        "mode": "IMMUTABLE_DRY_RUN_PREVIEW",
        "input": {
            "name": source.name,
            "format": source.suffix.casefold().lstrip("."),
            "bytes": source.stat().st_size,
            "sha256": input_sha,
            "record_count": len(records),
            "raw_content_included": False,
        },
        "as_of": as_of.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "summary": {
            **counts,
            "csv_hazard_record_count": len(csv_hazards),
            "formula_injection_count": sum(1 for item in csv_hazards.values() if "CSV_FORMULA_INJECTION" in item["reasons"]),
            "extra_column_record_count": sum(1 for item in csv_hazards.values() if "CSV_EXTRA_COLUMN" in item["reasons"]),
        },
        "records": sanitized,
        "history_candidates": _history_candidates(report),
        "dependencies": {
            **dependency_evidence,
            "c09_release_sha256": C09_RELEASE_SHA256,
            "b11_sha256_before": b11_before,
            "b11_sha256_after": b11_after,
            "b11_byte_identity_gate": "PASS",
        },
        "safety": {
            "database_write_count": 0,
            "b11_write_count": 0,
            "formal_history_write_count": 0,
            "collection_authorized": False,
            "live_source_authorized": False,
            "cta_enabled": False,
            "click_url": None,
        },
    }
