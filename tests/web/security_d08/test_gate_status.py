from __future__ import annotations

import unittest

from tests.web.security_d08.helpers import gate_result


class GateStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = gate_result()

    def test_harness_execution_passes_with_no_unexpected_failure(self) -> None:
        self.assertEqual(self.result["audit_execution"], "PASS")
        self.assertEqual(self.result["unexpected_failures"], [])

    def test_a10_b11_are_not_claimed_without_inputs(self) -> None:
        self.assertEqual(self.result["candidate_gate"], {
            "a10": "NOT_RUN_INPUT_UNAVAILABLE",
            "b11": "NOT_RUN_INPUT_UNAVAILABLE",
            "exact_pair_integration": "NOT_RUN_INPUT_UNAVAILABLE",
        })

    def test_targets_are_immutable_and_authority_is_offline(self) -> None:
        restrictions = self.result["restrictions"]
        self.assertFalse(restrictions["target_code_mutated"])
        self.assertFalse(restrictions["real_env_read"])
        self.assertEqual(restrictions["live_network_count"], 0)
        self.assertEqual(restrictions["affiliate_click_count"], 0)


if __name__ == "__main__":
    unittest.main()
