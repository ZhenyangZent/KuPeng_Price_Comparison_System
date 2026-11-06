from __future__ import annotations

import copy
import sqlite3
import sys
import unittest
from datetime import datetime, timezone

from tools.web_contract_audit.v2 import assess_v2_bundle
from tests.web.contract_audit.helpers import RELEASES, cleanup, request, workspace


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


class B06V2RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace()
        self.database = self.root / "approved_synthetic_copy.sqlite3"
        connection = sqlite3.connect(self.database)
        connection.executescript(SCHEMA)
        rows = [
            (1, "u1", "2026-11-01T00:00:00Z", "local", "USER_ENTERED", "Jacket", "P1", "V1", "S1", 300, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 0),
            (2, "u2", "2026-11-03T00:00:00Z", "file", "USER_FILE", "Jacket", "P1", "V1", "S1", 0, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 0),
            (3, "u3", "2026-11-04T00:00:00Z", "local", "USER_ENTERED", "Jacket XL", "P1", "V2", "S1", 400, "CURRENT_ITEM_PRICE", 1, "PAID", "IN_STOCK", 0),
            (4, "u4", "2026-11-04T01:00:00Z", "local", "USER_ENTERED", "Jacket Other Seller", "P1", "V1", "S2", 500, "CURRENT_ITEM_PRICE", 1, "FREE", "IN_STOCK", 0),
            (5, "s1", "2026-11-04T02:00:00Z", "fixture", "SYNTHETIC", "Synthetic Jacket", "PS", "VS", "SS", 123, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 1),
            (6, "x1", "2026-11-04T03:00:00Z", "feed", "APPROVED_FEED", "Unknown Source", "PX", "VX", "SX", 222, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 0),
            (7, "f1", "2026-11-06T00:00:00Z", "local", "USER_ENTERED", "Future", "PF", "VF", "SF", 1, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 0),
        ]
        connection.executemany("INSERT INTO observations VALUES(" + ",".join("?" for _ in range(15)) + ")", rows)
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        cleanup(self.root)

    def app(self, classification: str = "USER_RECORDED") -> PriceQueryApp:
        return PriceQueryApp(ReadonlyPriceRepository(self.database, allowed_root=self.root, clock=lambda: NOW, data_classification=classification))

    def bundle_for(self, app: PriceQueryApp, product_id: str) -> tuple[dict, dict, dict]:
        search = request(app, "/api/v2/products")[1]
        detail = request(app, f"/api/v2/products/{product_id}")[1]
        affiliate = request(app, f"/api/v2/products/{product_id}/affiliate")[1]
        return search, detail, affiliate

    def test_user_and_synthetic_sources_are_separated_and_unknown_is_excluded(self) -> None:
        user_app = self.app()
        search = request(user_app, "/api/v2/products")[1]
        self.assertEqual(search["total"], 3)
        self.assertEqual(search["data_classification"], "USER_RECORDED")
        self.assertNotIn("Synthetic", " ".join(item["title"] for item in search["items"]))
        self.assertNotIn("Unknown Source", " ".join(item["title"] for item in search["items"]))
        synthetic = request(self.app("SYNTHETIC_DEMO_ONLY"), "/api/v2/products")[1]
        self.assertEqual(synthetic["total"], 1)
        self.assertEqual(synthetic["data_source_status"], "SYNTHETIC_FIXTURE_ONLY")
        self.assertEqual(synthetic["items"][0]["title"], "Synthetic Jacket")

    def test_variant_seller_pagination_zero_unknown_cost_and_missing_days_are_honest(self) -> None:
        app = self.app()
        self.assertEqual(request(app, "/api/v2/products", {"q": "V2"})[1]["total"], 1)
        self.assertEqual(request(app, "/api/v2/products", {"q": "S2"})[1]["total"], 1)
        self.assertEqual(len(request(app, "/api/v2/products", {"page": "2", "limit": "2"})[1]["items"]), 1)
        search = request(app, "/api/v2/products")[1]
        chosen = None
        for item in search["items"]:
            detail = request(app, f"/api/v2/products/{item['id']}")[1]
            offer = detail["offers"][0]
            if offer["sku_id"] == "V1" and offer["seller_id"] == "S1":
                chosen = (item, detail)
                break
        self.assertIsNotNone(chosen)
        item, detail = chosen
        self.assertEqual(item["last_observed_price_twd"], 0)
        self.assertIn("PRICE_IS_USER_OBSERVED_NOT_CHECKOUT_TOTAL", item["quality_flags"])
        self.assertEqual(item["shipping_status"], "UNKNOWN")
        self.assertNotIn("shipping_fee_twd", item)
        self.assertEqual(detail["product"]["observed_days"], 2)
        self.assertEqual(len(detail["history"]), 2)
        affiliate = request(app, f"/api/v2/products/{item['id']}/affiliate")[1]
        assessment = assess_v2_bundle(search, detail, affiliate, evaluated_at=NOW)
        self.assertTrue(assessment.passed, assessment.findings)
        self.assertEqual(affiliate["affiliate"]["state"], "UNCONFIGURED")
        self.assertIsNone(affiliate["affiliate"]["click_url"])

    def test_contract_mutations_detect_price_cost_source_identity_and_affiliate_lies(self) -> None:
        app = self.app()
        search = request(app, "/api/v2/products")[1]
        product_id = search["items"][0]["id"]
        _, detail, affiliate = self.bundle_for(app, product_id)
        mutations: list[tuple[str, tuple[dict, dict, dict]]] = []

        bad_zero = copy.deepcopy(search)
        bad_zero["items"][0]["last_observed_price_twd"] = 0
        bad_zero["items"][0]["quality_flags"] = []
        mutations.append(("ZERO_PRICE_LACKS_OBSERVED_ONLY_FLAG", (bad_zero, detail, affiliate)))

        bad_cost = copy.deepcopy(search)
        bad_cost["items"][0]["shipping_status"] = "UNKNOWN"
        bad_cost["items"][0]["shipping_fee_twd"] = 0
        mutations.append(("UNKNOWN_SHIPPING_MUST_NOT_BECOME_ZERO_COST", (bad_cost, detail, affiliate)))

        bad_history = copy.deepcopy(detail)
        bad_history["history"][0]["source_type"] = "SYNTHETIC"
        mutations.append(("MIXED_OR_UNKNOWN_HISTORY_SOURCE", (search, bad_history, affiliate)))

        bad_condition = copy.deepcopy(detail)
        bad_condition["offers"][0]["item_condition"] = "NEW"
        mutations.append(("ITEM_CONDITION_UNPROVEN", (search, bad_condition, affiliate)))

        bad_days = copy.deepcopy(detail)
        bad_days["product"]["observed_days"] += 1
        mutations.append(("OBSERVED_DAYS_INTERPOLATED_OR_INCONSISTENT", (search, bad_days, affiliate)))

        bad_affiliate = copy.deepcopy(affiliate)
        bad_affiliate["affiliate"]["click_url"] = "https://www.tw.coupang.com/products/ordinary"
        bad_affiliate["affiliate"]["verified_product_match"] = True
        mutations.append(("UNCONFIGURED_AFFILIATE_CLICKABLE", (search, detail, bad_affiliate)))

        for expected, bundle in mutations:
            with self.subTest(expected=expected):
                codes = {item.code for item in assess_v2_bundle(*bundle, evaluated_at=NOW).findings}
                self.assertIn(expected, codes)

    def test_null_price_is_only_honest_without_claimed_observation(self) -> None:
        app = self.app()
        search = request(app, "/api/v2/products")[1]
        product_id = search["items"][0]["id"]
        _, detail, affiliate = self.bundle_for(app, product_id)
        honest = copy.deepcopy(search)
        honest["items"][0].update({"last_observed_price_twd": None, "last_observed_at": None, "observed_days": 0})
        self.assertNotIn("NULL_PRICE_HISTORY_CONTRADICTION", {f.code for f in assess_v2_bundle(honest, detail, affiliate, evaluated_at=NOW).findings})
        dishonest = copy.deepcopy(honest)
        dishonest["items"][0]["observed_days"] = 1
        self.assertIn("NULL_PRICE_HISTORY_CONTRADICTION", {f.code for f in assess_v2_bundle(dishonest, detail, affiliate, evaluated_at=NOW).findings})


if __name__ == "__main__":
    unittest.main()
