from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
import tracemalloc
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "services/price_query"
if str(SERVICE) not in sys.path:
    sys.path.insert(0, str(SERVICE))

from price_query import PriceQueryApp, ReadonlyPriceRepository, RepositoryError  # noqa: E402


NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)
TEMP_ROOT = Path(__file__).parent / ".tmp"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE observations(
 observation_id INTEGER PRIMARY KEY,
 submission_id TEXT NOT NULL,
 observed_at_utc TEXT NOT NULL,
 source_id TEXT,
 source_kind TEXT NOT NULL,
 product_title TEXT NOT NULL,
 product_id TEXT,
 variant_id TEXT,
 seller_id TEXT,
 displayed_price_twd INTEGER NOT NULL,
 price_basis TEXT NOT NULL,
 minimum_purchase_quantity INTEGER,
 shipping_status TEXT NOT NULL,
 stock_status TEXT NOT NULL,
 is_synthetic INTEGER NOT NULL
);
"""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fixture:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.executescript(SCHEMA)
        self.next_id = 1

    def add(
        self,
        *,
        observed: datetime,
        title: str = "Recorded Item",
        price: int = 199,
        product: str | None = "p1",
        variant: str | None = "v1",
        seller: str | None = "s1",
        basis: str = "CURRENT_ITEM_PRICE",
        minimum: int | None = 1,
        source_kind: str = "USER_ENTERED",
        source_id: str | None = "local-user",
        shipping: str = "UNKNOWN",
        stock: str = "UNKNOWN",
        synthetic: int = 0,
        submission: str | None = None,
    ) -> None:
        index = self.next_id
        self.next_id += 1
        stamp = observed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        values = (
            index,
            submission or f"submission-{index}",
            stamp,
            source_id,
            source_kind,
            title,
            product,
            variant,
            seller,
            price,
            basis,
            minimum,
            shipping,
            stock,
            synthetic,
        )
        self.connection.execute("INSERT INTO observations VALUES(" + ",".join("?" for _ in values) + ")", values)

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()


def request(app: PriceQueryApp, path: str, query: str = "", method: str = "GET") -> tuple[int, dict[str, object], dict[str, str]]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(app({"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query}, start_response))
    return int(str(captured["status"]).split()[0]), json.loads(body), captured["headers"]


class PriceQueryCase(unittest.TestCase):
    def setUp(self) -> None:
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

    def repository(self) -> ReadonlyPriceRepository:
        self.fixture.close()
        return ReadonlyPriceRepository(self.database, allowed_root=self.directory, clock=lambda: NOW)

    def app(self) -> PriceQueryApp:
        return PriceQueryApp(self.repository())

    def add_days(self, count: int, **kwargs) -> None:
        for day in range(1, count + 1):
            self.fixture.add(observed=NOW - timedelta(days=day), price=100 + day, **kwargs)

    def test_search_contract_and_headers(self):
        self.add_days(3)
        status, value, headers = request(self.app(), "/api/v1/products", "q=recorded&page=1&limit=20")
        self.assertEqual(status, 200)
        self.assertEqual(value["schema_version"], "CDH-WEB-CONTRACT-V1")
        self.assertEqual(value["data_source_status"], "USER_RECORDED_ONLY")
        self.assertEqual(value["total"], 1)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_search_empty_query_returns_all_paginated(self):
        for index in range(5):
            self.fixture.add(
                observed=NOW - timedelta(days=1),
                product=f"p{index}",
                variant=f"v{index}",
                title=f"Item {index}",
            )
        status, value, _ = request(self.app(), "/api/v1/products", "page=2&limit=2&q=")
        self.assertEqual(status, 200)
        self.assertEqual(value["total"], 5)
        self.assertEqual(len(value["items"]), 2)

    def test_query_is_case_insensitive_and_literal(self):
        self.fixture.add(observed=NOW - timedelta(days=1), title="Alpha 100%_Item")
        app = self.app()
        self.assertEqual(request(app, "/api/v1/products", "q=ALPHA")[1]["total"], 1)
        self.assertEqual(request(app, "/api/v1/products", "q=%25_")[1]["total"], 1)

    def test_invalid_pagination_is_400(self):
        self.add_days(1)
        app = self.app()
        for query in ("page=0", "page=x", "limit=0", "limit=101"):
            with self.subTest(query=query):
                status, value, _ = request(app, "/api/v1/products", query)
                self.assertEqual(status, 400)
                self.assertEqual(value["error"]["code"], "INVALID_PAGINATION")

    def test_detail_contract_history_and_period_low(self):
        self.add_days(3)
        app = self.app()
        product_id = request(app, "/api/v1/products")[1]["items"][0]["id"]
        status, value, _ = request(app, f"/api/v1/products/{product_id}")
        self.assertEqual(status, 200)
        self.assertEqual(value["observation_period_label"], "觀測期間最低價")
        self.assertEqual(value["observation_period_min_twd"], 101)
        self.assertEqual(len(value["history"]), 3)
        self.assertEqual(value["offers"][0]["item_condition"], "UNKNOWN")
        self.assertEqual(value["offers"][0]["item_condition_source"], "NOT_RECORDED")
        self.assertEqual(value["affiliate"]["state"], "UNCONFIGURED")

    def test_affiliate_route_is_disabled_and_has_no_url(self):
        self.add_days(1)
        app = self.app()
        product_id = request(app, "/api/v1/products")[1]["items"][0]["id"]
        status, value, _ = request(app, f"/api/v1/products/{product_id}/affiliate")
        self.assertEqual(status, 200)
        self.assertEqual(value["state"], "UNCONFIGURED")
        self.assertIsNone(value["click_url"])
        self.assertFalse(value["verified_product_match"])

    def test_unknown_product_and_route_are_404(self):
        self.add_days(1)
        app = self.app()
        self.assertEqual(request(app, "/api/v1/products/not-real")[0], 404)
        self.assertEqual(request(app, "/api/v3/products")[0], 404)

    def test_non_get_is_405(self):
        self.add_days(1)
        status, value, _ = request(self.app(), "/api/v1/products", method="POST")
        self.assertEqual(status, 405)
        self.assertEqual(value["error"]["code"], "METHOD_NOT_ALLOWED")

    def test_product_variant_seller_basis_and_minimum_never_merge(self):
        when = NOW - timedelta(days=1)
        values = [
            ("p1", "v1", "s1", "CURRENT_ITEM_PRICE", 1),
            ("p2", "v1", "s1", "CURRENT_ITEM_PRICE", 1),
            ("p1", "v2", "s1", "CURRENT_ITEM_PRICE", 1),
            ("p1", "v1", "s2", "CURRENT_ITEM_PRICE", 1),
            ("p1", "v1", "s1", "DISPLAYED_UNKNOWN", 1),
            ("p1", "v1", "s1", "CURRENT_ITEM_PRICE", 2),
        ]
        for product, variant, seller, basis, minimum in values:
            self.fixture.add(observed=when, product=product, variant=variant, seller=seller, basis=basis, minimum=minimum)
        result = self.repository().search("", page=1, limit=20)
        self.assertEqual(result["total"], 6)

    def test_incomplete_identity_isolated_per_submission(self):
        self.fixture.add(observed=NOW - timedelta(days=1), product=None, variant=None, seller=None, minimum=None, title="Same")
        self.fixture.add(observed=NOW - timedelta(days=2), product=None, variant=None, seller=None, minimum=None, title="Same")
        items = self.repository().search("", page=1, limit=20)["items"]
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["identity_state"] == "INCOMPLETE" for item in items))
        self.assertEqual(len({item["id"] for item in items}), 2)

    def test_user_sources_only_and_synthetic_excluded(self):
        self.fixture.add(observed=NOW - timedelta(days=1), source_kind="USER_ENTERED")
        self.fixture.add(observed=NOW - timedelta(days=2), source_kind="USER_FILE")
        self.fixture.add(observed=NOW - timedelta(days=3), source_kind="APPROVED_FEED")
        self.fixture.add(observed=NOW - timedelta(days=4), synthetic=1)
        repository = self.repository()
        detail = repository.detail(repository.search("", page=1, limit=20)["items"][0]["id"])
        self.assertEqual(len(detail["history"]), 2)
        self.assertEqual({row["source_type"] for row in detail["history"]}, {"USER_ENTERED", "USER_FILE"})

    def test_future_and_equal_now_timestamps_are_excluded(self):
        self.fixture.add(observed=NOW - timedelta(days=1))
        self.fixture.add(observed=NOW, price=1)
        self.fixture.add(observed=NOW + timedelta(seconds=1), price=2)
        repository = self.repository()
        detail = repository.detail(repository.search("", page=1, limit=20)["items"][0]["id"])
        self.assertEqual(len(detail["history"]), 1)
        self.assertEqual(detail["observation_period_min_twd"], 199)

    def test_invalid_timestamp_is_ignored_without_fabrication(self):
        self.fixture.add(observed=NOW - timedelta(days=1))
        self.fixture.connection.execute("UPDATE observations SET observed_at_utc='bad' WHERE observation_id=1")
        self.assertEqual(self.repository().search("", page=1, limit=20)["total"], 0)

    def test_duplicate_submission_is_idempotent(self):
        self.fixture.add(observed=NOW - timedelta(days=1), submission="same", price=100)
        self.fixture.add(observed=NOW - timedelta(days=2), submission="same", price=1)
        repository = self.repository()
        detail = repository.detail(repository.search("", page=1, limit=20)["items"][0]["id"])
        self.assertEqual(len(detail["history"]), 1)
        self.assertEqual(detail["observation_period_min_twd"], 100)

    def test_zero_is_preserved_not_null(self):
        self.fixture.add(observed=NOW - timedelta(days=1), price=0)
        item = self.repository().search("", page=1, limit=20)["items"][0]
        self.assertEqual(item["last_observed_price_twd"], 0)
        self.assertIn("PRICE_IS_USER_OBSERVED_NOT_CHECKOUT_TOTAL", item["quality_flags"])

    def test_large_integer_is_preserved(self):
        self.fixture.add(observed=NOW - timedelta(days=1), price=9_000_000_000_000)
        item = self.repository().search("", page=1, limit=20)["items"][0]
        self.assertEqual(item["last_observed_price_twd"], 9_000_000_000_000)

    def test_sample_days_are_completed_taipei_calendar_days(self):
        self.add_days(90)
        item = self.repository().search("", page=1, limit=20)["items"][0]
        self.assertEqual((item["sample_days_m7"], item["sample_days_m30"], item["sample_days_m90"]), (7, 30, 90))

    def test_missing_days_are_not_interpolated(self):
        self.fixture.add(observed=NOW - timedelta(days=1))
        self.fixture.add(observed=NOW - timedelta(days=30))
        item = self.repository().search("", page=1, limit=20)["items"][0]
        self.assertEqual(item["observed_days"], 2)
        self.assertEqual(item["sample_days_m30"], 2)
        self.assertIn("M30_LOW_COVERAGE", item["quality_flags"])

    def test_latest_row_controls_display_without_overwriting_history(self):
        self.fixture.add(observed=NOW - timedelta(days=2), title="Old title", price=200, shipping="UNKNOWN")
        self.fixture.add(observed=NOW - timedelta(days=1), title="New title", price=150, shipping="FREE")
        app = self.app()
        item = request(app, "/api/v1/products")[1]["items"][0]
        self.assertEqual(item["title"], "New title")
        self.assertEqual(item["last_observed_price_twd"], 150)
        self.assertEqual(item["shipping_status"], "FREE")
        self.assertEqual(len(request(app, f"/api/v1/products/{item['id']}")[1]["history"]), 2)

    def test_database_bytes_unchanged_after_all_routes(self):
        self.add_days(7)
        repository = self.repository()
        before = digest(self.database)
        app = PriceQueryApp(repository)
        item = request(app, "/api/v1/products")[1]["items"][0]
        request(app, f"/api/v1/products/{item['id']}")
        request(app, f"/api/v1/products/{item['id']}/affiliate")
        self.assertEqual(digest(self.database), before)

    def test_query_only_connection_rejects_write(self):
        self.add_days(1)
        repository = self.repository()
        connection = repository._connect()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("INSERT INTO observations(observation_id) VALUES(999)")
        finally:
            connection.close()

    def test_missing_schema_fails_without_migration(self):
        self.fixture.connection.close()
        broken = self.directory / "broken.sqlite3"
        sqlite3.connect(broken).close()
        before = digest(broken)
        repository = ReadonlyPriceRepository(broken, allowed_root=self.directory, clock=lambda: NOW)
        with self.assertRaises(RepositoryError):
            repository.search("", page=1, limit=20)
        self.assertEqual(digest(broken), before)

    def test_database_outside_allowed_root_is_rejected(self):
        self.add_days(1)
        self.fixture.close()
        outside = self.directory.parent
        with self.assertRaises(RepositoryError):
            ReadonlyPriceRepository(self.database, allowed_root=outside / "not-parent", clock=lambda: NOW)

    def test_symlink_database_rejected_when_supported(self):
        self.add_days(1)
        self.fixture.close()
        link = self.directory / "link.sqlite3"
        try:
            os.symlink(self.database, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable")
        with self.assertRaises(RepositoryError):
            ReadonlyPriceRepository(link, allowed_root=self.directory, clock=lambda: NOW)

    def test_runtime_has_no_outbound_or_secret_clients(self):
        text = "\n".join(path.read_text(encoding="utf-8").lower() for path in (ROOT / "services/price_query").rglob("*.py"))
        for forbidden in (
            "import requests",
            "urllib.request",
            "http.client",
            "selenium",
            "playwright",
            "winreg",
            "dotenv",
            "os.environ",
            "coupang.com",
        ):
            self.assertNotIn(forbidden, text)

    def test_10000_rows_complete_with_bounded_memory(self):
        for index in range(10000):
            self.fixture.add(
                observed=NOW - timedelta(days=index % 90 + 1, hours=index % 24),
                product=f"p-{index % 50}",
                variant=f"v-{index % 50}",
                seller=f"s-{index % 5}",
                price=index,
            )
        repository = self.repository()
        tracemalloc.start()
        started = time.perf_counter()
        result = repository.search("", page=1, limit=100)
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertEqual(result["total"], 50)
        self.assertLess(elapsed, 20.0)
        self.assertLess(peak, 128 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main(verbosity=2)
