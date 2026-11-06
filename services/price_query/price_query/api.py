from __future__ import annotations

import json
from http import HTTPStatus
from typing import Callable, Iterable
from urllib.parse import parse_qs, unquote

from .repository import (
    ReadonlyPriceRepository,
    RepositoryError,
    SCHEMA_VERSION_V1,
    SCHEMA_VERSION_V2,
)


StartResponse = Callable[[str, list[tuple[str, str]]], object]


class PriceQueryApp:
    def __init__(self, repository: ReadonlyPriceRepository) -> None:
        self.repository = repository

    @staticmethod
    def _response(start_response: StartResponse, status: HTTPStatus, payload: dict[str, object]) -> Iterable[bytes]:
        body = (json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        start_response(
            f"{status.value} {status.phrase}",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
                ("X-CDH-Schema-Version", str(payload.get("schema_version", SCHEMA_VERSION_V2))),
            ],
        )
        return [body]

    @staticmethod
    def _error(code: str, detail: str, schema_version: str = SCHEMA_VERSION_V2) -> dict[str, object]:
        return {"schema_version": schema_version, "error": {"code": code, "detail": detail}}

    def __call__(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        path = str(environ.get("PATH_INFO", ""))
        if path.startswith("/api/v1/") or path == "/api/v1":
            api_prefix = "/api/v1"
            schema_version = SCHEMA_VERSION_V1
        elif path.startswith("/api/v2/") or path == "/api/v2":
            api_prefix = "/api/v2"
            schema_version = SCHEMA_VERSION_V2
        else:
            api_prefix = "/api/v2"
            schema_version = SCHEMA_VERSION_V2
        if environ.get("REQUEST_METHOD") != "GET":
            return self._response(
                start_response,
                HTTPStatus.METHOD_NOT_ALLOWED,
                self._error("METHOD_NOT_ALLOWED", "GET required", schema_version),
            )
        try:
            if path == f"{api_prefix}/products":
                query = parse_qs(str(environ.get("QUERY_STRING", "")), keep_blank_values=True)
                term = query.get("q", [""])[0]
                page = int(query.get("page", ["1"])[0])
                limit = int(query.get("limit", ["20"])[0])
                if page < 1 or not 1 <= limit <= 100:
                    raise ValueError
                value = self.repository.search(
                    term,
                    page=page,
                    limit=limit,
                    schema_version=schema_version,
                )
                return self._response(start_response, HTTPStatus.OK, value)
            prefix = f"{api_prefix}/products/"
            if path.startswith(prefix):
                tail = path[len(prefix) :]
                affiliate = tail.endswith("/affiliate")
                product_id = unquote(tail[: -len("/affiliate")] if affiliate else tail)
                if not product_id or "/" in product_id:
                    return self._response(
                        start_response,
                        HTTPStatus.NOT_FOUND,
                        self._error("NOT_FOUND", "product not found", schema_version),
                    )
                value = (
                    self.repository.affiliate(product_id, schema_version=schema_version)
                    if affiliate
                    else self.repository.detail(product_id, schema_version=schema_version)
                )
                if value is None:
                    return self._response(
                        start_response,
                        HTTPStatus.NOT_FOUND,
                        self._error("NOT_FOUND", "product not found", schema_version),
                    )
                return self._response(start_response, HTTPStatus.OK, value)
            return self._response(
                start_response,
                HTTPStatus.NOT_FOUND,
                self._error("NOT_FOUND", "route not found", schema_version),
            )
        except (ValueError, OverflowError):
            return self._response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                self._error("INVALID_PAGINATION", "page>=1 and 1<=limit<=100 required", schema_version),
            )
        except RepositoryError as exc:
            return self._response(
                start_response,
                HTTPStatus.SERVICE_UNAVAILABLE,
                self._error("DATA_UNAVAILABLE", str(exc), schema_version),
            )
