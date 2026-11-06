from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/d04"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from cdh_d04.history import (  # noqa: E402
    CALCULATION_VERSION,
    CONTRACT,
    HistoryError,
    HistoryQuery,
    _median_floor,
    quality_report_markdown,
    write_versioned_export,
)


AS_OF = datetime(2026, 11, 4, 4, 0, tzinfo=timezone.utc)  # 12:00 Asia/Taipei
TEST_ROOT = ROOT / "experiments/D04/test_tmp"
TEST_ROOT.mkdir(parents=True, exist_ok=True)


SCHEMA = """
CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL);
INSERT INTO schema_migrations VALUES(1, '2026-11-01T00:00:00Z');
INSERT INTO schema_migrations VALUES(2, '2026-11-02T00:00:00Z');
CREATE TABLE observations(
  observation_id INTEGER PRIMARY KEY,
  raw_submission_id INTEGER NOT NULL UNIQUE,
  submission_id TEXT NOT NULL,
  observed_at_utc TEXT NOT NULL,
  imported_at_utc TEXT NOT NULL,
  source_id TEXT,
  source_kind TEXT NOT NULL,
  permission_scope TEXT NOT NULL,
  source_url TEXT,
  product_title TEXT NOT NULL,
  product_id TEXT,
  variant_id TEXT,
  seller_id TEXT,
  displayed_price_twd INTEGER NOT NULL,
  price_basis TEXT NOT NULL,
  minimum_purchase_quantity INTEGER,
  shipping_status TEXT NOT NULL,
  shipping_fee_twd INTEGER,
  stock_status TEXT NOT NULL,
  coupon_status TEXT NOT NULL,
  account_eligibility_status TEXT NOT NULL,
  mandatory_fee_status TEXT NOT NULL,
  qualification_state TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL,
  notes TEXT NOT NULL
);
"""


def sha256(path: Path) -> str:
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
        price: int = 100,
        submission: str | None = None,
        source: str = "USER_ENTERED",
        synthetic: int = 0,
        product: str | None = "p1",
        variant: str | None = "v1",
        seller: str | None = "s1",
        basis: str = "CURRENT_ITEM_PRICE",
        minimum: int | None = 1,
        title: str = "Synthetic item",
        shipping: str = "UNKNOWN",
        stock: str = "IN_STOCK",
        coupon: str = "UNKNOWN",
        eligibility: str = "UNKNOWN",
        mandatory_fee: str = "UNKNOWN",
    ) -> None:
        index = self.next_id
        self.next_id += 1
        text = observed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        self.connection.execute(
            "INSERT INTO observations VALUES(" + ",".join("?" for _ in range(25)) + ")",
            (
                index,
                index,
                submission or f"submission-{index}",
                text,
                text,
                None,
                source,
                "LOCAL_ONLY",
                None,
                title,
                product,
                variant,
                seller,
                price,
                basis,
                minimum,
                shipping,
                None,
                stock,
                coupon,
                eligibility,
                mandatory_fee,
                "UNVERIFIED",
                synthetic,
                "",
            ),
        )

    def commit_close(self) -> None:
        self.connection.commit()
        self.connection.close()


class HistoryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.root = Path(self.directory.name)
        self.database = self.root / "history.sqlite3"
        self.fixture = Fixture(self.database)

    def tearDown(self) -> None:
        try:
            self.fixture.connection.close()
        except sqlite3.Error:
            pass
        self.directory.cleanup()

    def export(self):
        self.fixture.commit_close()
        return HistoryQuery(self.database).export(as_of=AS_OF, generated_at=AS_OF)

    def add_days(self, count: int, *, price_start: int = 100, **kwargs) -> None:
        for day in range(1, count + 1):
            self.fixture.add(observed=AS_OF - timedelta(days=day), price=price_start + day, **kwargs)

    def test_contract_and_calculation_version(self):
        self.add_days(7)
        report = self.export()
        self.assertEqual(report["contract"], CONTRACT)
        self.assertEqual(report["calculation_version"], CALCULATION_VERSION)
        self.assertEqual(report["timezone"], "Asia/Taipei")

    def test_database_is_byte_identical_after_query(self):
        self.add_days(7)
        self.fixture.commit_close()
        before = sha256(self.database)
        HistoryQuery(self.database).export(as_of=AS_OF, generated_at=AS_OF)
        self.assertEqual(sha256(self.database), before)

    def test_only_user_sources_and_non_synthetic_are_read(self):
        self.fixture.add(observed=AS_OF - timedelta(days=1), source="USER_ENTERED")
        self.fixture.add(observed=AS_OF - timedelta(days=2), source="USER_FILE")
        self.fixture.add(observed=AS_OF - timedelta(days=3), source="APPROVED_FEED")
        self.fixture.add(observed=AS_OF - timedelta(days=4), synthetic=1)
        report = self.export()
        self.assertEqual(report["quality"]["source_row_count"], 2)
        self.assertEqual(report["series"][0]["source_counts"], {"USER_ENTERED": 1, "USER_FILE": 1})

    def test_exact_identity_is_comparable_with_seven_fresh_days(self):
        self.add_days(7)
        series = self.export()["series"][0]
        self.assertTrue(series["is_comparable"])
        self.assertEqual(series["comparison_status"], "READY_EXPLORATORY_ITEM_PRICE")
        self.assertFalse(series["verified_checkout_low_claim_allowed"])
        self.assertFalse(series["true_drop_claim_allowed"])

    def test_first_observation_never_comparable(self):
        self.add_days(1)
        series = self.export()["series"][0]
        self.assertFalse(series["is_comparable"])
        self.assertIn("FIRST_OBSERVATION_NO_COMPARISON", series["quality_flags"])

    def test_missing_identity_never_merges_similar_titles(self):
        self.fixture.add(observed=AS_OF - timedelta(days=1), product=None, title="Same Brand")
        self.fixture.add(observed=AS_OF - timedelta(days=2), product=None, title="Same Brand")
        report = self.export()
        self.assertEqual(len(report["series"]), 2)
        self.assertTrue(all(item["identity_state"] == "NEEDS_IDENTITY_REVIEW" for item in report["series"]))
        self.assertTrue(all(item["title_identity_used"] is False for item in report["series"]))

    def test_variant_seller_basis_and_minimum_are_separate_series(self):
        base = AS_OF - timedelta(days=1)
        self.fixture.add(observed=base, variant="v1", seller="s1", basis="CURRENT_ITEM_PRICE", minimum=1)
        self.fixture.add(observed=base, variant="v2", seller="s1", basis="CURRENT_ITEM_PRICE", minimum=1)
        self.fixture.add(observed=base, variant="v1", seller="s2", basis="CURRENT_ITEM_PRICE", minimum=1)
        self.fixture.add(observed=base, variant="v1", seller="s1", basis="DISPLAYED_UNKNOWN", minimum=1)
        self.fixture.add(observed=base, variant="v1", seller="s1", basis="CURRENT_ITEM_PRICE", minimum=2)
        self.assertEqual(len(self.export()["series"]), 5)

    def test_current_taipei_day_and_future_are_excluded(self):
        self.add_days(7)
        self.fixture.add(observed=AS_OF - timedelta(minutes=1), price=1)
        self.fixture.add(observed=AS_OF + timedelta(hours=1), price=2)
        series = self.export()["series"][0]
        self.assertEqual(series["observation_day_count"], 7)
        self.assertGreater(series["historical_low_twd"], 2)
        self.assertIn("CURRENT_OR_FUTURE_SAMPLE_EXCLUDED", series["quality_flags"])

    def test_timezone_normalization_uses_taipei_calendar_day(self):
        # 15:30 UTC and 16:30 UTC are different Taipei dates.
        self.fixture.add(observed=datetime(2026, 11, 1, 15, 30, tzinfo=timezone.utc), price=100)
        self.fixture.add(observed=datetime(2026, 11, 1, 16, 30, tzinfo=timezone.utc), price=200)
        series = self.export()["series"][0]
        self.assertEqual(series["observation_day_count"], 2)

    def test_same_utc_hour_keeps_first_only(self):
        first = AS_OF - timedelta(days=1, hours=2)
        self.fixture.add(observed=first, price=100)
        self.fixture.add(observed=first + timedelta(minutes=30), price=1)
        series = self.export()["series"][0]
        self.assertEqual(series["historical_low_twd"], 100)
        self.assertIn("SAME_UTC_HOUR_DEDUPED", series["quality_flags"])

    def test_daily_and_window_even_medians_floor_exactly(self):
        self.assertEqual(_median_floor([1, 2]), 1)
        self.assertEqual(_median_floor([9_000_000_000_000, 9_000_000_000_002]), 9_000_000_000_001)
        day = AS_OF - timedelta(days=1, hours=3)
        self.fixture.add(observed=day, price=101)
        self.fixture.add(observed=day + timedelta(hours=1), price=102)
        self.assertEqual(self.export()["series"][0]["historical_low_twd"], 101)

    def test_zero_is_preserved_but_never_verified_total(self):
        self.add_days(7, price_start=-1)
        series = self.export()["series"][0]
        self.assertEqual(series["historical_low_twd"], 0)
        self.assertIn("ZERO_PRICE_UNVERIFIED_TOTAL", series["quality_flags"])
        self.assertEqual(series["statistics_scope"], "EXPLORATORY_DISPLAYED_ITEM_PRICE_NOT_CHECKOUT_TOTAL")

    def test_large_integer_is_exact(self):
        self.add_days(7, price_start=9_000_000_000_000)
        series = self.export()["series"][0]
        self.assertGreater(series["median_twd"]["m30"], 8_000_000_000_000)

    def test_out_of_stock_excluded_and_unknown_stock_flagged(self):
        self.add_days(7)
        self.fixture.add(observed=AS_OF - timedelta(days=1, hours=4), price=1, stock="OUT_OF_STOCK")
        self.fixture.add(observed=AS_OF - timedelta(days=2, hours=4), price=102, stock="UNKNOWN")
        series = self.export()["series"][0]
        self.assertGreater(series["historical_low_twd"], 1)
        self.assertIn("OUT_OF_STOCK_SAMPLE_EXCLUDED", series["quality_flags"])
        self.assertIn("STOCK_UNKNOWN", series["quality_flags"])

    def test_conditional_coupon_or_eligibility_is_not_comparable(self):
        self.add_days(6)
        self.fixture.add(
            observed=AS_OF - timedelta(days=7),
            coupon="CONFIRMED",
            eligibility="CONFIRMED",
        )
        series = self.export()["series"][0]
        self.assertFalse(series["is_comparable"])
        self.assertEqual(series["comparison_status"], "CONDITIONAL_PRICE_UNBOUND")

    def test_reference_and_coupon_price_basis_are_not_comparable(self):
        for basis in ("REFERENCE_PRICE", "COUPON_INCLUDED_DISPLAY"):
            with self.subTest(basis=basis):
                directory = Path(self.root) / basis
                directory.mkdir()
                fixture = Fixture(directory / "db.sqlite3")
                for day in range(1, 8):
                    fixture.add(observed=AS_OF - timedelta(days=day), basis=basis)
                fixture.commit_close()
                item = HistoryQuery(directory / "db.sqlite3").export(as_of=AS_OF, generated_at=AS_OF)["series"][0]
                self.assertFalse(item["is_comparable"])
                self.assertEqual(item["comparison_status"], "UNSUPPORTED_PRICE_BASIS")

    def test_stale_history_is_explicit(self):
        for day in range(8, 15):
            self.fixture.add(observed=AS_OF - timedelta(days=day))
        series = self.export()["series"][0]
        self.assertFalse(series["is_comparable"])
        self.assertEqual(series["comparison_status"], "STALE_HISTORY")

    def test_window_counts_are_calendar_days(self):
        self.add_days(90)
        counts = self.export()["series"][0]["window_day_counts"]
        self.assertEqual(counts, {"m7": 7, "m30": 30, "m90": 90})

    def test_duplicate_submission_is_idempotently_ignored(self):
        for day in range(1, 8):
            self.fixture.add(observed=AS_OF - timedelta(days=day), submission=f"s-{day}")
        self.fixture.add(observed=AS_OF - timedelta(days=1, hours=5), submission="s-1", price=1)
        report = self.export()
        self.assertEqual(report["quality"]["duplicate_submission_row_count"], 1)
        self.assertGreater(report["series"][0]["historical_low_twd"], 1)

    def test_invalid_timestamp_is_counted_not_fabricated(self):
        self.fixture.add(observed=AS_OF - timedelta(days=1))
        self.fixture.connection.execute("UPDATE observations SET observed_at_utc='bad' WHERE observation_id=1")
        report = self.export()
        self.assertEqual(report["quality"]["invalid_timestamp_row_count"], 1)
        self.assertEqual(report["series"], [])

    def test_missing_schema_fails_closed_without_migration(self):
        self.fixture.connection.close()
        broken = self.root / "broken.sqlite3"
        sqlite3.connect(broken).close()
        before = sha256(broken)
        with self.assertRaises(HistoryError):
            HistoryQuery(broken).export(as_of=AS_OF, generated_at=AS_OF)
        self.assertEqual(sha256(broken), before)

    def test_naive_as_of_is_rejected(self):
        self.add_days(1)
        self.fixture.commit_close()
        with self.assertRaises(HistoryError):
            HistoryQuery(self.database).export(as_of=datetime(2026, 1, 1))

    def test_quality_report_keeps_unknown_explicit(self):
        self.add_days(1)
        report = self.export()
        text = quality_report_markdown(report)
        self.assertIn("SOURCE_BLOCKED", text)
        self.assertIn("不推定免運", text)

    def test_versioned_export_is_idempotent(self):
        self.add_days(7)
        report = self.export()
        output = self.root / "output"
        first, first_hash = write_versioned_export(report, output)
        second, second_hash = write_versioned_export(report, output)
        self.assertEqual(first, second)
        self.assertEqual(first_hash, second_hash)
        self.assertEqual(len(list(output.glob("history_*.json"))), 1)

    def test_cli_requires_explicit_database_and_emits_json(self):
        self.add_days(7)
        self.fixture.commit_close()
        output = self.root / "cli-output"
        command = [
            sys.executable,
            str(ROOT / "apps/d04/history_cli.py"),
            "--database",
            str(self.database),
            "--output-dir",
            str(output),
            "--as-of",
            AS_OF.isoformat(),
            "--generated-at",
            AS_OF.isoformat(),
        ]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        value = json.loads(completed.stdout)
        self.assertEqual(value["result"], "EXPORTED")
        self.assertEqual(value["database_mode"], "READ_ONLY")
        self.assertTrue(Path(value["output"]).is_file())

    def test_cli_missing_database_fails_with_exit_two(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "apps/d04/history_cli.py"),
                "--database",
                str(self.root / "missing.sqlite3"),
                "--output-dir",
                str(self.root / "out"),
                "--as-of",
                AS_OF.isoformat(),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["result"], "FAILED")

    def test_runtime_contains_no_network_browser_registry_notification_or_commerce_clients(self):
        runtime = "\n".join(path.read_text(encoding="utf-8").lower() for path in (ROOT / "apps/d04").rglob("*.py"))
        tokens = (
            "import requests",
            "requests.",
            "urllib.request",
            "http.client",
            "selenium",
            "playwright",
            "webbrowser",
            "winreg",
            "ctypes.windll",
            "schtasks",
            "smtplib",
            "tw.coupang.com",
        )
        for token in tokens:
            self.assertNotIn(token, runtime)


if __name__ == "__main__":
    unittest.main(verbosity=2)
