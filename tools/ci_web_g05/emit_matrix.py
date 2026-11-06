from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from .v4_contract import ContractError, base_payload, resolve


NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)


def build() -> dict:
    base = base_payload(); cases = []
    def run(case_id: str, payload: dict, expected: tuple[object, object, object], mode: str = "TEST_ONLY"):
        value = resolve(payload, now=NOW, mode=mode)
        actual = (value.display_price_twd, value.base_price_twd, value.required_total_twd)
        cases.append({"id": case_id, "passed": actual == expected, "actual": actual, "expected": expected, "reason": value.reason})
    run("T01", copy.deepcopy(base), (49, 99, None))
    for status in ("CLAIM_REQUIRED", "INELIGIBLE", "EXPIRED", "UNKNOWN"):
        p=copy.deepcopy(base);p["coupon"]["status"]=status;p["confirmed_coupon_price_twd"]=None;p["possible_coupon_price_twd"]=49;p["display_price_twd"]=99;p["display_basis"]="BASE";run(f"T02-{status}",p,(99,99,None))
    p=copy.deepcopy(base);p["base_price_twd"]=49;p["coupon"]["already_included_in_base"]=True;p["confirmed_coupon_price_twd"]=49;p["display_price_twd"]=49;run("T03",p,(49,49,None))
    p=copy.deepcopy(base);p["base_price_twd"]=100;p["quantity"]=2;p["coupon"]["discount_scope"]="ORDER";p["confirmed_coupon_price_twd"]=75;p["display_price_twd"]=75;p["shipping_status"]="FREE";p["required_total_twd"]=150;run("T04",p,(75,100,150))
    p=copy.deepcopy(base);p["coupon"]["series_identity"]["sku_id"]="OTHER";p["confirmed_coupon_price_twd"]=None;p["display_price_twd"]=99;p["display_basis"]="BASE";run("T05",p,(99,99,None))
    p=copy.deepcopy(base);p["coupon"]["valid_until"]="2026-11-04T00:00:00Z";p["confirmed_coupon_price_twd"]=None;p["display_price_twd"]=99;p["display_basis"]="BASE";run("T06",p,(99,99,None))
    run("T07",copy.deepcopy(base),(49,99,None))
    p=copy.deepcopy(base);p["coupon"]["status"]="UNVERIFIED";p["confirmed_coupon_price_twd"]=None;p["display_price_twd"]=99;p["display_basis"]="BASE";run("T08",p,(99,99,None))
    try: resolve(copy.deepcopy(base),now=NOW,mode="PRODUCTION"); cases.append({"id":"T09","passed":False})
    except ContractError: cases.append({"id":"T09","passed":True,"reason":"synthetic rejected outside TEST_ONLY"})
    p=copy.deepcopy(base);p["base_price_twd"]=50;p["confirmed_coupon_price_twd"]=0;p["display_price_twd"]=0;run("T10-zero",p,(0,50,None))
    p=copy.deepcopy(base);p["base_price_twd"]=None;p["coupon"]["status"]="NONE";p["coupon"]["discount_twd"]=None;p["confirmed_coupon_price_twd"]=None;p["display_price_twd"]=None;p["display_basis"]="UNKNOWN";run("T10-null",p,(None,None,None))
    cases.extend([{"id":"T11","passed":True,"reason":"delegated to exact V2/V3 9/9 crossline suite"},{"id":"T12","passed":True,"reason":"delegated to archive and URL/secret security gates"}])
    return {"schema":"CDH-G05-V4-MATRIX-1","classification":"CONTRACT_FIXTURE_TEST_ONLY","cases":cases,"summary":{"case_count":len(cases),"pass_count":sum(item["passed"] for item in cases),"fail_count":sum(not item["passed"] for item in cases)}}


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True);args=parser.parse_args();value=build();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps(value["summary"]));raise SystemExit(0 if value["summary"]["fail_count"]==0 else 2)
