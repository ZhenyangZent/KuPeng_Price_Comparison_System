from __future__ import annotations

import unittest

from tests.web.security_d08.helpers import gate_result


class ExactRejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = gate_result()

    def test_actual_b10_matches_central_search_and_detail(self) -> None:
        self.assertEqual(self.result["central_evidence_match"], {"search_without_data_version": True, "detail_without_data_version": True})

    def test_a09_reproduces_two_exact_error_classes(self) -> None:
        results = self.result["a09_parser"]["results"]
        self.assertEqual([item["code"] for item in results], ["V4_VERSION_MISMATCH", "INVALID_V4_PAYLOAD", "V4_VERSION_MISMATCH", "INVALID_V4_PAYLOAD"])
        self.assertTrue(all(not item["success"] for item in results))

    def test_f05_rejects_all_real_wire_shapes(self) -> None:
        results = self.result["f05_parser"]["results"]
        self.assertEqual([item["code"] for item in results], ["V4_STRUCTURE_INVALID"] * 4)
        self.assertTrue(all(not item["success"] for item in results))

    def test_a09_ui_is_fixture_not_http_integration(self) -> None:
        self.assertTrue(self.result["a09_parser"]["fixture_only_ui"])

    def test_expected_p1_findings_are_precisely_classified(self) -> None:
        self.assertEqual(self.result["priority_counts"], {"P0": 0, "P1": 3, "P2": 1})
        self.assertEqual([item["finding_id"] for item in self.result["findings"]], ["D08-P1-001", "D08-P1-002", "D08-P1-003", "D08-P2-001"])


if __name__ == "__main__":
    unittest.main()
