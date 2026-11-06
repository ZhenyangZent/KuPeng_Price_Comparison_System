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
MAX_QUERY_STRING_BYTES = 2048
MAX_PATH_CHARS = 512
MAX_RESPONSE_BYTES = 1_000_000


class CouponPriceV4App:
    def __init__(self, repository: CouponPriceRepository, *, allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost"), allowed_origins: tuple[str, ...] = ()) -> None:
        self.repository = repository
        self.allowed_hosts = frozenset(value.casefold() for value in allowed_hosts)
        self.allowed_origins = frozenset(allowed_origins)

    def _json(self, start_response: Callable, status: int, payload: dict[str, object], *, etag: str | None = None, cors_origin: str | None = None):
        body=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode("utf-8")
        if len(body)>MAX_RESPONSE_BYTES:
            status=500; body=json.dumps({"schema_version":SCHEMA_VERSION,"error":{"code":"RESPONSE_LIMIT_EXCEEDED","detail":"response exceeds local safety limit"}},separators=(",",":")).encode("utf-8")
        headers=[("Content-Type","application/json; charset=utf-8"),("Content-Length",str(len(body))),("X-CDH-Schema-Version",SCHEMA_VERSION),*SECURITY_HEADERS]
        if etag: headers.append(("ETag",etag))
        if cors_origin: headers.extend((("Access-Control-Allow-Origin",cors_origin),("Vary","Origin")))
        start_response(f"{status} {HTTPStatus(status).phrase}",headers); return [body]

    def _error(self,start_response:Callable,status:int,code:str,detail:str,*,cors_origin:str|None=None):
        return self._json(start_response,status,{"schema_version":SCHEMA_VERSION,"error":{"code":code,"detail":detail}},cors_origin=cors_origin)

    def _request_policy(self,environ:dict[str,object])->tuple[str|None,tuple[int,str,str]|None]:
        host=str(environ.get("HTTP_HOST","")).strip()
        if host:
            hostname=host.rsplit(":",1)[0].casefold() if ":" in host else host.casefold()
            if hostname not in self.allowed_hosts: return None,(400,"HOST_NOT_ALLOWED","only configured loopback hosts are accepted")
        origin=str(environ.get("HTTP_ORIGIN","")).strip() or None
        if origin is not None and origin not in self.allowed_origins: return None,(403,"ORIGIN_NOT_ALLOWED","origin is not in the explicit local allowlist")
        return origin,None

    def __call__(self,environ:dict[str,object],start_response:Callable):
        cors_origin,policy_error=self._request_policy(environ)
        if policy_error is not None: return self._error(start_response,*policy_error)
        method=str(environ.get("REQUEST_METHOD","GET")).upper()
        if method=="OPTIONS":
            if cors_origin is None: return self._error(start_response,405,"METHOD_NOT_ALLOWED","preflight requires an explicitly allowed origin")
            headers=[("Content-Length","0"),("Access-Control-Allow-Origin",cors_origin),("Access-Control-Allow-Methods","GET"),("Access-Control-Allow-Headers","If-None-Match"),("Vary","Origin"),*SECURITY_HEADERS]
            start_response("204 No Content",headers); return [b""]
        if method!="GET": return self._error(start_response,405,"METHOD_NOT_ALLOWED","read-only API accepts GET only",cors_origin=cors_origin)
        path=unquote(str(environ.get("PATH_INFO","/")))
        query_text=str(environ.get("QUERY_STRING",""))
        if len(path)>MAX_PATH_CHARS or len(query_text.encode("utf-8"))>MAX_QUERY_STRING_BYTES: return self._error(start_response,400,"REQUEST_LIMIT_EXCEEDED","path or query exceeds local safety limit",cors_origin=cors_origin)
        if "\x00" in path or ".." in path: return self._error(start_response,400,"INVALID_PATH","invalid path",cors_origin=cors_origin)
        try:
            if path=="/api/v4/products":
                query=parse_qs(query_text,keep_blank_values=True)
                try: page=int(query.get("page",["1"])[0]); limit=int(query.get("limit",["20"])[0])
                except ValueError: return self._error(start_response,400,"INVALID_PAGINATION","page and limit must be integers",cors_origin=cors_origin)
                if len(query.get("q",[""])[0])>200: return self._error(start_response,400,"QUERY_TOO_LONG","q must be at most 200 characters",cors_origin=cors_origin)
                payload=self.repository.search(query.get("q",[""])[0],page=page,limit=limit)
            elif path.startswith("/api/v4/products/"):
                payload=self.repository.detail(path[len("/api/v4/products/"):])
                if payload is None: return self._error(start_response,404,"NOT_FOUND","coupon series not found",cors_origin=cors_origin)
            else: return self._error(start_response,404,"NOT_FOUND","route not found",cors_origin=cors_origin)
            if str(environ.get("HTTP_IF_NONE_MATCH",""))==self.repository.data_version:
                headers=[("ETag",self.repository.data_version),*SECURITY_HEADERS]
                if cors_origin: headers.extend((("Access-Control-Allow-Origin",cors_origin),("Vary","Origin")))
                start_response("304 Not Modified",headers); return [b""]
            return self._json(start_response,200,payload,etag=self.repository.data_version,cors_origin=cors_origin)
        except CouponRepositoryError as exc:
            return self._error(start_response,400,"COUPON_SNAPSHOT_REJECTED",str(exc),cors_origin=cors_origin)
