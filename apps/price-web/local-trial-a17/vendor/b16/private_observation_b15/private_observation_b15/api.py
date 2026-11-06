from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from http import HTTPStatus
from typing import Callable
from urllib.parse import parse_qs, unquote

from .store import ObservationStore, StoreConflict, StoreError
from .validation import MAX_BODY_BYTES, ValidationError, parse_and_validate, strict_json


API_SCHEMA = "CDH-B15-PRIVATE-OBSERVATION-API-1"
MAX_RESPONSE_BYTES = 1_000_000
MAX_QUERY_BYTES = 2048


class PendingPreviews:
    def __init__(self, *, ttl_seconds: int = 600, clock: Callable[[], float] | None = None, max_items: int = 128, max_total_bytes: int = 2 * 1024 * 1024) -> None:
        if ttl_seconds < 1 or max_items < 1 or max_total_bytes < 1024:
            raise ValueError("preview retention settings are invalid")
        self.ttl_seconds = ttl_seconds
        self.clock = clock or time.monotonic
        self.max_items = max_items
        self.max_total_bytes = max_total_bytes
        self._items: dict[str, tuple[float, str, dict[str, object], int]] = {}
        self._lock = threading.Lock()

    def _cleanup_locked(self) -> int:
        now = self.clock()
        expired = [key for key, value in self._items.items() if value[0] < now]
        for key in expired:
            self._items.pop(key, None)
        return len(expired)

    def create(self, normalized: dict[str, object]) -> tuple[str, str, int]:
        size = len(json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        preview_id = secrets.token_urlsafe(24)
        token = secrets.token_urlsafe(32)
        expires = self.clock() + self.ttl_seconds
        with self._lock:
            self._cleanup_locked()
            total = sum(value[3] for value in self._items.values())
            if len(self._items) >= self.max_items or total + size > self.max_total_bytes:
                raise ValidationError("PREVIEW_CAPACITY_EXCEEDED")
            self._items[preview_id] = (expires, token, normalized, size)
        return preview_id, token, self.ttl_seconds

    def get(self, preview_id: object, token: object) -> dict[str, object]:
        if not isinstance(preview_id, str) or not isinstance(token, str):
            raise ValidationError("CONFIRMATION_TOKEN_INVALID")
        with self._lock:
            self._cleanup_locked()
            value = self._items.get(preview_id)
            if value is None or value[0] < self.clock() or not secrets.compare_digest(value[1], token):
                self._items.pop(preview_id, None)
                raise ValidationError("CONFIRMATION_TOKEN_INVALID_OR_EXPIRED")
            return value[2]

    def consume(self, preview_id: str) -> None:
        with self._lock:
            self._cleanup_locked()
            self._items.pop(preview_id, None)

    def retained_count(self) -> int:
        with self._lock:
            self._cleanup_locked()
            return len(self._items)


class PrivateObservationApp:
    def __init__(self, store: ObservationStore, *, baselines: dict[str, str], clock, allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost"), allowed_origins: tuple[str, ...] = (), csrf_token: str | None = None, pending: PendingPreviews | None = None) -> None:
        self.store = store
        self.baselines = dict(baselines)
        self.clock = clock
        self.allowed_hosts = frozenset(item.casefold() for item in allowed_hosts)
        self.allowed_origins = frozenset(allowed_origins)
        self.csrf_token = csrf_token or secrets.token_urlsafe(32)
        self.pending = pending or PendingPreviews()

    @staticmethod
    def _security_headers() -> list[tuple[str, str]]:
        return [("Cache-Control", "private, no-store"), ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"), ("Referrer-Policy", "no-referrer"), ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"), ("Permissions-Policy", "camera=(), geolocation=(), microphone=(), payment=(), usb=()")]

    def _json(self, start_response: Callable, status: int, payload: object, *, origin: str | None = None, etag: str | None = None):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(body) > MAX_RESPONSE_BYTES:
            status = 500
            body = b'{"schema_version":"CDH-B15-PRIVATE-OBSERVATION-API-1","error":{"code":"RESPONSE_LIMIT_EXCEEDED"}}'
        headers = [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body))), *self._security_headers()]
        if origin is not None:
            headers.extend((("Access-Control-Allow-Origin", origin), ("Vary", "Origin")))
        if etag is not None:
            headers.append(("ETag", etag))
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [body]

    def _error(self, start_response: Callable, status: int, code: str, *, origin: str | None = None, input_sha256: str | None = None):
        return self._json(start_response, status, {"schema_version": API_SCHEMA, "error": {"code": code, "input_sha256": input_sha256, "raw_content_included": False}}, origin=origin)

    def _policy(self, environ: dict[str, object]):
        host = str(environ.get("HTTP_HOST", "")).strip()
        if not host:
            return None, (400, "HOST_REQUIRED")
        hostname = host.rsplit(":", 1)[0].casefold() if ":" in host else host.casefold()
        if hostname not in self.allowed_hosts:
            return None, (400, "HOST_NOT_ALLOWED")
        origin = str(environ.get("HTTP_ORIGIN", "")).strip() or None
        if origin is not None and origin not in self.allowed_origins:
            return None, (403, "ORIGIN_NOT_ALLOWED")
        return origin, None

    @staticmethod
    def _query(text: str, allowed: set[str]) -> dict[str, list[str]]:
        if len(text.encode("utf-8")) > MAX_QUERY_BYTES:
            raise ValidationError("QUERY_TOO_LARGE")
        values = parse_qs(text, keep_blank_values=True)
        if set(values) - allowed or any(len(items) != 1 for items in values.values()):
            raise ValidationError("QUERY_INVALID")
        return values

    def _body(self, environ: dict[str, object]) -> bytes:
        content_type = str(environ.get("CONTENT_TYPE", "")).split(";", 1)[0].strip().casefold()
        if content_type != "application/json":
            raise ValidationError("CONTENT_TYPE_NOT_JSON")
        try:
            length = int(str(environ.get("CONTENT_LENGTH", "")))
        except ValueError as exc:
            raise ValidationError("CONTENT_LENGTH_INVALID") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValidationError("REQUEST_BODY_TOO_LARGE")
        raw = environ["wsgi.input"].read(length)
        if len(raw) != length:
            raise ValidationError("REQUEST_BODY_TRUNCATED")
        return raw

    def __call__(self, environ: dict[str, object], start_response: Callable):
        origin, error = self._policy(environ)
        if error is not None:
            return self._error(start_response, error[0], error[1])
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = unquote(str(environ.get("PATH_INFO", "/")))
        if len(path) > 512 or "\x00" in path or ".." in path:
            return self._error(start_response, 400, "PATH_INVALID", origin=origin)
        if method == "OPTIONS":
            if origin is None:
                return self._error(start_response, 405, "METHOD_NOT_ALLOWED")
            headers = [("Content-Length", "0"), ("Access-Control-Allow-Origin", origin), ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"), ("Access-Control-Allow-Headers", "Content-Type, X-CDH-CSRF-Token"), ("Vary", "Origin"), *self._security_headers()]
            start_response("204 No Content", headers)
            return [b""]
        try:
            if method == "GET" and path == "/api/private-observations/v1/session":
                return self._json(start_response, 200, {"schema_version": API_SCHEMA, "csrf_token": self.csrf_token, "storage_scope": "PRIVATE_LOCAL_ONLY", "baselines": self.baselines}, origin=origin)
            if method == "POST" and path in {"/api/private-observations/v1/preview", "/api/private-observations/v1/confirm"}:
                supplied = str(environ.get("HTTP_X_CDH_CSRF_TOKEN", ""))
                if not supplied or not secrets.compare_digest(supplied, self.csrf_token):
                    return self._error(start_response, 403, "CSRF_TOKEN_INVALID", origin=origin)
                raw = self._body(environ)
                if path.endswith("/preview"):
                    normalized = parse_and_validate(raw, now=self.clock())
                    preview_id, token, ttl = self.pending.create(normalized)
                    warning = "USER_REPORTED_COUPON_NOT_CONFIRMED" if normalized["user_reported_coupon"]["status"] == "USER_REPORTED" else "NO_COUPON_REPORTED"
                    return self._json(start_response, 200, {"schema_version": API_SCHEMA, "mode": "PREVIEW_NO_DATABASE_WRITE", "preview_id": preview_id, "confirm_token": token, "expires_in_seconds": ttl, "will_save": normalized, "warnings": ["PRIVATE_USER_ENTERED", "NOT_PLATFORM_VERIFIED", warning], "database_write_count": 0}, origin=origin)
                confirm, input_sha = strict_json(raw)
                if not isinstance(confirm, dict) or set(confirm) != {"preview_id", "confirm_token", "explicit_confirm"} or confirm.get("explicit_confirm") is not True:
                    raise ValidationError("EXPLICIT_CONFIRM_REQUIRED", input_sha256=input_sha)
                normalized = self.pending.get(confirm.get("preview_id"), confirm.get("confirm_token"))
                try:
                    result = self.store.commit(normalized)
                except StoreConflict:
                    return self._error(start_response, 409, "SUBMISSION_ID_CONTENT_CONFLICT", origin=origin)
                self.pending.consume(str(confirm["preview_id"]))
                return self._json(start_response, 201 if not result["idempotent_replay"] else 200, {"schema_version": API_SCHEMA, "status": "SAVED_PRIVATE_LOCAL", **result, "data_version": self.store.data_version()}, origin=origin)
            if method == "GET" and path == "/api/private-observations/v1/products":
                values = self._query(str(environ.get("QUERY_STRING", "")), {"q", "page", "limit"})
                try:
                    page = int(values.get("page", ["1"])[0]); limit = int(values.get("limit", ["20"])[0])
                except ValueError as exc:
                    raise ValidationError("PAGINATION_INVALID") from exc
                payload = self.store.search(values.get("q", [""])[0], page=page, limit=limit)
                return self._json(start_response, 200, payload, origin=origin, etag=payload["data_version"])
            prefix = "/api/private-observations/v1/products/"
            if method == "GET" and path.startswith(prefix):
                if environ.get("QUERY_STRING"):
                    raise ValidationError("QUERY_INVALID")
                payload = self.store.detail(path[len(prefix):])
                if payload is None:
                    return self._error(start_response, 404, "NOT_FOUND", origin=origin)
                return self._json(start_response, 200, payload, origin=origin, etag=payload["data_version"])
            if method not in {"GET", "POST"}:
                return self._error(start_response, 405, "METHOD_NOT_ALLOWED", origin=origin)
            return self._error(start_response, 404, "NOT_FOUND", origin=origin)
        except ValidationError as exc:
            return self._error(start_response, 400, exc.code, origin=origin, input_sha256=exc.input_sha256)
        except StoreError:
            return self._error(start_response, 400, "PRIVATE_STORE_REJECTED", origin=origin)
        except sqlite3.Error:
            return self._error(start_response, 500, "PRIVATE_STORE_TRANSACTION_FAILED", origin=origin)
