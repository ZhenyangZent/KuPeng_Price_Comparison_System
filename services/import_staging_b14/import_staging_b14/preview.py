from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .dependencies import (
    B11_RELEASE_SHA256,
    B12_RELEASE_SHA256,
    C09_RELEASE_SHA256,
    DependencyError,
    load_exact_b13,
    safe_file,
    sha256,
)


DTO_SCHEMA = "CDH-B14-STRICT-DRYRUN-PREVIEW-DTO-1"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 10_000
URL_VALUE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


class _DuplicateKey(ValueError):
    pass


class _InvalidConstant(ValueError):
    pass


class StrictIngressError(RuntimeError):
    def __init__(self, code: str, *, input_sha256: str | None = None) -> None:
        self.code = code
        self.input_sha256 = input_sha256
        super().__init__(code)


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise _InvalidConstant("JSON_NONSTANDARD_NUMBER")


def _strict_json_value(source: Path) -> tuple[object, str]:
    size = source.stat().st_size
    digest = sha256(source)
    if size > MAX_INPUT_BYTES:
        raise StrictIngressError("INPUT_SIZE_LIMIT_EXCEEDED", input_sha256=digest)
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise StrictIngressError("INPUT_CHANGED_DURING_READ", input_sha256=digest)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise StrictIngressError("INPUT_NOT_UTF8", input_sha256=digest) from exc
    try:
        value = json.loads(text, object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
    except _DuplicateKey as exc:
        raise StrictIngressError("JSON_DUPLICATE_KEY", input_sha256=digest) from exc
    except (_InvalidConstant, json.JSONDecodeError, RecursionError) as exc:
        raise StrictIngressError("JSON_INVALID", input_sha256=digest) from exc
    return value, digest


def strict_json_records(source: Path) -> tuple[list[object], str]:
    value, digest = _strict_json_value(source)
    if not isinstance(value, list):
        raise StrictIngressError("JSON_TOP_LEVEL_NOT_ARRAY", input_sha256=digest)
    if len(value) > MAX_RECORDS:
        raise StrictIngressError("RECORD_LIMIT_EXCEEDED", input_sha256=digest)
    return value, digest


def _redact_url_metadata(records: list[dict[str, object]]) -> int:
    count = 0
    for item in records:
        source = item.get("source")
        if not isinstance(source, dict):
            continue
        for name, value in list(source.items()):
            if isinstance(value, str) and URL_VALUE.match(value):
                source[name] = None
                count += 1
    return count


def build_preview(
    input_path: Path,
    *,
    input_root: Path,
    dependency_root: Path,
    b13_release: Path,
    b12_release: Path,
    c09_release: Path,
    b11_release: Path,
    as_of: datetime,
    project_root: Path,
    c09_request_bundle: Path | None = None,
) -> dict[str, object]:
    try:
        source = safe_file(input_path, allowed_root=input_root)
        b13_path = safe_file(b13_release, allowed_root=dependency_root)
        b13_preview, b13_dependencies, b13_evidence = load_exact_b13(b13_path, project_root=project_root)
    except DependencyError as exc:
        raise StrictIngressError("B13_DEPENDENCY_REJECTED") from exc

    kind = "csv" if source.suffix.casefold() == ".csv" else "json" if source.suffix.casefold() == ".json" else ""
    if not kind:
        raise StrictIngressError("INPUT_FORMAT_UNSUPPORTED")
    records: list[object] | None = None
    input_sha: str | None = None
    if kind == "json":
        records, input_sha = strict_json_records(source)

    try:
        b12_path = safe_file(b12_release, allowed_root=dependency_root)
        c09_path = safe_file(c09_release, allowed_root=dependency_root)
        b11_path = safe_file(b11_release, allowed_root=dependency_root)
    except DependencyError as exc:
        raise StrictIngressError("PINNED_DEPENDENCY_PATH_REJECTED", input_sha256=input_sha) from exc
    if sha256(b12_path) != B12_RELEASE_SHA256:
        raise StrictIngressError("B12_RELEASE_HASH_MISMATCH", input_sha256=input_sha)
    if sha256(c09_path) != C09_RELEASE_SHA256:
        raise StrictIngressError("C09_RELEASE_HASH_MISMATCH", input_sha256=input_sha)
    b11_before = sha256(b11_path)
    if b11_before != B11_RELEASE_SHA256:
        raise StrictIngressError("B11_RELEASE_HASH_MISMATCH", input_sha256=input_sha)

    try:
        b12, dependency_evidence = b13_dependencies.load_exact_b12(b12_path, project_root=project_root)
        if kind == "csv":
            records, input_sha = b12.load_records(source, allowed_root=input_root, input_format="csv")
    except Exception as exc:
        raise StrictIngressError("B12_PREFLIGHT_REJECTED", input_sha256=input_sha) from exc
    assert records is not None and input_sha is not None

    csv_hazards = b13_preview._csv_hazards(source)
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
            try:
                bundle_value, _bundle_sha = _strict_json_value(bundle)
            except StrictIngressError as exc:
                code = "C09_BUNDLE_JSON_DUPLICATE_KEY" if exc.code == "JSON_DUPLICATE_KEY" else "C09_BUNDLE_JSON_REJECTED"
                raise StrictIngressError(code, input_sha256=input_sha) from exc
            if not isinstance(bundle_value, dict):
                raise StrictIngressError("C09_BUNDLE_JSON_REJECTED", input_sha256=input_sha)
            verifier = b12.load_verified_c09_verifier(
                bundle,
                expected_input_sha256=input_sha,
                c09_release=c09_path,
                project_root=project_root,
            )
        except StrictIngressError:
            raise
        except Exception as exc:
            raise StrictIngressError("C09_VERIFIER_BINDING_REJECTED", input_sha256=input_sha) from exc
    try:
        report = b12.dry_run(prepared, input_sha256=input_sha, as_of=as_of, verifier=verifier)
    except Exception as exc:
        raise StrictIngressError("DRY_RUN_REJECTED", input_sha256=input_sha) from exc
    b11_after = sha256(b11_path)
    if b11_after != b11_before:
        raise StrictIngressError("B11_CHANGED_DURING_PREVIEW", input_sha256=input_sha)

    outcomes = report["outcomes"]
    sanitized = [
        b13_preview._sanitize_record(index, record, outcomes[index], csv_hazards.get(index))
        for index, record in enumerate(records)
    ]
    redacted_urls = _redact_url_metadata(sanitized)
    counts = dict(report["counts"])
    return {
        "schema_version": DTO_SCHEMA,
        "mode": "IMMUTABLE_STRICT_DRY_RUN_PREVIEW",
        "input": {
            "name": source.name,
            "format": kind,
            "bytes": source.stat().st_size,
            "sha256": input_sha,
            "record_count": len(records),
            "raw_content_included": False,
            "strict_json_duplicate_gate": "PASS" if kind == "json" else "NOT_APPLICABLE_CSV",
        },
        "as_of": as_of.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "summary": {
            **counts,
            "csv_hazard_record_count": len(csv_hazards),
            "formula_injection_count": sum(1 for item in csv_hazards.values() if "CSV_FORMULA_INJECTION" in item["reasons"]),
            "extra_column_record_count": sum(1 for item in csv_hazards.values() if "CSV_EXTRA_COLUMN" in item["reasons"]),
            "redacted_url_metadata_count": redacted_urls,
        },
        "records": sanitized,
        "history_candidates": b13_preview._history_candidates(report),
        "dependencies": {
            **b13_evidence,
            **dependency_evidence,
            "c09_release_sha256": C09_RELEASE_SHA256,
            "b11_sha256_before": b11_before,
            "b11_sha256_after": b11_after,
            "b11_byte_identity_gate": "PASS",
        },
        "ingress_policy": {
            "duplicate_json_keys_allowed": False,
            "key_comparison": "CASE_SENSITIVE_DECODED_UNICODE",
            "duplicate_detection_precedes_semantic_and_provenance_validation": True,
            "error_echoes_duplicate_key_or_value": False,
        },
        "safety": {
            "database_write_count": 0,
            "b11_write_count": 0,
            "formal_history_write_count": 0,
            "external_request_count": 0,
            "collection_authorized": False,
            "live_source_authorized": False,
            "cta_enabled": False,
            "click_url": None,
        },
    }
