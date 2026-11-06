from __future__ import annotations

import copy
import hashlib
import io
import json
import py_compile
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "services" / "affiliate_coupon_gate_v6"
B10_ZIP = ROOT / "review" / "F06" / "controlled_inputs" / "B10" / "CDH_B_R06_001_REVIEW.zip"
B10_ROOT = ROOT / "review" / "F06" / "controlled_inputs" / "B10" / "extracted" / "CDH_B_R06_001_REVIEW"
sys.path.insert(0, str(SERVICE))
sys.path.insert(0, str(B10_ROOT / "services" / "price_coupon_v4"))

from affiliate_coupon_gate_v6 import (  # noqa: E402
    AffiliateCouponGateV6,
    AffiliateTrustInput,
    B10WireError,
    GateRequest,
    RuntimeCeiling,
    adapt_detail_envelope,
    adapt_search_envelope,
)
from affiliate_coupon_gate_v6.static_policy import text_source_files  # noqa: E402
from price_coupon_v4 import CouponPriceRepository, CouponPriceV4App  # noqa: E402


NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)
EXPECTED_B10_SHA256 = "dfef51befb8785e069e4be5514b4eec106952deb5f52ee4cd98974c50273e549"
SCHEMA = (B10_ROOT / "services" / "price_coupon_v4" / "SCHEMA.sql").read_text(encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def base_series(**changes):
    value = {
        "series_key": "series-1", "title": "Synthetic coupon item", "platform": "COUPANG_TW",
        "product_id": "SYN-P-1", "sku_id": "SYN-SKU-1", "seller_id": "SYN-SELLER-1",
        "item_condition": "NEW", "package_signature": "1x100ml", "spec_signature": "volume=100ml",
        "minimum_purchase_quantity": 1, "shipping_status": "UNKNOWN", "identity_state": "EXACT",
        "data_classification": "SYNTHETIC_FIXTURE",
    }
    value.update(changes)
    return value


def base_observation(**changes):
    value = {
        "series_key": "series-1", "source_id": "SYN-SOURCE-1", "observed_at_utc": "2026-11-04T02:00:00Z",
        "base_price_twd": 99, "base_price_basis": "LISTED_ELIGIBLE", "coupon_id": "SYN-COUPON-1",
        "coupon_status": "CONFIRMED_APPLICABLE", "discount_twd": 50, "discount_scope": "UNIT",
        "already_included_in_base": 0, "eligibility_profile": "SYN-ELIGIBLE-PROFILE",
        "valid_from_utc": "2026-11-01T00:00:00Z", "valid_until_utc": "2026-11-30T23:59:59Z",
        "scope_evidence": "SYN-TEST-EVIDENCE", "coupon_product_id": "SYN-P-1",
        "coupon_sku_id": "SYN-SKU-1", "coupon_seller_id": "SYN-SELLER-1",
        "stored_confirmed_coupon_price_twd": 49, "stored_possible_coupon_price_twd": None,
        "pre_coupon_comparison_price_twd": None, "pre_coupon_comparison_source": None,
        "shipping_fee_twd": None, "mandatory_fee_twd": None,
        "data_classification": "SYNTHETIC_FIXTURE", "is_synthetic": 1,
    }
    value.update(changes)
    return value


def make_fixture(root: Path, *, series=None, observations=None, permission="ACTIVE_SYNTHETIC_FIXTURE", expires="2027-01-01T00:00:00Z", revoked=None):
    database = root / "coupon.sqlite3"
    authority = root / "coupon.authority.json"
    connection = sqlite3.connect(database)
    connection.executescript(SCHEMA)
    connection.execute("INSERT INTO coupon_schema VALUES(1)")
    connection.execute(
        "INSERT INTO coupon_metadata VALUES(?,?,?,?,?,?,?)",
        ("snapshot-v4", "CDH-COUPON-PRICE-V4", "SYNTHETIC_FIXTURE", permission, "2026-11-01T00:00:00Z", expires, revoked),
    )
    for item in series or [base_series()]:
        connection.execute(
            "INSERT INTO coupon_series VALUES(:series_key,:title,:platform,:product_id,:sku_id,:seller_id,:item_condition,:package_signature,:spec_signature,:minimum_purchase_quantity,:shipping_status,:identity_state,:data_classification)",
            item,
        )
    fields = (
        "series_key", "source_id", "observed_at_utc", "base_price_twd", "base_price_basis", "coupon_id",
        "coupon_status", "discount_twd", "discount_scope", "already_included_in_base", "eligibility_profile",
        "valid_from_utc", "valid_until_utc", "scope_evidence", "coupon_product_id", "coupon_sku_id",
        "coupon_seller_id", "stored_confirmed_coupon_price_twd", "stored_possible_coupon_price_twd",
        "pre_coupon_comparison_price_twd", "pre_coupon_comparison_source", "shipping_fee_twd",
        "mandatory_fee_twd", "data_classification", "is_synthetic",
    )
    for index, item in enumerate(observations if observations is not None else [base_observation()], 1):
        connection.execute(
            f"INSERT INTO coupon_observations(observation_id,{','.join(fields)}) VALUES(?,{','.join('?' for _ in fields)})",
            (index, *(item[name] for name in fields)),
        )
    connection.commit()
    connection.close()
    authority.write_text(
        json.dumps(
            {
                "schema_version": "CDH-B10-COUPON-SNAPSHOT-AUTHORITY-1",
                "database_sha256": digest(database),
                "data_classification": "SYNTHETIC_FIXTURE",
                "contains_private_data": False,
                "authorized_use": "AUTHORIZED_SYNTHETIC_OFFLINE_R06_B_ONLY",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return CouponPriceRepository(database, authority_file=authority, allowed_root=root, clock=lambda: NOW)


def wsgi_request(app, path: str):
    captured = {}
    route, _, query = path.partition("?")
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": route, "QUERY_STRING": query, "wsgi.input": io.BytesIO()}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(headers)

    body = b"".join(app(environ, start_response))
    return captured["status"], json.loads(body) if body else None, captured["headers"]


def disabled_affiliate(**changes):
    value = {
        "state": "DISABLED", "cta_enabled": False, "click_url": None,
        "metadata_verified": False, "envelope_id": None, "reason_codes": ("SOURCE_BLOCKED",),
    }
    value.update(changes)
    return AffiliateTrustInput(**value)


def disabled_ceiling(**changes):
    value = {
        "state": "SOURCE_AUTHORIZATION_REQUIRED", "source_authorization_required": True,
        "account_authorized": False, "runtime_authorized": False, "cta_enabled": False,
        "click_url": None, "endpoint_hosts": frozenset(), "redirect_hosts": frozenset(),
    }
    value.update(changes)
    return RuntimeCeiling(**value)


def request_for(snapshot, profile="SYN-ELIGIBLE-PROFILE"):
    return GateRequest(snapshot.series_identity, profile, True)


def evaluate(snapshot, *, request=None, affiliate=None, ceiling=None):
    return AffiliateCouponGateV6().evaluate(
        snapshot=snapshot,
        request=request or request_for(snapshot),
        affiliate=affiliate or disabled_affiliate(),
        ceiling=ceiling or disabled_ceiling(),
        now=NOW,
    )


class ActualB10WireTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "review" / "F06" / "tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix="case-", dir=base))

    def tearDown(self):
        shutil.rmtree(self.temp)

    def app(self, **kwargs):
        return CouponPriceV4App(make_fixture(self.temp, **kwargs))

    def test_exact_b10_release_hash_is_bound(self):
        self.assertEqual(digest(B10_ZIP), EXPECTED_B10_SHA256)
        manifest = json.loads((B10_ROOT / "REVIEW_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], "CDH-B10-REVIEW-MANIFEST-1")
        self.assertEqual(len(manifest["payloads"]), 51)

    def test_real_wsgi_search_and_detail_are_consumed(self):
        app = self.app()
        search_status, search_body, search_headers = wsgi_request(app, "/api/v4/products?q=coupon&page=1&limit=20")
        detail_status, detail_body, detail_headers = wsgi_request(app, "/api/v4/products/series-1")
        self.assertEqual((search_status, detail_status), (200, 200))
        self.assertNotIn("Access-Control-Allow-Origin", search_headers)
        self.assertIn("Content-Security-Policy", detail_headers)
        search = adapt_search_envelope(search_body)[0]
        detail = adapt_detail_envelope(detail_body)
        self.assertEqual(search.series_identity, detail.series_identity)
        self.assertEqual((detail.base_price_twd, detail.before_coupon_price_twd, detail.confirmed_coupon_price_twd), (99, 99, 49))
        self.assertEqual((len(detail.before_coupon_history), len(detail.confirmed_after_coupon_history)), (1, 1))
        decision = evaluate(detail)
        self.assertEqual((decision.display_price_twd, decision.display_basis), (49, "CONFIRMED_COUPON"))
        self.assertEqual((decision.before_coupon_history_count, decision.confirmed_after_coupon_history_count), (1, 1))
        self.assertFalse(decision.cta_enabled)
        self.assertIsNone(decision.click_url)

    def test_real_wsgi_two_item_order_coupon_preserves_total_semantics(self):
        obs = base_observation(base_price_twd=100, discount_twd=50, discount_scope="ORDER_TOTAL", stored_confirmed_coupon_price_twd=75)
        app = self.app(series=[base_series(minimum_purchase_quantity=2)], observations=[obs])
        detail = adapt_detail_envelope(wsgi_request(app, "/api/v4/products/series-1")[1])
        decision = evaluate(detail)
        self.assertEqual(decision.minimum_purchase_quantity, 2)
        self.assertEqual(decision.display_price_twd, 75)
        self.assertEqual(decision.minimum_item_spend_twd, 150)
        self.assertIsNone(decision.required_total_twd)

    def test_real_wsgi_already_included_preserves_before_price_and_does_not_double_discount(self):
        obs = base_observation(
            base_price_twd=49, already_included_in_base=1, stored_confirmed_coupon_price_twd=49,
            pre_coupon_comparison_price_twd=99, pre_coupon_comparison_source="SYN-LISTED-BASE-EVIDENCE",
        )
        detail = adapt_detail_envelope(wsgi_request(self.app(observations=[obs]), "/api/v4/products/series-1")[1])
        decision = evaluate(detail)
        self.assertEqual((decision.before_coupon_price_twd, decision.base_price_twd, decision.display_price_twd), (99, 49, 49))
        self.assertFalse(decision.coupon_applied)
        self.assertNotIn("ALREADY_INCLUDED_EVIDENCE_INVALID", decision.reason_codes)

    def test_real_wsgi_expired_permission_suppresses_prices_histories_and_cta(self):
        detail = adapt_detail_envelope(wsgi_request(self.app(expires="2026-11-05T03:59:59Z"), "/api/v4/products/series-1")[1])
        decision = evaluate(detail)
        self.assertEqual(decision.display_basis, "PRICE_UNAVAILABLE")
        self.assertIsNone(decision.display_price_twd)
        self.assertEqual((decision.before_coupon_history_count, decision.confirmed_after_coupon_history_count), (0, 0))
        self.assertIn("SOURCE_PERMISSION_EXPIRED", decision.reason_codes)
        self.assertFalse(decision.cta_enabled)

    def test_real_wsgi_unconfirmed_status_falls_back_to_base(self):
        for status in ("CLAIM_REQUIRED", "UNVERIFIED", "INELIGIBLE", "EXPIRED", "UNKNOWN", "NONE"):
            with self.subTest(status=status):
                folder = self.temp / status
                folder.mkdir()
                obs = base_observation(coupon_status=status, stored_confirmed_coupon_price_twd=None, stored_possible_coupon_price_twd=49)
                app = CouponPriceV4App(make_fixture(folder, observations=[obs]))
                snapshot = adapt_search_envelope(wsgi_request(app, "/api/v4/products")[1])[0]
                decision = evaluate(snapshot)
                self.assertEqual((decision.display_price_twd, decision.display_basis), (99, "BASE_PRICE"))
                self.assertIsNone(decision.confirmed_coupon_price_twd)
                self.assertFalse(decision.cta_enabled)

    def test_zero_price_remains_zero_but_unknown_shipping_total_is_null(self):
        obs = base_observation(base_price_twd=50, discount_twd=50, stored_confirmed_coupon_price_twd=0)
        snapshot = adapt_search_envelope(wsgi_request(self.app(observations=[obs]), "/api/v4/products")[1])[0]
        decision = evaluate(snapshot)
        self.assertEqual(decision.display_price_twd, 0)
        self.assertIsNone(decision.required_total_twd)
        self.assertNotEqual(decision.required_total_twd, 0)


class NegativeAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = ROOT / "review" / "F06" / "tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        cls.temp = Path(tempfile.mkdtemp(prefix="negative-", dir=base))
        app = CouponPriceV4App(make_fixture(cls.temp))
        cls.search = wsgi_request(app, "/api/v4/products")[1]
        cls.detail = wsgi_request(app, "/api/v4/products/series-1")[1]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp)

    def assert_code(self, payload, parser, code):
        with self.assertRaises(B10WireError) as caught:
            parser(payload)
        self.assertEqual(caught.exception.code, code)

    def test_envelope_and_product_extra_fields_are_rejected(self):
        value = copy.deepcopy(self.search)
        value["extra"] = True
        self.assert_code(value, adapt_search_envelope, "B10_SEARCH_STRUCTURE_INVALID")
        value = copy.deepcopy(self.detail)
        value["product"]["extra"] = True
        self.assert_code(value, adapt_detail_envelope, "B10_PRODUCT_STRUCTURE_INVALID")

    def test_secret_or_url_smuggling_is_rejected_at_any_depth(self):
        for key in ("click_url", "token", "cookie", "authorization"):
            with self.subTest(key=key):
                value = copy.deepcopy(self.detail)
                value["history"]["before_coupon"][0][key] = "synthetic"
                self.assert_code(value, adapt_detail_envelope, "FORBIDDEN_SECRET_OR_URL_FIELD")

    def test_history_series_and_quality_mismatches_are_rejected(self):
        value = copy.deepcopy(self.detail)
        value["history"]["before_coupon"][0]["series_key"] = "other"
        self.assert_code(value, adapt_detail_envelope, "HISTORY_SERIES_MISMATCH")
        value = copy.deepcopy(self.detail)
        value["history_quality"]["before_coupon"]["raw_sample_count"] = 2
        self.assert_code(value, adapt_detail_envelope, "HISTORY_RAW_COUNT_MISMATCH")
        value = copy.deepcopy(self.detail)
        value["history_quality"]["before_coupon"]["daily_representatives"][0]["representative_price_twd"] = 1
        self.assert_code(value, adapt_detail_envelope, "DAILY_REPRESENTATIVE_MISMATCH")

    def test_quantity_spend_and_unknown_shipping_contradictions_are_rejected(self):
        value = copy.deepcopy(self.search)
        value["items"][0]["minimum_purchase_quantity"] = 2
        self.assert_code(value, adapt_search_envelope, "MINIMUM_ITEM_SPEND_MISMATCH")
        value = copy.deepcopy(self.search)
        value["items"][0]["required_total_twd"] = 49
        self.assert_code(value, adapt_search_envelope, "UNKNOWN_SHIPPING_TOTAL_INVALID")

    def test_permission_denial_cannot_leak_price_or_history(self):
        value = copy.deepcopy(self.detail)
        value["product"]["source_permission"] = {"allowed": False, "state": "REVOKED", "reason": "SOURCE_PERMISSION_REVOKED"}
        self.assert_code(value, adapt_detail_envelope, "SOURCE_PERMISSION_PRICE_LEAK")
        value = copy.deepcopy(self.detail)
        value["product"]["source_permission"] = {"allowed": False, "state": "REVOKED", "reason": "SOURCE_PERMISSION_REVOKED"}
        value["product"].update(
            {
                "base_price_twd": None, "before_coupon_price_twd": None, "confirmed_coupon_price_twd": None,
                "possible_coupon_price_twd": None, "display_price_twd": None, "display_basis": "PRICE_UNAVAILABLE",
                "minimum_item_spend_twd": None, "required_total_twd": None,
                "quality_flags": ["SOURCE_PERMISSION_REVOKED"],
            }
        )
        self.assert_code(value, adapt_detail_envelope, "SOURCE_PERMISSION_HISTORY_LEAK")

    def test_already_included_requires_exact_comparison_evidence(self):
        value = copy.deepcopy(self.search)
        item = value["items"][0]
        item.update({"base_price_twd": 49, "before_coupon_price_twd": 99, "confirmed_coupon_price_twd": 49, "display_price_twd": 49, "minimum_item_spend_twd": 49})
        item["coupon"].update({"already_included_in_base": True, "pre_coupon_comparison_source": None})
        self.assert_code(value, adapt_search_envelope, "ALREADY_INCLUDED_EVIDENCE_INVALID")


class GateAndStaticPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = ROOT / "review" / "F06" / "tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        cls.temp = Path(tempfile.mkdtemp(prefix="gate-", dir=base))
        app = CouponPriceV4App(make_fixture(cls.temp))
        cls.snapshot = adapt_detail_envelope(wsgi_request(app, "/api/v4/products/series-1")[1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp)

    def test_identity_or_eligibility_mismatch_never_uses_coupon(self):
        changed = copy.copy(self.snapshot.series_identity)
        changed = type(changed)(changed.platform, changed.product_id, "OTHER", changed.seller_id, changed.condition, changed.package_signature)
        for request in (GateRequest(changed, "SYN-ELIGIBLE-PROFILE", True), request_for(self.snapshot, "OTHER")):
            with self.subTest(request=request):
                decision = evaluate(self.snapshot, request=request)
                self.assertEqual((decision.display_price_twd, decision.display_basis), (99, "BASE_PRICE"))
                self.assertFalse(decision.cta_enabled)

    def test_positive_looking_affiliate_and_ceiling_are_suppressed(self):
        affiliate = disabled_affiliate(
            state="VERIFIED", cta_enabled=True, click_url="https://affiliate.invalid/synthetic",
            metadata_verified=True, envelope_id="a" * 64,
        )
        ceiling = disabled_ceiling(
            state="RUNTIME_AUTHORIZED", source_authorization_required=False, account_authorized=True,
            runtime_authorized=True, cta_enabled=True, endpoint_hosts=frozenset({"affiliate.invalid"}),
            redirect_hosts=frozenset({"affiliate.invalid"}),
        )
        decision = evaluate(self.snapshot, affiliate=affiliate, ceiling=ceiling)
        self.assertFalse(decision.cta_enabled)
        self.assertIsNone(decision.click_url)
        self.assertIn("AFFILIATE_AUTHORITY_NOT_GRANTED_R07", decision.reason_codes)
        self.assertIn("UNTRUSTED_CLICK_URL_SUPPRESSED", decision.reason_codes)
        self.assertIn("UNAUTHORIZED_POSITIVE_CEILING_SUPPRESSED", decision.reason_codes)

    def test_audit_redacts_raw_source_coupon_profile_and_series_key(self):
        decision = evaluate(self.snapshot)
        encoded = json.dumps(decision.audit_event, ensure_ascii=False)
        for raw in ("SYN-SOURCE-1", "SYN-COUPON-1", "SYN-ELIGIBLE-PROFILE", "series-1", "SYN-SKU-1"):
            self.assertNotIn(raw, encoded)

    def test_static_scan_uses_text_allowlist_and_ignores_generated_bytecode(self):
        target = SERVICE / "affiliate_coupon_gate_v6" / "adapter.py"
        cache = SERVICE / "affiliate_coupon_gate_v6" / "__pycache__" / "policy-test.pyc"
        py_compile.compile(str(target), cfile=str(cache), doraise=True)
        try:
            files = tuple(text_source_files(SERVICE))
            self.assertNotIn(cache, files)
            source = "\n".join(path.read_text(encoding="utf-8") for path in files)
            for forbidden in ("requests", "httpx", "urllib.request", "socket", "selenium", "playwright", "os.environ", "dotenv", "coupang.com"):
                self.assertNotIn(forbidden, source.casefold())
        finally:
            cache.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
