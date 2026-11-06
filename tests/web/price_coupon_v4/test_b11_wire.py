from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"services"/"price_coupon_v4"))

from price_coupon_v4 import CouponPriceRepository,CouponPriceV4App,build_fixture_suite  # noqa:E402
from price_coupon_v4.server import main as server_main  # noqa:E402
from tests.web.price_coupon_v4.test_coupon_v4 import request  # noqa:E402

NOW=datetime(2026,11,5,4,0,tzinfo=timezone.utc)


def open_snapshot(root:Path,name:str)->CouponPriceRepository:
    target=root/name
    return CouponPriceRepository(target/"coupon.sqlite3",authority_file=target/"coupon.authority.json",allowed_root=target,clock=lambda:NOW)


class B11WireTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/"review"/"B11"/"tmp_tests"; base.mkdir(parents=True,exist_ok=True)
        self.temp=Path(tempfile.mkdtemp(prefix="case-",dir=base)); self.suite=self.temp/"suite"; self.manifest=build_fixture_suite(self.suite)

    def tearDown(self): shutil.rmtree(self.temp)

    def test_fixture_suite_is_sha_bound_and_has_all_states(self):
        self.assertEqual(self.manifest["schema_version"],"CDH-B11-FIXTURE-SUITE-1")
        self.assertEqual([x["directory"] for x in self.manifest["snapshots"]],["active","expired-source","revoked-source","empty-history"])
        for item in self.manifest["snapshots"]:
            target=self.suite/item["directory"]
            self.assertEqual(__import__("hashlib").sha256((target/item["database"]).read_bytes()).hexdigest(),item["database_sha256"])
            self.assertEqual(__import__("hashlib").sha256((target/item["authority"]).read_bytes()).hexdigest(),item["authority_sha256"])
        second=self.temp/"second-suite"; second_manifest=build_fixture_suite(second)
        self.assertEqual([x["database_sha256"] for x in self.manifest["snapshots"]],[x["database_sha256"] for x in second_manifest["snapshots"]])

    def test_active_fixture_replays_canonical_cases(self):
        repository=open_snapshot(self.suite,"active"); items={x["series_key"]:x for x in repository.search("",page=1,limit=100)["items"]}
        self.assertEqual((items["confirmed"]["base_price_twd"],items["confirmed"]["display_price_twd"]),(99,49))
        self.assertEqual((items["claim-required"]["display_basis"],items["claim-required"]["possible_coupon_price_twd"]),("BASE_PRICE",49))
        self.assertEqual(items["expired-coupon"]["display_basis"],"BASE_PRICE"); self.assertEqual(items["unknown-coupon"]["display_basis"],"BASE_PRICE")
        self.assertEqual((items["already-included"]["before_coupon_price_twd"],items["already-included"]["display_price_twd"]),(99,49))
        self.assertEqual((items["quantity-two"]["minimum_purchase_quantity"],items["quantity-two"]["display_price_twd"],items["quantity-two"]["minimum_item_spend_twd"]),(2,75,150))
        self.assertEqual(items["wrong-sku"]["display_basis"],"BASE_PRICE")
        self.assertEqual((items["zero"]["display_price_twd"],items["zero"]["shipping_status"],items["zero"]["required_total_twd"]),(0,"UNKNOWN",None))
        self.assertEqual(items["unavailable"]["display_basis"],"PRICE_UNAVAILABLE")

    def test_source_expired_revoked_and_empty_history(self):
        for name,reason in (("expired-source","SOURCE_PERMISSION_EXPIRED"),("revoked-source","SOURCE_PERMISSION_REVOKED")):
            repository=open_snapshot(self.suite,name); item=repository.search("")["items"][0]; detail=repository.detail(item["series_key"])
            self.assertEqual(item["display_basis"],"PRICE_UNAVAILABLE"); self.assertEqual(item["source_permission"]["reason"],reason); self.assertEqual(detail["history"],{"before_coupon":[],"confirmed_after_coupon":[]})
        detail=open_snapshot(self.suite,"empty-history").detail("empty-history")
        self.assertEqual(detail["product"]["display_basis"],"PRICE_UNAVAILABLE"); self.assertEqual(detail["history_quality"]["before_coupon"]["raw_sample_count"],0)

    def test_search_and_detail_exact_top_level_wire(self):
        repository=open_snapshot(self.suite,"active"); search=repository.search("",page=1,limit=3); detail=repository.detail("confirmed")
        self.assertEqual(set(search),{"schema_version","data_classification","items","page","limit","total","data_version"})
        self.assertEqual(set(detail),{"schema_version","data_classification","product","history","history_quality","data_version"})
        self.assertNotIn("schema_version",search["items"][0]); self.assertNotIn("history",detail["product"])
        self.assertEqual(search["data_version"],detail["data_version"])

    def test_machine_schema_required_fields_match_actual_wire(self):
        schema_root=ROOT/"services"/"price_coupon_v4"/"schema"
        product_schema=json.loads((schema_root/"cdh_coupon_price_v4.schema.json").read_text(encoding="utf-8")); search_schema=json.loads((schema_root/"cdh_coupon_price_v4_search.schema.json").read_text(encoding="utf-8")); detail_schema=json.loads((schema_root/"cdh_coupon_price_v4_detail.schema.json").read_text(encoding="utf-8"))
        repository=open_snapshot(self.suite,"active"); search=repository.search("",limit=1); detail=repository.detail("confirmed")
        self.assertEqual(set(search),set(search_schema["required"])); self.assertEqual(set(detail),set(detail_schema["required"])); self.assertEqual(set(search["items"][0]),set(product_schema["required"])); self.assertFalse(product_schema["additionalProperties"]); self.assertFalse(search_schema["additionalProperties"]); self.assertFalse(detail_schema["additionalProperties"])

    def test_host_and_origin_default_deny(self):
        app=CouponPriceV4App(open_snapshot(self.suite,"active"))
        self.assertEqual(request(app,"/api/v4/products",headers={"Host":"evil.invalid"})[0],400)
        self.assertEqual(request(app,"/api/v4/products",headers={"Origin":"https://evil.invalid"})[0],403)
        status,_,headers=request(app,"/api/v4/products",headers={"Host":"127.0.0.1:8766"}); self.assertEqual(status,200); self.assertNotIn("Access-Control-Allow-Origin",headers)

    def test_exact_loopback_cors_and_options_never_wildcard(self):
        origin="http://127.0.0.1:4173"; app=CouponPriceV4App(open_snapshot(self.suite,"active"),allowed_origins=(origin,))
        status,_,headers=request(app,"/api/v4/products",headers={"Host":"127.0.0.1:8766","Origin":origin}); self.assertEqual(status,200); self.assertEqual(headers["Access-Control-Allow-Origin"],origin); self.assertNotEqual(headers["Access-Control-Allow-Origin"],"*")
        status,body,headers=request(app,"/api/v4/products",method="OPTIONS",headers={"Host":"127.0.0.1:8766","Origin":origin}); self.assertEqual(status,204); self.assertIsNone(body); self.assertEqual(headers["Access-Control-Allow-Methods"],"GET")

    def test_304_400_404_405_security_and_etag(self):
        app=CouponPriceV4App(open_snapshot(self.suite,"active")); _,_,normal=request(app,"/api/v4/products")
        cases=(("/api/v4/products","GET",{"If-None-Match":normal["ETag"]},304),("/api/v4/products?limit=x","GET",None,400),("/missing","GET",None,404),("/api/v4/products","POST",None,405))
        for path,method,headers,expected in cases:
            status,_,response_headers=request(app,path,method=method,headers=headers); self.assertEqual(status,expected)
            for name in ("Cache-Control","Content-Security-Policy","Referrer-Policy","X-Content-Type-Options","X-Frame-Options","Permissions-Policy"): self.assertIn(name,response_headers)

    def test_request_size_and_pagination_boundaries(self):
        app=CouponPriceV4App(open_snapshot(self.suite,"active"))
        self.assertEqual(request(app,"/api/v4/products?q="+"x"*201)[0],400); self.assertEqual(request(app,"/api/v4/products?x="+"x"*2050)[0],400); self.assertEqual(request(app,"/"+"x"*513)[0],400)
        self.assertEqual(request(app,"/api/v4/products?page=0")[0],400); self.assertEqual(request(app,"/api/v4/products?limit=101")[0],400)

    def test_deterministic_sorting_and_pagination(self):
        repository=open_snapshot(self.suite,"active"); first=repository.search("",page=1,limit=3); second=repository.search("",page=2,limit=3)
        titles=[x["title"] for x in first["items"]+second["items"]]; self.assertEqual(titles,sorted(titles,key=str.casefold)); self.assertFalse({x["series_key"] for x in first["items"]}&{x["series_key"] for x in second["items"]})

    def test_server_check_and_non_loopback_bind_rejection(self):
        target=self.suite/"active"; output=io.StringIO()
        with redirect_stdout(output): code=server_main(["--database-copy",str(target/"coupon.sqlite3"),"--authority-file",str(target/"coupon.authority.json"),"--fixture-root",str(target),"--host","127.0.0.1","--port","8766","--check"])
        self.assertEqual(code,0); self.assertEqual(json.loads(output.getvalue())["status"],"READY")
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit): server_main(["--database-copy",str(target/"coupon.sqlite3"),"--authority-file",str(target/"coupon.authority.json"),"--fixture-root",str(target),"--host","0.0.0.0","--check"])


if __name__=="__main__": unittest.main()
