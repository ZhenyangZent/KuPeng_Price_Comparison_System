from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import make_server

FRONTEND_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = FRONTEND_ROOT / "upstream" / "B11_RELEASE" / "services" / "price_coupon_v4"
if not (SERVICE_ROOT / "price_coupon_v4" / "api.py").is_file():
    raise RuntimeError(f"Pinned B11 release source is unavailable: {SERVICE_ROOT}")
sys.path.insert(0, str(SERVICE_ROOT))

from price_coupon_v4 import CouponPriceRepository, CouponPriceV4App  # noqa: E402

NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def series(key: str, title: str, sku: str, seller: str, *, quantity: int = 1) -> dict[str, object]:
    return {
        "series_key": key, "title": title, "platform": "COUPANG_TW", "product_id": "SYN-P-1", "sku_id": sku,
        "seller_id": seller, "item_condition": "NEW", "package_signature": "1x100ml", "spec_signature": f"sku={sku}",
        "minimum_purchase_quantity": quantity, "shipping_status": "UNKNOWN", "identity_state": "EXACT", "data_classification": "SYNTHETIC_FIXTURE"
    }


def observation(key: str, source: str, observed: str, sku: str, seller: str, *, base: int | None = 99, status: str = "CONFIRMED_APPLICABLE", discount: int | None = 50, scope: str = "UNIT", confirmed: int | None = 49, possible: int | None = None, valid_until: str = "2026-11-30T23:59:59Z") -> dict[str, object]:
    return {
        "series_key": key, "source_id": source, "observed_at_utc": observed, "base_price_twd": base,
        "base_price_basis": "LISTED_ELIGIBLE" if base is not None else "UNKNOWN", "coupon_id": None if status == "NONE" else f"COUPON-{key}",
        "coupon_status": status, "discount_twd": discount, "discount_scope": scope, "already_included_in_base": 0,
        "eligibility_profile": None if status == "NONE" else "SYN-ELIGIBLE-PROFILE", "valid_from_utc": None if status == "NONE" else "2026-11-01T00:00:00Z",
        "valid_until_utc": None if status == "NONE" else valid_until, "scope_evidence": None if status == "NONE" else f"SCOPE-{key}",
        "coupon_product_id": None if status == "NONE" else "SYN-P-1", "coupon_sku_id": None if status == "NONE" else sku,
        "coupon_seller_id": None if status == "NONE" else seller, "stored_confirmed_coupon_price_twd": confirmed,
        "stored_possible_coupon_price_twd": possible, "pre_coupon_comparison_price_twd": None, "pre_coupon_comparison_source": None,
        "shipping_fee_twd": None, "mandatory_fee_twd": None, "data_classification": "SYNTHETIC_FIXTURE", "is_synthetic": 1
    }


def build_snapshot(root: Path) -> tuple[Path, Path]:
    database, authority = root / "b10-actual.sqlite3", root / "b10-actual.authority.json"
    schema = (SERVICE_ROOT / "SCHEMA.sql").read_text(encoding="utf-8")
    connection = sqlite3.connect(database)
    connection.executescript(schema)
    connection.execute("INSERT INTO coupon_schema VALUES(1)")
    connection.execute("INSERT INTO coupon_metadata VALUES(?,?,?,?,?,?,?)", ("a10-b10-actual", "CDH-COUPON-PRICE-V4", "SYNTHETIC_FIXTURE", "ACTIVE_SYNTHETIC_FIXTURE", "2026-11-01T00:00:00Z", "2027-01-01T00:00:00Z", None))
    series_rows = [
        series("series-confirmed", "B10 Actual｜Confirmed coupon", "SYN-SKU-CONFIRMED", "SYN-SELLER-A"),
        series("series-claim", "B10 Actual｜Claim required", "SYN-SKU-CLAIM", "SYN-SELLER-A"),
        series("series-expired", "B10 Actual｜Expired coupon", "SYN-SKU-EXPIRED", "SYN-SELLER-B"),
        series("series-zero", "B10 Actual｜Zero product price", "SYN-SKU-ZERO", "SYN-SELLER-C"),
        series("series-unknown", "B10 Actual｜Unavailable price", "SYN-SKU-UNKNOWN", "SYN-SELLER-D"),
        series("series-multi", "B10 Actual｜Two-item order coupon", "SYN-SKU-MULTI", "SYN-SELLER-E", quantity=2),
        series("series-variant", "B10 Actual｜Confirmed coupon", "SYN-SKU-OTHER", "SYN-SELLER-F")
    ]
    for row in series_rows:
        connection.execute("INSERT INTO coupon_series VALUES(:series_key,:title,:platform,:product_id,:sku_id,:seller_id,:item_condition,:package_signature,:spec_signature,:minimum_purchase_quantity,:shipping_status,:identity_state,:data_classification)", row)
    observations = [
        observation("series-confirmed", "SRC-CONF-OLD", "2026-11-03T02:00:00Z", "SYN-SKU-CONFIRMED", "SYN-SELLER-A", base=129, discount=50, confirmed=79),
        observation("series-confirmed", "SRC-CONF-NEW", "2026-11-04T02:00:00Z", "SYN-SKU-CONFIRMED", "SYN-SELLER-A"),
        observation("series-claim", "SRC-CLAIM", "2026-11-04T02:00:00Z", "SYN-SKU-CLAIM", "SYN-SELLER-A", base=100, status="CLAIM_REQUIRED", discount=25, confirmed=None, possible=75),
        observation("series-expired", "SRC-EXPIRED", "2026-11-04T02:00:00Z", "SYN-SKU-EXPIRED", "SYN-SELLER-B", base=120, discount=40, confirmed=80, valid_until="2026-11-04T23:59:59Z"),
        observation("series-zero", "SRC-ZERO", "2026-11-04T02:00:00Z", "SYN-SKU-ZERO", "SYN-SELLER-C", base=50, discount=50, confirmed=0),
        observation("series-unknown", "SRC-UNKNOWN", "2026-11-04T02:00:00Z", "SYN-SKU-UNKNOWN", "SYN-SELLER-D", base=None, status="NONE", discount=None, scope="NONE", confirmed=None),
        observation("series-multi", "SRC-MULTI", "2026-11-04T02:00:00Z", "SYN-SKU-MULTI", "SYN-SELLER-E", base=100, discount=50, scope="ORDER_TOTAL", confirmed=75),
        observation("series-variant", "SRC-VARIANT", "2026-11-04T02:00:00Z", "SYN-SKU-OTHER", "SYN-SELLER-F", base=109, discount=20, confirmed=89)
    ]
    fields = ("series_key","source_id","observed_at_utc","base_price_twd","base_price_basis","coupon_id","coupon_status","discount_twd","discount_scope","already_included_in_base","eligibility_profile","valid_from_utc","valid_until_utc","scope_evidence","coupon_product_id","coupon_sku_id","coupon_seller_id","stored_confirmed_coupon_price_twd","stored_possible_coupon_price_twd","pre_coupon_comparison_price_twd","pre_coupon_comparison_source","shipping_fee_twd","mandatory_fee_twd","data_classification","is_synthetic")
    for index, row in enumerate(observations, 1):
        connection.execute(f"INSERT INTO coupon_observations(observation_id,{','.join(fields)}) VALUES(?,{','.join('?' for _ in fields)})", (index, *(row[name] for name in fields)))
    connection.commit(); connection.close()
    authority.write_text(json.dumps({"schema_version":"CDH-B10-COUPON-SNAPSHOT-AUTHORITY-1","database_sha256":sha256(database),"data_classification":"SYNTHETIC_FIXTURE","contains_private_data":False,"authorized_use":"AUTHORIZED_SYNTHETIC_OFFLINE_R06_B_ONLY"}, sort_keys=True), encoding="utf-8")
    return database, authority


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--runtime-root", type=Path, required=True)
    args = parser.parse_args()
    args.runtime_root.mkdir(parents=True, exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix="b10-wsgi-", dir=args.runtime_root))
    database, authority = build_snapshot(runtime)
    repository = CouponPriceRepository(database, authority_file=authority, allowed_root=runtime, clock=lambda: NOW)
    server = make_server("127.0.0.1", args.port, CouponPriceV4App(repository))
    print(json.dumps({"status":"B11_ACTUAL_WSGI_READY","upstream_release_sha256":"6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a","url":f"http://127.0.0.1:{args.port}","database_sha256":sha256(database),"data_version":repository.data_version,"runtime":str(runtime)}, ensure_ascii=False), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
