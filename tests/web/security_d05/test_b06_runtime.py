from __future__ import annotations

import sqlite3
import sys
import unittest
from datetime import datetime, timezone

from tests.web.security_d05.helpers import RELEASES, cleanup, request, workspace


B06_IMPORT = str(RELEASES / "CDH_B06_001_REVIEW.zip") + "/services/price_query"
if B06_IMPORT not in sys.path:
    sys.path.insert(0, B06_IMPORT)

from price_query import PriceQueryApp, ReadonlyPriceRepository  # noqa: E402


NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)
SCHEMA = """
CREATE TABLE observations(
 observation_id INTEGER PRIMARY KEY, submission_id TEXT NOT NULL,
 observed_at_utc TEXT NOT NULL, source_id TEXT, source_kind TEXT NOT NULL,
 product_title TEXT NOT NULL, product_id TEXT, variant_id TEXT, seller_id TEXT,
 displayed_price_twd INTEGER NOT NULL, price_basis TEXT NOT NULL,
 minimum_purchase_quantity INTEGER, shipping_status TEXT NOT NULL,
 stock_status TEXT NOT NULL, is_synthetic INTEGER NOT NULL
);
"""


class B06RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace()
        self.database = self.root / "isolated.sqlite3"
        connection = sqlite3.connect(self.database)
        connection.executescript(SCHEMA)
        rows = [
            (1, "u1", "2026-10-20T00:00:00Z", "manual", "USER_ENTERED", "Same Name", "P1", "V1", "S1", 300, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 0),
            (2, "u2", "2026-11-03T00:00:00Z", "file", "USER_FILE", "Same Name", "P1", "V1", "S1", 0, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 0),
            (3, "u3", "2026-11-04T00:00:00Z", "manual", "USER_ENTERED", "Same Name", "P1", "V2", "S1", 400, "CURRENT_ITEM_PRICE", 1, "PAID", "IN_STOCK", 0),
            (4, "u4", "2026-11-04T01:00:00Z", "manual", "USER_ENTERED", "Same Name", "P1", "V1", "S2", 500, "CURRENT_ITEM_PRICE", 1, "FREE", "IN_STOCK", 0),
            (5, "s1", "2026-11-04T02:00:00Z", "fixture", "SYNTHETIC", "Synthetic", "PS", "VS", "SS", 123, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 1),
            (6, "x1", "2026-11-04T03:00:00Z", "feed", "APPROVED_FEED", "Unknown", "PX", "VX", "SX", 222, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 0),
        ]
        connection.executemany("INSERT INTO observations VALUES(" + ",".join("?" for _ in range(15)) + ")", rows)
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        cleanup(self.root)

    def app(self, classification: str = "USER_RECORDED") -> PriceQueryApp:
        repo = ReadonlyPriceRepository(self.database, allowed_root=self.root, clock=lambda: NOW, data_classification=classification)
        return PriceQueryApp(repo)

    def test_search_detail_history_and_affiliate_v2_shape(self) -> None:
        app = self.app()
        status, search, headers = request(app, "/api/v2/products")
        self.assertEqual(status, 200)
        self.assertEqual(search["schema_version"], "CDH-WEB-CONTRACT-V2")
        self.assertEqual(search["total"], 3)
        self.assertEqual(headers["Cache-Control"], "no-store")
        product_id = search["items"][0]["id"]
        detail = request(app, f"/api/v2/products/{product_id}")[1]
        affiliate = request(app, f"/api/v2/products/{product_id}/affiliate")[1]
        self.assertEqual(detail["product"]["id"], product_id)
        self.assertIsInstance(detail["history"], list)
        self.assertEqual(affiliate["product_id"], product_id)
        self.assertEqual(affiliate["affiliate"]["state"], "UNCONFIGURED")
        self.assertIsNone(affiliate["affiliate"]["click_url"])

    def test_same_name_wrong_sku_and_seller_never_merge(self) -> None:
        app = self.app()
        search = request(app, "/api/v2/products", {"q": "Same Name"})[1]
        identities = set()
        for item in search["items"]:
            detail = request(app, f"/api/v2/products/{item['id']}")[1]
            offer = detail["offers"][0]
            identities.add((offer["product_id"], offer["sku_id"], offer["seller_id"]))
        self.assertEqual(identities, {("P1", "V1", "S1"), ("P1", "V2", "S1"), ("P1", "V1", "S2")})

    def test_zero_unknown_missing_days_and_stale_are_not_reinterpreted(self) -> None:
        app = self.app()
        search = request(app, "/api/v2/products") [1]
        target = next(item for item in search["items"] if item["last_observed_price_twd"] == 0)
        self.assertEqual(target["shipping_status"], "UNKNOWN")
        self.assertIn("PRICE_IS_USER_OBSERVED_NOT_CHECKOUT_TOTAL", target["quality_flags"])
        self.assertIn("M30_LOW_COVERAGE", target["quality_flags"])
        detail = request(app, f"/api/v2/products/{target['id']}")[1]
        self.assertEqual(detail["observation_period_min_twd"], 0)
        self.assertEqual(len(detail["history"]), 2)
        self.assertEqual(target["observed_days"], 2)

    def test_source_classifications_are_separated(self) -> None:
        user = request(self.app(), "/api/v2/products")[1]
        synthetic = request(self.app("SYNTHETIC_DEMO_ONLY"), "/api/v2/products")[1]
        self.assertEqual(user["data_classification"], "USER_RECORDED")
        self.assertNotIn("Synthetic", " ".join(item["title"] for item in user["items"]))
        self.assertEqual(synthetic["data_source_status"], "SYNTHETIC_FIXTURE_ONLY")
        self.assertEqual([item["title"] for item in synthetic["items"]], ["Synthetic"])

    def test_v1_is_still_available_and_therefore_downgrade_must_be_blocked_by_a(self) -> None:
        app = self.app()
        v1 = request(app, "/api/v1/products")[1]
        v2 = request(app, "/api/v2/products")[1]
        self.assertEqual(v1["schema_version"], "CDH-WEB-CONTRACT-V1")
        self.assertEqual(v2["schema_version"], "CDH-WEB-CONTRACT-V2")
        product_id = v1["items"][0]["id"]
        flattened = request(app, f"/api/v1/products/{product_id}/affiliate")[1]
        self.assertIn("state", flattened)
        self.assertNotIn("affiliate", flattened)


if __name__ == "__main__":
    unittest.main()
