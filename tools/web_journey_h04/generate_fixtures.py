from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from v4_contract import validate_v4


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "tools" / "web_journey_h04" / "site" / "fixtures.json"
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def ident(key: str, seller: str | None = None) -> dict[str, str]:
    return {"platform": "COUPANG_TW", "product_id": f"SYN-P-{key}", "sku_id": f"SYN-SKU-{key}", "seller_id": seller or f"SYN-SELLER-{key}", "condition": "NEW", "package_signature": "1x100ml"}


def item(key: str, title: str, base: int | None, status: str, *, discount: int = 0, confirmed: int | None = None, possible: int | None = None, included: bool = False, seller_match: bool = True, empty_history: bool = False, shipping: str = "UNKNOWN", order: bool = False) -> dict[str, object]:
    series = ident(key)
    bound = deepcopy(series)
    if not seller_match:
        bound["seller_id"] = "SYN-OTHER-SELLER"
    coupon = {"coupon_id": f"SYN-COUPON-{key}", "status": status, "discount_twd": discount, "already_included_in_base": included, "discount_scope": "ORDER" if order else "ITEM", "eligibility_profile": "SYN-ELIGIBLE" if status == "CONFIRMED_APPLICABLE" else None, "valid_from": "2026-11-01T00:00:00Z", "valid_until": "2026-11-30T23:59:59Z" if status != "EXPIRED" else "2026-11-04T00:00:00Z", "scope_evidence": "SYN-TEST-EVIDENCE" if status == "CONFIRMED_APPLICABLE" else None, "bound_identity": bound}
    effective_confirmed = confirmed if status == "CONFIRMED_APPLICABLE" and seller_match else None
    display = effective_confirmed if effective_confirmed is not None else base
    before = [] if empty_history or base is None else [{"observed_at": "2026-11-03T08:00:00Z", "price_twd": base, "series_identity": series, "source_id": f"SYN-SOURCE-{key}-BASE", "scope_evidence": "SYN-TEST-EVIDENCE"}]
    after = [] if empty_history or effective_confirmed is None else [{"observed_at": "2026-11-05T08:00:00Z", "price_twd": effective_confirmed, "series_identity": series, "source_id": f"SYN-SOURCE-{key}-COUPON", "scope_evidence": "SYN-TEST-EVIDENCE", "coupon_status": "CONFIRMED_APPLICABLE", "coupon_id": coupon["coupon_id"], "eligibility_profile": "SYN-ELIGIBLE"}]
    value: dict[str, object] = {"schema_version": "CDH-COUPON-PRICE-V4", "title": title, "series_identity": series, "data_classification": "SYNTHETIC_FIXTURE", "source_id": f"SYN-SOURCE-{key}", "observed_at": "2026-11-05T08:00:00Z", "base_price_twd": base, "coupon": coupon, "confirmed_coupon_price_twd": effective_confirmed, "possible_coupon_price_twd": possible, "display_price_twd": display, "display_basis": "CONFIRMED_COUPON" if effective_confirmed is not None else ("BASE_PRICE" if base is not None else "UNAVAILABLE"), "shipping_status": shipping, "required_total_twd": None, "history": {"before_coupon": before, "confirmed_after_coupon": after}}
    if order:
        value.update({"minimum_quantity": 2, "required_merchandise_total_twd": 150})
    validate_v4(value, now=NOW)
    return value


def main() -> None:
    fixtures = [
        item("CONFIRMED", "TEST_ONLY｜確認券折商品", 99, "CONFIRMED_APPLICABLE", discount=50, confirmed=49),
        item("CLAIM", "TEST_ONLY｜尚未領券商品", 100, "CLAIM_REQUIRED", discount=20, possible=80),
        item("EXPIRED", "TEST_ONLY｜過期券商品", 120, "EXPIRED", discount=30, possible=90),
        item("SELLER", "TEST_ONLY｜不同賣家券商品", 110, "CONFIRMED_APPLICABLE", discount=40, possible=70, seller_match=False),
        item("EMPTY", "TEST_ONLY｜空歷史商品", 88, "NONE", empty_history=True),
        item("ZERO", "TEST_ONLY｜零元券後商品", 50, "CONFIRMED_APPLICABLE", discount=50, confirmed=0),
        item("UNKNOWN", "TEST_ONLY｜價格未知商品", None, "UNKNOWN"),
        item("INCLUDED", "TEST_ONLY｜券已含於基價", 49, "CONFIRMED_APPLICABLE", discount=50, confirmed=49, included=True),
        item("ORDER", "TEST_ONLY｜最低兩件整筆券", 100, "CONFIRMED_APPLICABLE", discount=50, confirmed=75, order=True),
    ]
    output = {"schema_version": "CDH-H04-SYNTHETIC-SITE-1", "authority": "AUTHORIZED_SYNTHETIC_OFFLINE_R06_H_ONLY", "products": fixtures, "invalid_timestamp_case": {"id": "INVALID_TIME", "title": "TEST_ONLY｜非法時間戳", "observed_at": "2026-11-03T010:00:00Z", "error_code": "INVALID_TIMESTAMP"}}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "products": len(fixtures), "output": str(OUTPUT)}))


if __name__ == "__main__":
    main()
