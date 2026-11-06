from __future__ import annotations

import unittest

from tools.web_security_d06.targets import verify_target
from tests.web.security_d06.helpers import A07, A07_SHA, A08, A08_SHA, B08, B08_SHA, B09, B09_SHA


class TargetTests(unittest.TestCase):
    def test_a07_exact_hash_crc_and_manifest_payloads(self) -> None:
        value = verify_target(A07, expected_sha256=A07_SHA)
        self.assertTrue(value.crc_pass)
        self.assertTrue(value.safe_paths)
        self.assertTrue(value.no_symlinks)
        self.assertTrue(value.no_casefold_duplicates)
        self.assertEqual(value.manifest_payload_count, 64)
        self.assertEqual(value.manifest_mismatch_count, 0)
        self.assertEqual(value.manifest_missing_count, 0)
        self.assertEqual(value.manifest_undeclared, ("CDH_A07_001_REVIEW/input_contract/MANIFEST.json",))

    def test_b08_exact_hash_crc_and_manifest_payloads(self) -> None:
        value = verify_target(B08, expected_sha256=B08_SHA)
        self.assertTrue(value.crc_pass)
        self.assertTrue(value.safe_paths)
        self.assertTrue(value.no_symlinks)
        self.assertTrue(value.no_casefold_duplicates)
        self.assertEqual(value.manifest_payload_count, 37)
        self.assertEqual(value.manifest_mismatch_count, 0)
        self.assertEqual(value.manifest_missing_count, 0)
        self.assertEqual(value.manifest_undeclared_count, 0)

    def test_a08_exact_hash_crc_and_manifest_payloads(self) -> None:
        value = verify_target(A08, expected_sha256=A08_SHA)
        self.assertTrue(value.crc_pass)
        self.assertEqual(value.manifest_payload_count, 75)
        self.assertEqual(value.manifest_mismatch_count, 0)
        self.assertEqual(value.manifest_missing_count, 0)
        self.assertEqual(value.manifest_undeclared_count, 0)

    def test_b09_exact_hash_crc_and_manifest_payloads(self) -> None:
        value = verify_target(B09, expected_sha256=B09_SHA)
        self.assertTrue(value.crc_pass)
        self.assertEqual(value.manifest_payload_count, 39)
        self.assertEqual(value.manifest_mismatch_count, 0)
        self.assertEqual(value.manifest_missing_count, 0)
        self.assertEqual(value.manifest_undeclared_count, 0)


if __name__ == "__main__":
    unittest.main()
