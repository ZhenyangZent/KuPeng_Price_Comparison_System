from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

AUTHORITY = "AUTHORIZED_SYNTHETIC_OFFLINE_R06_B_ONLY"
FIXED_GENERATED_AT = "2026-11-05T00:00:00Z"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _series(key: str, *, minimum_quantity: int = 1) -> dict[str, object]:
    suffix=key.upper().replace("-","_")
    return {"series_key":key,"title":f"Synthetic {key}","platform":"COUPANG_TW","product_id":f"SYN-P-{suffix}","sku_id":f"SYN-SKU-{suffix}","seller_id":f"SYN-SELLER-{suffix}","item_condition":"NEW","package_signature":"1x100ml","spec_signature":"volume=100ml","minimum_purchase_quantity":minimum_quantity,"shipping_status":"UNKNOWN","identity_state":"EXACT","data_classification":"SYNTHETIC_FIXTURE"}


def _observation(series: dict[str, object], *, source_id: str, base: int | None = 99, status: str = "CONFIRMED_APPLICABLE", discount: int | None = 50, scope: str = "UNIT", confirmed: int | None = 49, possible: int | None = None, already_included: bool = False, comparison: int | None = None, comparison_source: str | None = None, coupon_sku: str | None = None) -> dict[str, object]:
    return {"series_key":series["series_key"],"source_id":source_id,"observed_at_utc":"2026-11-04T02:00:00Z","base_price_twd":base,"base_price_basis":"LISTED_ELIGIBLE" if base is not None else "UNAVAILABLE","coupon_id":f"SYN-COUPON-{series['series_key'].upper()}","coupon_status":status,"discount_twd":discount,"discount_scope":scope,"already_included_in_base":1 if already_included else 0,"eligibility_profile":"SYN-ELIGIBLE-PROFILE","valid_from_utc":"2026-11-01T00:00:00Z","valid_until_utc":"2026-11-30T23:59:59Z","scope_evidence":f"SYN-EVIDENCE-{source_id}","coupon_product_id":series["product_id"],"coupon_sku_id":coupon_sku or series["sku_id"],"coupon_seller_id":series["seller_id"],"stored_confirmed_coupon_price_twd":confirmed,"stored_possible_coupon_price_twd":possible,"pre_coupon_comparison_price_twd":comparison,"pre_coupon_comparison_source":comparison_source,"shipping_fee_twd":None,"mandatory_fee_twd":None,"data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1}


def active_cases() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    series=[_series("confirmed"),_series("claim-required"),_series("expired-coupon"),_series("unknown-coupon"),_series("already-included"),_series("quantity-two",minimum_quantity=2),_series("wrong-sku"),_series("zero"),_series("unavailable")]
    by_key={item["series_key"]:item for item in series}
    observations=[
        _observation(by_key["confirmed"],source_id="confirmed"),
        _observation(by_key["claim-required"],source_id="claim",status="CLAIM_REQUIRED",confirmed=None,possible=49),
        _observation(by_key["expired-coupon"],source_id="expired",status="EXPIRED",confirmed=None),
        _observation(by_key["unknown-coupon"],source_id="unknown",status="UNKNOWN",confirmed=None,possible=49),
        _observation(by_key["already-included"],source_id="included",base=49,already_included=True,confirmed=49,comparison=99,comparison_source="SYN-LISTED-BASE"),
        _observation(by_key["quantity-two"],source_id="quantity",base=100,scope="ORDER_TOTAL",confirmed=75),
        _observation(by_key["wrong-sku"],source_id="wrong",coupon_sku="SYN-SKU-OTHER"),
        _observation(by_key["zero"],source_id="zero",base=50,confirmed=0),
        _observation(by_key["unavailable"],source_id="unavailable",base=None,confirmed=None),
    ]
    return series,observations


def build_snapshot(root: Path, *, permission: str, expires_at: str | None, revoked_at: str | None, series: list[dict[str, object]], observations: list[dict[str, object]]) -> dict[str, object]:
    root.mkdir(parents=True,exist_ok=False)
    database=root/"coupon.sqlite3"; authority=root/"coupon.authority.json"
    schema=(Path(__file__).resolve().parents[1]/"SCHEMA.sql").read_text(encoding="utf-8")
    connection=sqlite3.connect(database); connection.executescript(schema); connection.execute("INSERT INTO coupon_schema VALUES(1)"); connection.execute("INSERT INTO coupon_metadata VALUES(?,?,?,?,?,?,?)",(f"snapshot-{root.name}","CDH-COUPON-PRICE-V4","SYNTHETIC_FIXTURE",permission,FIXED_GENERATED_AT,expires_at,revoked_at))
    for item in series: connection.execute("INSERT INTO coupon_series VALUES(:series_key,:title,:platform,:product_id,:sku_id,:seller_id,:item_condition,:package_signature,:spec_signature,:minimum_purchase_quantity,:shipping_status,:identity_state,:data_classification)",item)
    fields=("series_key","source_id","observed_at_utc","base_price_twd","base_price_basis","coupon_id","coupon_status","discount_twd","discount_scope","already_included_in_base","eligibility_profile","valid_from_utc","valid_until_utc","scope_evidence","coupon_product_id","coupon_sku_id","coupon_seller_id","stored_confirmed_coupon_price_twd","stored_possible_coupon_price_twd","pre_coupon_comparison_price_twd","pre_coupon_comparison_source","shipping_fee_twd","mandatory_fee_twd","data_classification","is_synthetic")
    for index,item in enumerate(observations,1): connection.execute(f"INSERT INTO coupon_observations(observation_id,{','.join(fields)}) VALUES(? ,{','.join('?' for _ in fields)})",(index,*(item[name] for name in fields)))
    connection.commit(); connection.close(); database_sha=_sha256(database)
    authority.write_text(json.dumps({"schema_version":"CDH-B10-COUPON-SNAPSHOT-AUTHORITY-1","database_sha256":database_sha,"data_classification":"SYNTHETIC_FIXTURE","contains_private_data":False,"authorized_use":AUTHORITY},sort_keys=True),encoding="utf-8")
    return {"directory":root.name,"database":"coupon.sqlite3","database_sha256":database_sha,"authority":"coupon.authority.json","authority_sha256":_sha256(authority),"series_count":len(series),"observation_count":len(observations),"permission":permission}


def build_fixture_suite(root: Path) -> dict[str, object]:
    if root.exists(): raise FileExistsError("fixture suite output must not already exist")
    root.mkdir(parents=True)
    series,observations=active_cases(); one_series=[_series("source-state")]; one_observation=[_observation(one_series[0],source_id="source-state")]; empty_series=[_series("empty-history")]
    snapshots=[
        build_snapshot(root/"active",permission="ACTIVE_SYNTHETIC_FIXTURE",expires_at="2027-01-01T00:00:00Z",revoked_at=None,series=series,observations=observations),
        build_snapshot(root/"expired-source",permission="ACTIVE_SYNTHETIC_FIXTURE",expires_at="2026-11-05T03:59:59Z",revoked_at=None,series=one_series,observations=one_observation),
        build_snapshot(root/"revoked-source",permission="REVOKED",expires_at="2027-01-01T00:00:00Z",revoked_at="2026-11-05T03:00:00Z",series=one_series,observations=one_observation),
        build_snapshot(root/"empty-history",permission="ACTIVE_SYNTHETIC_FIXTURE",expires_at="2027-01-01T00:00:00Z",revoked_at=None,series=empty_series,observations=[]),
    ]
    manifest={"schema_version":"CDH-B11-FIXTURE-SUITE-1","classification":"CONTRACT_FIXTURE_TEST_ONLY","snapshots":snapshots}
    (root/"FIXTURE_MANIFEST.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return manifest
