from __future__ import annotations

import unittest

from tools.web_security_d07.gate import run_gate
from tests.web.security_d07.helpers import A08, B09_002


class GateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_gate(A08, B09_002)

    def test_baseline_is_accepted_with_only_disclosed_p2(self) -> None:
        self.assertEqual(self.result["integration_acceptance"], "PASS_WITH_P2")
        self.assertEqual(self.result["priority_counts"], {"P0": 0, "P1": 0, "P2": 2})

    def test_coupon_matrix_all_passes(self) -> None:
        value = self.result["coupon_cases"]
        self.assertEqual(value["executed"], value["passed"])

    def test_header_before_failures_are_not_hidden(self) -> None:
        self.assertFalse(self.result["baseline_headers"]["frontend"]["passed"])
        self.assertFalse(self.result["baseline_headers"]["backend"]["passed"])

    def test_no_target_mutation_or_live_authority(self) -> None:
        restrictions = self.result["restrictions"]
        self.assertFalse(restrictions["target_code_mutated"])
        self.assertFalse(restrictions["real_env_read"])
        self.assertEqual(restrictions["live_network_count"], 0)
        self.assertEqual(restrictions["affiliate_click_count"], 0)


if __name__ == "__main__":
    unittest.main()
