from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
H05 = ROOT / "review" / "H05"
EVIDENCE = H05 / "evidence"


def load(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


class ExactA09B10EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = json.loads((H05 / "INPUT_READBACK.json").read_text(encoding="utf-8"))
        cls.http = load("B10_ACTUAL_HTTP.json")
        cls.parser = load("A09_B10_PARSER_RESULT.json")
        cls.browser = load("EXACT_A09_B10_BROWSER.json")
        cls.har = load("NETWORK_HAR.json")

    def test_01_exact_input_integrity(self) -> None:
        self.assertEqual(self.inputs["status"], "PASS")
        for lane in ("R07", "A09", "B10"):
            item = self.inputs["inputs"][lane]
            self.assertEqual(item["crc"], "PASS")
            self.assertEqual(item["manifest_mismatch"], 0)
            self.assertEqual(item["unsafe_paths"], 0)
            self.assertEqual(item["symlinks"], 0)

    def test_02_exact_hash_bindings(self) -> None:
        self.assertEqual(self.inputs["inputs"]["R07"]["sha256"], "76b1332c3e2cd82a05e5f26e6d3e0c01cdf65e828f82d5b586902bdfacda2827")
        self.assertEqual(self.inputs["inputs"]["A09"]["sha256"], "96d239e4a3bb5ca57624c0b8d6e06344ad68b6482b13d8ee9b72a8f1997ebbde")
        self.assertEqual(self.inputs["inputs"]["B10"]["sha256"], "dfef51befb8785e069e4be5514b4eec106952deb5f52ee4cd98974c50273e549")

    def test_03_real_b10_search_and_detail(self) -> None:
        self.assertEqual(self.http["search"]["status"], 200)
        self.assertEqual(self.http["detail"]["status"], 200)
        self.assertEqual(self.http["search"]["body"]["schema_version"], "CDH-COUPON-PRICE-V4")
        self.assertEqual(self.http["detail"]["body"]["schema_version"], "CDH-COUPON-PRICE-V4")

    def test_04_real_b10_coupon_prices(self) -> None:
        product = self.http["detail"]["body"]["product"]
        self.assertEqual(product["display_price_twd"], 49)
        self.assertEqual(product["before_coupon_price_twd"], 99)
        self.assertEqual(product["display_basis"], "CONFIRMED_COUPON")
        self.assertEqual(product["coupon"]["status"], "CONFIRMED_APPLICABLE")

    def test_05_real_b10_dual_history(self) -> None:
        history = self.http["detail"]["body"]["history"]
        self.assertEqual([x["price_twd"] for x in history["before_coupon"]], [99])
        self.assertEqual([x["price_twd"] for x in history["confirmed_after_coupon"]], [49])

    def test_06_real_b10_negative_and_cache_paths(self) -> None:
        self.assertEqual(self.http["missing"]["status"], 404)
        self.assertEqual(self.http["missing"]["body"]["error"]["code"], "NOT_FOUND")
        self.assertEqual(self.http["not_modified"]["status"], 304)
        self.assertEqual(self.http["not_modified"]["etag"], self.http["search"]["headers"]["etag"])

    def test_07_real_b10_security_headers(self) -> None:
        headers = self.http["search"]["headers"]
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertEqual(headers["x-frame-options"], "DENY")
        self.assertEqual(headers["referrer-policy"], "no-referrer")
        self.assertIn("default-src 'none'", headers["content-security-policy"])

    def test_08_exact_a09_parser_reproduces_wire_blocker(self) -> None:
        expected = [
            ("search_item", "V4_VERSION_MISMATCH"),
            ("search_envelope", "INVALID_V4_PAYLOAD"),
            ("detail_product", "V4_VERSION_MISMATCH"),
            ("detail_envelope", "INVALID_V4_PAYLOAD"),
        ]
        actual = [(x["name"], x["code"]) for x in self.parser["attempts"]]
        self.assertEqual(actual, expected)
        self.assertTrue(self.parser["expected_blocker_match"])

    def test_09_exact_a09_ui_does_not_use_b10(self) -> None:
        ui = self.browser["a09_ui"]
        self.assertTrue(ui["builtin_fixture_banner"])
        self.assertEqual(ui["b10_api_requests_during_ui"], 0)
        self.assertEqual(ui["disabled_cta_count"], 1)
        self.assertEqual(ui["outbound_cta_count"], 0)
        self.assertEqual(self.browser["exact_a09_b10_gate"], "FAIL_INCOMPATIBLE_NO_UI_FETCH")

    def test_10_cross_origin_fetch_is_blocked(self) -> None:
        cors = self.browser["cors_fetch_from_a09"]
        self.assertFalse(cors["ok"])
        self.assertEqual(cors["name"], "TypeError")
        self.assertIn("Failed to fetch", cors["message"])

    def test_11_network_is_loopback_only(self) -> None:
        self.assertEqual(self.browser["network"]["external_request_count"], 0)
        self.assertEqual(self.har["external_request_count"], 0)
        self.assertGreater(len(self.har["entries"]), 0)

    def test_12_screenshots_are_valid_pngs(self) -> None:
        for rel in (self.browser["a09_ui"]["screenshot"], self.browser["b10_real_http"]["screenshot"]):
            path = ROOT / rel
            data = path.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", data[16:24])
            self.assertGreaterEqual(width, 800)
            self.assertGreaterEqual(height, 600)

    def test_13_a10_b11_is_not_misreported(self) -> None:
        self.assertEqual(self.inputs["inputs"]["A10"]["state"], "NOT_AVAILABLE")
        self.assertEqual(self.inputs["inputs"]["B11"]["state"], "NOT_AVAILABLE")
        self.assertEqual(self.browser["exact_a10_b11_gate"], "NOT_RUN_INPUT_UNAVAILABLE")

    def test_14_h05_is_self_contained(self) -> None:
        text_files = list((ROOT / "tools" / "web_journey_h05").glob("*.*"))
        content = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in text_files if p.is_file())
        self.assertNotIn("review/H03", content.replace("\\", "/"))
        self.assertNotIn("review/H04", content.replace("\\", "/"))


if __name__ == "__main__":
    unittest.main()
