from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
H07 = ROOT / "review" / "H07"
EVIDENCE = H07 / "evidence"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ActualA10R08B11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = load(H07 / "INPUT_READBACK.json")
        cls.browser = load(EVIDENCE / "ACTUAL_A10R08_B11_BROWSER.json")
        cls.http = load(EVIDENCE / "B11_ACTUAL_HTTP.json")
        cls.har = load(EVIDENCE / "NETWORK_HAR.json")
        cls.journeys = {item["name"]: item for item in cls.browser["journeys"]}

    def test_01_pinned_input_integrity(self) -> None:
        self.assertEqual(self.inputs["status"], "PASS_INPUT_INTEGRITY_PINNED_R09")
        for label in ("R09", "A10_R08", "B11"):
            item = self.inputs["inputs"][label]
            self.assertEqual(item["crc"], "PASS")
            self.assertEqual(item["manifest_mismatch"], 0)
            self.assertEqual(item["unsafe_paths"], 0)
            self.assertEqual(item["symlinks"], 0)

    def test_02_exact_hash_bindings(self) -> None:
        self.assertEqual(self.inputs["inputs"]["R09"]["sha256"], "be0ee2febae110a16bac12dd6c00e26c74e8006f4eb944b5fdad0d6d0a76a71b")
        self.assertEqual(self.inputs["inputs"]["A10_R08"]["sha256"], "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd")
        self.assertEqual(self.inputs["inputs"]["B11"]["sha256"], "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a")
        self.assertTrue(self.inputs["inputs"]["A10_R08"]["final_pass_authorized"])

    def test_03_new_frontend_baseline_not_h06(self) -> None:
        self.assertEqual(self.browser["a10_r08"]["sha256"], "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd")
        self.assertNotEqual(self.browser["a10_r08"]["sha256"], "eb4b449972f1bb6bccd9457e8ee88a2b3c69f2a2001b17fc5adfceb23c6a7e08")

    def test_04_real_b11_http(self) -> None:
        self.assertEqual(self.http["search"]["status"], 200)
        self.assertEqual(self.http["search"]["body"]["total"], 9)
        self.assertTrue(all(item["status"] == 200 for item in self.http["details"].values()))

    def test_05_confirmed_price_raw_and_daily_wire(self) -> None:
        detail = self.http["details"]["confirmed"]["body"]
        self.assertEqual(detail["product"]["display_price_twd"], 49)
        self.assertEqual(detail["product"]["before_coupon_price_twd"], 99)
        self.assertEqual([item["price_twd"] for item in detail["history"]["before_coupon"]], [99])
        self.assertEqual([item["price_twd"] for item in detail["history"]["confirmed_after_coupon"]], [49])
        self.assertTrue(self.browser["daily_history_wire_gate"]["pass"])

    def test_06_daily_history_dom_gap_is_reproduced(self) -> None:
        gate = self.browser["daily_history_dom_gate"]
        self.assertFalse(gate["before_visible"])
        self.assertFalse(gate["after_visible"])
        self.assertFalse(gate["explicit_daily_label_visible"])
        self.assertFalse(gate["pass"])
        self.assertEqual(self.browser["product_integration_gate"], "FAIL_DAILY_HISTORY_NOT_RENDERED")

    def test_07_browser_evidence_collection_complete(self) -> None:
        self.assertEqual(self.browser["evidence_collection_gate"], "PASS")
        self.assertEqual(len(self.browser["journeys"]), 10)
        self.assertTrue(all(item["pass"] for item in self.browser["journeys"]))

    def test_08_real_browser_search_and_detail_requests(self) -> None:
        self.assertEqual(self.browser["browser_search_request_count"], 11)
        self.assertEqual(self.browser["browser_detail_request_count"], 10)
        urls = [item["url"] for item in self.har["entries"]]
        self.assertTrue(any("/cdh-coupon-v4/api/v4/products?" in url for url in urls))
        self.assertTrue(any("/cdh-coupon-v4/api/v4/products/confirmed" in url for url in urls))

    def test_09_claim_and_expired_fail_closed(self) -> None:
        claim = self.http["details"]["claim-required"]["body"]["product"]
        expired = self.http["details"]["expired-coupon"]["body"]["product"]
        self.assertEqual(claim["display_price_twd"], 99)
        self.assertIsNone(claim["confirmed_coupon_price_twd"])
        self.assertEqual(expired["display_price_twd"], 99)
        self.assertIsNone(expired["confirmed_coupon_price_twd"])

    def test_10_zero_and_unavailable_are_distinct(self) -> None:
        zero = self.http["details"]["zero"]["body"]["product"]
        unavailable = self.http["details"]["unavailable"]["body"]["product"]
        self.assertEqual(zero["display_price_twd"], 0)
        self.assertIsNone(zero["required_total_twd"])
        self.assertIsNone(unavailable["display_price_twd"])

    def test_11_keyboard_quantity_two(self) -> None:
        item = self.journeys["a10r08-b11-keyboard-quantity-two"]
        self.assertIn("q=SYN-SKU-QUANTITY_TWO", item["url"])
        self.assertIn("series=quantity-two", item["url"])
        product = self.http["details"]["quantity-two"]["body"]["product"]
        self.assertEqual(product["minimum_purchase_quantity"], 2)
        self.assertEqual(product["minimum_item_spend_twd"], 150)

    def test_12_empty_search_has_no_fixture_fallback(self) -> None:
        item = self.journeys["a10r08-b11-empty-search"]
        self.assertTrue(item["pass"])
        self.assertEqual(item["disabled_cta_count"], 0)

    def test_13_timeout_and_recovery(self) -> None:
        self.assertTrue(self.journeys["a10r08-b11-timeout-mobile"]["pass"])
        self.assertTrue(self.journeys["a10r08-b11-timeout-recovery-mobile"]["pass"])

    def test_14_revoked_source(self) -> None:
        self.assertTrue(self.journeys["a10r08-b11-revoked-source"]["pass"])

    def test_15_http_negative_security(self) -> None:
        self.assertEqual(self.http["missing"]["status"], 404)
        self.assertEqual(self.http["hostile_host"]["status"], 400)
        self.assertEqual(self.http["hostile_origin"]["status"], 403)

    def test_16_cta_layout_and_viewports(self) -> None:
        self.assertEqual(self.journeys["a10r08-b11-confirmed-desktop"]["viewport"], "1440x1100")
        self.assertEqual(self.journeys["a10r08-b11-unavailable-mobile"]["viewport"], "390x844")
        for item in self.browser["journeys"]:
            self.assertEqual(item["disabled_cta_count"], item["expected_disabled_cta_count"])
            self.assertEqual(item["outbound_anchor_count"], 0)
            self.assertFalse(item["horizontal_overflow"])

    def test_17_network_is_loopback_only(self) -> None:
        self.assertEqual(self.browser["external_request_count"], 0)
        self.assertEqual(self.har["external_request_count"], 0)

    def test_18_screenshots_are_valid_pngs(self) -> None:
        paths = [item["screenshot"] for item in self.browser["journeys"]] + [self.browser["daily_history_dom_gate"]["history_screenshot"]]
        self.assertEqual(len(paths), 11)
        for rel in paths:
            data = (ROOT / rel).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", data[16:24])
            self.assertGreaterEqual(width, 390)
            self.assertGreaterEqual(height, 844)

    def test_19_no_substitute_ui_or_h06_dependency(self) -> None:
        self.assertEqual(list((ROOT / "tools" / "web_journey_h07").glob("*.html")), [])
        text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in (ROOT / "tools" / "web_journey_h07").glob("*.*") if path.is_file())
        self.assertNotIn("review/H06", text.replace("\\", "/"))
        self.assertEqual(self.browser["a10_r08"]["source"], "manifest-verified R08 continuation release dist")


if __name__ == "__main__":
    unittest.main()
