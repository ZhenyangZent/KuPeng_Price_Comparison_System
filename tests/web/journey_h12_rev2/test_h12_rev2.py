from __future__ import annotations

import hashlib
import json
import socket
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
H12 = ROOT / "review" / "H12_REV2"
EVIDENCE = H12 / "evidence"
PROJECT = H12 / "runtime" / "project"
EXPECTED_A16 = "8eba2b5059c92fcd71897ee345527c78741ebe6c3230c45eab87dd4921b339e4"
EXPECTED_B16 = "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class H12Rev2EvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.input = read_json(H12 / "INPUT_READBACK.json")
        cls.stage = read_json(H12 / "STAGED_PROJECT.json")
        cls.negative = read_json(EVIDENCE / "LAUNCHER_NEGATIVE_TESTS.json")
        cls.browser = read_json(EVIDENCE / "ACTUAL_H12_REV2_BROWSER_HTTP.json")
        cls.attempt1 = read_json(H12 / "attempt1_selector_fail" / "ACTUAL_H12_REV2_BROWSER_HTTP.json")
        cls.sqlite = read_json(EVIDENCE / "SQLITE_READONLY_EVIDENCE.json")

    def test_01_exact_a16_integrity(self) -> None:
        self.assertEqual(self.input["status"], "PASS")
        self.assertEqual(self.input["a16"]["sha256"], EXPECTED_A16)
        self.assertEqual(self.input["a16"]["crc"], "PASS")
        self.assertEqual(self.input["a16"]["manifest_payloads"], 53)
        self.assertEqual(sum(self.input["a16"][key] for key in ("mismatch", "undeclared", "missing", "duplicates", "case_collisions")), 0)

    def test_02_eight_pinned_dependencies_and_no_h_loader(self) -> None:
        self.assertEqual(len(self.input["pinned_releases"]), 8)
        self.assertEqual(self.input["pinned_releases"]["CDH_B_R12_003_REVIEW.zip"], EXPECTED_B16)
        self.assertEqual(self.stage["pinned_release_count"], 8)
        self.assertEqual(self.stage["h_test_loader_file_count"], 0)
        self.assertEqual(self.stage["nested_dependency_zip_execution_count"], 0)

    def test_03_root_cmd_is_crlf(self) -> None:
        for name in ("Start-CDH-MVP.cmd", "Status-CDH-MVP.cmd", "Stop-CDH-MVP.cmd"):
            data = (PROJECT / name).read_bytes()
            self.assertIn(b"\r\n", data)
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""))

    def test_04_launcher_negative_cases(self) -> None:
        self.assertEqual(self.negative["status"], "PASS")
        self.assertTrue(self.negative["missing_dependency_gate"])
        self.assertTrue(self.negative["occupied_port_gate"])
        self.assertEqual(self.negative["unknown_process_termination_count"], 0)

    def test_05_attempt1_selector_failure_preserved(self) -> None:
        self.assertEqual(self.attempt1["status"], "FAIL")
        self.assertIn("Timed out waiting for manual confirmation", self.attempt1["error"])
        self.assertEqual(self.attempt1["browser_test_exit_code"], 1)

    def test_06_actual_browser_terminal_failure_is_preserved(self) -> None:
        self.assertEqual(self.browser["status"], "FAIL")
        self.assertEqual(self.browser["browser_test_exit_code"], 1)
        self.assertEqual(self.browser["chrome_process_exit_code"], 0)
        self.assertFalse(self.browser["gates"]["first_use_controls_and_classification"])

    def test_07_all_other_product_gates_pass(self) -> None:
        failed = [name for name, passed in self.browser["gates"].items() if not passed]
        self.assertEqual(failed, ["first_use_controls_and_classification"])
        self.assertEqual(sum(bool(value) for value in self.browser["gates"].values()), 16)

    def test_08_formal_root_cmd_start_status_stop(self) -> None:
        receipts = self.browser["launcher_receipts"]
        self.assertEqual([item["action"] for item in receipts], ["start", "status", "stop", "status", "start", "status", "stop", "status"])
        self.assertTrue(all(item["exit_code"] == 0 and item["stderr"] == "" for item in receipts))
        self.assertTrue(all(item["entry"].endswith("-CDH-MVP.cmd") for item in receipts))

    def test_09_health_is_exact_b16_rev3(self) -> None:
        self.assertEqual(self.browser["health"]["b16_r12_sha256"], EXPECTED_B16)
        self.assertEqual(self.browser["health"]["b16_revision"], "REV3")
        self.assertEqual(self.browser["integration"], "A16_REV2_ROOT_CMD_FIRST_USE_TO_B16_REV3")
        self.assertFalse(self.browser["h_test_loader_used"])

    def test_10_import_and_manual_counts(self) -> None:
        self.assertEqual([self.browser[key] for key in ("rows_after_csv", "rows_after_json", "rows_after_replay", "rows_after_manual")], [2, 4, 4, 5])
        self.assertTrue(self.browser["gates"]["invalid_422_clear_no_write"])
        self.assertTrue(self.browser["gates"]["duplicate_confirm_idempotent"])
        self.assertTrue(self.browser["gates"]["manual_preview_confirm"])

    def test_11_restart_and_read_only_query(self) -> None:
        self.assertEqual(self.browser["website_restart_count"], 1)
        self.assertEqual(self.browser["browser_post_after_restart_count"], 0)
        self.assertEqual(self.browser["rows_before_read"], self.browser["rows_after_read"])
        self.assertEqual(self.browser["database_sha256_before_read"], self.browser["database_sha256_after_read"])

    def test_12_private_history_tracks(self) -> None:
        for key in ("csv_detail", "json_detail"):
            detail = self.browser[key]
            self.assertEqual([row["price"] for row in detail["before_raw"]], [1000, 950])
            self.assertEqual([row["price"] for row in detail["reported_raw"]], [900])
            self.assertEqual(detail["confirmed_raw"], [])
            self.assertTrue(detail["confirmed_empty"] and detail["not_verified"] and detail["cta_disabled"])
        self.assertEqual([row["price"] for row in self.browser["manual_detail"]["before_raw"]], [1200])
        self.assertEqual([row["price"] for row in self.browser["manual_detail"]["reported_raw"]], [1000])

    def test_13_sqlite_is_synthetic_private_and_unverified(self) -> None:
        self.assertTrue(self.sqlite["read_only_hash_unchanged"])
        self.assertTrue(self.sqlite["evidence_database_copy_matches"])
        self.assertEqual(self.sqlite["row_counts"]["observations"], 5)
        self.assertTrue(all(row["confirmed_after_coupon_price_twd"] is None and row["platform_verified"] == 0 for row in self.sqlite["observations"]))
        self.assertTrue(all(row["source_class"] == "USER_ENTERED" and row["visibility"] == "PRIVATE_LOCAL" for row in self.sqlite["observations"]))

    def test_14_mobile_and_narrow_no_overflow(self) -> None:
        captures = {item["name"]: item for item in self.browser["captures"]}
        self.assertEqual(captures["01-mobile-first-use"]["viewport_width"], 390)
        self.assertEqual(captures["02-narrow-first-use"]["viewport_width"], 700)
        self.assertFalse(captures["01-mobile-first-use"]["horizontal_overflow"])
        self.assertFalse(captures["02-narrow-first-use"]["horizontal_overflow"])

    def test_15_no_external_or_formal_actions(self) -> None:
        self.assertEqual(self.browser["external_request_count"], 0)
        self.assertEqual(self.browser["formal_database_write_count"], 0)
        self.assertTrue(self.browser["gates"]["no_console_exceptions"])

    def test_16_failure_is_initial_affiliate_assertion_timing(self) -> None:
        classification = self.browser["classification"]
        self.assertEqual(classification["cards"], 3)
        self.assertTrue(all(classification[key] for key in ("synthetic_search", "manual", "batch", "private_history")))
        self.assertFalse(classification["affiliate_disabled"])
        self.assertTrue(all(self.browser[key]["cta_disabled"] for key in ("csv_detail", "json_detail", "manual_detail")))

    def test_17_server_is_stopped(self) -> None:
        self.assertFalse((PROJECT / "data" / "local_mvp" / "state" / "active.json").exists())
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", 12337)), 0)


if __name__ == "__main__":
    unittest.main()
