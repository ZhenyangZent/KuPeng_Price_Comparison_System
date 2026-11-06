from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from datetime import datetime, timezone

from tests.web.security_d05.helpers import RELEASES, cleanup, workspace


B07_IMPORT = str(RELEASES / "CDH_B07_001_REVIEW.zip") + "/services/price_quality"
if B07_IMPORT not in sys.path:
    sys.path.insert(0, B07_IMPORT)

from price_quality import QualityError, QualityReadModel, sha256_file  # noqa: E402


NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)
SCHEMA = """
CREATE TABLE price_quality_schema(version INTEGER NOT NULL);
INSERT INTO price_quality_schema VALUES(1);
CREATE TABLE observations(
 observation_id INTEGER PRIMARY KEY, submission_id TEXT NOT NULL,
 observed_at_utc TEXT NOT NULL, source_kind TEXT NOT NULL,
 source_authorization TEXT NOT NULL, product_title TEXT NOT NULL,
 product_id TEXT, seller_id TEXT, variant_id TEXT,
 minimum_purchase_quantity INTEGER, package_signature TEXT,
 item_condition TEXT, displayed_price_twd INTEGER NOT NULL,
 price_basis TEXT, shipping_status TEXT NOT NULL, is_synthetic INTEGER NOT NULL
);
"""


class B07QualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace()
        self.database = self.root / "quality.sqlite3"
        self.auth = self.root / "authorization.json"
        connection = sqlite3.connect(self.database)
        connection.executescript(SCHEMA)
        rows = [
            (1, "e1", "2026-10-20T00:00:00Z", "USER_ENTERED", "USER_AUTHORIZED", "Jacket", "P1", "S1", "V1", 1, "one-item", "NEW", 0, "CURRENT_ITEM_PRICE", "UNKNOWN", 0),
            (2, "e2", "2026-10-21T00:00:00Z", "USER_FILE", "USER_AUTHORIZED", "Jacket", "P1", "S1", "V1", 1, "one-item", "NEW", 100, "CURRENT_ITEM_PRICE", "UNKNOWN", 0),
            (3, "i1", "2026-10-22T00:00:00Z", "USER_ENTERED", "USER_AUTHORIZED", "Jacket", "P1", "S1", None, 1, "one-item", "UNKNOWN", 50, "CURRENT_ITEM_PRICE", "PAID", 0),
            (4, "today", "2026-11-05T01:00:00Z", "USER_ENTERED", "USER_AUTHORIZED", "Jacket", "P1", "S1", "V1", 1, "one-item", "NEW", 1, "CURRENT_ITEM_PRICE", "UNKNOWN", 0),
        ]
        connection.executemany("INSERT INTO observations VALUES(" + ",".join("?" for _ in range(16)) + ")", rows)
        connection.commit()
        connection.close()
        self._write_auth()

    def tearDown(self) -> None:
        cleanup(self.root)

    def _write_auth(self) -> None:
        value = {
            "schema": "CDH-PRICE-QUALITY-AUTH-1",
            "copy_kind": "ISOLATED_READONLY_COPY",
            "database_sha256": sha256_file(self.database),
            "data_classification": "USER_AUTHORIZED_COPY",
            "approved_source_kinds": ["USER_ENTERED", "USER_FILE"],
            "contains_private_fields": False,
        }
        self.auth.write_text(json.dumps(value), encoding="utf-8")

    def model(self) -> QualityReadModel:
        return QualityReadModel(self.database, self.auth, allowed_root=self.root, clock=lambda: NOW)

    def test_zero_stale_unknown_missing_days_and_today_exclusion_are_explicit(self) -> None:
        report = self.model().analyze()
        exact = next(item for item in report["series"] if item["exact_match_claim_allowed"])
        self.assertEqual(exact["source_freshness"], "STALE")
        self.assertEqual(exact["shipping_status"], "UNKNOWN")
        self.assertEqual(exact["period_low_twd"], 0)
        self.assertIn("ZERO_PRICE_NOT_FREE_SHIPPING_OR_CHECKOUT_TOTAL", exact["quality_flags"])
        self.assertIn("CURRENT_OR_FUTURE_SAMPLE_EXCLUDED", exact["quality_flags"])
        self.assertEqual(exact["valid_day_count"], 2)
        self.assertLess(exact["windows"]["m30"]["coverage_ratio"], 1)

    def test_incomplete_identity_isolated_and_exact_claim_denied(self) -> None:
        report = self.model().analyze()
        incomplete = next(item for item in report["series"] if not item["exact_match_claim_allowed"])
        self.assertEqual(incomplete["identity_state"], "NEEDS_IDENTITY_EVIDENCE")
        self.assertIn("IDENTITY_EVIDENCE_INCOMPLETE", incomplete["quality_flags"])

    def test_mixed_or_unauthorized_source_is_rejected(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute(
            "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (5, "bad", "2026-10-23T00:00:00Z", "SYNTHETIC", "SYNTHETIC_FIXTURE", "Bad", "P2", "S2", "V2", 1, "one", "NEW", 10, "CURRENT_ITEM_PRICE", "UNKNOWN", 1),
        )
        connection.commit(); connection.close()
        self._write_auth()
        with self.assertRaisesRegex(QualityError, "mixed, unauthorized"):
            self.model().analyze()

    def test_hash_bound_authorization_refuses_database_mutation(self) -> None:
        original = self.auth.read_text(encoding="utf-8")
        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE observations SET displayed_price_twd=999 WHERE observation_id=1")
        connection.commit(); connection.close()
        self.auth.write_text(original, encoding="utf-8")
        with self.assertRaisesRegex(QualityError, "SHA-256"):
            self.model()


if __name__ == "__main__":
    unittest.main()
