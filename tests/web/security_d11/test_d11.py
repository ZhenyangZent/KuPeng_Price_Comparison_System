from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tools.web_security_d11.archive import A11_SHA256, B14_SHA256, verify_a11, verify_b14
from tools.web_security_d11.audit import run
from tools.web_security_d11.duplicate_json import DUPLICATE_MUTATIONS, DuplicateKeyError, strict_json_loads

ROOT = Path(__file__).resolve().parents[3]


class DuplicateJsonOracleTests(unittest.TestCase):
    def test_all_mutations_are_rejected_after_decoding(self) -> None:
        for name, payload in DUPLICATE_MUTATIONS.items():
            with self.subTest(name=name), self.assertRaises(DuplicateKeyError):
                strict_json_loads(payload)

    def test_unique_nested_document_is_accepted(self) -> None:
        self.assertEqual(strict_json_loads('[{"identity":{"sku_id":"SYN-A"}}]')[0]["identity"]["sku_id"], "SYN-A")


class ExactInputTests(unittest.TestCase):
    def test_a11_exact_archive_and_manifest(self) -> None:
        result = verify_a11(ROOT / "review/releases/CDH_A_R09_001_REVIEW.zip")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["zip_sha256"], A11_SHA256)
        self.assertTrue(result["manifest_coverage_pass"])

    def test_integrated_audit(self) -> None:
        result = run(ROOT)
        self.assertTrue(all(item["status"] == "PASS" for item in result["targets"].values()))
        self.assertEqual(result["a11_runtime_security"]["status"], "PASS")
        self.assertEqual(result["a11_source_and_evidence"]["daily_source_and_dist_gate"], "PASS")
        self.assertEqual(result["a11_source_and_evidence"]["daily_browser_dom_gate"], "NOT_RUN_BROWSER_EVIDENCE_INSUFFICIENT")
        self.assertEqual(result["a11_source_and_evidence"]["unknown_key_gate"], "P2_OPEN_UNKNOWN_FIELDS_IGNORED")
        self.assertFalse(result["a11_source_and_evidence"]["external_anchor_present"])
        self.assertTrue(result["a11_source_and_evidence"]["cta_disabled"])
        self.assertEqual(result["b14_status"], "PASS_SCOPED")

    def test_b14_exact_archive_and_manifest(self) -> None:
        result = verify_b14(ROOT / "review/releases/CDH_B_R10_001_REVIEW.zip")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["zip_sha256"], B14_SHA256)
        self.assertEqual(result["manifest_sha256"], "99a697f76f00b7f0822ccb0c490f56305ac1d53a7b584247a897b78fb55b145b")


class B14IndependentMutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        service = ROOT / "review/D11/input_b14/CDH_B_R10_001_REVIEW/services/import_staging_b14"
        sys.path.insert(0, str(service))
        from import_staging_b14.preview import StrictIngressError, strict_json_records  # type: ignore
        cls.error = StrictIngressError
        cls.strict_json_records = staticmethod(strict_json_records)

    def test_exact_b14_rejects_all_independent_duplicate_mutations(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "review/D11") as directory:
            root = Path(directory)
            for index, (name, payload) in enumerate(DUPLICATE_MUTATIONS.items()):
                with self.subTest(name=name):
                    target = root / f"{index}.json"
                    target.write_text(payload, encoding="utf-8")
                    with self.assertRaises(self.error) as raised:
                        self.strict_json_records(target)
                    self.assertEqual(raised.exception.code, "JSON_DUPLICATE_KEY")
                    self.assertNotIn("sku", str(raised.exception).casefold())

    def test_exact_b14_allows_case_distinct_keys_then_leaves_semantics_downstream(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "review/D11") as directory:
            target = Path(directory) / "case.json"
            target.write_text('[{"sku_id":"A","SKU_ID":"B"}]', encoding="utf-8")
            records, _ = self.strict_json_records(target)
        self.assertEqual(records, [{"sku_id": "A", "SKU_ID": "B"}])


class B13BaselineRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        service = ROOT / "review/D11/input_b13/CDH_B_R09_001_REVIEW/services/import_staging_b12"
        sys.path.insert(0, str(service))
        from import_staging_b12.staging import load_records  # type: ignore
        cls.load_records = staticmethod(load_records)

    def test_b13_reproduces_last_value_wins_for_nested_unicode_collision(self) -> None:
        payload = b'[{"identity":{"sku_id":"SYN-A","sku_\\u0069d":"SYN-B"}}]'
        with tempfile.TemporaryDirectory(dir=ROOT / "review/D11") as directory:
            root = Path(directory)
            target = root / "input.json"
            target.write_bytes(payload)
            records, _ = self.load_records(target, allowed_root=root, input_format="json")
        self.assertEqual(records[0]["identity"]["sku_id"], "SYN-B")

    def test_b13_reproduces_last_value_wins_for_same_and_different_values(self) -> None:
        for payload, expected in ((b'[{"record_id":"A","record_id":"A"}]', "A"), (b'[{"record_id":"A","record_id":"B"}]', "B")):
            with tempfile.TemporaryDirectory(dir=ROOT / "review/D11") as directory:
                root = Path(directory)
                target = root / "input.json"
                target.write_bytes(payload)
                records, _ = self.load_records(target, allowed_root=root, input_format="json")
            self.assertEqual(records[0]["record_id"], expected)


if __name__ == "__main__":
    unittest.main()
