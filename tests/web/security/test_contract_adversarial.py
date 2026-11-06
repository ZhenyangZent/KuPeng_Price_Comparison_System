from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.web_security.audit import validate_product_detail, validate_search_response
from tools.web_security.simulated_web import SimulatedProductService, build_search_path

from tests.web.security.helpers import search_response, summary


class SearchContractTests(unittest.TestCase):
    def test_checked_in_valid_fixture_passes(self) -> None:
        payload = json.loads(Path("tests/web/security/fixtures/valid_search.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_search_response(payload), ())

    def test_schema_and_user_recorded_status_are_mandatory(self) -> None:
        payload = search_response(schema_version="wrong", data_source_status="WHOLE_MARKET")
        errors = validate_search_response(payload)
        self.assertIn("SCHEMA_VERSION_INVALID", errors)
        self.assertIn("DATA_SOURCE_STATUS_INVALID", errors)

    def test_forged_zero_requires_complete_cost_provenance(self) -> None:
        errors = validate_search_response(search_response(summary(last_observed_price_twd=0)))
        self.assertIn("ITEM_0_FORGED_OR_UNPROVEN_ZERO", errors)
        verified = summary(last_observed_price_twd=0, zero_price_provenance="VERIFIED_COMPLETE_COST")
        self.assertNotIn("ITEM_0_FORGED_OR_UNPROVEN_ZERO", validate_search_response(search_response(verified)))

    def test_missing_or_invalid_shipping_is_actionable(self) -> None:
        item = summary()
        del item["shipping_status"]
        errors = validate_search_response(search_response(item))
        self.assertIn("ITEM_0_MISSING_SHIPPING_STATUS", errors)
        self.assertIn("ITEM_0_SHIPPING_STATUS_INVALID", errors)

    def test_synthetic_fixture_cannot_leak_to_public_results(self) -> None:
        item = summary(source_type="SYNTHETIC")
        self.assertIn("ITEM_0_SYNTHETIC_LEAK", validate_search_response(search_response(item)))
        service = SimulatedProductService.from_items(
            (item, summary(id="public-1", title="Public coffee"))
        )
        result = service.search("synthetic")
        self.assertEqual(result["items"], [])

    def test_price_basis_and_variant_signature_must_be_explicit(self) -> None:
        item = summary(price_basis="MEMBER_ONLY", variant_signature="")
        errors = validate_search_response(search_response(item))
        self.assertIn("ITEM_0_PRICE_BASIS_INVALID", errors)
        self.assertIn("ITEM_0_VARIANT_SIGNATURE_MISSING", errors)

    def test_search_query_is_encoded_not_interpolated(self) -> None:
        path = build_search_path('x&redirect=https://evil.invalid/<script>')
        self.assertIn("q=x%26redirect%3Dhttps%3A%2F%2Fevil.invalid%2F%3Cscript%3E", path)
        self.assertEqual(path.count("redirect="), 0)


class ProductDetailContractTests(unittest.TestCase):
    @staticmethod
    def valid_detail():
        product = summary()
        return {
            "schema_version": "CDH-WEB-CONTRACT-V1",
            "product": product,
            "offers": [
                {
                    "offer_id": "offer-1",
                    "seller_id": "seller-1",
                    "sku_id": "sku-1",
                    "item_condition": "NEW",
                    "price_basis": "GENERAL_OBSERVED",
                }
            ],
            "history": [
                {
                    "observed_at": "2026-11-05T00:00:00Z",
                    "price_twd": 199,
                    "source_type": "USER_FILE",
                    "source_id": "fixture-file-1",
                    "sku_id": "sku-1",
                    "price_basis": "GENERAL_OBSERVED",
                }
            ],
            "observation_period_min_twd": 199,
        }

    def test_valid_detail_passes(self) -> None:
        self.assertEqual(validate_product_detail(self.valid_detail(), expected_product_id="product-1"), ())

    def test_wrong_product_sku_and_price_basis_are_rejected(self) -> None:
        detail = self.valid_detail()
        detail["offers"][0]["price_basis"] = "WOW_MEMBER"
        detail["history"][0]["sku_id"] = "sku-other"
        errors = validate_product_detail(detail, expected_product_id="product-1")
        self.assertIn("SKU_PRICE_BASIS_MISMATCH", errors)
        self.assertIn("HISTORY_SKU_MISMATCH", errors)

    def test_synthetic_history_and_unbounded_low_claim_are_rejected(self) -> None:
        detail = self.valid_detail()
        detail["history"][0]["source_type"] = "SYNTHETIC"
        detail["marketing_label"] = "上市以來最低價"
        errors = validate_product_detail(detail, expected_product_id="product-1")
        self.assertIn("FIXTURE_OR_UNAPPROVED_SOURCE_LEAK", errors)
        self.assertIn("UNBOUNDED_LOWEST_PRICE_CLAIM", errors)


if __name__ == "__main__":
    unittest.main()
