from __future__ import annotations

import unittest

from tools.web_contract_audit.targets import verify_target
from tests.web.contract_audit.helpers import RELEASES


class TargetIdentityTests(unittest.TestCase):
    def test_hash_bound_received_targets_are_safe_zip_inputs(self) -> None:
        expected = {
            "CDH_B06_001_REVIEW.zip": "d99284c7e6d422b16255b51d29aacb5034a1d43b254c4aca6fa389cef6caf3ae",
            "CDH_C03_001_REVIEW.zip": "c500af034827fddf376419e1792b5d46d29112eea745cb9bf5a57030d5c7fd76",
            "CDH_F01_001_REVIEW.zip": "cb524e6bc9def5308c04bcfecb07c4be074eb0c852d71fd53a5fb877b95f9154",
        }
        for name, digest in expected.items():
            with self.subTest(name=name):
                identity = verify_target(RELEASES / name, expected_sha256=digest)
                self.assertTrue(identity.crc_pass)
                self.assertTrue(identity.safe_paths)
                self.assertTrue(identity.no_symlinks)
                self.assertTrue(identity.no_casefold_duplicates)


if __name__ == "__main__":
    unittest.main()
