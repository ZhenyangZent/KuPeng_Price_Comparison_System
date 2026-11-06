from __future__ import annotations

import hashlib
import json
import socket
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
H12 = ROOT / "review" / "H12_REV3"
EVIDENCE = H12 / "evidence"
PROJECT = H12 / "runtime" / "project"
EXPECTED_A16 = "8eba2b5059c92fcd71897ee345527c78741ebe6c3230c45eab87dd4921b339e4"
EXPECTED_B16 = "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7"
EXPECTED_H12_REV2 = "df490f54ff4315e2c4171248464040e02ce2eef58265d1e5c3f88e4854294b80"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class H12Rev3EvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.input = read_json(H12 / "INPUT_READBACK.json")
        cls.stage = read_json(H12 / "STAGED_PROJECT.json")
        cls.targeted = read_json(EVIDENCE / "TARGETED_AFFILIATE_GATE.json")
        cls.combined = read_json(EVIDENCE / "COMBINED_GATE_EVIDENCE.json")

    def test_01_exact_inputs(self) -> None:
        self.assertEqual(self.input["a16"]["sha256"], EXPECTED_A16)
        self.assertEqual(self.input["pinned_releases"]["CDH_B_R12_003_REVIEW.zip"], EXPECTED_B16)
        self.assertEqual(sha256(ROOT / "review" / "releases" / "CDH_H_R12_004_REVIEW.zip"), EXPECTED_H12_REV2)

    def test_02_a16_integrity_and_clean_stage(self) -> None:
        self.assertEqual(self.input["status"], "PASS")
        self.assertEqual(self.input["a16"]["crc"], "PASS")
        self.assertEqual(self.input["a16"]["manifest_payloads"], 53)
        self.assertEqual(sum(self.input["a16"][key] for key in ("mismatch", "undeclared", "missing", "duplicates", "case_collisions")), 0)
        self.assertEqual(self.stage["h_test_loader_file_count"], 0)
        self.assertEqual(self.stage["pinned_release_count"], 8)

    def test_03_targeted_scope_only(self) -> None:
        self.assertEqual(self.targeted["scope"], "TARGETED_FIRST_USE_CONTROLS_AND_CLASSIFICATION_ONLY")
        self.assertFalse(self.targeted["single_run_full_17_gate_claimed"])
        self.assertEqual(self.targeted["prior_h12_rev2_browser_test_exit_code"], 1)

    def test_04_targeted_browser_passed(self) -> None:
        self.assertEqual(self.targeted["status"], "PASS")
        self.assertEqual(self.targeted["targeted_browser_test_exit_code"], 0)
        self.assertEqual(self.targeted["chrome_process_exit_code"], 0)
        self.assertEqual(self.targeted["targeted_gate_pass_count"], self.targeted["targeted_gate_count"])

    def test_05_required_apis_and_classification_ready(self) -> None:
        self.assertTrue(self.targeted["gates"]["classification_and_required_api_ready"])
        self.assertEqual(self.targeted["final_state"]["classification_cards"], 3)
        for label in ("SYNTHETIC DEMO", "PRIVATE USER-REPORTED", "PLATFORM CONFIRMED"):
            self.assertIn(label, self.targeted["final_state"]["classification_text"])

    def test_06_no_actionable_affiliate_during_load(self) -> None:
        self.assertGreater(self.targeted["load_sample_count"], 0)
        self.assertEqual(self.targeted["actionable_during_load_count"], 0)
        self.assertTrue(self.targeted["gates"]["no_actionable_affiliate_during_load"])
        self.assertTrue(all(sample["enabled_affiliate_button_count"] == 0 and sample["affiliate_anchor_count"] == 0 and sample["external_anchor_count"] == 0 for sample in self.targeted["load_samples"]))

    def test_07_explicit_cta_exists_and_is_disabled(self) -> None:
        final = self.targeted["final_state"]
        self.assertGreater(final["affiliate_card_count"], 0)
        self.assertGreater(final["cta_count"], 0)
        self.assertTrue(final["cta_disabled"])
        self.assertEqual(final["enabled_affiliate_button_count"], 0)
        self.assertEqual(final["cta_text"], "正式連結尚未核准")

    def test_08_no_external_affiliate_link_or_request(self) -> None:
        self.assertEqual(self.targeted["final_state"]["affiliate_anchor_count"], 0)
        self.assertEqual(self.targeted["final_state"]["external_anchor_count"], 0)
        self.assertEqual(self.targeted["external_request_count"], 0)
        self.assertTrue(self.targeted["gates"]["no_trusted_or_external_affiliate_link"])

    def test_09_exact_b16_health(self) -> None:
        self.assertEqual(self.targeted["health"]["b16_r12_sha256"], EXPECTED_B16)
        self.assertEqual(self.targeted["health"]["b16_revision"], "REV3")
        self.assertTrue(self.targeted["gates"]["exact_a16_b16_identity"])

    def test_10_formal_root_cmd_only(self) -> None:
        receipts = self.targeted["launcher_receipts"]
        self.assertEqual([item["action"] for item in receipts], ["start", "status", "stop", "status"])
        self.assertTrue(all(item["exit_code"] == 0 and item["stderr"] == "" for item in receipts))
        self.assertFalse(self.targeted["h_test_loader_used"])

    def test_11_no_private_database_or_console_exception(self) -> None:
        self.assertFalse(self.targeted["private_database_created"])
        self.assertFalse((PROJECT / "data" / "private_user_observations_b15" / "private_user_observations.sqlite3").exists())
        self.assertTrue(self.targeted["gates"]["no_console_exception"])

    def test_12_dom_and_screenshot_exist(self) -> None:
        self.assertTrue((EVIDENCE / "dom" / "01-affiliate-gate-ready.html").is_file())
        self.assertTrue((EVIDENCE / "screenshots" / "01-affiliate-gate-ready.png").is_file())

    def test_13_composite_evidence_is_explicit(self) -> None:
        self.assertEqual(self.combined["status"], "PASS_SCOPED_COMPOSITE_EVIDENCE")
        self.assertFalse(self.combined["single_run_full_17_gate_claimed"])
        self.assertEqual(self.combined["h12_rev2"]["browser_test_exit_code"], 1)
        self.assertEqual(self.combined["h12_rev2"]["passed_gate_count"], 16)
        self.assertEqual(self.combined["h12_rev2"]["failed_gates"], ["first_use_controls_and_classification"])
        self.assertEqual(self.combined["composite_product_gate_pass_count"], 17)
        self.assertEqual(self.combined["composite_product_gate_count"], 17)

    def test_14_server_is_stopped(self) -> None:
        self.assertFalse((PROJECT / "data" / "local_mvp" / "state" / "active.json").exists())
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", 12340)), 0)


if __name__ == "__main__":
    unittest.main()
