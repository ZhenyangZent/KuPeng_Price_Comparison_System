from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path


def _load(root: Path):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "services" / "price_coupon_v4"))
    sys.path.insert(0, str(root / "services" / "price_quality_adapter"))
    sys.path.insert(0, str(root / "services" / "price_query_v3"))
    source = root / "tests" / "web" / "price_coupon_v4" / "test_coupon_v4.py"
    spec = importlib.util.spec_from_file_location("d08_exact_b10_fixture", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("B10_FIXTURE_IMPORT_SPEC_FAILURE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _case_root(work: Path, name: str) -> Path:
    value = work / name
    value.mkdir(parents=True, exist_ok=False)
    return value


def run(root: Path, work: Path) -> dict[str, object]:
    fixture = _load(root)
    base = _case_root(work, "base")
    repository = fixture.repository(base)
    app = fixture.CouponPriceV4App(repository)
    search_status, search, search_headers = fixture.request(app, "/api/v4/products?q=coupon&page=1&limit=20")
    detail_status, detail, detail_headers = fixture.request(app, "/api/v4/products/series-1")
    etag = search_headers["ETag"]
    status_304, body_304, headers_304 = fixture.request(app, "/api/v4/products/series-1", headers={"If-None-Match": etag})
    status_404, body_404, headers_404 = fixture.request(app, "/missing")
    status_405, body_405, headers_405 = fixture.request(app, "/api/v4/products", method="POST")
    status_options, body_options, headers_options = fixture.request(app, "/api/v4/products", method="OPTIONS")
    hostile_host_status, hostile_host_body, hostile_host_headers = fixture.request(app, "/api/v4/products", headers={"Host": "evil.invalid"})
    hostile_origin_status, hostile_origin_body, hostile_origin_headers = fixture.request(app, "/api/v4/products", headers={"Origin": "https://evil.invalid"})

    double_root = _case_root(work, "double")
    double_obs = fixture.base_observation(
        base_price_twd=49, already_included_in_base=1, stored_confirmed_coupon_price_twd=0,
        pre_coupon_comparison_price_twd=99, pre_coupon_comparison_source="SYN-LISTED-BASE-EVIDENCE",
    )
    double_item = fixture.repository(double_root, observations=[double_obs]).search("")["items"][0]

    mismatch_root = _case_root(work, "mismatch")
    mismatch_item = fixture.repository(mismatch_root, observations=[fixture.base_observation(coupon_sku_id="OTHER")]).search("")["items"][0]

    quantity_root = _case_root(work, "quantity")
    quantity_obs = fixture.base_observation(base_price_twd=100, discount_twd=50, discount_scope="ORDER_TOTAL", stored_confirmed_coupon_price_twd=75)
    quantity_item = fixture.repository(quantity_root, series=[fixture.base_series(minimum_purchase_quantity=2)], observations=[quantity_obs]).search("")["items"][0]

    private_root = _case_root(work, "private")
    private_item = fixture.repository(private_root, observations=[fixture.base_observation(eligibility_profile="FIRST_PURCHASE_CONFIRMED_SYNTHETIC")]).search("")["items"][0]

    expired_root = _case_root(work, "expired")
    expired_obs = fixture.base_observation(valid_until_utc="2026-11-04T23:59:59Z")
    expired_detail = fixture.repository(expired_root, observations=[expired_obs]).detail("series-1")

    zero_root = _case_root(work, "zero")
    zero_item = fixture.repository(zero_root, observations=[fixture.base_observation(base_price_twd=50, discount_twd=50, stored_confirmed_coupon_price_twd=0)]).search("")["items"][0]

    invalid_time_root = _case_root(work, "invalid-time")
    invalid_time_item = fixture.repository(invalid_time_root, observations=[fixture.base_observation(observed_at_utc="not-a-time")]).search("")["items"][0]

    revoked_root = _case_root(work, "revoked")
    revoked_item = fixture.repository(revoked_root, revoked="2026-11-05T03:00:00Z").search("")["items"][0]

    return {
        "search": {"status": search_status, "body": search, "headers": search_headers},
        "detail": {"status": detail_status, "body": detail, "headers": detail_headers},
        "http_negative": {
            "304": {"status": status_304, "body": body_304, "headers": headers_304},
            "404": {"status": status_404, "body": body_404, "headers": headers_404},
            "405": {"status": status_405, "body": body_405, "headers": headers_405},
            "OPTIONS": {"status": status_options, "body": body_options, "headers": headers_options},
            "hostile_host": {"status": hostile_host_status, "body": hostile_host_body, "headers": hostile_host_headers},
            "hostile_origin": {"status": hostile_origin_status, "body": hostile_origin_body, "headers": hostile_origin_headers},
        },
        "coupon_negative": {
            "double_discount": double_item,
            "wrong_sku": mismatch_item,
            "quantity_order": quantity_item,
            "private_coupon": private_item,
            "expired": expired_detail,
            "zero_unknown_shipping": zero_item,
            "invalid_timestamp": invalid_time_item,
            "revoked_source": revoked_item,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=False)
    try:
        print(json.dumps(run(args.root.resolve(), args.work.resolve()), ensure_ascii=False, separators=(",", ":")))
    finally:
        shutil.rmtree(args.work, ignore_errors=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
