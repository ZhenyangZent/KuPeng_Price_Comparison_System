from __future__ import annotations

import json
from http import HTTPStatus
from typing import Callable
from urllib.parse import parse_qs, unquote

from price_quality_adapter import AdapterError, PriceQualityRepository
from price_quality_adapter.repository import ADAPTER_CONTRACT, WIRE_CONTRACT

SECURITY_HEADERS = [
    ("Cache-Control", "private, no-store"),
    ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Permissions-Policy", "accelerometer=(), camera=(), geolocation=(), microphone=(), payment=(), usb=()"),
]


class PriceQueryV3App:
    def __init__(self, repository: PriceQualityRepository) -> None:
        self.repository = repository

    @staticmethod
    def _json(start_response: Callable, status: int, payload: dict[str, object], *, etag: str | None = None):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            *SECURITY_HEADERS,
            ("X-CDH-Schema-Version", str(payload.get("schema_version", "UNKNOWN"))),
        ]
        if etag:
            headers.append(("ETag", etag))
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [body]

    def _error(self, start_response: Callable, status: int, code: str, detail: str, schema: str = WIRE_CONTRACT):
        return self._json(start_response, status, {"schema_version": schema, "error": {"code": code, "detail": detail}})

    def __call__(self, environ: dict[str, object], start_response: Callable):
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        if method != "GET":
            return self._error(start_response, 405, "METHOD_NOT_ALLOWED", "read-only API accepts GET only")
        path = unquote(str(environ.get("PATH_INFO", "/")))
        if "\x00" in path or ".." in path:
            return self._error(start_response, 400, "INVALID_PATH", "invalid path")
        try:
            if path == "/api/v2/products":
                query = parse_qs(str(environ.get("QUERY_STRING", "")), keep_blank_values=True)
                search = query.get("q", [""])[0]
                try:
                    page = int(query.get("page", ["1"])[0])
                    limit = int(query.get("limit", ["20"])[0])
                except ValueError:
                    return self._error(start_response, 400, "INVALID_PAGINATION", "page and limit must be integers")
                payload = self.repository.search(search, page=page, limit=limit)
                return self._json(start_response, 200, payload, etag=self.repository.data_version)
            prefix = "/api/v2/products/"
            if path.startswith(prefix):
                tail = path[len(prefix):]
                if tail.endswith("/affiliate"):
                    key = tail[:-len("/affiliate")]
                    payload = self.repository.affiliate(key)
                else:
                    key = tail
                    payload = self.repository.detail(key)
                if payload is None:
                    return self._error(start_response, 404, "NOT_FOUND", "product not found")
                return self._json(start_response, 200, payload, etag=self.repository.data_version)
            quality_prefix = "/api/v3/quality/"
            if path.startswith(quality_prefix):
                key = path[len(quality_prefix):]
                if str(environ.get("HTTP_IF_NONE_MATCH", "")) == self.repository.data_version:
                    start_response("304 Not Modified", [("ETag", self.repository.data_version), *SECURITY_HEADERS])
                    return [b""]
                payload = self.repository.quality(key)
                if payload is None:
                    return self._error(start_response, 404, "NOT_FOUND", "quality series not found", ADAPTER_CONTRACT)
                return self._json(start_response, 200, payload, etag=self.repository.data_version)
            return self._error(start_response, 404, "NOT_FOUND", "route not found")
        except AdapterError as exc:
            return self._error(start_response, 400, "ADAPTER_INPUT_REJECTED", str(exc))
