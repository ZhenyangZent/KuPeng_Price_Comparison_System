from __future__ import annotations

import unittest

from tools.web_security_d06.targets import verify_target
from tools.web_security_d08.r07_evidence import DETAIL_SHA256, SEARCH_SHA256, load_r07_evidence
from tests.web.security_d08.helpers import A09, A09_SHA, B10, B10_SHA, F05, F05_SHA, R07


class IdentityAndEvidenceTests(unittest.TestCase):
    def test_a09_exact_archive(self) -> None:
        value = verify_target(A09, expected_sha256=A09_SHA)
        self.assertEqual(value.manifest_payload_count, 98)
        self.assertEqual((value.manifest_mismatch_count, value.manifest_missing_count, value.manifest_undeclared_count), (0, 0, 0))

    def test_b10_exact_archive(self) -> None:
        value = verify_target(B10, expected_sha256=B10_SHA)
        self.assertEqual(value.manifest_payload_count, 51)
        self.assertEqual((value.manifest_mismatch_count, value.manifest_missing_count, value.manifest_undeclared_count), (0, 0, 0))

    def test_f05_exact_archive_and_auxiliary_sums(self) -> None:
        value = verify_target(F05, expected_sha256=F05_SHA)
        self.assertEqual(value.manifest_payload_count, 46)
        self.assertEqual((value.manifest_mismatch_count, value.manifest_missing_count), (0, 0))
        self.assertEqual(value.manifest_undeclared, ("CDH_F_R06_001_REVIEW/SHA256SUMS.txt",))

    def test_r07_bundle_and_evidence_hashes(self) -> None:
        value = load_r07_evidence(R07)
        self.assertEqual(value["identity"]["payloads"], 20)
        self.assertEqual(value["search_sha256"], SEARCH_SHA256)
        self.assertEqual(value["detail_sha256"], DETAIL_SHA256)


if __name__ == "__main__":
    unittest.main()
