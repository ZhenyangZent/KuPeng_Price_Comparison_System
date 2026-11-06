from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from tools.web_security.audit import audit_zip
from tools.web_security.crossline import audit_crossline_contract, audit_frontend_backend_release_zips
from tests.web.security.helpers import cleanup, workspace


TARGET_BASE = (
    Path(".")
    if Path("apps/price-web/frontend/src/types.ts").is_file()
    else Path("target_inputs")
)
RELEASES = (TARGET_BASE / "review" / "releases").resolve()
B05_IMPORT_ROOT = str(RELEASES / "CDH_B05_001_REVIEW.zip") + "/services/price_query"
if B05_IMPORT_ROOT not in sys.path:
    sys.path.insert(0, B05_IMPORT_ROOT)

from price_query import PriceQueryApp, ReadonlyPriceRepository  # noqa: E402


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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request(app: PriceQueryApp, path: str, query: dict[str, str] | None = None) -> tuple[int, dict[str, object]]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info=None):
        captured["status"] = status

    body = b"".join(
        app(
            {
                "REQUEST_METHOD": "GET",
                "PATH_INFO": path,
                "QUERY_STRING": urlencode(query or {}),
            },
            start_response,
        )
    )
    return int(str(captured["status"]).split()[0]), json.loads(body)


class ActualReleaseAuditTests(unittest.TestCase):
    def test_hash_bound_a05_and_b05_releases_pass_artifact_audit(self) -> None:
        expected = {
            "CDH_A05_001_REVIEW.zip": "66652edfd641869ac63ea44c0254e712441fceccd77ea3bb78f706120cb14d0e",
            "CDH_B05_001_REVIEW.zip": "31ab7903f56dfc4fc339d6b04aea74eebb1fea257a4e69554202cafc4c8c953e",
        }
        for name, digest in expected.items():
            with self.subTest(name=name):
                target = RELEASES / name
                self.assertEqual(sha256(target), digest)
                result = audit_zip(target, owner=name[4])
                self.assertTrue(result.passed, result.findings)

    def test_actual_a05_b05_source_alignment_gaps_are_actionable(self) -> None:
        result = audit_frontend_backend_release_zips(
            RELEASES / "CDH_A05_001_REVIEW.zip",
            RELEASES / "CDH_B05_001_REVIEW.zip",
        )
        codes = {finding.code for finding in result.findings}
        self.assertTrue(
            {
                "FRONTEND_CLASSIFICATION_SYNTHETIC_ONLY",
                "FRONTEND_AFFILIATE_GUARD_INCOMPLETE",
                "LOOPBACK_PORT_MISMATCH",
                "SAME_ORIGIN_PROXY_MISSING",
                "LOCAL_TRANSPORT_NOT_INTEGRATED",
            }
            <= codes
        )
        self.assertFalse(result.passed)


class ActualB05RuntimeCounterexampleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace()
        self.database = self.root / "approved_b05_copy.sqlite3"
        connection = sqlite3.connect(self.database)
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                1,
                "submission-1",
                "2026-11-04T00:00:00Z",
                "local-user",
                "USER_ENTERED",
                "Recorded Jacket",
                "product-1",
                "SKU-XL-42",
                "seller-1",
                199,
                "CURRENT_ITEM_PRICE",
                1,
                "UNKNOWN",
                "UNKNOWN",
                0,
            ),
        )
        connection.commit()
        connection.close()
        repository = ReadonlyPriceRepository(
            self.database,
            allowed_root=self.root,
            clock=lambda: datetime(2026, 11, 5, tzinfo=timezone.utc),
        )
        self.app = PriceQueryApp(repository)

    def tearDown(self) -> None:
        cleanup(self.root)

    def test_actual_b05_responses_trigger_every_known_contract_counterexample(self) -> None:
        self.assertEqual(request(self.app, "/api/v1/products", {"q": "SKU-XL-42"})[0], 200)
        variant = request(self.app, "/api/v1/products", {"q": "SKU-XL-42"})[1]
        search = request(self.app, "/api/v1/products")[1]
        product_id = str(search["items"][0]["id"])
        detail = request(self.app, f"/api/v1/products/{product_id}")[1]
        affiliate = request(self.app, f"/api/v1/products/{product_id}/affiliate")[1]
        findings = audit_crossline_contract(
            search,
            detail,
            affiliate,
            variant_query_total=int(variant["total"]),
        )
        codes = {finding.code for finding in findings}
        self.assertEqual(
            codes,
            {
                "SEARCH_DATA_CLASSIFICATION_MISSING",
                "DETAIL_DATA_SOURCE_STATUS_MISSING",
                "DETAIL_DATA_CLASSIFICATION_MISSING",
                "AFFILIATE_DTO_NOT_NESTED",
                "VARIANT_SEARCH_CONTRACT_MISMATCH",
                "ITEM_CONDITION_UNPROVEN",
            },
        )
        self.assertEqual({finding.owner for finding in findings}, {"B", "B/F", "A/B"})


if __name__ == "__main__":
    unittest.main()
