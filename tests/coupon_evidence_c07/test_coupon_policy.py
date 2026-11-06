from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path

from research.coupon_evidence_c07.fixture_builder import apply_case, load_fixture_pack
from research.coupon_evidence_c07.policy import CouponEvidenceError, evaluate_coupon_evidence
from research.coupon_evidence_c07.validate_all import _check_expected

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "research" / "coupon_evidence_c07"
PACK_PATH = BASE / "SYNTHETIC_PROVENANCE_FIXTURES.json"
PACK = load_fixture_pack(PACK_PATH)
NOW = datetime.fromisoformat(PACK["evaluation_time"].replace("Z", "+00:00"))


def base_record() -> dict:
    return copy.deepcopy(PACK["base_record"])


def _make_fixture_test(case_id: str):
    def test(self):
        record, expected = apply_case(PACK, case_id)
        if "error" in expected:
            with self.assertRaisesRegex(CouponEvidenceError, expected["error"]):
                evaluate_coupon_evidence(record, now=NOW)
        else:
            result = evaluate_coupon_evidence(record, now=NOW)
            _check_expected(result, expected)
            self.assertFalse(result["runtime_authorized"])
            self.assertFalse(result["cta_enabled"])
            self.assertIsNone(result["click_url"])
    return test


class ContractFixtureTests(unittest.TestCase):
    pass


for _case in PACK["cases"]:
    setattr(ContractFixtureTests, "test_" + _case["id"].lower(), _make_fixture_test(_case["id"]))


class StructuralRejectionTests(unittest.TestCase):
    def assertRejected(self, record: dict):
        with self.assertRaises(CouponEvidenceError):
            evaluate_coupon_evidence(record, now=NOW)

    def test_wrong_schema(self):
        record = base_record(); record["schema_version"] = "OTHER"; self.assertRejected(record)

    def test_unknown_top_level_field(self):
        record = base_record(); record["extra"] = True; self.assertRejected(record)

    def test_missing_top_level_field(self):
        record = base_record(); del record["shipping"]; self.assertRejected(record)

    def test_wrong_market(self):
        record = base_record(); record["market"] = "KR"; self.assertRejected(record)

    def test_wrong_platform(self):
        record = base_record(); record["series_identity"]["platform"] = "OTHER"; self.assertRejected(record)

    def test_missing_identity_field(self):
        record = base_record(); del record["series_identity"]["seller_id"]; self.assertRejected(record)

    def test_blank_identity_value(self):
        record = base_record(); record["series_identity"]["sku_id"] = ""; self.assertRejected(record)

    def test_timestamp_without_timezone(self):
        record = base_record(); record["observed_at"] = "2026-11-05T00:00:00"; self.assertRejected(record)

    def test_negative_base_price(self):
        record = base_record(); record["base_price"]["amount_twd"] = -1; self.assertRejected(record)

    def test_boolean_is_not_price(self):
        record = base_record(); record["base_price"]["amount_twd"] = True; self.assertRejected(record)

    def test_unavailable_base_cannot_be_zero(self):
        record = base_record(); record["base_price"]["status"] = "UNAVAILABLE"; record["base_price"]["amount_twd"] = 0; self.assertRejected(record)

    def test_known_base_needs_source_evidence(self):
        record = base_record(); record["base_price"]["source_evidence_id"] = None; self.assertRejected(record)

    def test_wrong_currency(self):
        record = base_record(); record["base_price"]["currency"] = "USD"; self.assertRejected(record)

    def test_minimum_quantity_zero(self):
        record = base_record(); record["coupon"]["minimum_quantity"] = 0; self.assertRejected(record)

    def test_negative_discount(self):
        record = base_record(); record["coupon"]["discount_twd"] = -1; self.assertRejected(record)

    def test_reversed_coupon_window(self):
        record = base_record(); record["coupon"]["valid_until"] = "2026-10-01T00:00:00Z"; self.assertRejected(record)

    def test_none_coupon_with_id(self):
        record = base_record(); record["coupon"]["status"] = "NONE"; self.assertRejected(record)

    def test_unknown_coupon_status(self):
        record = base_record(); record["coupon"]["status"] = "MAGIC"; self.assertRejected(record)

    def test_unknown_eligibility_status(self):
        record = base_record(); record["coupon"]["eligibility_evidence"] = "MAGIC"; self.assertRejected(record)

    def test_unknown_shipping_must_be_null(self):
        record = base_record(); record["shipping"]["amount_twd"] = 0; self.assertRejected(record)

    def test_known_shipping_cannot_be_negative(self):
        record = base_record(); record["shipping"] = {"status": "KNOWN", "amount_twd": -1}; self.assertRejected(record)

    def test_unknown_source_authorization(self):
        record = base_record(); record["evidence"]["source_authorization"] = "AUTHORIZED_BY_GUESS"; self.assertRejected(record)

    def test_duplicate_evidence_class(self):
        record = base_record(); record["evidence"]["evidence_classes"].append("source"); self.assertRejected(record)

    def test_unknown_evidence_class(self):
        record = base_record(); record["evidence"]["evidence_classes"] = ["coupon_magic"]; self.assertRejected(record)

    def test_invalid_document_hash(self):
        record = base_record(); record["evidence"]["document_sha256"] = "ABC"; self.assertRejected(record)

    def test_missing_right(self):
        record = base_record(); del record["rights"]["product_price_access"]; self.assertRejected(record)

    def test_verified_right_needs_locator(self):
        record = base_record(); record["rights"]["price_history_storage"]["evidence_locator"] = None; self.assertRejected(record)

    def test_unverified_right_cannot_have_locator(self):
        record = base_record(); record["rights"]["affiliate_url_conversion"]["evidence_locator"] = "bad"; self.assertRejected(record)

    def test_preapproved_review_rejected(self):
        record = base_record(); record["review"]["central_approval"] = "APPROVED"; self.assertRejected(record)

    def test_runtime_authorized_review_rejected(self):
        record = base_record(); record["review"]["runtime_authorized"] = True; self.assertRejected(record)

    def test_cta_enabled_review_rejected(self):
        record = base_record(); record["review"]["cta_enabled"] = True; self.assertRejected(record)

    def test_click_url_review_rejected(self):
        record = base_record(); record["review"]["click_url"] = "https://example.test"; self.assertRejected(record)

    def test_secret_key_rejected(self):
        record = base_record(); record["coupon"]["secret_key"] = "synthetic"; self.assertRejected(record)

    def test_account_id_rejected(self):
        record = base_record(); record["evidence"]["account_id"] = "redacted"; self.assertRejected(record)

    def test_synthetic_classification_needs_test_source(self):
        record = base_record(); record["evidence"]["source_authorization"] = "SOURCE_BLOCKED"; self.assertRejected(record)

    def test_real_looking_record_cannot_use_test_source(self):
        record = base_record(); record["fixture_class"] = "USER_PROVIDED_REDACTED_EVIDENCE"; record["data_classification"] = "USER_PROVIDED_REDACTED"; self.assertRejected(record)


class OutputInvariantTests(unittest.TestCase):
    def test_before_and_after_histories_are_distinct_objects(self):
        result = evaluate_coupon_evidence(base_record(), now=NOW)
        self.assertIsNot(result["history"]["before_coupon"], result["history"]["confirmed_after_coupon"])

    def test_before_history_keeps_base_price(self):
        result = evaluate_coupon_evidence(base_record(), now=NOW)
        self.assertEqual(99, result["history"]["before_coupon"]["price_twd"])

    def test_after_history_keeps_coupon_identity(self):
        result = evaluate_coupon_evidence(base_record(), now=NOW)
        self.assertEqual("SYN-COUPON-1", result["history"]["confirmed_after_coupon"]["coupon_id"])

    def test_affiliate_right_remains_unverified_while_coupon_test_passes(self):
        record = base_record()
        self.assertEqual("UNVERIFIED", record["rights"]["affiliate_url_conversion"]["state"])
        self.assertEqual("TEST_ONLY_CONFIRMED", evaluate_coupon_evidence(record, now=NOW)["evidence_status"])

    def test_display_price_is_not_required_total(self):
        record, _ = apply_case(PACK, "KNOWN_SHIPPING_COMPUTES_REQUIRED_TOTAL")
        result = evaluate_coupon_evidence(record, now=NOW)
        self.assertEqual(49, result["display_price_twd"])
        self.assertEqual(109, result["required_total_twd"])

    def test_all_results_keep_cta_disabled(self):
        for case in PACK["cases"]:
            record, expected = apply_case(PACK, case["id"])
            if "error" not in expected:
                self.assertFalse(evaluate_coupon_evidence(record, now=NOW)["cta_enabled"])


class CliAndArtifactTests(unittest.TestCase):
    def test_validate_all_cli(self):
        completed = subprocess.run([sys.executable, "-m", "research.coupon_evidence_c07.validate_all"], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("VALID", json.loads(completed.stdout)["status"])

    def test_single_record_cli(self):
        completed = subprocess.run(
            [sys.executable, "-m", "research.coupon_evidence_c07.cli", str(PACK_PATH), "--case", "T01_CONFIRMED_99_MINUS_50", "--now", PACK["evaluation_time"]],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("TEST_ONLY_CONFIRMED", json.loads(completed.stdout)["evidence_status"])

    def test_fixture_ids_unique(self):
        ids = [case["id"] for case in PACK["cases"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_required_t01_to_t12_coverage(self):
        joined = " ".join(case["id"] for case in PACK["cases"])
        for identifier in ("T01", "T02", "T03", "T04", "T05", "T06", "T07", "T08", "T09", "T10", "T11", "T12"):
            self.assertIn(identifier, joined)


if __name__ == "__main__":
    unittest.main()
