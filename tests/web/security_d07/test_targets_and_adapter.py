from __future__ import annotations

import unittest

from tools.web_security_d06.targets import verify_target
from tools.web_security_d07.adapter_flow import run_exact_a08_b09_002_flow
from tests.web.security_d07.helpers import A08, A08_SHA, B09_002, B09_002_SHA


class TargetIdentityTests(unittest.TestCase):
    def test_a08_exact_archive(self) -> None:
        value = verify_target(A08, expected_sha256=A08_SHA)
        self.assertTrue(value.crc_pass)
        self.assertTrue(value.safe_paths)
        self.assertTrue(value.no_symlinks)
        self.assertTrue(value.no_casefold_duplicates)
        self.assertEqual(value.manifest_payload_count, 75)
        self.assertEqual(value.manifest_mismatch_count, 0)
        self.assertEqual(value.manifest_missing_count, 0)
        self.assertEqual(value.manifest_undeclared_count, 0)

    def test_b09_002_exact_archive(self) -> None:
        value = verify_target(B09_002, expected_sha256=B09_002_SHA)
        self.assertTrue(value.crc_pass)
        self.assertTrue(value.safe_paths)
        self.assertTrue(value.no_symlinks)
        self.assertTrue(value.no_casefold_duplicates)
        self.assertEqual(value.manifest_payload_count, 40)
        self.assertEqual(value.manifest_mismatch_count, 0)
        self.assertEqual(value.manifest_missing_count, 0)
        self.assertEqual(value.manifest_undeclared_count, 0)


class ExactAdapterFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_exact_a08_b09_002_flow(A08, B09_002)

    def test_exact_frontend_parser_accepts_all_v2_calls(self) -> None:
        self.assertEqual(self.result["parser_call_count"], 9)
        self.assertEqual(self.result["parser_success_count"], 9)
        self.assertEqual(self.result["parser_failure_count"], 0)

    def test_v2_raw_min_remains_separate_from_v3_daily_low(self) -> None:
        self.assertEqual(self.result["v2_raw_history_prices"], [10, 20, 30])
        self.assertEqual(self.result["v2_raw_min_twd"], 10)
        self.assertEqual(self.result["v2_reported_min_twd"], 10)
        self.assertEqual(self.result["v3_daily_representative_low_twd"], 20)

    def test_real_adapter_fixture_is_synthetic_and_cta_closed(self) -> None:
        detail = self.result["synthetic_v2_detail"]
        self.assertEqual(detail["data_classification"], "SYNTHETIC_DEMO_ONLY")
        self.assertEqual(detail["affiliate"]["state"], "UNCONFIGURED")
        self.assertIsNone(detail["affiliate"]["click_url"])


if __name__ == "__main__":
    unittest.main()
