from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import unittest
import urllib.request
from datetime import timedelta
from pathlib import Path
from wsgiref.simple_server import make_server

from e2e_fixture_server import build_synthetic_fixture, create_app
from test_price_query import Fixture, NOW, ROOT, TEMP_ROOT, request

from price_query import PriceQueryApp, ReadonlyPriceRepository, RepositoryError
from price_query.repository import SYNTHETIC_CLASSIFICATION


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ContractV2Case(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.directory = Path(self.temp.name)
        self.database = self.directory / "copy.sqlite3"
        self.fixture = Fixture(self.database)

    def tearDown(self) -> None:
        try:
            self.fixture.connection.close()
        except sqlite3.Error:
            pass
        self.temp.cleanup()

    def repository(self, *, classification: str = "USER_RECORDED") -> ReadonlyPriceRepository:
        self.fixture.close()
        return ReadonlyPriceRepository(
            self.database,
            allowed_root=self.directory,
            clock=lambda: NOW,
            data_classification=classification,
        )

    def app(self, *, classification: str = "USER_RECORDED") -> PriceQueryApp:
        return PriceQueryApp(self.repository(classification=classification))

    def add_default(self, **kwargs) -> None:
        values = {
            "observed": NOW - timedelta(days=1),
            "title": "Recorded Headphones",
            "product": "PRODUCT-42",
            "variant": "SKU-XL-42",
            "seller": "SELLER-9",
            "minimum": 2,
            "shipping": "UNKNOWN",
        }
        values.update(kwargs)
        self.fixture.add(**values)

    def test_v2_search_has_explicit_user_classification(self):
        self.add_default()
        status, value, headers = request(self.app(), "/api/v2/products")
        self.assertEqual(status, 200)
        self.assertEqual(value["schema_version"], "CDH-WEB-CONTRACT-V2")
        self.assertEqual(value["data_source_status"], "USER_RECORDED_ONLY")
        self.assertEqual(value["data_classification"], "USER_RECORDED")
        self.assertEqual(value["contract_compatibility"], ["CDH-WEB-CONTRACT-V1"])
        self.assertEqual(headers["X-CDH-Schema-Version"], "CDH-WEB-CONTRACT-V2")

    def test_v2_detail_has_classification_and_unknown_condition(self):
        self.add_default()
        app = self.app()
        product_id = request(app, "/api/v2/products")[1]["items"][0]["id"]
        value = request(app, f"/api/v2/products/{product_id}")[1]
        self.assertEqual(value["data_source_status"], "USER_RECORDED_ONLY")
        self.assertEqual(value["data_classification"], "USER_RECORDED")
        self.assertEqual(value["offers"][0]["item_condition"], "UNKNOWN")
        self.assertEqual(value["offers"][0]["item_condition_source"], "NOT_RECORDED")

    def test_v2_affiliate_is_nested_and_disabled(self):
        self.add_default()
        app = self.app()
        product_id = request(app, "/api/v2/products")[1]["items"][0]["id"]
        value = request(app, f"/api/v2/products/{product_id}/affiliate")[1]
        self.assertEqual(value["schema_version"], "CDH-WEB-CONTRACT-V2")
        self.assertNotIn("state", value)
        self.assertEqual(value["affiliate"]["state"], "UNCONFIGURED")
        self.assertIsNone(value["affiliate"]["click_url"])
        self.assertFalse(value["affiliate"]["verified_product_match"])
        self.assertIsNone(value["affiliate"]["bound_product_id"])

    def test_v1_affiliate_remains_flattened_with_additive_classification(self):
        self.add_default()
        app = self.app()
        product_id = request(app, "/api/v1/products")[1]["items"][0]["id"]
        value = request(app, f"/api/v1/products/{product_id}/affiliate")[1]
        self.assertEqual(value["schema_version"], "CDH-WEB-CONTRACT-V1")
        self.assertEqual(value["data_classification"], "USER_RECORDED")
        self.assertEqual(value["state"], "UNCONFIGURED")
        self.assertNotIn("affiliate", value)

    def test_error_envelope_uses_requested_contract_version(self):
        self.add_default()
        app = self.app()
        self.assertEqual(request(app, "/api/v1/products", method="POST")[1]["schema_version"], "CDH-WEB-CONTRACT-V1")
        self.assertEqual(request(app, "/api/v2/products", method="POST")[1]["schema_version"], "CDH-WEB-CONTRACT-V2")

    def test_search_matches_title_product_variant_seller_and_signature(self):
        self.add_default()
        app = self.app()
        for term in ("headphones", "PRODUCT-42", "SKU-XL-42", "SELLER-9", "variant:SKU-XL-42"):
            with self.subTest(term=term):
                value = request(app, "/api/v2/products", f"q={term}")[1]
                self.assertEqual(value["total"], 1)
        self.assertEqual(request(app, "/api/v2/products", "q=OTHER-SKU")[1]["total"], 0)

    def test_coverage_is_completed_calendar_days_without_interpolation(self):
        for day in range(1, 8):
            self.add_default(observed=NOW - timedelta(days=day), submission=f"coverage-{day}")
        item = request(self.app(), "/api/v2/products")[1]["items"][0]
        self.assertEqual(item["coverage"]["basis"], "COMPLETED_CALENDAR_DAYS")
        self.assertEqual(item["coverage"]["timezone"], "Asia/Taipei")
        self.assertEqual(item["coverage"]["m7"], {"sample_days": 7, "status": "COMPLETE"})
        self.assertEqual(item["coverage"]["m30"], {"sample_days": 7, "status": "PARTIAL"})

    def test_zero_price_does_not_turn_unknown_shipping_into_free(self):
        self.add_default(price=0, shipping="UNKNOWN")
        item = request(self.app(), "/api/v2/products")[1]["items"][0]
        self.assertEqual(item["last_observed_price_twd"], 0)
        self.assertEqual(item["shipping_status"], "UNKNOWN")
        self.assertIn("SHIPPING_UNKNOWN", item["quality_flags"])

    def test_default_mode_excludes_synthetic_rows(self):
        self.add_default()
        self.fixture.add(
            observed=NOW - timedelta(days=1),
            title="Synthetic hidden",
            product="SYN-P",
            variant="SYN-SKU",
            seller="SYN-S",
            source_kind="SYNTHETIC",
            synthetic=1,
        )
        value = request(self.app(), "/api/v2/products")[1]
        self.assertEqual(value["total"], 1)
        self.assertEqual(value["data_classification"], "USER_RECORDED")

    def test_explicit_synthetic_fixture_mode_is_separate(self):
        self.add_default()
        self.fixture.add(
            observed=NOW - timedelta(days=1),
            title="Synthetic visible only in fixture mode",
            product="SYN-P",
            variant="SYN-SKU",
            seller="SYN-S",
            source_kind="SYNTHETIC",
            synthetic=1,
        )
        value = request(self.app(classification=SYNTHETIC_CLASSIFICATION), "/api/v2/products")[1]
        self.assertEqual(value["total"], 1)
        self.assertEqual(value["data_source_status"], "SYNTHETIC_FIXTURE_ONLY")
        self.assertEqual(value["data_classification"], "SYNTHETIC_DEMO_ONLY")

    def test_unknown_classification_is_rejected(self):
        self.add_default()
        self.fixture.close()
        with self.assertRaises(RepositoryError):
            ReadonlyPriceRepository(
                self.database,
                allowed_root=self.directory,
                clock=lambda: NOW,
                data_classification="GUESSED",
            )

    def test_api_never_uses_wildcard_cors(self):
        self.add_default()
        _, _, headers = request(self.app(), "/api/v2/products")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_v2_requests_preserve_database_bytes(self):
        self.add_default()
        app = self.app()
        before = digest(self.database)
        product_id = request(app, "/api/v2/products")[1]["items"][0]["id"]
        request(app, f"/api/v2/products/{product_id}")
        request(app, f"/api/v2/products/{product_id}/affiliate")
        self.assertEqual(digest(self.database), before)

    def test_actual_loopback_http_uses_synthetic_fixture_classification(self):
        fixture = self.directory / "e2e.sqlite3"
        build_synthetic_fixture(fixture)
        app = create_app(fixture, self.directory)
        server = make_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/api/v2/products?q=SKU-E2E-BLK",
                timeout=5,
            ) as response:
                value = json.loads(response.read())
            self.assertEqual(value["total"], 1)
            self.assertEqual(value["data_classification"], "SYNTHETIC_DEMO_ONLY")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_frozen_contract_documents_ports_and_no_public_cors(self):
        contract = (ROOT / "services/price_query/CONTRACT_V2.md").read_text(encoding="utf-8")
        proxy = (ROOT / "services/price_query/LOOPBACK_PROXY_CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("CDH-WEB-CONTRACT-V2", contract)
        self.assertIn("127.0.0.1:4173", proxy)
        self.assertIn("127.0.0.1:8765", proxy)
        self.assertIn("no `Access-Control-Allow-Origin:*`", proxy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
