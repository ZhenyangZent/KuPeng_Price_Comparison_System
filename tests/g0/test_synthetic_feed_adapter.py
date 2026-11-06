from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research.G0.synthetic_feed_adapter import (
    Outcome,
    PermissionStatus,
    SourceConfig,
    SourceRecord,
    SyntheticFeedAdapter,
    canonical_product_url,
    load_json_records,
)


NOW = datetime(2026, 11, 2, 0, 2, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "g0" / "synthetic_feed_records.json"


def configs() -> tuple[SourceConfig, ...]:
    return (
        SourceConfig(
            "synthetic-feed",
            True,
            PermissionStatus.LOCAL_ONLY,
            "G0-TASK-SYNTHETIC-AUTHORITY",
            frozenset({"INGEST_SYNTHETIC"}),
            1800,
        ),
        SourceConfig(
            "user-import",
            True,
            PermissionStatus.LOCAL_ONLY,
            "G0-TASK-USER-IMPORT-AUTHORITY",
            frozenset({"INGEST_USER_IMPORT"}),
            1800,
        ),
        SourceConfig(
            "unverified-real-feed",
            True,
            PermissionStatus.UNVERIFIED,
            "NO-OPERATING-PERMISSION",
            frozenset({"AUTO_DISCOVERY"}),
            1800,
        ),
    )


def complete_record(**changes: object) -> SourceRecord:
    values: dict[str, object] = {
        "source_id": "synthetic-feed",
        "operation": "INGEST_SYNTHETIC",
        "record_id": "complete",
        "record_version": 1,
        "claim_class": "SYNTHETIC_ASSERTION",
        "product_url": "https://www.tw.coupang.com/products/synthetic-complete?vendorItemId=42&utm_source=test",
        "source_published_at": NOW - timedelta(minutes=1),
        "received_at": NOW,
        "claim_price_minor": 0,
        "price_basis": "CURRENT_TOTAL",
        "sku_id": "sku-complete",
        "stock_state": "IN_STOCK",
        "minimum_quantity": 1,
        "wow_eligible": True,
        "shipping_state": "KNOWN_ZERO",
        "shipping_minor": 0,
        "fee_state": "KNOWN_ZERO",
        "fee_minor": 0,
        "tax_state": "KNOWN_ZERO",
        "tax_minor": 0,
    }
    values.update(changes)
    return SourceRecord(**values)  # type: ignore[arg-type]


class FixtureAndDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = SyntheticFeedAdapter(configs())
        self.records = {record.record_id: record for record in load_json_records(FIXTURE.read_text(encoding="utf-8"))}

    def test_01_fixture_has_at_least_twelve_bounded_records(self) -> None:
        self.assertGreaterEqual(len(self.records), 12)

    def test_02_new_synthetic_product_is_discovered_and_synthetically_qualified(self) -> None:
        result = self.adapter.ingest(self.records["fresh-complete"])
        self.assertEqual(result.outcome, Outcome.DISCOVERED)
        self.assertTrue(result.qualification_ready)
        self.assertEqual(result.qualification_scope, "SYNTHETIC_ONLY")

    def test_03_duplicate_clue_from_another_record_is_semantically_deduplicated(self) -> None:
        self.adapter.ingest(self.records["community-duplicate-a"])
        duplicate = self.adapter.ingest(self.records["community-duplicate-b"])
        self.assertEqual(duplicate.outcome, Outcome.DUPLICATE)
        self.assertIn("SEMANTIC_CLUE_DUPLICATE", duplicate.reason_codes)

    def test_04_old_post_uses_source_time_and_is_stale(self) -> None:
        result = self.adapter.ingest(self.records["stale-post"])
        self.assertEqual(result.outcome, Outcome.STALE_CLUE)
        self.assertIn("SOURCE_CLUE_STALE", result.reason_codes)

    def test_05_malicious_lookalike_product_link_is_rejected_without_fetch(self) -> None:
        result = self.adapter.ingest(self.records["malicious-link"])
        self.assertEqual(result.outcome, Outcome.REJECTED)
        self.assertIn("PRODUCT_URL_NOT_DIRECT_APPROVED_HOST", result.reason_codes)

    def test_06_community_zero_rumor_never_becomes_purchase_qualification(self) -> None:
        result = self.adapter.ingest(self.records["community-zero-rumor"])
        self.assertEqual(result.outcome, Outcome.DISCOVERED)
        self.assertFalse(result.qualification_ready)
        self.assertIn("COMMUNITY_CLAIM_NOT_PURCHASE_EVIDENCE", result.reason_codes)

    def test_07_missing_wow_shipping_is_silent_waiting_evidence(self) -> None:
        result = self.adapter.ingest(self.records["shipping-unknown"])
        self.assertFalse(result.qualification_ready)
        self.assertIn("SHIPPING_UNKNOWN", result.reason_codes)

    def test_08_coupon_already_included_is_not_subtracted_twice(self) -> None:
        result = self.adapter.ingest(self.records["coupon-included"])
        self.assertEqual(result.effective_item_minor, 4900)

    def test_09_future_source_timestamp_is_rejected(self) -> None:
        result = self.adapter.ingest(self.records["future-record"])
        self.assertEqual(result.outcome, Outcome.REJECTED)
        self.assertIn("SOURCE_TIME_IN_FUTURE", result.reason_codes)

    def test_10_unknown_fee_blocks_qualification(self) -> None:
        result = self.adapter.ingest(self.records["fee-unknown"])
        self.assertFalse(result.qualification_ready)
        self.assertIn("REQUIRED_FEE_UNKNOWN", result.reason_codes)

    def test_11_unknown_tax_blocks_qualification(self) -> None:
        result = self.adapter.ingest(self.records["tax-unknown"])
        self.assertFalse(result.qualification_ready)
        self.assertIn("TAX_UNKNOWN", result.reason_codes)

    def test_12_unknown_stock_blocks_qualification(self) -> None:
        result = self.adapter.ingest(self.records["stock-unknown"])
        self.assertFalse(result.qualification_ready)
        self.assertIn("STOCK_UNKNOWN_OR_UNAVAILABLE", result.reason_codes)

    def test_13_explicit_user_import_can_only_prove_user_provided_scope(self) -> None:
        result = self.adapter.ingest(self.records["user-complete"])
        self.assertTrue(result.qualification_ready)
        self.assertEqual(result.qualification_scope, "SYNTHETIC_ONLY")
        self.assertNotIn("#", result.canonical_url or "")


class PermissionAndCorrectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = SyntheticFeedAdapter(configs())

    def test_14_source_disabled_stops_immediately(self) -> None:
        self.adapter.set_enabled("synthetic-feed", False)
        result = self.adapter.ingest(complete_record())
        self.assertEqual(result.outcome, Outcome.SOURCE_DISABLED)

    def test_15_unverified_real_source_cannot_auto_discover(self) -> None:
        record = complete_record(
            source_id="unverified-real-feed",
            operation="AUTO_DISCOVERY",
            record_id="unverified",
        )
        result = self.adapter.ingest(record)
        self.assertEqual(result.outcome, Outcome.REJECTED)
        self.assertIn("SOURCE_OPERATION_NOT_APPROVED", result.reason_codes)

    def test_16_wrong_record_can_be_corrected_only_by_higher_version(self) -> None:
        first = complete_record(record_id="correction", claim_price_minor=500)
        corrected = replace(first, record_version=2, claim_price_minor=0)
        self.assertEqual(self.adapter.ingest(first).outcome, Outcome.DISCOVERED)
        result = self.adapter.ingest(corrected)
        self.assertEqual(result.outcome, Outcome.UPDATED)
        self.assertEqual(result.effective_item_minor, 0)

    def test_17_same_version_conflict_is_rejected(self) -> None:
        first = complete_record(record_id="conflict", claim_price_minor=500)
        conflict = replace(first, claim_price_minor=0)
        self.adapter.ingest(first)
        result = self.adapter.ingest(conflict)
        self.assertEqual(result.outcome, Outcome.REJECTED)
        self.assertIn("SOURCE_VERSION_CONFLICT", result.reason_codes)

    def test_18_version_rollback_is_rejected(self) -> None:
        newer = complete_record(record_id="rollback", record_version=2)
        older = replace(newer, record_version=1)
        self.adapter.ingest(newer)
        result = self.adapter.ingest(older)
        self.assertEqual(result.outcome, Outcome.REJECTED)
        self.assertIn("SOURCE_VERSION_ROLLBACK", result.reason_codes)

    def test_19_unconfirmed_coupon_over_price_never_creates_zero(self) -> None:
        record = complete_record(claim_price_minor=100, coupon_discount_minor=200)
        result = self.adapter.ingest(record)
        self.assertIsNone(result.effective_item_minor)
        self.assertFalse(result.qualification_ready)
        self.assertIn("COUPON_EXCEEDS_PRICE_UNCONFIRMED", result.reason_codes)

    def test_20_boolean_price_is_rejected_not_one(self) -> None:
        result = self.adapter.ingest(complete_record(claim_price_minor=True))
        self.assertEqual(result.outcome, Outcome.REJECTED)
        self.assertIn("CLAIM_PRICE_INVALID", result.reason_codes)

    def test_21_tracking_parameters_and_fragments_are_removed(self) -> None:
        url = canonical_product_url(
            "https://www.tw.coupang.com/products/example?utm_source=x&vendorItemId=7#fragment"
        )
        self.assertEqual(url, "https://www.tw.coupang.com/products/example?vendorItemId=7")

    def test_22_local_permission_does_not_expand_to_auto_discovery(self) -> None:
        record = complete_record(operation="AUTO_DISCOVERY")
        result = self.adapter.ingest(record)
        self.assertEqual(result.outcome, Outcome.REJECTED)

    def test_23_json_loader_rejects_non_list_and_unbounded_feed(self) -> None:
        with self.assertRaises(ValueError):
            load_json_records(json.dumps({"not": "a-list"}))
        with self.assertRaises(ValueError):
            load_json_records(json.dumps([{}] * 1001))


if __name__ == "__main__":
    unittest.main(verbosity=2)
