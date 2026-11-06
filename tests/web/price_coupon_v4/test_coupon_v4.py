from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"services"/"price_coupon_v4"))
sys.path.insert(0,str(ROOT/"services"/"price_quality_adapter"))
sys.path.insert(0,str(ROOT/"services"/"price_query_v3"))

from price_coupon_v4 import CouponPriceRepository,CouponPriceV4App,CouponRepositoryError  # noqa:E402
from price_query_v3 import PriceQueryV3App  # noqa:E402
from tests.web.price_query_v3.test_adapter import repo as b09_repo  # noqa:E402

NOW=datetime(2026,11,5,4,0,tzinfo=timezone.utc)
SCHEMA=(ROOT/"services"/"price_coupon_v4"/"SCHEMA.sql").read_text(encoding="utf-8")


def digest(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()


def base_series(**changes):
    value={"series_key":"series-1","title":"Synthetic coupon item","platform":"COUPANG_TW","product_id":"SYN-P-1","sku_id":"SYN-SKU-1","seller_id":"SYN-SELLER-1","item_condition":"NEW","package_signature":"1x100ml","spec_signature":"volume=100ml","minimum_purchase_quantity":1,"shipping_status":"UNKNOWN","identity_state":"EXACT","data_classification":"SYNTHETIC_FIXTURE"}
    value.update(changes); return value


def base_observation(**changes):
    value={"series_key":"series-1","source_id":"SYN-SOURCE-1","observed_at_utc":"2026-11-04T02:00:00Z","base_price_twd":99,"base_price_basis":"LISTED_ELIGIBLE","coupon_id":"SYN-COUPON-1","coupon_status":"CONFIRMED_APPLICABLE","discount_twd":50,"discount_scope":"UNIT","already_included_in_base":0,"eligibility_profile":"SYN-ELIGIBLE-PROFILE","valid_from_utc":"2026-11-01T00:00:00Z","valid_until_utc":"2026-11-30T23:59:59Z","scope_evidence":"SYN-TEST-EVIDENCE","coupon_product_id":"SYN-P-1","coupon_sku_id":"SYN-SKU-1","coupon_seller_id":"SYN-SELLER-1","stored_confirmed_coupon_price_twd":49,"stored_possible_coupon_price_twd":None,"pre_coupon_comparison_price_twd":None,"pre_coupon_comparison_source":None,"shipping_fee_twd":None,"mandatory_fee_twd":None,"data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1}
    value.update(changes); return value


def make_fixture(root:Path,*,series=None,observations=None,permission="ACTIVE_SYNTHETIC_FIXTURE",expires="2027-01-01T00:00:00Z",revoked=None):
    database=root/"coupon.sqlite3"; authority=root/"coupon.authority.json"
    connection=sqlite3.connect(database); connection.executescript(SCHEMA); connection.execute("INSERT INTO coupon_schema VALUES(1)")
    connection.execute("INSERT INTO coupon_metadata VALUES(?,?,?,?,?,?,?)",("snapshot-v4","CDH-COUPON-PRICE-V4","SYNTHETIC_FIXTURE",permission,"2026-11-01T00:00:00Z",expires,revoked))
    for item in series or [base_series()]:
        connection.execute("INSERT INTO coupon_series VALUES(:series_key,:title,:platform,:product_id,:sku_id,:seller_id,:item_condition,:package_signature,:spec_signature,:minimum_purchase_quantity,:shipping_status,:identity_state,:data_classification)",item)
    fields=("series_key","source_id","observed_at_utc","base_price_twd","base_price_basis","coupon_id","coupon_status","discount_twd","discount_scope","already_included_in_base","eligibility_profile","valid_from_utc","valid_until_utc","scope_evidence","coupon_product_id","coupon_sku_id","coupon_seller_id","stored_confirmed_coupon_price_twd","stored_possible_coupon_price_twd","pre_coupon_comparison_price_twd","pre_coupon_comparison_source","shipping_fee_twd","mandatory_fee_twd","data_classification","is_synthetic")
    for index,item in enumerate(observations if observations is not None else [base_observation()],1):
        connection.execute(f"INSERT INTO coupon_observations(observation_id,{','.join(fields)}) VALUES(? ,{','.join('?' for _ in fields)})",(index,*(item[name] for name in fields)))
    connection.commit(); connection.close()
    authority.write_text(json.dumps({"schema_version":"CDH-B10-COUPON-SNAPSHOT-AUTHORITY-1","database_sha256":digest(database),"data_classification":"SYNTHETIC_FIXTURE","contains_private_data":False,"authorized_use":"AUTHORIZED_SYNTHETIC_OFFLINE_R06_B_ONLY"},sort_keys=True),encoding="utf-8")
    return database,authority


def repository(root:Path,**kwargs):
    database,authority=make_fixture(root,**kwargs)
    return CouponPriceRepository(database,authority_file=authority,allowed_root=root,clock=lambda:NOW)


def request(app,path,method="GET",headers=None):
    captured={}; parts=path.split("?",1); environ={"REQUEST_METHOD":method,"PATH_INFO":parts[0],"QUERY_STRING":parts[1] if len(parts)>1 else "","wsgi.input":io.BytesIO()}
    for key,value in (headers or {}).items(): environ["HTTP_"+key.upper().replace("-","_")]=value
    def start(status,response_headers): captured["status"]=int(status.split()[0]); captured["headers"]=dict(response_headers)
    body=b"".join(app(environ,start)); return captured["status"],json.loads(body) if body else None,captured["headers"]


class CouponV4Tests(unittest.TestCase):
    def setUp(self):
        base=ROOT/"review"/"B10"/"tmp_tests"; base.mkdir(parents=True,exist_ok=True)
        self.temp=Path(tempfile.mkdtemp(prefix="case-",dir=base))

    def tearDown(self): shutil.rmtree(self.temp)

    def test_t01_confirmed_coupon_is_primary_and_base_preserved(self):
        r=repository(self.temp); item=r.search("coupon")["items"][0]
        self.assertEqual((item["base_price_twd"],item["confirmed_coupon_price_twd"],item["display_price_twd"]),(99,49,49))
        self.assertEqual(item["display_basis"],"CONFIRMED_COUPON")
        self.assertEqual(item["shipping_status"],"UNKNOWN"); self.assertIsNone(item["required_total_twd"])

    def test_shared_synthetic_fixture_is_explicit_and_consumable(self):
        value=json.loads((ROOT/"services"/"price_coupon_v4"/"fixtures"/"synthetic_coupon_v4.json").read_text(encoding="utf-8"))
        self.assertEqual(value["schema_version"],"CDH-COUPON-PRICE-V4"); self.assertEqual(value["classification"],"CONTRACT_FIXTURE_TEST_ONLY")
        self.assertEqual(value["product"]["display_price_twd"],49); self.assertEqual(value["product"]["base_price_twd"],99)

    def test_t02_nonconfirmed_statuses_never_change_primary(self):
        for index,status in enumerate(("CLAIM_REQUIRED","UNVERIFIED","INELIGIBLE","EXPIRED","UNKNOWN","NONE")):
            root=self.temp/str(index); root.mkdir(); r=repository(root,observations=[base_observation(coupon_status=status,stored_confirmed_coupon_price_twd=None,stored_possible_coupon_price_twd=49)])
            item=r.search("")["items"][0]
            self.assertEqual((item["display_price_twd"],item["display_basis"]),(99,"BASE_PRICE")); self.assertIsNone(item["confirmed_coupon_price_twd"])
            self.assertEqual(item["possible_coupon_price_twd"],49 if status in {"CLAIM_REQUIRED","UNVERIFIED","UNKNOWN"} else None)

    def test_t03_already_included_coupon_is_not_deducted_twice(self):
        obs=base_observation(base_price_twd=49,already_included_in_base=1,stored_confirmed_coupon_price_twd=49,pre_coupon_comparison_price_twd=99,pre_coupon_comparison_source="SYN-LISTED-BASE-EVIDENCE")
        r=repository(self.temp,observations=[obs]); item=r.detail("series-1")
        self.assertEqual(item["product"]["display_price_twd"],49); self.assertEqual(item["product"]["before_coupon_price_twd"],99)
        self.assertEqual(item["product"]["coupon"]["pre_coupon_comparison_source"],"SYN-LISTED-BASE-EVIDENCE")
        self.assertEqual(item["history"]["before_coupon"][0]["price_twd"],99); self.assertEqual(item["history"]["confirmed_after_coupon"][0]["price_twd"],49)

    def test_t04_order_coupon_two_item_quantity(self):
        obs=base_observation(base_price_twd=100,discount_twd=50,discount_scope="ORDER_TOTAL",stored_confirmed_coupon_price_twd=75)
        item=repository(self.temp,series=[base_series(minimum_purchase_quantity=2)],observations=[obs]).search("")["items"][0]
        self.assertEqual(item["display_price_twd"],75); self.assertEqual(item["minimum_item_spend_twd"],150); self.assertIsNone(item["required_total_twd"])

    def test_t05_cross_sku_or_seller_coupon_is_rejected(self):
        for index,change in enumerate(({"coupon_sku_id":"OTHER"},{"coupon_seller_id":"OTHER"},{"coupon_product_id":"OTHER"})):
            root=self.temp/str(index); root.mkdir(); item=repository(root,observations=[base_observation(**change)]).search("")["items"][0]
            self.assertEqual(item["display_price_twd"],99); self.assertIsNone(item["confirmed_coupon_price_twd"]); self.assertIn("COUPON_IDENTITY_MISMATCH",item["quality_flags"])

    def test_t06_each_historical_coupon_stays_with_its_observation(self):
        old=base_observation(source_id="old",observed_at_utc="2026-11-02T02:00:00Z",coupon_id="OLD",discount_twd=9,stored_confirmed_coupon_price_twd=90)
        new=base_observation(source_id="new",observed_at_utc="2026-11-04T02:00:00Z",coupon_id="NEW",discount_twd=50,stored_confirmed_coupon_price_twd=49)
        detail=repository(self.temp,observations=[new,old]).detail("series-1")
        self.assertEqual([(x["coupon_id"],x["price_twd"]) for x in detail["history"]["confirmed_after_coupon"]],[("OLD",90),("NEW",49)])

    def test_t07_unknown_shipping_never_becomes_free_total(self):
        item=repository(self.temp,observations=[base_observation(base_price_twd=50,discount_twd=50,stored_confirmed_coupon_price_twd=0)]).search("")["items"][0]
        self.assertEqual(item["display_price_twd"],0); self.assertIsNone(item["required_total_twd"]); self.assertEqual(item["shipping_status"],"UNKNOWN")

    def test_t08_private_eligibility_is_retained_not_generalized(self):
        item=repository(self.temp,observations=[base_observation(eligibility_profile="FIRST_PURCHASE_CONFIRMED_SYNTHETIC")]).search("")["items"][0]
        self.assertEqual(item["coupon"]["eligibility_profile"],"FIRST_PURCHASE_CONFIRMED_SYNTHETIC"); self.assertNotIn("public",json.dumps(item).lower())

    def test_t09_source_permission_expiry_suppresses_price_and_history(self):
        r=repository(self.temp,expires="2026-11-05T03:59:59Z"); detail=r.detail("series-1")
        self.assertEqual(detail["product"]["display_basis"],"PRICE_UNAVAILABLE"); self.assertIsNone(detail["product"]["display_price_twd"])
        self.assertEqual(detail["history"],{"before_coupon":[],"confirmed_after_coupon":[]})

    def test_t10_zero_and_null_are_distinct(self):
        zero=repository(self.temp,observations=[base_observation(base_price_twd=50,discount_twd=50,stored_confirmed_coupon_price_twd=0)]).search("")["items"][0]
        self.assertEqual(zero["display_price_twd"],0)
        root=self.temp/"null"; root.mkdir(); unknown=repository(root,observations=[base_observation(base_price_twd=None,stored_confirmed_coupon_price_twd=None)]).search("")["items"][0]
        self.assertIsNone(unknown["display_price_twd"]); self.assertEqual(unknown["display_basis"],"PRICE_UNAVAILABLE")

    def test_expired_now_coupon_remains_historical_but_not_current(self):
        obs=base_observation(valid_from_utc="2026-11-01T00:00:00Z",valid_until_utc="2026-11-04T23:59:59Z")
        detail=repository(self.temp,observations=[obs]).detail("series-1")
        self.assertEqual(detail["product"]["display_basis"],"BASE_PRICE"); self.assertEqual(detail["history"]["confirmed_after_coupon"][0]["price_twd"],49)

    def test_invalid_discount_math_and_incomplete_evidence_fail_closed(self):
        cases=(base_observation(stored_confirmed_coupon_price_twd=48),base_observation(scope_evidence=None),base_observation(eligibility_profile="UNKNOWN"),base_observation(discount_twd=1000,stored_confirmed_coupon_price_twd=0),base_observation(base_price_twd=49,already_included_in_base=1,stored_confirmed_coupon_price_twd=49,pre_coupon_comparison_price_twd=100,pre_coupon_comparison_source="BAD-MATH"),base_observation(base_price_twd=49,already_included_in_base=1,stored_confirmed_coupon_price_twd=49,pre_coupon_comparison_price_twd=99,pre_coupon_comparison_source=None))
        for index,obs in enumerate(cases):
            root=self.temp/str(index); root.mkdir(); item=repository(root,observations=[obs]).search("")["items"][0]
            self.assertEqual(item["display_basis"],"BASE_PRICE"); self.assertIsNone(item["confirmed_coupon_price_twd"])

    def test_raw_histories_and_daily_representatives_are_separate(self):
        observations=[]
        for index,(hour,base,after) in enumerate(((0,99,49),(1,109,59),(2,119,69))): observations.append(base_observation(source_id=str(index),observed_at_utc=f"2026-11-04T{hour:02}:00:00Z",base_price_twd=base,stored_confirmed_coupon_price_twd=after,discount_twd=50))
        detail=repository(self.temp,observations=observations).detail("series-1")
        self.assertEqual(detail["history_quality"]["before_coupon"]["raw_sample_count"],3); self.assertEqual(detail["history_quality"]["before_coupon"]["daily_representatives"][0]["representative_price_twd"],109)
        self.assertEqual(detail["history_quality"]["confirmed_after_coupon"]["daily_representatives"][0]["representative_price_twd"],59)

    def test_api_search_detail_etag_headers_and_no_cors(self):
        app=CouponPriceV4App(repository(self.temp)); status,search,headers=request(app,"/api/v4/products?q=coupon")
        self.assertEqual(status,200); self.assertEqual(search["schema_version"],"CDH-COUPON-PRICE-V4"); self.assertEqual(search["items"][0]["display_price_twd"],49)
        for name in ("Content-Security-Policy","Referrer-Policy","X-Frame-Options","Permissions-Policy","X-Content-Type-Options"): self.assertIn(name,headers)
        self.assertNotIn("Access-Control-Allow-Origin",headers)
        etag=headers["ETag"]; status,body,headers=request(app,"/api/v4/products/series-1",headers={"If-None-Match":etag}); self.assertEqual(status,304); self.assertIsNone(body); self.assertIn("Content-Security-Policy",headers)

    def test_b09_v2_v3_headers_and_wire_remain_compatible(self):
        root=self.temp/"b09"; root.mkdir(); app=PriceQueryV3App(b09_repo(root))
        for path in ("/api/v2/products","/api/v2/products/series-1","/api/v3/quality/series-1","/missing"):
            status,body,headers=request(app,path)
            self.assertIn(status,(200,404)); self.assertIn("Content-Security-Policy",headers); self.assertEqual(headers["Referrer-Policy"],"no-referrer"); self.assertNotIn("Access-Control-Allow-Origin",headers)
        search=request(app,"/api/v2/products")[1]; self.assertEqual(set(search),{"schema_version","data_source_status","data_classification","contract_compatibility","items","page","limit","total"})
        etag=request(app,"/api/v2/products")[2]["ETag"]
        status,body,headers=request(app,"/api/v3/quality/series-1",headers={"If-None-Match":etag})
        self.assertEqual(status,304); self.assertIsNone(body); self.assertIn("Content-Security-Policy",headers); self.assertIn("Permissions-Policy",headers)

    def test_hash_private_mixed_and_outside_guards(self):
        database,authority=make_fixture(self.temp); data=json.loads(authority.read_text()); data["database_sha256"]="0"*64; authority.write_text(json.dumps(data))
        with self.assertRaisesRegex(CouponRepositoryError,"SHA-256"): CouponPriceRepository(database,authority_file=authority,allowed_root=self.temp,clock=lambda:NOW)
        data["database_sha256"]=digest(database); data["contains_private_data"]=True; authority.write_text(json.dumps(data))
        with self.assertRaisesRegex(CouponRepositoryError,"non-private"): CouponPriceRepository(database,authority_file=authority,allowed_root=self.temp,clock=lambda:NOW)

        mixed=self.temp/"mixed"; mixed.mkdir(); database,authority=make_fixture(mixed)
        connection=sqlite3.connect(database); connection.execute("UPDATE coupon_observations SET data_classification='OTHER'"); connection.commit(); connection.close()
        data=json.loads(authority.read_text()); data["database_sha256"]=digest(database); authority.write_text(json.dumps(data))
        with self.assertRaisesRegex(CouponRepositoryError,"mixed or non-synthetic"): CouponPriceRepository(database,authority_file=authority,allowed_root=mixed,clock=lambda:NOW)
        outside=self.temp/"outside"; outside.mkdir()
        database,authority=make_fixture(outside)
        with self.assertRaisesRegex(CouponRepositoryError,"below allowed root"): CouponPriceRepository(database,authority_file=authority,allowed_root=self.temp/"mixed",clock=lambda:NOW)

    def test_invalid_observation_time_or_empty_source_is_unavailable(self):
        for index,obs in enumerate((base_observation(observed_at_utc="0000"),base_observation(source_id=""))):
            root=self.temp/str(index); root.mkdir(); item=repository(root,observations=[obs]).search("")["items"][0]
            self.assertEqual(item["display_basis"],"PRICE_UNAVAILABLE"); self.assertIsNone(item["display_price_twd"])

    def test_history_truncation_is_exact_not_length_guess(self):
        start=datetime(2026,10,1,0,0,tzinfo=timezone.utc)
        rows=[base_observation(source_id=f"s-{i}",observed_at_utc=(start+timedelta(minutes=i)).isoformat(timespec="seconds").replace("+00:00","Z")) for i in range(500)]
        detail=repository(self.temp,observations=rows).detail("series-1")
        self.assertEqual(len(detail["history"]["before_coupon"]),500); self.assertFalse(detail["history_quality"]["before_coupon"]["truncated"])
        root=self.temp/"more"; root.mkdir(); rows.append(base_observation(source_id="s-500",observed_at_utc=(start+timedelta(minutes=500)).isoformat(timespec="seconds").replace("+00:00","Z")))
        detail=repository(root,observations=rows).detail("series-1")
        self.assertEqual(len(detail["history"]["before_coupon"]),500); self.assertTrue(detail["history_quality"]["before_coupon"]["truncated"])

    def test_database_bytes_unchanged_and_index_present(self):
        r=repository(self.temp); before=digest(r.database); r.search(""); r.detail("series-1"); self.assertEqual(digest(r.database),before)
        connection=sqlite3.connect(r.database); plan=" ".join(str(x) for x in connection.execute("EXPLAIN QUERY PLAN SELECT * FROM coupon_observations WHERE series_key=? AND observed_at_utc<=? ORDER BY observed_at_utc DESC",("series-1","2026-11-05T04:00:00Z"))); connection.close(); self.assertIn("idx_coupon_observations_series_time",plan)

    def test_get_only_errors_are_hardened(self):
        app=CouponPriceV4App(repository(self.temp))
        for path,method,expected in (("/api/v4/products","POST",405),("/missing","GET",404),("/api/v4/products?limit=101","GET",400)):
            status,_,headers=request(app,path,method=method); self.assertEqual(status,expected); self.assertIn("Content-Security-Policy",headers)


if __name__=="__main__": unittest.main()
