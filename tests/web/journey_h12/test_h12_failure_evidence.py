from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
H12 = ROOT / "review" / "H12"


class H12FailureEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = json.loads((H12 / "INPUT_READBACK.json").read_text(encoding="utf-8"))
        cls.stage = json.loads((H12 / "STAGED_PROJECT.json").read_text(encoding="utf-8"))
        cls.attempt1 = json.loads((H12 / "evidence" / "ACTUAL_H12_BROWSER_HTTP_ATTEMPT1_UNDOCUMENTED_DEPENDENCY_FAIL.json").read_text(encoding="utf-8"))
        cls.attempt2 = json.loads((H12 / "evidence" / "ACTUAL_H12_BROWSER_HTTP.json").read_text(encoding="utf-8"))
        cls.negative = json.loads((H12 / "evidence" / "LAUNCHER_NEGATIVE_TESTS.json").read_text(encoding="utf-8"))
        cls.analysis = json.loads((H12 / "evidence" / "FIRST_USE_FAILURE_ANALYSIS.json").read_text(encoding="utf-8"))

    def test_exact_a16_manifest_and_crc(self) -> None:
        self.assertEqual(self.inputs["a16"]["sha256"], "3c6d329cebdda9f8d269f3740952f897b6c95e932d0e04fef4a625defe0fc37e")
        self.assertEqual(self.inputs["a16"]["crc"], "PASS")
        self.assertEqual(self.inputs["a16"]["manifest_payloads"], 117)
        self.assertEqual(sum(self.inputs["a16"][key] for key in ("mismatch", "undeclared", "missing", "duplicates", "case_collisions")), 0)

    def test_clean_stage_has_no_h_loader(self) -> None:
        self.assertEqual(self.stage["h_test_loader_file_count"], 0)
        self.assertEqual(self.stage["nested_dependency_zip_execution_count"], 0)

    def test_undocumented_dependency_failure_is_preserved(self) -> None:
        self.assertEqual(self.attempt1["status"], "FAIL")
        self.assertIn("CDH_B_R09_001_REVIEW.zip", self.attempt1["error"])

    def test_start_ready_only_after_four_exact_transitive_releases(self) -> None:
        self.assertTrue(self.analysis["gates"]["start_reached_ready_after_exact_transitive_inputs"])
        self.assertEqual(self.analysis["defects"][0]["missing_exact_releases"].keys(), {
            "CDH_B_R09_001_REVIEW.zip", "CDH_B_R10_001_REVIEW.zip", "CDH_C_R10_002_REVIEW.zip", "CDH_A_R11_004_REVIEW.zip"
        })

    def test_root_status_cmd_failure_is_preserved(self) -> None:
        receipt = self.attempt2["launcher_receipts"][1]
        self.assertEqual(receipt["entry"], "Status-CDH-MVP.cmd")
        self.assertEqual(receipt["exit_code"], 9009)
        self.assertEqual(receipt["payload"]["status"], "FAILED")

    def test_all_root_cmd_files_are_lf_only(self) -> None:
        for item in self.analysis["defects"][1]["line_endings"].values():
            self.assertEqual(item["crlf_count"], 0)
            self.assertGreater(item["bare_lf_count"], 0)

    def test_missing_dependency_and_occupied_port_fail_closed(self) -> None:
        self.assertTrue(self.analysis["gates"]["missing_dependency_fail_closed"])
        self.assertTrue(self.analysis["gates"]["occupied_port_fail_closed"])
        self.assertEqual(self.negative["unknown_process_termination_count"], 0)

    def test_server_stopped_after_failure(self) -> None:
        self.assertTrue(self.analysis["gates"]["server_stopped_after_failure"])

    def test_no_database_or_browser_activity(self) -> None:
        self.assertTrue(self.analysis["gates"]["no_private_database_created"])
        self.assertTrue(self.analysis["gates"]["chrome_not_started"])
        self.assertEqual(self.analysis["formal_database_write_count"], 0)
        self.assertEqual(self.analysis["isolated_database_write_count"], 0)

    def test_terminal_classification_and_owner(self) -> None:
        self.assertEqual(self.analysis["status"], "FAIL_A16_FIRST_USE_BLOCKERS")
        self.assertEqual(self.analysis["responsible_workline"], "A")
        self.assertFalse(self.analysis["stronger_model_required"])


if __name__ == "__main__":
    unittest.main()
