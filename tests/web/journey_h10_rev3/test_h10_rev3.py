from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "review" / "H10_REV3" / "evidence"
RUNNER = ROOT / "tools" / "web_journey_h10" / "run_actual_h10_rev2.mjs"
TWD = re.compile(r"^NT\$\s*(0|[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)$")


def parse_twd(value: str) -> int | None:
    match = TWD.fullmatch(value.strip())
    return int(match.group(1).replace(",", "")) if match else None


class H10Rev3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.actual = json.loads((EVIDENCE / "ACTUAL_H10_REV3_BROWSER_HTTP.json").read_text(encoding="utf-8"))
        cls.receipt = json.loads((EVIDENCE / "BROWSER_PROCESS_RECEIPT.json").read_text(encoding="utf-8"))
        cls.sqlite = json.loads((EVIDENCE / "SQLITE_READONLY_EVIDENCE.json").read_text(encoding="utf-8"))
        cls.inputs = json.loads((ROOT / "review" / "H10_REV3" / "INPUT_READBACK.json").read_text(encoding="utf-8"))
        cls.runner = RUNNER.read_text(encoding="utf-8")

    def test_strict_twd_accepts_spacing_and_full_amounts(self) -> None:
        self.assertEqual(parse_twd("NT$1,000"), 1000)
        self.assertEqual(parse_twd("NT$ 1,000"), 1000)
        self.assertEqual(parse_twd("NT$\t900"), 900)
        self.assertEqual(parse_twd("NT$950"), 950)
        self.assertEqual(parse_twd("NT$ 0"), 0)

    def test_strict_twd_rejects_non_exact_text(self) -> None:
        for value in ("foo NT$ 1,000", "NT$ 1,000 extra", "NT$ 1,00", "NT$ -1", "NT$ 01", "NT$ 1.5"):
            with self.subTest(value=value):
                self.assertIsNone(parse_twd(value))

    def test_runner_uses_anchored_parser_and_numeric_daily_gates(self) -> None:
        self.assertIn("/^NT\\\\$\\\\s*(0|[1-9]\\\\d*|[1-9]\\\\d{0,2}(?:,\\\\d{3})+)$/u", self.runner)
        self.assertIn("x=>[x.date,x.samples,x.price_twd]", self.runner)
        self.assertNotIn("before_daily.map(x=>[x.date,x.samples,x.price_text])", self.runner)
        self.assertNotIn("reported_daily.map(x=>[x.date,x.samples,x.price_text])", self.runner)

    def test_browser_and_chrome_exited_cleanly(self) -> None:
        self.assertEqual(self.receipt["exit_code"], 0)
        self.assertEqual(self.actual["browser_test_exit_code"], 0)
        self.assertEqual(self.actual["chrome_process_exit_code"], 0)
        self.assertEqual(self.actual["status"], "PASS")

    def test_all_23_product_gates_pass(self) -> None:
        self.assertEqual(len(self.actual["gates"]), 23)
        self.assertTrue(all(self.actual["gates"].values()))

    def test_daily_dates_samples_and_prices(self) -> None:
        detail = self.actual["search_results"][0]
        self.assertEqual(
            [(item["date"], item["samples"], item["price_twd"]) for item in detail["before_daily"]],
            [("2026-11-03", 1, 1000), ("2026-11-04", 1, 950)],
        )
        self.assertEqual(
            [(item["date"], item["samples"], item["price_twd"]) for item in detail["reported_daily"]],
            [("2026-11-03", 1, 900)],
        )

    def test_raw_tracks_and_confirmed_empty(self) -> None:
        detail = self.actual["search_results"][0]
        self.assertEqual([item["price"] for item in detail["before_raw"]], [1000, 950])
        self.assertEqual([item["price"] for item in detail["reported_raw"]], [900])
        self.assertEqual(detail["confirmed_raw"], [])
        self.assertEqual(detail["confirmed_daily"], [])
        self.assertTrue(detail["confirmed_empty"])

    def test_three_search_modes_are_exact_and_separated(self) -> None:
        self.assertEqual([item["kind"] for item in self.actual["search_results"]], ["title", "product_id", "sku"])
        self.assertTrue(all(item["result_count"] == 1 for item in self.actual["search_results"]))
        self.assertTrue(all(item["exact_container"] for item in self.actual["search_results"]))
        self.assertTrue(all(item["synthetic_outside"] and item["b11_outside"] for item in self.actual["search_results"]))

    def test_read_after_restart_did_not_write(self) -> None:
        self.assertEqual(self.actual["browser_post_after_restart_count"], 0)
        self.assertEqual(self.actual["rows_before_read"], 2)
        self.assertEqual(self.actual["rows_after_read"], 2)
        self.assertTrue(self.actual["database_unchanged_by_read"])
        self.assertEqual(self.actual["database_sha256_before_read"], self.actual["database_sha256_after_read"])

    def test_sqlite_is_two_isolated_synthetic_observations(self) -> None:
        self.assertEqual(self.sqlite["row_counts"]["observations"], 2)
        self.assertTrue(self.sqlite["read_only_hash_unchanged"])
        self.assertTrue(self.sqlite["evidence_database_copy_matches"])
        self.assertEqual([row["before_coupon_price_twd"] for row in self.sqlite["observations"]], [1000, 950])
        self.assertEqual([row["user_reported_coupon_price_twd"] for row in self.sqlite["observations"]], [900, None])
        self.assertTrue(all(row["confirmed_after_coupon_price_twd"] is None for row in self.sqlite["observations"]))
        self.assertTrue(all(row["platform_verified"] == 0 for row in self.sqlite["observations"]))

    def test_safety_and_capture_evidence(self) -> None:
        self.assertEqual(self.actual["external_request_count"], 0)
        self.assertEqual(len(self.actual["captures"]), 9)
        self.assertTrue(all(not item["horizontal_overflow"] for item in self.actual["captures"]))
        self.assertTrue(all(item["cta_disabled"] and item["external_links"] == 0 for item in self.actual["search_results"]))

    def test_exact_input_integrity(self) -> None:
        expected = {
            "A14": "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160",
            "B15_REV2": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
            "G10": "9efa1ba175e6579a210af092c3e35c7b44c1e60cb69d400fd0b4b3c2bfd91b14",
        }
        for key, sha in expected.items():
            item = self.inputs["inputs"][key]
            self.assertEqual(item["sha256"], sha)
            self.assertEqual(item["crc"], "PASS")
            for count in ("mismatch", "missing", "undeclared", "duplicates", "case_collisions", "unsafe_paths", "symlinks"):
                self.assertEqual(item[count], 0)


if __name__ == "__main__":
    unittest.main()
