from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import tracemalloc
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "price_quality_adapter"))
sys.path.insert(0, str(ROOT / "services" / "price_query_v3"))

from price_quality_adapter import AdapterError, PriceQualityRepository, build_quality_report  # noqa: E402
from price_query_v3 import PriceQueryV3App  # noqa: E402

NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)
SCHEMA = (ROOT / "services" / "price_quality_adapter" / "SCHEMA.sql").read_text(encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_fixture(
    root: Path,
    *,
    classification: str = "SYNTHETIC_FIXTURE",
    permission: str = "ACTIVE_SYNTHETIC_FIXTURE",
    expires: str | None = "2027-01-01T00:00:00Z",
    revoked: str | None = None,
    series: list[dict[str, object]] | None = None,
    observations: list[dict[str, object]] | None = None,
) -> tuple[Path, Path]:
    database = root / "snapshot.sqlite3"
    source_sha = "1" * 64
    report_sha = "2" * 64
    default_series = [{
        "series_key": "series-1", "title": "Synthetic zero item", "platform": "COUPANG_TW",
        "product_id": "product-1", "seller_id": "seller-1", "variant_id": "sku-1",
        "spec_signature": "flavor=plain;weight=100g",
        "minimum_purchase_quantity": 1, "package_signature": "1x100g", "item_condition": "NEW",
        "price_basis": "CURRENT_ITEM_PRICE", "identity_state": "EXACT", "exact_match_claim_allowed": 1,
        "shipping_status": "UNKNOWN", "data_classification": classification, "source_kind": "SYNTHETIC",
        "quality_flags_json": "[]",
    }]
    default_observations = []
    for index in range(10):
        when = NOW - timedelta(days=10-index, hours=2)
        default_observations.append({
            "series_key": "series-1", "submission_id": f"submission-{index}",
            "observed_at_utc": when.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "taipei_date": when.astimezone().date().isoformat(), "price_twd": 100-index,
            "source_type": "SYNTHETIC", "source_id": f"source-{index}",
            "data_classification": classification, "is_synthetic": 1 if classification == "SYNTHETIC_FIXTURE" else 0,
        })
    # Asia/Taipei is UTC+8 and test host is Taipei; explicit correction avoids host dependence.
    for item in default_observations:
        observed = datetime.fromisoformat(str(item["observed_at_utc"]).replace("Z", "+00:00"))
        item["taipei_date"] = (observed + timedelta(hours=8)).date().isoformat()
    connection = sqlite3.connect(database)
    connection.executescript(SCHEMA)
    connection.execute("INSERT INTO adapter_schema VALUES(1)")
    connection.execute(
        "INSERT INTO snapshot_metadata VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("snapshot-1", "CDH-PRICE-QUALITY-READMODEL-1", "CDH-WEB-CONTRACT-V2", classification,
         permission, "2026-11-01T00:00:00Z", expires, revoked, source_sha, report_sha),
    )
    for item in series or default_series:
        connection.execute(
            "INSERT INTO series VALUES(:series_key,:title,:platform,:product_id,:seller_id,:variant_id,:spec_signature,"
            ":minimum_purchase_quantity,:package_signature,:item_condition,:price_basis,:identity_state,"
            ":exact_match_claim_allowed,:shipping_status,:data_classification,:source_kind,:quality_flags_json)", item,
        )
    for index, item in enumerate(observations if observations is not None else default_observations, 1):
        connection.execute(
            "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)",
            (index, item["series_key"], item["submission_id"], item["observed_at_utc"], item["taipei_date"],
             item["price_twd"], item["source_type"], item["source_id"], item["data_classification"], item["is_synthetic"]),
        )
    connection.commit()
    connection.close()
    authority = root / "snapshot.authority.json"
    authority.write_text(json.dumps({
        "schema_version": "CDH-B08-SNAPSHOT-AUTHORITY-1",
        "database_sha256": sha256(database),
        "data_classification": classification,
        "contains_private_data": False,
        "authorized_use": "OFFLINE_LOCAL_READONLY_B08_ONLY",
    }, sort_keys=True), encoding="utf-8")
    return database, authority


def repo(root: Path, **kwargs) -> PriceQualityRepository:
    database, authority = make_fixture(root, **kwargs)
    return PriceQualityRepository(database, authority_file=authority, allowed_root=root, clock=lambda: NOW)


def request(app, path: str, *, method: str = "GET", headers: dict[str, str] | None = None):
    captured = {}
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path.split("?", 1)[0], "QUERY_STRING": path.split("?", 1)[1] if "?" in path else "", "wsgi.input": io.BytesIO()}
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    def start(status, response_headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(response_headers)
    body = b"".join(app(environ, start))
    return captured["status"], (json.loads(body) if body else None), captured["headers"]


class AdapterTests(unittest.TestCase):
    def setUp(self):
        test_root = ROOT / "review" / "B09" / "tmp_tests"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix="case-", dir=test_root))

    def tearDown(self):
        shutil.rmtree(self.temp)

    def test_v2_wire_key_sets_are_unchanged_and_v3_is_separate(self):
        app = PriceQueryV3App(repo(self.temp))
        status, search, headers = request(app, "/api/v2/products?q=zero")
        self.assertEqual(status, 200)
        self.assertEqual(set(search), {"schema_version", "data_source_status", "data_classification", "contract_compatibility", "items", "page", "limit", "total"})
        self.assertEqual(set(search["items"][0]), {"id", "title", "variant_signature", "last_observed_price_twd", "last_observed_at", "observed_days", "sample_days_m7", "sample_days_m30", "sample_days_m90", "coverage", "shipping_status", "price_basis", "source_price_basis", "identity_state", "quality_flags", "thumbnail"})
        self.assertEqual(headers["X-CDH-Schema-Version"], "CDH-WEB-CONTRACT-V2")
        status, detail, _ = request(app, "/api/v2/products/series-1")
        self.assertEqual(set(detail), {"schema_version", "data_source_status", "data_classification", "contract_compatibility", "product", "offers", "history", "observation_period_min_twd", "observation_period_label", "affiliate"})
        self.assertEqual(set(detail["offers"][0]), {"offer_id", "seller_id", "sku_id", "product_id", "minimum_purchase_quantity", "item_condition", "item_condition_source", "price_basis", "source_price_basis", "identity_state"})
        self.assertEqual(set(detail["history"][0]), {"observed_at", "price_twd", "source_type", "source_id"})
        self.assertNotIn("new_low_valid", detail)
        self.assertEqual(request(app, "/api/v3/quality/series-1")[1]["schema_version"], "CDH-PRICE-QUALITY-ADAPTER-V3")

    def test_v2_raw_history_min_is_distinct_from_v3_daily_representative_low(self):
        rows=[]
        for index,(hour,price) in enumerate(((0,10),(1,20),(2,30))):
            when=datetime(2026,11,4,hour,0,tzinfo=timezone.utc)
            rows.append({"series_key":"series-1","submission_id":f"same-day-{index}","observed_at_utc":when.isoformat(timespec="seconds").replace("+00:00","Z"),"taipei_date":"2026-11-04","price_twd":price,"source_type":"SYNTHETIC","source_id":f"same-day-{index}","data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1})
        r=repo(self.temp,observations=rows)
        detail=r.detail("series-1")
        quality=r.quality("series-1")
        self.assertEqual([item["price_twd"] for item in detail["history"]],[10,20,30])
        self.assertEqual(detail["observation_period_min_twd"],10)
        self.assertEqual(quality["period_low_twd"],20)
        api_detail=request(PriceQueryV3App(r),"/api/v2/products/series-1")[1]
        api_quality=request(PriceQueryV3App(r),"/api/v3/quality/series-1")[1]
        self.assertEqual(api_detail["observation_period_min_twd"],10)
        self.assertEqual(api_quality["period_low_twd"],20)

    def test_v2_empty_history_has_null_minimum(self):
        r=repo(self.temp,permission="REVOKED",revoked="2026-11-01T00:00:00Z")
        detail=r.detail("series-1")
        self.assertEqual(detail["history"],[])
        self.assertIsNone(detail["observation_period_min_twd"])
        self.assertEqual(detail["product"]["price_basis"],"UNAVAILABLE")
        self.assertIsNone(detail["product"]["last_observed_price_twd"])

    def test_v2_500_item_truncation_minimum_is_only_visible_history(self):
        rows=[]
        start=datetime(2026,10,1,0,0,tzinfo=timezone.utc)
        for index in range(501):
            when=start+timedelta(minutes=index)
            rows.append({"series_key":"series-1","submission_id":f"truncate-{index}","observed_at_utc":when.isoformat(timespec="seconds").replace("+00:00","Z"),"taipei_date":(when+timedelta(hours=8)).date().isoformat(),"price_twd":1 if index==0 else 100+index,"source_type":"SYNTHETIC","source_id":f"truncate-{index}","data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1})
        detail=repo(self.temp,observations=rows).detail("series-1")
        self.assertEqual(len(detail["history"]),500)
        self.assertNotIn(1,[item["price_twd"] for item in detail["history"]])
        self.assertEqual(detail["observation_period_min_twd"],101)

    def test_affiliate_is_nested_and_unconfigured(self):
        value = request(PriceQueryV3App(repo(self.temp)), "/api/v2/products/series-1/affiliate")[1]
        self.assertEqual(set(value), {"schema_version", "data_source_status", "data_classification", "contract_compatibility", "product_id", "affiliate"})
        self.assertEqual(value["affiliate"], {"state": "UNCONFIGURED", "click_url": None, "verified_product_match": False, "bound_product_id": None})

    def test_zero_is_not_null_and_shipping_remains_unknown(self):
        r = repo(self.temp)
        connection = sqlite3.connect(r.database)
        with self.assertRaises(sqlite3.OperationalError):
            connection.execute("PRAGMA query_only=ON").execute("UPDATE observations SET price_twd=0")
        connection.close()
        # Build a zero fixture rather than mutating the governed read-only snapshot.
        other = self.temp / "zero"; other.mkdir()
        when = NOW - timedelta(days=1, hours=2)
        obs = [{"series_key":"series-1","submission_id":"zero","observed_at_utc":when.isoformat(timespec="seconds").replace("+00:00","Z"),"taipei_date":(when+timedelta(hours=8)).date().isoformat(),"price_twd":0,"source_type":"SYNTHETIC","source_id":"zero","data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1}]
        item = repo(other, observations=obs).search("", page=1, limit=20)["items"][0]
        self.assertEqual(item["last_observed_price_twd"], 0)
        self.assertEqual(item["shipping_status"], "UNKNOWN")

    def test_null_price_never_becomes_zero(self):
        other = self.temp / "null"; other.mkdir()
        r = repo(other, observations=[])
        item = r.search("", page=1, limit=20)["items"][0]
        self.assertIsNone(item["last_observed_price_twd"])
        self.assertEqual(item["observed_days"], 0)

    def test_expired_revoked_and_inactive_sources_fail_closed(self):
        for index, kwargs in enumerate((
            {"expires":"2026-11-05T03:59:59Z"}, {"permission":"REVOKED","revoked":"2026-11-01T00:00:00Z"}, {"permission":"SOURCE_BLOCKED"},
        )):
            root = self.temp / str(index); root.mkdir()
            r = repo(root, **kwargs)
            self.assertIsNone(r.search("", page=1, limit=20)["items"][0]["last_observed_price_twd"])
            self.assertEqual(r.detail("series-1")["history"], [])
            self.assertFalse(r.quality("series-1")["source_permission"]["allowed"])

    def test_coupon_basis_and_incomplete_identity_fail_closed(self):
        base = [{"series_key":"series-1","title":"x","platform":"COUPANG_TW","product_id":"p","seller_id":"s","variant_id":"v","spec_signature":"size=1","minimum_purchase_quantity":1,"package_signature":"1x","item_condition":"NEW","price_basis":"COUPON_AFTER_DISCOUNT","identity_state":"EXACT","exact_match_claim_allowed":1,"shipping_status":"UNKNOWN","data_classification":"SYNTHETIC_FIXTURE","source_kind":"SYNTHETIC","quality_flags_json":"[]"}]
        r = repo(self.temp, series=base)
        self.assertIsNone(r.search("", page=1, limit=20)["items"][0]["last_observed_price_twd"])
        self.assertIn("PRICE_BASIS_CONDITIONAL_OR_UNSUPPORTED", r.quality("series-1")["incompatibility_reasons"])
        root = self.temp / "incomplete"; root.mkdir(); base[0] = {**base[0], "price_basis":"CURRENT_ITEM_PRICE", "seller_id":None, "identity_state":"INCOMPLETE", "exact_match_claim_allowed":0}
        self.assertIn("IDENTITY_DIMENSION_MISSING", repo(root, series=base).quality("series-1")["incompatibility_reasons"])

    def test_cross_seller_package_and_condition_are_distinct(self):
        template = {"title":"x","platform":"COUPANG_TW","product_id":"p","variant_id":"v","spec_signature":"size=1","minimum_purchase_quantity":1,"item_condition":"NEW","price_basis":"CURRENT_ITEM_PRICE","identity_state":"EXACT","exact_match_claim_allowed":1,"shipping_status":"UNKNOWN","data_classification":"SYNTHETIC_FIXTURE","source_kind":"SYNTHETIC","quality_flags_json":"[]"}
        series = [
            {**template,"series_key":"a","seller_id":"s1","package_signature":"1x"},
            {**template,"series_key":"b","seller_id":"s2","package_signature":"1x"},
            {**template,"series_key":"c","seller_id":"s1","package_signature":"2x"},
        ]
        observations=[]
        for i,key in enumerate("abc"):
            when=NOW-timedelta(days=2,hours=i); observations.append({"series_key":key,"submission_id":key,"observed_at_utc":when.isoformat(timespec="seconds").replace("+00:00","Z"),"taipei_date":(when+timedelta(hours=8)).date().isoformat(),"price_twd":i,"source_type":"SYNTHETIC","source_id":key,"data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1})
        r=repo(self.temp,series=series,observations=observations)
        self.assertEqual(r.search("",page=1,limit=20)["total"],3)
        self.assertEqual([r.quality(key)["identity"]["seller_id"] for key in "abc"],["s1","s2","s1"])
        self.assertEqual([r.detail(key)["observation_period_min_twd"] for key in "abc"],[0,1,2])

    def test_mixed_valid_and_unknown_series_remain_independently_visible(self):
        template={"title":"mixed","platform":"COUPANG_TW","product_id":"p","variant_id":"v","spec_signature":"size=1","minimum_purchase_quantity":1,"package_signature":"1x","item_condition":"NEW","price_basis":"CURRENT_ITEM_PRICE","shipping_status":"UNKNOWN","data_classification":"SYNTHETIC_FIXTURE","source_kind":"SYNTHETIC","quality_flags_json":"[]"}
        series=[{**template,"series_key":"valid","seller_id":"s1","identity_state":"EXACT","exact_match_claim_allowed":1},{**template,"series_key":"unknown","seller_id":None,"identity_state":"INCOMPLETE","exact_match_claim_allowed":0}]
        observations=[]
        for index,key in enumerate(("valid","unknown")):
            when=NOW-timedelta(days=2,hours=index)
            observations.append({"series_key":key,"submission_id":key,"observed_at_utc":when.isoformat(timespec="seconds").replace("+00:00","Z"),"taipei_date":(when+timedelta(hours=8)).date().isoformat(),"price_twd":10+index,"source_type":"SYNTHETIC","source_id":key,"data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1})
        r=repo(self.temp,series=series,observations=observations)
        items={item["id"]:item for item in r.search("mixed",page=1,limit=20)["items"]}
        self.assertEqual(items["valid"]["last_observed_price_twd"],10)
        self.assertIsNone(items["unknown"]["last_observed_price_twd"])
        self.assertEqual(items["unknown"]["price_basis"],"UNAVAILABLE")
        self.assertEqual(r.detail("unknown")["history"],[])
        self.assertIsNone(r.detail("unknown")["observation_period_min_twd"])

    def test_user_authorized_copy_and_unknown_source_rows_are_handled_explicitly(self):
        user_series=[{"series_key":"series-1","title":"user copy","platform":"COUPANG_TW","product_id":"p","seller_id":"s","variant_id":"v","spec_signature":"size=1","minimum_purchase_quantity":1,"package_signature":"1x","item_condition":"NEW","price_basis":"CURRENT_ITEM_PRICE","identity_state":"EXACT","exact_match_claim_allowed":1,"shipping_status":"UNKNOWN","data_classification":"USER_AUTHORIZED_COPY","source_kind":"USER_FILE","quality_flags_json":"[]"}]
        when=NOW-timedelta(days=2)
        user_rows=[{"series_key":"series-1","submission_id":"user","observed_at_utc":when.isoformat(timespec="seconds").replace("+00:00","Z"),"taipei_date":(when+timedelta(hours=8)).date().isoformat(),"price_twd":42,"source_type":"USER_FILE","source_id":"user-file","data_classification":"USER_AUTHORIZED_COPY","is_synthetic":0}]
        r=repo(self.temp,classification="USER_AUTHORIZED_COPY",permission="ACTIVE_USER_COPY",series=user_series,observations=user_rows)
        self.assertEqual(r.detail("series-1")["observation_period_min_twd"],42)
        self.assertEqual(r.search("",page=1,limit=20)["data_classification"],"USER_RECORDED")

        other=self.temp/"unknown-source"; other.mkdir()
        valid=NOW-timedelta(days=2,hours=1)
        bad=NOW-timedelta(days=2,hours=2)
        rows=[{"series_key":"series-1","submission_id":"bad","observed_at_utc":bad.isoformat(timespec="seconds").replace("+00:00","Z"),"taipei_date":(bad+timedelta(hours=8)).date().isoformat(),"price_twd":1,"source_type":"UNKNOWN","source_id":"bad","data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1},{"series_key":"series-1","submission_id":"good","observed_at_utc":valid.isoformat(timespec="seconds").replace("+00:00","Z"),"taipei_date":(valid+timedelta(hours=8)).date().isoformat(),"price_twd":10,"source_type":"SYNTHETIC","source_id":"good","data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1}]
        filtered=repo(other,observations=rows)
        self.assertEqual([item["price_twd"] for item in filtered.detail("series-1")["history"]],[10])
        self.assertEqual(filtered.quality("series-1")["period_low_twd"],10)

    def test_reverse_time_same_hour_current_and_future_handling(self):
        rows=[]
        times=[NOW-timedelta(days=2,hours=1,minutes=1),NOW-timedelta(days=2,hours=1,minutes=20),NOW-timedelta(days=3),NOW+timedelta(hours=1),NOW-timedelta(hours=1)]
        for i,when in enumerate(reversed(times)):
            rows.append({"series_key":"series-1","submission_id":str(i),"observed_at_utc":when.isoformat(timespec="seconds").replace("+00:00","Z"),"taipei_date":(when+timedelta(hours=8)).date().isoformat(),"price_twd":10+i,"source_type":"SYNTHETIC","source_id":str(i),"data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1})
        q=repo(self.temp,observations=rows).quality("series-1")
        self.assertEqual(q["daily_sample_count"],2)
        self.assertEqual(q["valid_observation_count"],3)

    def test_first_observation_cannot_be_new_low_and_seven_day_baseline_can(self):
        first=self.temp/"first"; first.mkdir(); when=NOW-timedelta(days=1,hours=2)
        one=[{"series_key":"series-1","submission_id":"1","observed_at_utc":when.isoformat(timespec="seconds").replace("+00:00","Z"),"taipei_date":(when+timedelta(hours=8)).date().isoformat(),"price_twd":1,"source_type":"SYNTHETIC","source_id":"1","data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1}]
        q=repo(first,observations=one).quality("series-1")
        self.assertFalse(q["new_low_valid"]); self.assertEqual(q["new_low_reason"],"FIRST_OBSERVATION_HAS_NO_PRIOR_BASELINE")
        rows=[]
        for i in range(8):
            when=NOW-timedelta(days=8-i,hours=2); price=50 if i<7 else 1
            rows.append({"series_key":"series-1","submission_id":str(i),"observed_at_utc":when.isoformat(timespec="seconds").replace("+00:00","Z"),"taipei_date":(when+timedelta(hours=8)).date().isoformat(),"price_twd":price,"source_type":"SYNTHETIC","source_id":str(i),"data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1})
        q=repo(self.temp,observations=rows).quality("series-1")
        self.assertTrue(q["new_low_valid"]); self.assertEqual(q["new_low_reason"],"VALID_NEW_PERIOD_LOW")

    def test_mixed_classification_is_refused(self):
        database, authority=make_fixture(self.temp)
        connection=sqlite3.connect(database); connection.execute("UPDATE observations SET data_classification='USER_AUTHORIZED_COPY' WHERE observation_id=1"); connection.commit(); connection.close()
        data=json.loads(authority.read_text()); data["database_sha256"]=sha256(database); authority.write_text(json.dumps(data))
        with self.assertRaisesRegex(AdapterError,"mixed or mismatched"):
            PriceQualityRepository(database,authority_file=authority,allowed_root=self.temp,clock=lambda:NOW)

    def test_hash_schema_private_and_contract_guards(self):
        database,authority=make_fixture(self.temp)
        data=json.loads(authority.read_text()); data["database_sha256"]="0"*64; authority.write_text(json.dumps(data))
        with self.assertRaisesRegex(AdapterError,"SHA-256 mismatch"):
            PriceQualityRepository(database,authority_file=authority,allowed_root=self.temp,clock=lambda:NOW)
        data["database_sha256"]=sha256(database); data["contains_private_data"]=True; authority.write_text(json.dumps(data))
        with self.assertRaisesRegex(AdapterError,"private data"):
            PriceQualityRepository(database,authority_file=authority,allowed_root=self.temp,clock=lambda:NOW)

    def test_outside_root_and_symlink_are_refused(self):
        database,authority=make_fixture(self.temp)
        outside_root = ROOT / "review" / "B09" / "tmp_tests"
        other=Path(tempfile.mkdtemp(prefix="outside-", dir=outside_root))
        try:
            with self.assertRaisesRegex(AdapterError,"below allowed root"):
                PriceQualityRepository(database,authority_file=authority,allowed_root=other,clock=lambda:NOW)
            link=self.temp/"link.sqlite3"
            try:
                os.symlink(database,link)
            except OSError:
                self.skipTest("symlink creation not permitted")
            with self.assertRaisesRegex(AdapterError,"links and reparse"):
                PriceQualityRepository(link,authority_file=authority,allowed_root=self.temp,clock=lambda:NOW)
        finally:
            shutil.rmtree(other)

    def test_pagination_and_etag(self):
        app=PriceQueryV3App(repo(self.temp))
        status,value,headers=request(app,"/api/v2/products?page=1&limit=1")
        self.assertEqual((status,value["page"],value["limit"]),(200,1,1))
        status,value,_=request(app,"/api/v3/quality/series-1",headers={"If-None-Match":headers["ETag"]})
        self.assertEqual(status,304); self.assertIsNone(value)
        self.assertEqual(request(app,"/api/v2/products?limit=101")[0],400)

    def test_metrics_cache_is_bounded_hits_and_expires_with_permission_clock(self):
        current=[NOW]
        database,authority=make_fixture(self.temp,expires="2026-11-05T04:01:00Z")
        r=PriceQualityRepository(database,authority_file=authority,allowed_root=self.temp,clock=lambda:current[0])
        self.assertTrue(r.quality("series-1")["source_permission"]["allowed"])
        first=r.cache_info()
        r.quality("series-1")
        second=r.cache_info()
        self.assertGreater(second["hits"],first["hits"])
        self.assertLessEqual(second["size"],second["max_size"])
        current[0]=NOW+timedelta(minutes=2)
        expired=r.quality("series-1")
        self.assertFalse(expired["source_permission"]["allowed"])
        self.assertEqual(expired["source_permission"]["reason"],"SOURCE_PERMISSION_EXPIRED")

    def test_metrics_cache_evicts_beyond_256_series(self):
        series=[]; observations=[]
        when=NOW-timedelta(days=2)
        for index in range(300):
            key=f"series-{index}"
            series.append({"series_key":key,"title":key,"platform":"COUPANG_TW","product_id":f"p-{index}","seller_id":"s","variant_id":f"v-{index}","spec_signature":"size=1","minimum_purchase_quantity":1,"package_signature":"1x","item_condition":"NEW","price_basis":"CURRENT_ITEM_PRICE","identity_state":"EXACT","exact_match_claim_allowed":1,"shipping_status":"UNKNOWN","data_classification":"SYNTHETIC_FIXTURE","source_kind":"SYNTHETIC","quality_flags_json":"[]"})
            observations.append({"series_key":key,"submission_id":key,"observed_at_utc":when.isoformat(timespec="seconds").replace("+00:00","Z"),"taipei_date":(when+timedelta(hours=8)).date().isoformat(),"price_twd":index,"source_type":"SYNTHETIC","source_id":key,"data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1})
        r=repo(self.temp,series=series,observations=observations)
        for index in range(300):
            self.assertIsNotNone(r.quality(f"series-{index}"))
        self.assertEqual(r.cache_info()["size"],256)

    def test_history_limit_and_index_query_plan(self):
        r=repo(self.temp)
        with self.assertRaisesRegex(AdapterError,"history_limit"):
            r.detail("series-1",history_limit=501)
        connection=sqlite3.connect(r.database)
        plan=" ".join(str(row) for row in connection.execute("EXPLAIN QUERY PLAN SELECT observed_at_utc FROM observations WHERE series_key=? AND observed_at_utc<? ORDER BY observed_at_utc DESC",("series-1","2026-11-05T04:00:00Z")))
        connection.close()
        self.assertIn("idx_observations_series_time",plan)

    def test_get_only_no_cors_and_not_found(self):
        app=PriceQueryV3App(repo(self.temp))
        self.assertEqual(request(app,"/api/v2/products",method="POST")[0],405)
        status,_,headers=request(app,"/api/v2/products")
        self.assertEqual(status,200); self.assertNotIn("Access-Control-Allow-Origin",headers)
        self.assertEqual(request(app,"/api/v2/products/missing")[0],404)

    def test_snapshot_bytes_remain_unchanged(self):
        r=repo(self.temp); before=sha256(r.database)
        r.search("",page=1,limit=10); r.detail("series-1"); r.quality("series-1")
        self.assertEqual(sha256(r.database),before)

    def test_batch_recalculation_is_readonly_and_versioned(self):
        r=repo(self.temp); before=sha256(r.database)
        report=build_quality_report(r,page_size=1)
        self.assertEqual(report["schema_version"],"CDH-B08-BATCH-QUALITY-REPORT-1")
        self.assertEqual(report["series_count"],1)
        self.assertEqual(report["data_version"],r.data_version)
        self.assertEqual(sha256(r.database),before)

    def test_large_snapshot_over_50k_is_bounded(self):
        rows=[]
        for i in range(50001):
            when=NOW-timedelta(days=1+(i%89),hours=2,minutes=i%60)
            rows.append({"series_key":"series-1","submission_id":f"large-{i}","observed_at_utc":when.isoformat(timespec="seconds").replace("+00:00","Z"),"taipei_date":(when+timedelta(hours=8)).date().isoformat(),"price_twd":i%1000,"source_type":"SYNTHETIC","source_id":f"large-{i}","data_classification":"SYNTHETIC_FIXTURE","is_synthetic":1})
        r=repo(self.temp,observations=rows)
        tracemalloc.start(); detail=r.detail("series-1"); _,peak=tracemalloc.get_traced_memory(); tracemalloc.stop()
        self.assertEqual(len(detail["history"]),500)
        self.assertTrue(r.quality("series-1")["history_truncated"])
        self.assertLess(peak,32*1024*1024)


if __name__ == "__main__":
    unittest.main()
