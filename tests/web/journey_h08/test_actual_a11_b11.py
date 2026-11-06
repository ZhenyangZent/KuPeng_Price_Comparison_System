from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
H08 = ROOT / "review" / "H08"
EVIDENCE = H08 / "evidence"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ActualA11B11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = load(H08 / "INPUT_READBACK.json")
        cls.browser = load(EVIDENCE / "ACTUAL_A11_B11_BROWSER.json")
        cls.http = load(EVIDENCE / "B11_ACTUAL_HTTP.json")
        cls.har = load(EVIDENCE / "NETWORK_HAR.json")
        cls.launcher = load(EVIDENCE / "A11_LAUNCHER_JOURNEY.json")
        cls.journeys = {item["name"]: item for item in cls.browser["journeys"]}

    def test_01_input_integrity(self) -> None:
        self.assertEqual(self.inputs["status"], "PASS_INPUT_INTEGRITY_PINNED_R10")
        for label in ("R10", "A11_R09", "B11_R07"):
            item = self.inputs["inputs"][label]
            self.assertEqual(item["crc"], "PASS")
            self.assertEqual(item["manifest_mismatch"], 0)
            self.assertEqual(item["unsafe_paths"], 0)
            self.assertEqual(item["symlinks"], 0)

    def test_02_exact_hash_bindings(self) -> None:
        self.assertEqual(self.inputs["inputs"]["R10"]["sha256"], "0474031243db86ffc7c7b05e7569f701f5705cf84a25b98453b987f1c99b7abc")
        self.assertEqual(self.inputs["inputs"]["A11_R09"]["sha256"], "40e54a65a7c2bfe808bcaa528e75058ab96c98c4f68d9cfa09259b7e5b97a0cd")
        self.assertEqual(self.inputs["inputs"]["B11_R07"]["sha256"], "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a")

    def test_03_real_b11_http_and_security(self) -> None:
        self.assertEqual(self.http["search"]["status"], 200)
        self.assertEqual(self.http["search"]["body"]["total"], 9)
        self.assertTrue(all(item["status"] == 200 for item in self.http["details"].values()))
        self.assertEqual(self.http["missing"]["status"], 404)
        self.assertEqual(self.http["hostile_host"]["status"], 400)
        self.assertEqual(self.http["hostile_origin"]["status"], 403)

    def test_04_confirmed_prices_and_raw_history(self) -> None:
        detail = self.http["details"]["confirmed"]["body"]
        self.assertEqual(detail["product"]["display_price_twd"], 49)
        self.assertEqual(detail["product"]["before_coupon_price_twd"], 99)
        self.assertEqual([item["price_twd"] for item in detail["history"]["before_coupon"]], [99])
        self.assertEqual([item["price_twd"] for item in detail["history"]["confirmed_after_coupon"]], [49])
        self.assertTrue(self.browser["raw_history_dom_gate"]["pass"])

    def test_05_daily_wire_values_and_counts(self) -> None:
        gate = self.browser["daily_history_wire_gate"]
        self.assertTrue(gate["pass"])
        self.assertEqual(gate["before"], [{"taipei_date": "2026-11-04", "representative_price_twd": 99, "sample_count": 1}])
        self.assertEqual(gate["after"], [{"taipei_date": "2026-11-04", "representative_price_twd": 49, "sample_count": 1}])

    def test_06_daily_dom_labels_prices_counts(self) -> None:
        gate = self.browser["daily_history_dom_gate"]
        self.assertTrue(gate["pass"])
        self.assertEqual([item["label"] for item in gate["groups"]], ["B11 券前每日代表價", "B11 已確認券後每日代表價"])
        self.assertEqual([item["rows"][0]["price"] for item in gate["groups"]], ["NT$ 99", "NT$ 49"])
        self.assertEqual([item["rows"][0]["sample_count"] for item in gate["groups"]], ["1 個 raw 樣本", "1 個 raw 樣本"])

    def test_07_browser_collection_complete(self) -> None:
        self.assertEqual(self.browser["evidence_collection_gate"], "PASS")
        self.assertEqual(self.browser["product_integration_gate"], "PASS_SCOPED")
        self.assertEqual(len(self.browser["journeys"]), 11)
        self.assertTrue(all(item["pass"] for item in self.browser["journeys"]))

    def test_08_real_browser_requests(self) -> None:
        self.assertEqual(self.browser["browser_search_request_count"], 12)
        self.assertEqual(self.browser["browser_detail_request_count"], 10)
        urls = [item["url"] for item in self.har["entries"]]
        self.assertTrue(any("/cdh-coupon-v4/api/v4/products?" in url for url in urls))
        self.assertTrue(any("/cdh-coupon-v4/api/v4/products/confirmed" in url for url in urls))

    def test_09_claim_and_expired_fail_closed(self) -> None:
        for key in ("claim-required", "expired-coupon"):
            product = self.http["details"][key]["body"]["product"]
            self.assertEqual(product["display_price_twd"], 99)
            self.assertIsNone(product["confirmed_coupon_price_twd"])

    def test_10_zero_and_unknown_distinct(self) -> None:
        zero = self.http["details"]["zero"]["body"]["product"]
        unavailable = self.http["details"]["unavailable"]["body"]["product"]
        self.assertEqual(zero["display_price_twd"], 0)
        self.assertIsNone(zero["required_total_twd"])
        self.assertIsNone(unavailable["display_price_twd"])

    def test_11_quantity_and_keyboard(self) -> None:
        journey = self.journeys["a11-b11-keyboard-quantity-two"]
        self.assertIn("q=SYN-SKU-QUANTITY_TWO", journey["url"])
        self.assertIn("series=quantity-two", journey["url"])
        product = self.http["details"]["quantity-two"]["body"]["product"]
        self.assertEqual(product["minimum_purchase_quantity"], 2)
        self.assertEqual(product["minimum_item_spend_twd"], 150)

    def test_12_empty_timeout_retry_bad_json(self) -> None:
        for name in ("a11-b11-empty-search", "a11-b11-timeout-mobile", "a11-b11-timeout-recovery-mobile", "a11-b11-bad-json"):
            self.assertTrue(self.journeys[name]["pass"])
        self.assertEqual(self.journeys["a11-b11-bad-json"]["disabled_cta_count"], 0)

    def test_13_revoked_source(self) -> None:
        self.assertTrue(self.journeys["a11-b11-revoked-source"]["pass"])

    def test_14_cta_and_responsive_layout(self) -> None:
        self.assertEqual(self.journeys["a11-b11-confirmed-desktop"]["viewport"], "1440x1100")
        self.assertEqual(self.journeys["a11-b11-unavailable-mobile"]["viewport"], "390x844")
        for item in self.browser["journeys"]:
            self.assertEqual(item["disabled_cta_count"], item["expected_disabled_cta_count"])
            self.assertEqual(item["outbound_anchor_count"], 0)
            self.assertFalse(item["horizontal_overflow"])

    def test_15_network_is_loopback_only(self) -> None:
        self.assertEqual(self.browser["external_request_count"], 0)
        self.assertEqual(self.har["external_request_count"], 0)

    def test_16_screenshots_valid(self) -> None:
        paths = [item["screenshot"] for item in self.browser["journeys"]] + [self.browser["daily_history_dom_gate"]["history_screenshot"]]
        self.assertEqual(len(paths), 12)
        for rel in paths:
            data = (ROOT / rel).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", data[16:24])
            self.assertGreaterEqual(width, 390)
            self.assertGreaterEqual(height, 844)

    def test_17_launcher_exact_stage(self) -> None:
        staged = self.launcher["staged_exact_project"]
        self.assertEqual(staged["control_sha256"], "7c94748631c1b686cd812ab0d0304aed21751d6d64336a4983f65e86381a620d")
        self.assertEqual(staged["preview_server_sha256"], "a0f388b17a593da498280a65073f92d0794fb603f4bdf1dc70aa63b184ed9210")
        self.assertEqual(staged["dist_manifest_sha256"], "86d369bb74e51c925a403d996f09d823a54231c05f9ceb908ba1cb47042a58e4")

    def test_18_launcher_lifecycle(self) -> None:
        self.assertTrue(self.launcher["all_pass"])
        for key in ("start_1_ready", "status_1_ready", "stop_1_clean", "status_after_stop", "same_port_restart_ready", "status_2_ready", "stop_2_clean"):
            self.assertTrue(self.launcher["checks"][key], key)

    def test_19_launcher_safety(self) -> None:
        for key in ("wrong_token_rejected", "wrong_token_no_effect", "unknown_process_not_terminated", "collision_port_released_by_test_owner"):
            self.assertTrue(self.launcher["checks"][key], key)

    def test_20_no_substitute_ui(self) -> None:
        self.assertEqual(list((ROOT / "tools" / "web_journey_h08").glob("*.html")), [])
        self.assertEqual(self.browser["a11_r09"]["source"], "manifest-verified R09 release dist")


if __name__ == "__main__":
    unittest.main()
