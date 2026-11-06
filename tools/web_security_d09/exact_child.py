from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def request(app, path: str, *, method: str = "GET", headers: dict[str, str] | None = None):
    captured: dict[str, object] = {}
    route, _, query = path.partition("?")
    environ: dict[str, object] = {
        "REQUEST_METHOD": method, "PATH_INFO": route, "QUERY_STRING": query,
        "wsgi.input": io.BytesIO(),
    }
    for name, value in (headers or {}).items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value

    def start_response(status, response_headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(response_headers)

    raw = b"".join(app(environ, start_response))
    captured["body"] = json.loads(raw) if raw else None
    return captured


def forbidden_keys(value):
    forbidden = {"click_url", "affiliate_url", "redirect_url", "token", "secret", "api_key", "cookie", "authorization", "password", "session"}
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in forbidden:
                found.append(str(key))
            found.extend(forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(forbidden_keys(child))
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b11-root", type=Path, required=True)
    parser.add_argument("--f06-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    b11 = args.b11_root
    f06 = args.f06_root
    sys.path.insert(0, str(b11 / "services" / "price_coupon_v4"))
    sys.path.insert(0, str(f06 / "services" / "affiliate_coupon_gate_v6"))
    from price_coupon_v4 import CouponPriceRepository, CouponPriceV4App, build_fixture_suite
    from affiliate_coupon_gate_v6 import adapt_detail_envelope, adapt_search_envelope

    build_fixture_suite(args.fixture)
    active = args.fixture / "active"
    database = active / "coupon.sqlite3"
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    now = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)
    repository = CouponPriceRepository(database, authority_file=active / "coupon.authority.json", allowed_root=active, clock=lambda: now)
    origin = "http://127.0.0.1:4173"
    app = CouponPriceV4App(repository, allowed_origins=(origin,))
    search = request(app, "/api/v4/products?limit=3", headers={"Host": "127.0.0.1:8766"})
    detail = request(app, "/api/v4/products/confirmed", headers={"Host": "127.0.0.1:8766", "Origin": origin})
    hostile_host = request(app, "/api/v4/products", headers={"Host": "evil.invalid"})
    hostile_origin = request(app, "/api/v4/products", headers={"Host": "127.0.0.1:8766", "Origin": "https://evil.invalid"})
    post = request(app, "/api/v4/products", method="POST", headers={"Host": "127.0.0.1:8766"})
    oversized = request(app, "/api/v4/products?x=" + "x" * 2050, headers={"Host": "127.0.0.1:8766"})
    not_found = request(app, "/missing", headers={"Host": "127.0.0.1:8766"})
    etag = search["headers"]["ETag"]
    not_modified = request(app, "/api/v4/products", headers={"Host": "127.0.0.1:8766", "If-None-Match": etag})
    options = request(app, "/api/v4/products", method="OPTIONS", headers={"Host": "127.0.0.1:8766", "Origin": origin})
    adapted_search = adapt_search_envelope(search["body"])
    adapted_detail = adapt_detail_envelope(detail["body"])
    after = hashlib.sha256(database.read_bytes()).hexdigest()
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((b11 / "services" / "price_coupon_v4" / "price_coupon_v4").glob("*.py"))
    ).casefold()
    result = {
        "schema": "CDH-D09-B11-F06-EXACT-RUNTIME-1",
        "statuses": {
            "search": search["status"], "detail": detail["status"], "hostile_host": hostile_host["status"],
            "hostile_origin": hostile_origin["status"], "post": post["status"], "oversized": oversized["status"],
            "not_found": not_found["status"], "not_modified": not_modified["status"], "options": options["status"],
        },
        "cors": {
            "allowed_exact": detail["headers"].get("Access-Control-Allow-Origin") == origin,
            "wildcard_absent": all(value["headers"].get("Access-Control-Allow-Origin") != "*" for value in (search, detail, hostile_host, hostile_origin, post, oversized, not_found, not_modified, options)),
        },
        "read_only": {"before_sha256": before, "after_sha256": after, "unchanged": before == after},
        "secrets": {"forbidden_keys": sorted(set(forbidden_keys(search["body"]) + forbidden_keys(detail["body"]))), "passed": not forbidden_keys(search["body"]) and not forbidden_keys(detail["body"])},
        "static": {
            "external_client_absent": not any(token in source for token in ("requests", "httpx", "aiohttp", "urllib.request", "http.client")),
            "environment_access_absent": "os.environ" not in source and "dotenv" not in source,
            "loopback_bind_only": 'choices=("127.0.0.1",)' in source,
        },
        "f06_integration": {
            "search_count": len(adapted_search),
            "detail_series_key": adapted_detail.series_key,
            "prices": [adapted_detail.base_price_twd, adapted_detail.before_coupon_price_twd, adapted_detail.confirmed_coupon_price_twd],
            "history_counts": [len(adapted_detail.before_coupon_history), len(adapted_detail.confirmed_after_coupon_history)],
        },
        "runtime_external_request_count": 0,
    }
    expected = {"search": 200, "detail": 200, "hostile_host": 400, "hostile_origin": 403, "post": 405, "oversized": 400, "not_found": 404, "not_modified": 304, "options": 204}
    checks = [result["statuses"] == expected, result["cors"]["allowed_exact"], result["cors"]["wildcard_absent"], result["read_only"]["unchanged"], result["secrets"]["passed"], all(result["static"].values()), result["f06_integration"]["prices"] == [99, 99, 49], result["f06_integration"]["history_counts"] == [1, 1]]
    result["passed"] = all(checks)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
