from __future__ import annotations

import json
import secrets
import sqlite3
from http import HTTPStatus
from typing import Callable
from urllib.parse import unquote

from . import dependencies as _dependencies  # noqa: F401
from private_observation_b15.api import API_SCHEMA as B15_API_SCHEMA
from private_observation_b15.api import PrivateObservationApp
from private_observation_b15.store import StoreConflict, StoreError

from .parser import MAX_ENVELOPE_BYTES, BatchValidationError, parse_preview_request, strict_json
from .pending import PendingBatches
from .store import BatchObservationStore


API_SCHEMA = "CDH-B16-PRIVATE-BATCH-API-1"
CONFIRM_SCHEMA = "CDH-B16-BATCH-CONFIRM-REQUEST-1"
MAX_CONFIRM_BYTES = 16 * 1024


class BatchImportApp:
    def __init__(self, store: BatchObservationStore, *, baselines: dict[str, str], clock, allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost"), allowed_origins: tuple[str, ...] = (), csrf_token: str | None = None, pending: PendingBatches | None = None) -> None:
        self.store = store
        self.clock = clock
        self.pending = pending or PendingBatches()
        self.base = PrivateObservationApp(
            store,
            baselines=baselines,
            clock=clock,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
            csrf_token=csrf_token,
        )

    @property
    def csrf_token(self) -> str:
        return self.base.csrf_token

    def _json(self, start_response: Callable, status: int, payload: object, *, origin: str | None = None):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            *self.base._security_headers(),
        ]
        if origin is not None:
            headers.extend((("Access-Control-Allow-Origin", origin), ("Vary", "Origin")))
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [body]

    def _error(self, start_response: Callable, status: int, code: str, *, origin: str | None = None, input_sha256: str | None = None, errors: list[dict[str, object]] | None = None):
        payload: dict[str, object] = {
            "schema_version": API_SCHEMA,
            "error": {"code": code, "input_sha256": input_sha256, "raw_content_included": False},
        }
        if errors is not None:
            payload["row_errors"] = errors
        return self._json(start_response, status, payload, origin=origin)

    @staticmethod
    def _read_body(environ: dict[str, object], maximum: int) -> bytes:
        content_type = str(environ.get("CONTENT_TYPE", "")).split(";", 1)[0].strip().casefold()
        if content_type != "application/json":
            raise BatchValidationError("CONTENT_TYPE_NOT_JSON")
        try:
            length = int(str(environ.get("CONTENT_LENGTH", "")))
        except ValueError as exc:
            raise BatchValidationError("CONTENT_LENGTH_INVALID") from exc
        if length < 0 or length > maximum:
            raise BatchValidationError("REQUEST_BODY_TOO_LARGE")
        raw = environ["wsgi.input"].read(length)
        if len(raw) != length:
            raise BatchValidationError("REQUEST_BODY_TRUNCATED")
        return raw

    @staticmethod
    def _summary(row_number: int, normalized: dict[str, object], action: str) -> dict[str, object]:
        coupon = normalized["user_reported_coupon"]
        return {
            "row_number": row_number,
            "action": action,
            "submission_id": normalized["submission_id"],
            "title": normalized["title"],
            "series_key": normalized["series_key"],
            "observed_at": normalized["observed_at"],
            "taipei_date": normalized["taipei_date"],
            "before_coupon_price_twd": normalized["before_coupon_price_twd"],
            "user_reported_coupon_price_twd": coupon["price_twd"],
            "confirmed_after_coupon_price_twd": None,
            "coupon_status": coupon["status"],
            "coupon_evidence_level": coupon["evidence_level"],
            "source_class": normalized["source"]["source_class"],
            "visibility": normalized["source"]["visibility"],
            "platform_verified": False,
        }

    def _preview(self, environ: dict[str, object], start_response: Callable, origin: str | None):
        parsed = parse_preview_request(self._read_body(environ, MAX_ENVELOPE_BYTES), now=self.clock())
        errors = [
            {key: value for key, value in row.items() if key in {"row_number", "error", "input_sha256"}}
            for row in parsed.rows
            if "error" in row
        ]
        unique: list[dict[str, object]] = []
        preview_rows: list[dict[str, object]] = []
        by_submission: dict[str, dict[str, object]] = {}
        fingerprints: set[str] = set()
        duplicate_input_count = 0
        for row in parsed.rows:
            normalized = row.get("normalized")
            if not isinstance(normalized, dict):
                continue
            submission_id = str(normalized["submission_id"])
            fingerprint = str(normalized["observation_fingerprint"])
            previous = by_submission.get(submission_id)
            if previous is not None and previous["observation_fingerprint"] != fingerprint:
                errors.append({"row_number": row["row_number"], "error": "SUBMISSION_ID_CONTENT_CONFLICT_IN_FILE"})
                preview_rows.append(self._summary(int(row["row_number"]), normalized, "REJECTED_CONFLICT"))
                continue
            if previous is not None or fingerprint in fingerprints:
                duplicate_input_count += 1
                preview_rows.append(self._summary(int(row["row_number"]), normalized, "DUPLICATE_IN_FILE_SKIPPED"))
                continue
            by_submission[submission_id] = normalized
            fingerprints.add(fingerprint)
            unique.append(normalized)
            preview_rows.append(self._summary(int(row["row_number"]), normalized, "NEW_OR_IDEMPOTENT_ON_CONFIRM"))
        if errors:
            return self._json(start_response, 422, {
                "schema_version": API_SCHEMA,
                "status": "PREVIEW_REJECTED",
                "can_confirm": False,
                "database_write_count": 0,
                "filename": parsed.filename,
                "media_type": parsed.media_type,
                "file_sha256": parsed.file_sha256,
                "row_count": len(parsed.rows),
                "valid_row_count": len(parsed.rows) - len(errors),
                "error_count": len(errors),
                "rows": preview_rows,
                "row_errors": errors,
            }, origin=origin)
        try:
            database_summary = self.store.classify_batch(unique)
        except StoreConflict:
            return self._error(start_response, 409, "SUBMISSION_ID_CONTENT_CONFLICT", origin=origin)
        preview_id, token, ttl = self.pending.create(unique, parsed.file_sha256, duplicate_input_count)
        return self._json(start_response, 200, {
            "schema_version": API_SCHEMA,
            "status": "PREVIEW_READY_NO_DATABASE_WRITE",
            "can_confirm": True,
            "database_write_count": 0,
            "preview_id": preview_id,
            "confirm_token": token,
            "expires_in_seconds": ttl,
            "filename": parsed.filename,
            "media_type": parsed.media_type,
            "file_sha256": parsed.file_sha256,
            "row_count": len(parsed.rows),
            "unique_record_count": len(unique),
            "duplicate_input_count": duplicate_input_count,
            "database_summary": database_summary,
            "rows": preview_rows,
            "warnings": ["PRIVATE_USER_ENTERED", "NOT_PLATFORM_VERIFIED", "USER_REPORTED_COUPON_NOT_CONFIRMED"],
        }, origin=origin)

    def _confirm(self, environ: dict[str, object], start_response: Callable, origin: str | None):
        value, input_sha = strict_json(self._read_body(environ, MAX_CONFIRM_BYTES), maximum=MAX_CONFIRM_BYTES, too_large_code="REQUEST_BODY_TOO_LARGE")
        fields = {"schema_version", "preview_id", "confirm_token", "explicit_confirm"}
        if not isinstance(value, dict) or set(value) != fields or value.get("schema_version") != CONFIRM_SCHEMA or value.get("explicit_confirm") is not True:
            raise BatchValidationError("EXPLICIT_CONFIRM_REQUIRED", input_sha256=input_sha)
        claim = self.pending.claim(value.get("preview_id"), value.get("confirm_token"))
        try:
            result = self.store.commit_batch(
                claim.records,
                file_sha256=claim.file_sha256,
                duplicate_input_count=claim.duplicate_input_count,
            )
        except StoreConflict:
            self.pending.fail(claim)
            return self._error(start_response, 409, "SUBMISSION_ID_CONTENT_CONFLICT", origin=origin)
        except Exception:
            self.pending.fail(claim)
            raise
        self.pending.complete(claim)
        return self._json(start_response, 200 if result["idempotent_replay"] else 201, {
            "schema_version": API_SCHEMA,
            "status": "BATCH_SAVED_PRIVATE_LOCAL",
            **result,
            "data_version": self.store.data_version(),
        }, origin=origin)

    def __call__(self, environ: dict[str, object], start_response: Callable):
        path = unquote(str(environ.get("PATH_INFO", "/")))
        prefix = "/api/private-observations/v1/batch-"
        if not path.startswith(prefix):
            return self.base(environ, start_response)
        origin, policy_error = self.base._policy(environ)
        if policy_error is not None:
            return self._error(start_response, policy_error[0], policy_error[1])
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        if len(path) > 512 or "\x00" in path or ".." in path:
            return self._error(start_response, 400, "PATH_INVALID", origin=origin)
        if method == "OPTIONS":
            return self.base(environ, start_response)
        if method != "POST":
            return self._error(start_response, 405, "METHOD_NOT_ALLOWED", origin=origin)
        if path not in {"/api/private-observations/v1/batch-preview", "/api/private-observations/v1/batch-confirm"}:
            return self._error(start_response, 404, "NOT_FOUND", origin=origin)
        supplied = str(environ.get("HTTP_X_CDH_CSRF_TOKEN", ""))
        if not supplied or not secrets.compare_digest(supplied, self.csrf_token):
            return self._error(start_response, 403, "CSRF_TOKEN_INVALID", origin=origin)
        try:
            if path.endswith("batch-preview"):
                return self._preview(environ, start_response, origin)
            return self._confirm(environ, start_response, origin)
        except BatchValidationError as exc:
            status = 409 if exc.code in {"CONFIRMATION_ALREADY_IN_PROGRESS", "CONFIRMATION_FAILED_NEW_PREVIEW_REQUIRED"} else 400
            return self._error(start_response, status, exc.code, origin=origin, input_sha256=exc.input_sha256)
        except StoreError:
            return self._error(start_response, 400, "PRIVATE_STORE_REJECTED", origin=origin)
        except sqlite3.Error:
            return self._error(start_response, 500, "PRIVATE_STORE_TRANSACTION_FAILED", origin=origin)

