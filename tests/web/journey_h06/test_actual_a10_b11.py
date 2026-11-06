from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
H06 = ROOT / "review" / "H06"
EVIDENCE = H06 / "evidence"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ActualA10B11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = load(H06 / "INPUT_READBACK.json")
        cls.browser = load(EVIDENCE / "ACTUAL_A10_B11_BROWSER.json")
        cls.http = load(EVIDENCE / "B11_ACTUAL_HTTP.json")
        cls.har = load(EVIDENCE / "NETWORK_HAR.json")
        cls.journeys = {item["name"]: item for item in cls.browser["journeys"]}

    def test_01_input_integrity(self) -> None:
        self.assertEqual(self.inputs["status"], "PASS_INPUT_INTEGRITY_A10_PRESENT_BUT_UNACKNOWLEDGED")
        for label in ("R08", "A10", "B11"):
            item = self.inputs["inputs"][label]
            self.assertEqual(item["crc"], "PASS")
            self.assertEqual(item["manifest_mismatch"], 0)
            self.assertEqual(item["unsafe_paths"], 0)
            self.assertEqual(item["symlinks"], 0)

    def test_02_exact_hash_bindings(self) -> None:
        self.assertEqual(self.inputs["inputs"]["R08"]["sha256"], "61d75b334fd7073202691bab887186261c85d1fa42af05e79f16d1a46f24b144")
        self.assertEqual(self.inputs["inputs"]["A10"]["sha256"], "eb4b449972f1bb6bccd9457e8ee88a2b3c69f2a2001b17fc5adfceb23c6a7e08")
        self.assertEqual(self.inputs["inputs"]["B11"]["sha256"], "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a")

    def test_03_a10_ack_gate_is_fail_closed(self) -> None:
        a10 = self.inputs["inputs"]["A10"]
        self.assertEqual(a10["central_ack_state"], "NOT_ACKNOWLEDGED_IN_R08_AUTHORITY")
        self.assertFalse(a10["final_pass_authorized"])
        self.assertEqual(self.browser["final_integration_gate"], "PROVISIONAL_PASS_AWAITING_CENTRAL_A10_SHA_ACK")

    def test_04_b11_real_search(self) -> None:
        self.assertEqual(self.http["search"]["status"], 200)
        self.assertEqual(self.http["search"]["body"]["schema_version"], "CDH-COUPON-PRICE-V4")
        self.assertEqual(self.http["search"]["body"]["total"], 9)

    def test_05_confirmed_price_and_dual_history(self) -> None:
        detail = self.http["details"]["confirmed"]["body"]
        self.assertEqual(detail["product"]["display_price_twd"], 49)
        self.assertEqual(detail["product"]["before_coupon_price_twd"], 99)
        self.assertEqual(detail["product"]["display_basis"], "CONFIRMED_COUPON")
        self.assertEqual([item["price_twd"] for item in detail["history"]["before_coupon"]], [99])
        self.assertEqual([item["price_twd"] for item in detail["history"]["confirmed_after_coupon"]], [49])

    def test_06_expired_coupon_is_not_confirmed(self) -> None:
        detail = self.http["details"]["expired-coupon"]["body"]
        self.assertEqual(detail["product"]["display_price_twd"], 99)
        self.assertEqual(detail["product"]["display_basis"], "BASE_PRICE")
        self.assertEqual(detail["history"]["confirmed_after_coupon"], [])

    def test_07_zero_is_distinct_from_unavailable(self) -> None:
        zero = self.http["details"]["zero"]["body"]["product"]
        unavailable = self.http["details"]["unavailable"]["body"]["product"]
        self.assertEqual(zero["display_price_twd"], 0)
        self.assertIsNone(zero["required_total_twd"])
        self.assertIsNone(unavailable["display_price_twd"])
        self.assertEqual(unavailable["display_basis"], "PRICE_UNAVAILABLE")

    def test_08_identity_and_quantity_are_preserved(self) -> None:
        quantity = self.http["details"]["quantity-two"]["body"]["product"]
        wrong_sku = self.http["details"]["wrong-sku"]["body"]["product"]
        self.assertEqual(quantity["minimum_purchase_quantity"], 2)
        self.assertEqual(wrong_sku["series_identity"]["sku_id"], "SYN-SKU-WRONG_SKU")
        self.assertIn("COUPON_IDENTITY_MISMATCH", wrong_sku["quality_flags"])
        self.assertIn("COUPON_IDENTITY_MISMATCH", wrong_sku["coupon"]["evaluation_reasons"])
        self.assertIsNone(wrong_sku["confirmed_coupon_price_twd"])

    def test_09_b11_http_negative_security(self) -> None:
        self.assertEqual(self.http["missing"]["status"], 404)
        self.assertEqual(self.http["hostile_host"]["status"], 400)
        self.assertEqual(self.http["hostile_origin"]["status"], 403)

    def test_10_all_browser_journeys_pass(self) -> None:
        self.assertEqual(len(self.browser["journeys"]), 7)
        self.assertTrue(all(item["pass"] for item in self.browser["journeys"]))
        self.assertEqual(self.browser["evidence_result"], "PASS_PROVISIONAL_EVIDENCE")

    def test_11_real_browser_search_and_detail_requests(self) -> None:
        self.assertGreater(self.browser["browser_search_request_count"], 0)
        self.assertGreater(self.browser["browser_detail_request_count"], 0)
        urls = [item["url"] for item in self.har["entries"]]
        self.assertTrue(any("/cdh-coupon-v4/api/v4/products?" in url for url in urls))
        self.assertTrue(any("/cdh-coupon-v4/api/v4/products/confirmed" in url for url in urls))

    def test_12_desktop_mobile_and_keyboard(self) -> None:
        self.assertEqual(self.journeys["a10-b11-confirmed-desktop"]["viewport"], "1440x1100")
        self.assertEqual(self.journeys["a10-b11-unavailable-mobile"]["viewport"], "390x844")
        keyboard = self.journeys["a10-b11-keyboard-search-zero"]
        self.assertIn("q=zero", keyboard["url"])
        self.assertIn("series=zero", keyboard["url"])

    def test_13_timeout_and_recovery(self) -> None:
        self.assertTrue(self.journeys["a10-b11-timeout-mobile"]["pass"])
        self.assertEqual(self.journeys["a10-b11-timeout-mobile"]["disabled_cta_count"], 0)
        self.assertTrue(self.journeys["a10-b11-timeout-recovery-mobile"]["pass"])

    def test_14_revoked_source_fails_closed(self) -> None:
        revoked = self.journeys["a10-b11-revoked-source-desktop"]
        self.assertEqual(revoked["viewport"], "1024x900")
        self.assertTrue(revoked["pass"])

    def test_15_cta_and_layout_gates(self) -> None:
        for item in self.browser["journeys"]:
            self.assertEqual(item["outbound_anchor_count"], 0)
            self.assertFalse(item["horizontal_overflow"])
            self.assertEqual(item["disabled_cta_count"], item["expected_disabled_cta_count"])

    def test_16_network_is_loopback_only(self) -> None:
        self.assertEqual(self.browser["external_request_count"], 0)
        self.assertEqual(self.har["external_request_count"], 0)

    def test_17_screenshots_are_valid_pngs(self) -> None:
        for item in self.browser["journeys"]:
            data = (ROOT / item["screenshot"]).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", data[16:24])
            expected_width, expected_height = map(int, item["viewport"].split("x"))
            self.assertEqual((width, height), (expected_width, expected_height))

    def test_18_no_substitute_website(self) -> None:
        html_files = list((ROOT / "tools" / "web_journey_h06").glob("*.html"))
        self.assertEqual(html_files, [])
        self.assertEqual(self.browser["a10"]["source"], "manifest-verified release dist")
        self.assertIn("separately extracted exact WSGI", self.browser["b11"]["source"])


if __name__ == "__main__":
    unittest.main()
