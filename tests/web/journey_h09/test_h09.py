from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
H09 = ROOT / "review" / "H09"
EVIDENCE = H09 / "evidence"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class H09EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = load(H09 / "INPUT_READBACK.json")
        cls.raw = load(EVIDENCE / "ACTUAL_H09_BROWSER_HTTP.json")
        cls.db = load(EVIDENCE / "SQLITE_READONLY_EVIDENCE.json")
        cls.verification = load(EVIDENCE / "H09_VERIFICATION.json")
        cls.negative = cls.raw["negative_results"]
        cls.persistent = cls.negative["persistent_detail"]

    def test_01_exact_a13_b15(self):
        self.assertEqual(self.inputs["inputs"]["A13_REV3"]["sha256"], "d1b8814f0ae54f5fa5fae77c873620fe70da979fcbfe689a333096fab897b274")
        self.assertEqual(self.inputs["inputs"]["B15_REV2"]["sha256"], "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe")

    def test_02_manifests_crc_and_safety(self):
        for item in self.inputs["inputs"].values():
            self.assertEqual(item["crc"], "PASS"); self.assertEqual(item["manifest_mismatch"], 0)
            self.assertEqual(item["unsafe_paths"], 0); self.assertEqual(item["symlinks"], 0)

    def test_03_launcher_restart(self):
        self.assertEqual([item["result"]["status"] for item in self.raw["controls"]], ["READY", "READY", "STOPPED", "READY", "READY", "STOPPED"])

    def test_04_preview_no_write(self):
        self.assertEqual(self.raw["preview1"]["writeCount"], "寫入次數 0")
        self.assertEqual(self.raw["preview2"]["writeCount"], "寫入次數 0")

    def test_05_two_commits(self):
        self.assertTrue(self.raw["commit1"]["saveText"].startswith("已保存至隔離本機觀測庫"))
        self.assertTrue(self.raw["commit2"]["saveText"].startswith("已保存至隔離本機觀測庫"))

    def test_06_two_date_raw_and_daily(self):
        self.assertEqual(self.persistent["before"], [1000, 950])
        self.assertEqual([item["taipei_date"] for item in self.persistent["daily"]], ["2026-11-03", "2026-11-04"])
        self.assertEqual([item["sample_count"] for item in self.persistent["daily"]], [1, 1])

    def test_07_coupon_not_promoted(self):
        self.assertEqual(self.persistent["confirmed"], [])
        self.assertEqual(self.persistent["reported"], [900])

    def test_08_unknown_totals(self):
        self.assertEqual(self.raw["preview1"]["totalText"], "UNKNOWN")
        self.assertIsNone(self.persistent["required_total_twd"])

    def test_09_private_labels(self):
        self.assertEqual(self.negative["persistent_search"]["classification"], "PRIVATE_LOCAL_USER_ENTERED")
        self.assertEqual(self.persistent["source_state"], "PRIVATE_LOCAL_ONLY")

    def test_10_restart_idempotent(self):
        self.assertEqual(self.raw["database_sha256_before_restart"], self.raw["database_sha256_after_idempotent_replay"])
        self.assertTrue(self.raw["restart_replay"]["saveText"].startswith("相同觀測已存在，未重複新增"))

    def test_11_rejections(self):
        self.assertEqual((self.negative["missing_csrf"]["status"], self.negative["missing_csrf"]["code"]), (403, "CSRF_TOKEN_INVALID"))
        self.assertEqual((self.negative["duplicate_json"]["status"], self.negative["duplicate_json"]["code"]), (400, "JSON_DUPLICATE_KEY"))
        self.assertEqual((self.negative["rejected_source"]["status"], self.negative["rejected_source"]["code"]), (400, "SOURCE_CLASS_NOT_ALLOWED"))
        self.assertEqual((self.negative["submission_conflict"]["confirm_status"], self.negative["submission_conflict"]["code"]), (409, "SUBMISSION_ID_CONTENT_CONFLICT"))

    def test_12_cta_disabled(self):
        self.assertFalse(self.persistent["cta_enabled"]); self.assertIsNone(self.persistent["click_url"])

    def test_13_sqlite_evidence(self):
        self.assertTrue(self.db["read_only_hash_unchanged"]); self.assertTrue(self.db["evidence_database_copy_matches"])
        self.assertEqual(self.db["row_counts"]["observations"], 3); self.assertEqual(self.db["h09_main_product_matches"]["observations"], 2)

    def test_14_backups(self):
        self.assertEqual(self.db["backup_count"], 2)

    def test_15_baselines_immutable(self):
        self.assertEqual(self.raw["baseline_before"], self.raw["baseline_after"])
        self.assertEqual(self.raw["formal_database_write_count"], 0)

    def test_16_no_external_network(self):
        self.assertEqual(self.raw["external_request_count"], 0)
        self.assertTrue(all(not item["external_anchors"] for item in self.raw["captures"]))

    def test_17_screenshots(self):
        self.assertEqual(len(self.raw["captures"]), 7)
        for item in self.raw["captures"]:
            data = (ROOT / item["screenshot"]).read_bytes(); self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", data[16:24]); self.assertGreaterEqual(width, 1400); self.assertGreaterEqual(height, 1100)
        self.assertTrue(all(item["width"] == 1440 and item["height"] == 1100 for item in self.raw["captures"]))

    def test_18_final_verification(self):
        self.assertEqual(self.verification["status"], "PASS_COMPLETE_WINDOWS_PRIVATE_OBSERVATION_E2E")
        self.assertTrue(all(self.verification["gates"].values()))


if __name__ == "__main__":
    unittest.main()
