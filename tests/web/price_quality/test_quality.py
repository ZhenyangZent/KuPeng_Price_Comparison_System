from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "services" / "price_quality"
if str(SERVICE) not in sys.path:
    sys.path.insert(0, str(SERVICE))

from price_quality import (  # noqa: E402
    AUTH_SCHEMA,
    QualityError,
    QualityReadModel,
    SYNTHETIC_CLASSIFICATION,
    USER_CLASSIFICATION,
    sha256_file,
)


NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)
TEMP_ROOT = Path(__file__).parent / ".tmp"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
SCHEMA = """
CREATE TABLE price_quality_schema(version INTEGER NOT NULL);
INSERT INTO price_quality_schema VALUES(1);
CREATE TABLE observations(
 observation_id INTEGER PRIMARY KEY,
 submission_id TEXT NOT NULL,
 observed_at_utc TEXT NOT NULL,
 source_kind TEXT NOT NULL,
 source_authorization TEXT NOT NULL,
 product_title TEXT NOT NULL,
 product_id TEXT,
 seller_id TEXT,
 variant_id TEXT,
 minimum_purchase_quantity INTEGER,
 package_signature TEXT,
 item_condition TEXT,
 displayed_price_twd INTEGER NOT NULL,
 price_basis TEXT,
 shipping_status TEXT NOT NULL,
 is_synthetic INTEGER NOT NULL,
 private_note TEXT
);
"""


class Fixture:
    def __init__(self, root: Path, classification: str = USER_CLASSIFICATION) -> None:
        self.root = root
        self.database = root / "copy.sqlite3"
        self.authorization = root / "authorization.json"
        self.classification = classification
        self.connection = sqlite3.connect(self.database)
        self.connection.executescript(SCHEMA)
        self.next_id = 1
        self.closed = False

    def add(
        self,
        *,
        observed: datetime,
        submission: str | None = None,
        title: str = "Recorded product",
        product: object = "P-1",
        seller: object = "S-1",
        variant: object = "SKU-1",
        quantity: object = 1,
        package: object = "1_UNIT",
        condition: object = "NEW",
        price: object = 199,
        basis: object = "CURRENT_ITEM_PRICE",
        shipping: str = "UNKNOWN",
        source_kind: str | None = None,
        source_authorization: str | None = None,
        synthetic: int | None = None,
        private_note: str | None = None,
    ) -> None:
        index = self.next_id
        self.next_id += 1
        if self.classification == USER_CLASSIFICATION:
            default_source, default_auth, default_synthetic = "USER_ENTERED", "USER_AUTHORIZED", 0
        else:
            default_source, default_auth, default_synthetic = "SYNTHETIC", "SYNTHETIC_FIXTURE", 1
        values = (
            index,
            submission or f"submission-{index}",
            observed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            source_kind or default_source,
            source_authorization or default_auth,
            title,
            product,
            seller,
            variant,
            quantity,
            package,
            condition,
            price,
            basis,
            shipping,
            default_synthetic if synthetic is None else synthetic,
            private_note,
        )
        self.connection.execute("INSERT INTO observations VALUES(" + ",".join("?" for _ in values) + ")", values)

    def close(self) -> None:
        if not self.closed:
            self.connection.commit()
            self.connection.close()
            self.closed = True

    def authorize(self, **overrides) -> None:
        self.close()
        sources = ["USER_ENTERED", "USER_FILE"] if self.classification == USER_CLASSIFICATION else ["SYNTHETIC"]
        value = {
            "schema": AUTH_SCHEMA,
            "copy_kind": "ISOLATED_READONLY_COPY",
            "database_sha256": sha256_file(self.database),
            "data_classification": self.classification,
            "approved_source_kinds": sources,
            "contains_private_fields": False,
        }
        value.update(overrides)
        self.authorization.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


class QualityCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.directory = Path(self.temp.name)
        self.fixture = Fixture(self.directory)

    def tearDown(self) -> None:
        self.fixture.close()
        self.temp.cleanup()

    def model(self, **kwargs) -> QualityReadModel:
        self.fixture.authorize()
        return QualityReadModel(
            self.fixture.database,
            self.fixture.authorization,
            allowed_root=self.directory,
            clock=lambda: NOW,
            **kwargs,
        )

    def add_day(self, days: int, **kwargs) -> None:
        self.fixture.add(observed=NOW - timedelta(days=days), **kwargs)

    def test_authorized_user_copy_and_report_contract(self):
        self.add_day(1)
        report = self.model().analyze()
        self.assertEqual(report["contract"], "CDH-PRICE-QUALITY-READMODEL-1")
        self.assertEqual(report["data_classification"], USER_CLASSIFICATION)
        self.assertFalse(report["source"]["private_fields_exported"])
        self.assertEqual(report["quality"]["exact_series_count"], 1)

    def test_synthetic_fixture_is_explicit_and_separate(self):
        self.fixture.close()
        synthetic_root = self.directory / "synthetic-root"
        synthetic_root.mkdir()
        self.fixture = Fixture(synthetic_root, SYNTHETIC_CLASSIFICATION)
        self.add_day(1)
        report = self.model().analyze()
        self.assertEqual(report["data_classification"], SYNTHETIC_CLASSIFICATION)
        self.assertEqual(report["source"]["approved_source_kinds"], ["SYNTHETIC"])

    def test_mixed_or_unauthorized_rows_are_refused(self):
        self.add_day(1)
        self.add_day(2, source_kind="SYNTHETIC", source_authorization="SYNTHETIC_FIXTURE", synthetic=1)
        with self.assertRaisesRegex(QualityError, "mixed, unauthorized"):
            self.model().analyze()

    def test_authorization_hash_mismatch_is_refused(self):
        self.add_day(1)
        self.fixture.authorize(database_sha256="0" * 64)
        with self.assertRaisesRegex(QualityError, "SHA-256"):
            QualityReadModel(
                self.fixture.database,
                self.fixture.authorization,
                allowed_root=self.directory,
                clock=lambda: NOW,
            )

    def test_private_field_declaration_is_refused(self):
        self.add_day(1)
        self.fixture.authorize(contains_private_fields=True)
        with self.assertRaisesRegex(QualityError, "private fields"):
            QualityReadModel(
                self.fixture.database,
                self.fixture.authorization,
                allowed_root=self.directory,
                clock=lambda: NOW,
            )

    def test_schema_missing_column_is_refused(self):
        self.fixture.connection.execute("ALTER TABLE observations RENAME TO old_observations")
        self.fixture.close()
        self.fixture.authorize()
        with self.assertRaises(QualityError):
            QualityReadModel(
                self.fixture.database,
                self.fixture.authorization,
                allowed_root=self.directory,
                clock=lambda: NOW,
            ).analyze()

    def test_incompatible_schema_version_is_refused(self):
        self.fixture.connection.execute("UPDATE price_quality_schema SET version=2")
        self.fixture.close()
        self.fixture.authorize()
        with self.assertRaisesRegex(QualityError, "incompatible"):
            QualityReadModel(
                self.fixture.database,
                self.fixture.authorization,
                allowed_root=self.directory,
                clock=lambda: NOW,
            ).analyze()

    def test_corrupt_database_is_refused(self):
        self.fixture.close()
        self.fixture.database.write_bytes(b"not sqlite")
        self.fixture.authorize()
        with self.assertRaises(QualityError):
            QualityReadModel(
                self.fixture.database,
                self.fixture.authorization,
                allowed_root=self.directory,
                clock=lambda: NOW,
            ).analyze()

    def test_symlink_database_is_refused_when_supported(self):
        self.add_day(1)
        self.fixture.authorize()
        link = self.directory / "linked.sqlite3"
        try:
            os.symlink(self.fixture.database, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable")
        with self.assertRaises(QualityError):
            QualityReadModel(link, self.fixture.authorization, allowed_root=self.directory, clock=lambda: NOW)

    def test_database_outside_allowed_root_is_refused(self):
        self.add_day(1)
        self.fixture.authorize()
        other = self.directory / "allowed"
        other.mkdir()
        with self.assertRaises(QualityError):
            QualityReadModel(self.fixture.database, self.fixture.authorization, allowed_root=other, clock=lambda: NOW)

    def test_formal_d01_database_path_is_refused_even_with_sidecar(self):
        self.add_day(1)
        self.fixture.authorize()
        formal = self.directory / "data" / "d01" / "observations.sqlite3"
        formal.parent.mkdir(parents=True)
        shutil.copyfile(self.fixture.database, formal)
        with self.assertRaisesRegex(QualityError, "formal D01"):
            QualityReadModel(formal, self.fixture.authorization, allowed_root=self.directory, clock=lambda: NOW)

    def test_every_identity_dimension_partitions_series(self):
        values = [
            {},
            {"product": "P-2"},
            {"seller": "S-2"},
            {"variant": "SKU-2"},
            {"quantity": 2},
            {"package": "2_PACK"},
            {"condition": "USED"},
            {"basis": "BUNDLE_PRICE"},
        ]
        for index, changes in enumerate(values):
            self.add_day(index + 1, submission=f"identity-{index}", **changes)
        report = self.model().analyze(limit=100)
        self.assertEqual(report["pagination"]["total"], 8)
        self.assertTrue(all(item["exact_match_claim_allowed"] for item in report["series"]))

    def test_incomplete_or_unknown_identity_is_isolated(self):
        self.add_day(1, submission="unknown-1", condition="UNKNOWN")
        self.add_day(2, submission="unknown-2", condition="UNKNOWN")
        report = self.model().analyze()
        self.assertEqual(report["pagination"]["total"], 2)
        self.assertTrue(all(not item["exact_match_claim_allowed"] for item in report["series"]))

    def test_completed_taipei_windows_and_no_missing_fill(self):
        for day in (1, 2, 7, 30, 90):
            self.add_day(day, submission=f"day-{day}", price=100 + day)
        item = self.model().analyze()["series"][0]
        self.assertEqual(item["windows"]["m7"]["valid_day_count"], 3)
        self.assertEqual(item["windows"]["m30"]["valid_day_count"], 4)
        self.assertEqual(item["windows"]["m90"]["valid_day_count"], 5)
        self.assertEqual(item["valid_day_count"], 5)

    def test_daily_median_low_and_duplicate_burst_do_not_overweight_window(self):
        base = NOW - timedelta(days=1)
        self.fixture.add(observed=base.replace(hour=1), submission="first", price=100)
        for index in range(100):
            self.fixture.add(observed=base.replace(hour=1, minute=index % 60), submission=f"burst-{index}", price=999)
        self.fixture.add(observed=base.replace(hour=2), submission="second", price=200)
        self.add_day(2, submission="previous-day", price=300)
        item = self.model().analyze()["series"][0]
        first_day = item["daily"][-1]
        self.assertEqual(first_day["sample_count"], 2)
        self.assertEqual(first_day["median_twd"], 150)
        self.assertEqual(first_day["low_twd"], 100)
        self.assertEqual(item["windows"]["m7"]["median_of_daily_medians_twd"], 225)

    def test_today_and_future_cannot_pollute_baseline(self):
        self.add_day(1, price=200)
        self.fixture.add(observed=NOW, submission="today", price=1)
        self.fixture.add(observed=NOW + timedelta(days=1), submission="future", price=0)
        item = self.model().analyze()["series"][0]
        self.assertEqual(item["period_low_twd"], 200)
        self.assertEqual(item["excluded_current_or_future_count"], 2)

    def test_stale_source_is_explicit(self):
        self.add_day(10)
        item = self.model().analyze()["series"][0]
        self.assertEqual(item["source_freshness"], "STALE")
        self.assertIn("STALE_SOURCE", item["quality_flags"])

    def test_zero_remains_zero_and_shipping_unknown(self):
        self.add_day(1, price=0, shipping="UNKNOWN")
        item = self.model().analyze()["series"][0]
        self.assertEqual(item["period_low_twd"], 0)
        self.assertEqual(item["shipping_status"], "UNKNOWN")
        self.assertIn("ZERO_PRICE_NOT_FREE_SHIPPING_OR_CHECKOUT_TOTAL", item["quality_flags"])
        self.assertIn("SHIPPING_UNKNOWN", item["quality_flags"])

    def test_duplicate_submission_is_idempotent(self):
        self.add_day(1, submission="same", price=100)
        self.add_day(2, submission="same", price=1)
        report = self.model().analyze()
        self.assertEqual(report["quality"]["duplicate_submission_count"], 1)
        self.assertEqual(report["series"][0]["period_low_twd"], 100)

    def test_pagination_is_bounded(self):
        for index in range(12):
            self.add_day(1, product=f"P-{index}", variant=f"SKU-{index}", submission=f"p-{index}")
        report = self.model().analyze(page=2, limit=5)
        self.assertEqual(report["pagination"], {"page": 2, "limit": 5, "total": 12})
        self.assertEqual(len(report["series"]), 5)
        with self.assertRaises(QualityError):
            self.model().analyze(page=0)

    def test_database_bytes_are_unchanged(self):
        self.add_day(1)
        model = self.model()
        before = sha256_file(self.fixture.database)
        model.analyze()
        self.assertEqual(sha256_file(self.fixture.database), before)

    def test_query_only_connection_rejects_write(self):
        self.add_day(1)
        model = self.model()
        connection = model._connect()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE observations SET displayed_price_twd=0")
        finally:
            connection.close()

    def test_private_column_content_is_not_exported(self):
        self.add_day(1, private_note="PRIVATE-DO-NOT-EXPORT")
        payload = json.dumps(self.model().analyze(), ensure_ascii=False)
        self.assertNotIn("PRIVATE-DO-NOT-EXPORT", payload)
        self.assertNotIn("private_note", payload)

    def test_cli_writes_report_only_below_allowed_root(self):
        self.add_day(1)
        self.fixture.authorize()
        output = self.directory / "reports" / "DATA_QUALITY_REPORT.json"
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(SERVICE)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "price_quality.cli",
                "--database-copy",
                str(self.fixture.database),
                "--authorization",
                str(self.fixture.authorization),
                "--allowed-root",
                str(self.directory),
                "--as-of",
                "2026-11-05T04:00:00Z",
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["contract"], "CDH-PRICE-QUALITY-READMODEL-1")

    def test_fetch_size_bound_and_10000_rows_peak_memory(self):
        for index in range(10_000):
            self.fixture.add(
                observed=NOW - timedelta(days=index % 90 + 1, hours=index % 24),
                submission=f"bulk-{index}",
                price=index % 1000,
            )
        model = self.model(fetch_size=128)
        tracemalloc.start()
        report = model.analyze()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertEqual(report["quality"]["source_row_count"], 10_000)
        self.assertLess(peak, 128 * 1024 * 1024)
        with self.assertRaises(QualityError):
            QualityReadModel(
                self.fixture.database,
                self.fixture.authorization,
                allowed_root=self.directory,
                fetch_size=5000,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
