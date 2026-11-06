from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[3]
H03 = PROJECT / "review" / "H03"


class H03FixedIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baselines = json.loads((H03 / "BASELINE_READBACK.json").read_text(encoding="utf-8"))
        cls.cases = json.loads((H03 / "runtime" / "B09_CASES.json").read_text(encoding="utf-8"))
        cls.contract = json.loads((H03 / "runtime" / "A08_B09_CONTRACT_RESULTS.json").read_text(encoding="utf-8"))
        cls.browser = json.loads((H03 / "evidence" / "BROWSER_JOURNEY_A08_B09.json").read_text(encoding="utf-8"))

    def test_fixed_packages_and_manifests_are_pinned(self) -> None:
        self.assertEqual(self.baselines["status"], "PASS")
        for label in ("A08", "B09"):
            self.assertEqual(self.baselines["baselines"][label]["archive"]["crc"], "PASS")
            self.assertTrue(self.baselines["baselines"][label]["manifest"]["pass"])
            self.assertEqual(self.baselines["baselines"][label]["manifest"]["mismatch"], 0)

    def test_exact_a08_b09_contract_calls_all_pass(self) -> None:
        self.assertEqual(self.contract["counts"], {"total": 9, "pass": 9, "fail": 0})
        self.assertTrue(self.contract["expected_outcome_match"])
        self.assertEqual(self.contract["product_integration_gate"], "PASS")

    def test_unavailable_remains_null_and_raw_daily_lows_are_distinct(self) -> None:
        unavailable = next(item for item in self.cases["cases"] if item["case"] == "unavailable")
        mismatch = next(item for item in self.cases["cases"] if item["case"] == "raw_min_mismatch")
        self.assertIsNone(unavailable["search"]["items"][0]["last_observed_price_twd"])
        self.assertEqual(unavailable["search"]["items"][0]["price_basis"], "UNAVAILABLE")
        self.assertEqual(unavailable["detail"]["history"], [])
        self.assertEqual(mismatch["derived"], {"raw_history_min_twd": 10, "v2_observation_period_min_twd": 10, "v3_daily_period_low_twd": 20})

    def test_browser_search_mobile_stale_retry_keyboard_and_affiliate(self) -> None:
        self.assertTrue(self.browser["all_journeys_pass"])
        self.assertEqual(len(self.browser["results"]), 5)
        self.assertTrue(all(item["pass"] for item in self.browser["results"]))
        self.assertEqual(self.browser["network"]["external_request_count"], 0)
        zero = next(item for item in self.browser["results"] if "zero-desktop" in item["case"])
        self.assertEqual(zero["action_evidence"]["typed_query"], "SYN-EARBUD-WHT")
        self.assertIn("q=SYN-EARBUD-WHT", zero["action_evidence"]["search_keyboard_enter"]["url"])
        self.assertTrue(zero["action_evidence"]["retry_button_clicked"])
        self.assertEqual(zero["action_evidence"]["keyboard_tab_active"], {"tag": "BUTTON", "text": "搜尋紀錄"})
        for item in self.browser["results"]:
            if "synthetic" in item["case"]:
                self.assertGreater(item["disabled_affiliate_button_count"], 0)
                self.assertEqual(item["outbound_affiliate_anchor_count"], 0)

    def test_screenshots_are_nonempty_pngs(self) -> None:
        for item in self.browser["results"]:
            screenshot = PROJECT / Path(item["screenshot"])
            data = screenshot.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", data[16:24])
            self.assertGreater(width, 300)
            self.assertGreater(height, 700)


if __name__ == "__main__":
    unittest.main()
