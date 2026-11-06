from __future__ import annotations

import json
from http import HTTPStatus
from typing import Callable
from urllib.parse import parse_qs, unquote

from .repository import SCHEMA_VERSION, CouponPriceRepository, CouponRepositoryError


SECURITY_HEADERS = [
    ("Cache-Control", "private, no-store"),
    ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Permissions-Policy", "accelerometer=(), camera=(), geolocation=(), microphone=(), payment=(), usb=()"),
]


class CouponPriceV4App:
    def __init__(self, repository: CouponPriceRepository) -> None:
        self.repository = repository

    @staticmethod
    def _json(start_response: Callable, status: int, payload: dict[str, object], *, etag: str | None = None):
        body=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode("utf-8")
        headers=[("Content-Type","application/json; charset=utf-8"),("Content-Length",str(len(body))),("X-CDH-Schema-Version",SCHEMA_VERSION),*SECURITY_HEADERS]
        if etag: headers.append(("ETag",etag))
        start_response(f"{status} {HTTPStatus(status).phrase}",headers); return [body]

    def _error(self,start_response:Callable,status:int,code:str,detail:str):
        return self._json(start_response,status,{"schema_version":SCHEMA_VERSION,"error":{"code":code,"detail":detail}})

    def __call__(self,environ:dict[str,object],start_response:Callable):
        if str(environ.get("REQUEST_METHOD","GET")).upper()!="GET": return self._error(start_response,405,"METHOD_NOT_ALLOWED","read-only API accepts GET only")
        path=unquote(str(environ.get("PATH_INFO","/")))
        if "\x00" in path or ".." in path: return self._error(start_response,400,"INVALID_PATH","invalid path")
        try:
            if path=="/api/v4/products":
                query=parse_qs(str(environ.get("QUERY_STRING","")),keep_blank_values=True)
                try: page=int(query.get("page",["1"])[0]); limit=int(query.get("limit",["20"])[0])
                except ValueError: return self._error(start_response,400,"INVALID_PAGINATION","page and limit must be integers")
                payload=self.repository.search(query.get("q",[""])[0],page=page,limit=limit)
            elif path.startswith("/api/v4/products/"):
                payload=self.repository.detail(path[len("/api/v4/products/"):])
                if payload is None: return self._error(start_response,404,"NOT_FOUND","coupon series not found")
            else: return self._error(start_response,404,"NOT_FOUND","route not found")
            if str(environ.get("HTTP_IF_NONE_MATCH",""))==self.repository.data_version:
                start_response("304 Not Modified",[("ETag",self.repository.data_version),*SECURITY_HEADERS]); return [b""]
            return self._json(start_response,200,payload,etag=self.repository.data_version)
        except CouponRepositoryError as exc:
            return self._error(start_response,400,"COUPON_SNAPSHOT_REJECTED",str(exc))
