from __future__ import annotations

import hashlib
import json
import re
from typing import Callable
from urllib.parse import parse_qs


STATUS_SCHEMA = "CDH-B14-PREVIEW-STATUS-1"
MAX_QUERY_BYTES = 2048
MAX_RESPONSE_BYTES = 1_000_000
IDENTITY_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


class PreviewStatusApp:
    """GET-only loopback view over an already computed B14 DTO."""

    def __init__(self, preview: dict[str, object]) -> None:
        self.preview = preview
        self.etag = '"' + hashlib.sha256(_json(preview)).hexdigest() + '"'

    @staticmethod
    def _security_headers() -> list[tuple[str, str]]:
        return [
            ("Cache-Control", "no-store"),
            ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
            ("Referrer-Policy", "no-referrer"),
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            ("Permissions-Policy", "geolocation=(), camera=(), microphone=()"),
        ]

    def _response(self, start_response: Callable, status: str, value: object | None, *, etag: bool = False):
        body = b"" if value is None else _json(value)
        if len(body) > MAX_RESPONSE_BYTES:
            status = "500 Internal Server Error"
            body = _json({"schema_version": STATUS_SCHEMA, "error": "RESPONSE_LIMIT_EXCEEDED"})
        headers = self._security_headers()
        if body:
            headers.extend((("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))))
        if etag:
            headers.append(("ETag", self.etag))
        start_response(status, headers)
        return [body]

    @staticmethod
    def _page(query: str) -> tuple[int, int]:
        if len(query.encode("utf-8")) > MAX_QUERY_BYTES:
            raise ValueError("QUERY_TOO_LARGE")
        values = parse_qs(query, keep_blank_values=True, strict_parsing=False)
        if set(values) - {"page", "limit"}:
            raise ValueError("UNKNOWN_QUERY_PARAMETER")
        if any(len(items) != 1 for items in values.values()):
            raise ValueError("DUPLICATE_QUERY_PARAMETER")
        try:
            page = int(values.get("page", ["1"])[0])
            limit = int(values.get("limit", ["50"])[0])
        except ValueError as exc:
            raise ValueError("PAGINATION_INVALID") from exc
        if page < 1 or limit < 1 or limit > 100:
            raise ValueError("PAGINATION_OUT_OF_RANGE")
        return page, limit

    def __call__(self, environ: dict[str, object], start_response: Callable):
        host = str(environ.get("HTTP_HOST", ""))
        if host and host.split(":", 1)[0].casefold() not in {"127.0.0.1", "localhost"}:
            return self._response(start_response, "400 Bad Request", {"schema_version": STATUS_SCHEMA, "error": "HOST_NOT_ALLOWED"})
        if environ.get("HTTP_ORIGIN"):
            return self._response(start_response, "403 Forbidden", {"schema_version": STATUS_SCHEMA, "error": "ORIGIN_NOT_ALLOWED"})
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return self._response(start_response, "405 Method Not Allowed", {"schema_version": STATUS_SCHEMA, "error": "METHOD_NOT_ALLOWED"})
        path = str(environ.get("PATH_INFO", ""))
        try:
            page, limit = self._page(str(environ.get("QUERY_STRING", "")))
        except ValueError as exc:
            return self._response(start_response, "400 Bad Request", {"schema_version": STATUS_SCHEMA, "error": str(exc)})
        if path == "/api/import-preview/v2/status":
            if environ.get("HTTP_IF_NONE_MATCH") == self.etag:
                return self._response(start_response, "304 Not Modified", None, etag=True)
            records = self.preview["records"]
            start = (page - 1) * limit
            body = {
                "schema_version": STATUS_SCHEMA,
                "preview_schema_version": self.preview["schema_version"],
                "input": self.preview["input"],
                "as_of": self.preview["as_of"],
                "summary": self.preview["summary"],
                "dependencies": self.preview["dependencies"],
                "ingress_policy": self.preview["ingress_policy"],
                "safety": self.preview["safety"],
                "page": page,
                "limit": limit,
                "total": len(records),
                "records": records[start:start + limit],
                "history_candidate_count": len(self.preview["history_candidates"]),
            }
            return self._response(start_response, "200 OK", body, etag=True)
        prefix = "/api/import-preview/v2/history/"
        if path.startswith(prefix):
            identity_key = path[len(prefix):]
            if not IDENTITY_KEY_RE.fullmatch(identity_key):
                return self._response(start_response, "404 Not Found", {"schema_version": STATUS_SCHEMA, "error": "NOT_FOUND"})
            candidate = next((item for item in self.preview["history_candidates"] if item["identity_key"] == identity_key), None)
            if candidate is None:
                return self._response(start_response, "404 Not Found", {"schema_version": STATUS_SCHEMA, "error": "NOT_FOUND"})
            if environ.get("HTTP_IF_NONE_MATCH") == self.etag:
                return self._response(start_response, "304 Not Modified", None, etag=True)
            observations = candidate["observations"]
            start = (page - 1) * limit
            body = {
                "schema_version": STATUS_SCHEMA,
                "identity_key": identity_key,
                "series_key": candidate["series_key"],
                "identity": candidate["identity"],
                "page": page,
                "limit": limit,
                "total": len(observations),
                "observations": observations[start:start + limit],
            }
            return self._response(start_response, "200 OK", body, etag=True)
        return self._response(start_response, "404 Not Found", {"schema_version": STATUS_SCHEMA, "error": "NOT_FOUND"})
