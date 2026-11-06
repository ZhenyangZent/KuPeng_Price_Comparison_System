from __future__ import annotations

import contextlib
import copy
import hashlib
import http.client
import json
import shutil
import sys
import tempfile
import threading
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server


ROOT = Path(__file__).resolve().parents[2]
V7_SERVICE = ROOT / "services" / "affiliate_coupon_gate_v7"
B11_INPUT = ROOT / "review" / "F07" / "controlled_inputs" / "B11"
F06_INPUT = ROOT / "review" / "F07" / "controlled_inputs" / "F06"
B11_RELEASE = B11_INPUT / "extracted" / "CDH_B_R07_001_REVIEW"
F06_RELEASE = F06_INPUT / "extracted" / "CDH_F_R07_001_REVIEW"
sys.path.insert(0, str(V7_SERVICE))
sys.path.insert(0, str(F06_RELEASE / "services" / "affiliate_coupon_gate_v6"))
sys.path.insert(0, str(B11_RELEASE / "services" / "price_coupon_v4"))

import affiliate_coupon_gate_v6 as f06  # noqa: E402
from affiliate_coupon_gate_v7 import BindingError, ExactB11F06Binding  # noqa: E402
from price_coupon_v4 import CouponPriceRepository, CouponPriceV4App  # noqa: E402


NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)
FIXTURE_ROOT = B11_RELEASE / "services" / "price_coupon_v4" / "fixtures" / "b11_suite"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        return None


@contextlib.contextmanager
def actual_http(snapshot_name: str):
    target = FIXTURE_ROOT / snapshot_name
    repository = CouponPriceRepository(
        target / "coupon.sqlite3",
        authority_file=target / "coupon.authority.json",
        allowed_root=target,
        clock=lambda: NOW,
    )
    app = CouponPriceV4App(repository)
    server = make_server("127.0.0.1", 0, app, handler_class=QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("loopback B11 server did not stop")


def http_json(port: int, path: str):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        return response.status, json.loads(body) if body else None, dict(response.getheaders())
    finally:
        connection.close()


def disabled_affiliate(**changes):
    values = {
        "state": "DISABLED", "cta_enabled": False, "click_url": None,
        "metadata_verified": False, "envelope_id": None, "reason_codes": ("SOURCE_BLOCKED",),
    }
    values.update(changes)
    return f06.AffiliateTrustInput(**values)


def disabled_ceiling(**changes):
    values = {
        "state": "SOURCE_AUTHORIZATION_REQUIRED", "source_authorization_required": True,
        "account_authorized": False, "runtime_authorized": False, "cta_enabled": False,
        "click_url": None, "endpoint_hosts": frozenset(), "redirect_hosts": frozenset(),
    }
    values.update(changes)
    return f06.RuntimeCeiling(**values)


def exact_binding():
    return ExactB11F06Binding(
        b11_zip=B11_INPUT / "CDH_B_R07_001_REVIEW.zip",
        b11_extracted=B11_INPUT / "extracted",
        f06_zip=F06_INPUT / "CDH_F_R07_001_REVIEW.zip",
        f06_extracted=F06_INPUT / "extracted",
        adapter_module=f06,
    )


class F07BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binding = exact_binding()

    def decision(self, snapshot, *, identity=None, profile=None, affiliate=None, ceiling=None):
        chosen_profile = snapshot.coupon.eligibility_profile if profile is None else profile
        return self.binding.evaluate(
            snapshot=snapshot,
            request=f06.GateRequest(identity or snapshot.series_identity, chosen_profile, True),
            affiliate=affiliate or disabled_affiliate(),
            ceiling=ceiling or disabled_ceiling(),
            now=NOW,
        )

    def test_exact_release_and_adapter_origin_binding(self):
        evidence = self.binding.evidence
        self.assertEqual(evidence.b11.sha256, "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a")
        self.assertEqual((evidence.b11.entries, evidence.b11.payloads), (74, 73))
        self.assertEqual(evidence.f06.sha256, "c2db9aa981cbc935b52944516d5b4259829ffa5af892ac3dc7d28fc6b022ac89")
        self.assertEqual((evidence.f06.entries, evidence.f06.payloads), (90, 89))
        self.assertEqual(evidence.b11_fixture_count, 4)
        self.assertTrue(Path(evidence.adapter_origin).is_relative_to(F06_RELEASE))

    def test_modified_release_is_rejected_before_use(self):
        base = ROOT / "review" / "F07" / "tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix="binding-", dir=base))
        try:
            changed = folder / "changed.zip"
            shutil.copy2(B11_INPUT / "CDH_B_R07_001_REVIEW.zip", changed)
            data = bytearray(changed.read_bytes())
            data[-1] ^= 1
            changed.write_bytes(data)
            with self.assertRaises(BindingError) as caught:
                ExactB11F06Binding(
                    b11_zip=changed, b11_extracted=B11_INPUT / "extracted",
                    f06_zip=F06_INPUT / "CDH_F_R07_001_REVIEW.zip", f06_extracted=F06_INPUT / "extracted",
                    adapter_module=f06,
                )
            self.assertEqual(caught.exception.code, "RELEASE_SHA256_MISMATCH")
        finally:
            shutil.rmtree(folder)

    def test_wrong_adapter_origin_is_rejected(self):
        fake = types.ModuleType("fake_f06")
        fake.__file__ = str(V7_SERVICE / "affiliate_coupon_gate_v7" / "binding.py")
        fake.adapt_search_envelope = lambda value: value
        fake.adapt_detail_envelope = lambda value: value
        fake.AffiliateCouponGateV6 = lambda: None
        with self.assertRaises(BindingError) as caught:
            ExactB11F06Binding(
                b11_zip=B11_INPUT / "CDH_B_R07_001_REVIEW.zip", b11_extracted=B11_INPUT / "extracted",
                f06_zip=F06_INPUT / "CDH_F_R07_001_REVIEW.zip", f06_extracted=F06_INPUT / "extracted",
                adapter_module=fake,
            )
        self.assertEqual(caught.exception.code, "F06_ADAPTER_ORIGIN_MISMATCH")

    def test_active_actual_http_all_nine_cases(self):
        with actual_http("active") as port:
            status, payload, headers = http_json(port, "/api/v4/products?page=1&limit=20")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["items"]), 9)
        self.assertEqual(headers["X-CDH-Schema-Version"], "CDH-COUPON-PRICE-V4")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        snapshots = {item.series_key: item for item in self.binding.adapt_search(payload)}
        decisions = {key: self.decision(item) for key, item in snapshots.items()}
        expected = {
            "confirmed": (49, "CONFIRMED_COUPON"),
            "claim-required": (99, "BASE_PRICE"),
            "expired-coupon": (99, "BASE_PRICE"),
            "unknown-coupon": (99, "BASE_PRICE"),
            "already-included": (49, "CONFIRMED_COUPON"),
            "quantity-two": (75, "CONFIRMED_COUPON"),
            "wrong-sku": (99, "BASE_PRICE"),
            "zero": (0, "CONFIRMED_COUPON"),
            "unavailable": (None, "PRICE_UNAVAILABLE"),
        }
        self.assertEqual({key: (item.display_price_twd, item.display_basis) for key, item in decisions.items()}, expected)
        self.assertEqual((decisions["quantity-two"].minimum_purchase_quantity, decisions["quantity-two"].minimum_item_spend_twd), (2, 150))
        self.assertEqual((decisions["already-included"].before_coupon_price_twd, decisions["already-included"].coupon_applied), (99, False))
        self.assertEqual((decisions["zero"].display_price_twd, decisions["zero"].required_total_twd), (0, None))
        for decision in decisions.values():
            self.assertFalse(decision.cta_enabled)
            self.assertIsNone(decision.click_url)

    def test_confirmed_actual_http_detail_preserves_dual_raw_and_daily_history(self):
        with actual_http("active") as port:
            status, payload, _ = http_json(port, "/api/v4/products/confirmed")
        self.assertEqual(status, 200)
        snapshot = self.binding.adapt_detail(payload)
        decision = self.decision(snapshot)
        self.assertEqual((snapshot.before_coupon_price_twd, decision.display_price_twd), (99, 49))
        self.assertEqual((len(snapshot.before_coupon_history), len(snapshot.confirmed_after_coupon_history)), (1, 1))
        self.assertEqual(snapshot.before_coupon_history_quality.daily_representatives, (("2026-11-04", 99, 1),))
        self.assertEqual(snapshot.confirmed_after_coupon_history_quality.daily_representatives, (("2026-11-04", 49, 1),))
        self.assertFalse(decision.cta_enabled)

    def test_expired_and_revoked_actual_http_suppress_prices_histories_and_cta(self):
        for name, reason in (("expired-source", "SOURCE_PERMISSION_EXPIRED"), ("revoked-source", "SOURCE_PERMISSION_REVOKED")):
            with self.subTest(name=name), actual_http(name) as port:
                status, search, _ = http_json(port, "/api/v4/products")
                key = search["items"][0]["series_key"]
                detail_status, detail, _ = http_json(port, f"/api/v4/products/{key}")
            self.assertEqual((status, detail_status), (200, 200))
            snapshot = self.binding.adapt_detail(detail)
            decision = self.decision(snapshot)
            self.assertEqual(snapshot.source_permission.reason, reason)
            self.assertEqual((decision.display_price_twd, decision.display_basis), (None, "PRICE_UNAVAILABLE"))
            self.assertEqual((len(snapshot.before_coupon_history), len(snapshot.confirmed_after_coupon_history)), (0, 0))
            self.assertFalse(decision.cta_enabled)

    def test_empty_actual_http_is_unavailable_not_zero(self):
        with actual_http("empty-history") as port:
            status, detail, _ = http_json(port, "/api/v4/products/empty-history")
        self.assertEqual(status, 200)
        snapshot = self.binding.adapt_detail(detail)
        decision = self.decision(snapshot)
        self.assertIsNone(decision.display_price_twd)
        self.assertNotEqual(decision.display_price_twd, 0)
        self.assertEqual(decision.display_basis, "PRICE_UNAVAILABLE")
        self.assertEqual((snapshot.before_coupon_history_quality.raw_sample_count, snapshot.confirmed_after_coupon_history_quality.raw_sample_count), (0, 0))

    def test_canonical_databases_remain_read_only_across_http(self):
        before = {path.relative_to(FIXTURE_ROOT).as_posix(): sha256(path) for path in FIXTURE_ROOT.rglob("*.sqlite3")}
        for name in ("active", "expired-source", "revoked-source", "empty-history"):
            with actual_http(name) as port:
                self.assertEqual(http_json(port, "/api/v4/products")[0], 200)
        after = {path.relative_to(FIXTURE_ROOT).as_posix(): sha256(path) for path in FIXTURE_ROOT.rglob("*.sqlite3")}
        self.assertEqual(before, after)


class F07MutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binding = exact_binding()
        with actual_http("active") as port:
            cls.search = http_json(port, "/api/v4/products?page=1&limit=20")[1]
            cls.detail = http_json(port, "/api/v4/products/confirmed")[1]

    def assert_adapter_code(self, payload, method: str, code: str):
        with self.assertRaises(f06.B10WireError) as caught:
            getattr(self.binding, method)(payload)
        self.assertEqual(caught.exception.code, code)

    def test_unknown_fields_are_rejected_not_stripped(self):
        value = copy.deepcopy(self.search)
        value["future_field"] = "must-not-strip"
        self.assert_adapter_code(value, "adapt_search", "B10_SEARCH_STRUCTURE_INVALID")
        value = copy.deepcopy(self.search)
        value["items"][0]["future_field"] = "must-not-strip"
        self.assert_adapter_code(value, "adapt_search", "B10_PRODUCT_STRUCTURE_INVALID")

    def test_quantity_and_permission_mutations_are_rejected(self):
        value = copy.deepcopy(self.search)
        value["items"][0]["minimum_purchase_quantity"] = 2
        self.assert_adapter_code(value, "adapt_search", "MINIMUM_ITEM_SPEND_MISMATCH")
        value = copy.deepcopy(self.search)
        value["items"][0]["source_permission"]["allowed"] = False
        self.assert_adapter_code(value, "adapt_search", "SOURCE_PERMISSION_CONTRADICTION")

    def test_history_identity_count_and_daily_mutations_are_rejected(self):
        value = copy.deepcopy(self.detail)
        value["history"]["before_coupon"][0]["series_key"] = "other"
        self.assert_adapter_code(value, "adapt_detail", "HISTORY_SERIES_MISMATCH")
        value = copy.deepcopy(self.detail)
        value["history_quality"]["before_coupon"]["raw_sample_count"] = 2
        self.assert_adapter_code(value, "adapt_detail", "HISTORY_RAW_COUNT_MISMATCH")
        value = copy.deepcopy(self.detail)
        value["history_quality"]["confirmed_after_coupon"]["daily_representatives"][0]["representative_price_twd"] = 1
        self.assert_adapter_code(value, "adapt_detail", "DAILY_REPRESENTATIVE_MISMATCH")

    def test_identity_and_expiry_mutations_fail_coupon_closed(self):
        snapshot = self.binding.adapt_search(self.search)[0]
        value = copy.deepcopy(self.search)
        value["items"][0]["series_identity"]["sku_id"] = "MUTATED-SKU"
        mutated = self.binding.adapt_search(value)[0]
        decision = self.binding.evaluate(
            snapshot=mutated,
            request=f06.GateRequest(snapshot.series_identity, mutated.coupon.eligibility_profile, True),
            affiliate=disabled_affiliate(), ceiling=disabled_ceiling(), now=NOW,
        )
        self.assertEqual(decision.display_basis, "BASE_PRICE")
        self.assertIn("COUPON_SERIES_IDENTITY_MISMATCH", decision.reason_codes)
        self.assertFalse(decision.cta_enabled)
        value = copy.deepcopy(self.search)
        value["items"][0]["coupon"]["valid_until"] = "2026-11-05T03:59:59Z"
        expired = self.binding.adapt_search(value)[0]
        decision = self.binding.evaluate(
            snapshot=expired,
            request=f06.GateRequest(expired.series_identity, expired.coupon.eligibility_profile, True),
            affiliate=disabled_affiliate(), ceiling=disabled_ceiling(), now=NOW,
        )
        self.assertEqual(decision.display_basis, "BASE_PRICE")
        self.assertIn("COUPON_NOT_CURRENTLY_VALID", decision.reason_codes)
        self.assertFalse(decision.cta_enabled)

    def test_positive_looking_affiliate_inputs_never_enable(self):
        snapshot = self.binding.adapt_detail(self.detail)
        affiliate = disabled_affiliate(
            state="VERIFIED", cta_enabled=True, click_url="https://affiliate.invalid/synthetic",
            metadata_verified=True, envelope_id="a" * 64,
        )
        ceiling = disabled_ceiling(
            state="RUNTIME_AUTHORIZED", source_authorization_required=False, account_authorized=True,
            runtime_authorized=True, cta_enabled=True, endpoint_hosts=frozenset({"affiliate.invalid"}),
            redirect_hosts=frozenset({"affiliate.invalid"}),
        )
        decision = self.binding.evaluate(
            snapshot=snapshot,
            request=f06.GateRequest(snapshot.series_identity, snapshot.coupon.eligibility_profile, True),
            affiliate=affiliate, ceiling=ceiling, now=NOW,
        )
        self.assertFalse(decision.cta_enabled)
        self.assertIsNone(decision.click_url)
        self.assertIn("AFFILIATE_AUTHORITY_NOT_GRANTED_R07", decision.reason_codes)


if __name__ == "__main__":
    unittest.main()
