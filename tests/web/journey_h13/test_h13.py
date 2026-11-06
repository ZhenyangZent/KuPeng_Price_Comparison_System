from __future__ import annotations

import hashlib
import json
import socket
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
H13 = ROOT / "review" / "H13"
EVIDENCE = H13 / "evidence"
PROJECT = H13 / "runtime" / "project"
EXPECTED_A17 = "5de6b85e72767e8135b7ff0e6e3acb534965d5f636f61eea918cb082b02a8237"
EXPECTED_RUNTIME = "b75814678c51490cfcb00e60b80f46e7c22e40af95118796bae1f856a6f1a176"
EXPECTED_B11 = "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"
EXPECTED_B15 = "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe"
EXPECTED_B16 = "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class H13EvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.input = read_json(H13 / "INPUT_READBACK.json")
        cls.stage = read_json(H13 / "STAGED_PROJECT.json")
        cls.negative = read_json(EVIDENCE / "LAUNCHER_NEGATIVE_TESTS.json")
        cls.browser = read_json(EVIDENCE / "ACTUAL_H13_BROWSER_HTTP.json")
        cls.attempt1 = read_json(H13 / "attempt1_harness_tdz" / "ACTUAL_H13_BROWSER_HTTP.json")
        cls.reconciliation = read_json(EVIDENCE / "FAILURE_RECONCILIATION.json")
        cls.safety = read_json(EVIDENCE / "A17_SAFETY_SCAN.json")

    def test_01_exact_a17_integrity(self) -> None:
        self.assertEqual(self.input["status"], "PASS")
        self.assertEqual(self.input["a17"]["sha256"], EXPECTED_A17)
        self.assertEqual(self.input["a17"]["crc"], "PASS")
        self.assertEqual(self.input["a17"]["manifest_payloads"], 91)
        self.assertEqual(sum(self.input["a17"][key] for key in ("mismatch", "undeclared", "missing", "duplicates", "case_collisions")), 0)

    def test_02_integrated_runtime_manifest(self) -> None:
        runtime = self.input["runtime"]
        self.assertEqual(runtime["manifest_payloads"], 58)
        self.assertEqual(runtime["manifest_sha256"], EXPECTED_RUNTIME)
        self.assertEqual(runtime["missing"] + runtime["mismatch"] + runtime["undeclared"], 0)
        self.assertEqual(runtime["source_releases"]["B11_R07"]["sha256"], EXPECTED_B11)
        self.assertEqual(runtime["source_releases"]["B15_REV2"]["sha256"], EXPECTED_B15)
        self.assertEqual(runtime["source_releases"]["B16_REV3"]["sha256"], EXPECTED_B16)

    def test_03_no_external_historical_release_dependency(self) -> None:
        self.assertEqual(self.stage["review_releases_dependency_read_count"], 0)
        self.assertEqual(self.stage["external_historical_zip_copy_count"], 0)
        self.assertEqual(self.stage["unexpected_project_review_release_path_count"], 0)
        self.assertEqual(self.stage["bundled_baseline_zip_count"], 6)

    def test_04_root_trial_cmd_crlf(self) -> None:
        for name in ("Start-CDH-Trial.cmd", "Status-CDH-Trial.cmd", "Stop-CDH-Trial.cmd"):
            data = (PROJECT / name).read_bytes()
            self.assertIn(b"\r\n", data)
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""))

    def test_05_launcher_negative_cases(self) -> None:
        self.assertEqual(self.negative["status"], "PASS")
        self.assertTrue(self.negative["missing_runtime_gate"])
        self.assertTrue(self.negative["occupied_port_gate"])
        self.assertEqual(self.negative["unknown_process_termination_count"], 0)

    def test_06_a17_safety_scan(self) -> None:
        self.assertEqual(self.safety["status"], "PASS")
        for key in ("forbidden_name_hits", "secret_pattern_hits", "registry_mutation_pattern_hits", "service_install_pattern_hits", "prepackaged_private_history_payloads"):
            self.assertEqual(self.safety[key], [])

    def test_07_attempt1_harness_failure_preserved(self) -> None:
        self.assertEqual(self.attempt1["status"], "FAIL")
        self.assertEqual(self.attempt1["browser_test_exit_code"], 1)
        self.assertIn("Cannot access 'manualPreview' before initialization", self.attempt1["error"])

    def test_08_actual_browser_failure_preserved(self) -> None:
        self.assertEqual(self.browser["status"], "FAIL")
        self.assertEqual(self.browser["browser_test_exit_code"], 1)
        self.assertIn("timed out waiting for PROD-B16-CSV detail", self.browser["error"])

    def test_09_formal_trial_cmd_and_versions(self) -> None:
        receipts = self.browser["launcher_receipts"]
        self.assertEqual([item["action"] for item in receipts], ["start", "status", "stop", "status", "start", "status"])
        self.assertTrue(all(item["exit_code"] == 0 and item["stderr"] == "" for item in receipts))
        start = receipts[0]["payload"]
        self.assertEqual(start["runtime_bundle_manifest_sha256"], EXPECTED_RUNTIME)
        self.assertEqual(start["b11_r07_sha256"], EXPECTED_B11)
        self.assertEqual(start["b15_r11_rev2_sha256"], EXPECTED_B15)
        self.assertEqual(start["b16_r12_rev3_sha256"], EXPECTED_B16)

    def test_10_successful_http_before_failure(self) -> None:
        pairs = [(item["method"], item["status"], item["url"]) for item in self.browser["network"]]
        self.assertTrue(any(method == "GET" and status == 200 and "api/v4/products?q=already-included" in url for method, status, url in pairs))
        self.assertTrue(any(method == "POST" and status == 201 and url.endswith("/confirm") for method, status, url in pairs))
        self.assertEqual(sum(method == "POST" and status == 201 and url.endswith("/batch-confirm") for method, status, url in pairs), 2)

    def test_11_five_synthetic_private_observations(self) -> None:
        self.assertTrue(self.reconciliation["readonly_inspection_hash_unchanged"])
        self.assertEqual(self.reconciliation["row_counts"]["observations"], 5)
        self.assertEqual({row["product_id"] for row in self.reconciliation["observations"]}, {"PROD-H13-TRIAL", "PROD-B16-CSV", "PROD-B16-EXAMPLE"})
        self.assertTrue(all(row["confirmed_after_coupon_price_twd"] is None and row["platform_verified"] == 0 for row in self.reconciliation["observations"]))
        self.assertTrue(all(row["source_class"] == "USER_ENTERED" and row["visibility"] == "PRIVATE_LOCAL" for row in self.reconciliation["observations"]))

    def test_12_restart_read_path_has_no_post(self) -> None:
        self.assertEqual(self.reconciliation["post_after_restart_count"], 0)
        self.assertEqual(self.browser["launcher_receipts"][2]["payload"]["status"], "STOPPED")
        self.assertEqual(self.browser["launcher_receipts"][4]["payload"]["status"], "READY")

    def test_13_stale_result_race_is_reproducible(self) -> None:
        self.assertEqual(self.reconciliation["status"], "FAIL_H_TEST_STALE_RESULT_RACE")
        self.assertIn("products?q=PROD-B16-CSV", self.reconciliation["csv_search_request"]["url"])
        self.assertTrue(self.reconciliation["stale_manual_detail_hash_observed"])
        self.assertFalse(self.reconciliation["csv_detail_request_observed"])

    def test_14_browser_evidence_and_no_external_request(self) -> None:
        self.assertEqual(len(self.browser["captures"]), 5)
        self.assertEqual(self.browser["console_events"], [])
        external = [item for item in self.browser["network"] if item["url"].startswith(("http:", "https:")) and "127.0.0.1" not in item["url"] and "localhost" not in item["url"]]
        self.assertEqual(external, [])

    def test_15_private_data_location(self) -> None:
        self.assertIn("review/H13/runtime/project/data/A17_private_history", self.reconciliation["database"])
        self.assertTrue((EVIDENCE / "synthetic_A17_private_history.sqlite3").is_file())

    def test_16_server_is_stopped(self) -> None:
        self.assertFalse((PROJECT / "data" / "A17_trial" / "state" / "active.json").exists())
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", 12341)), 0)


if __name__ == "__main__":
    unittest.main()
