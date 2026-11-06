from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[3]
RUNTIME = PROJECT / "review" / "H03" / "runtime"


class H03ContractReproductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads((RUNTIME / "B08_CASES.json").read_text(encoding="utf-8"))
        cls.result = json.loads((RUNTIME / "A07_B08_CONTRACT_RESULTS.json").read_text(encoding="utf-8"))

    def test_exact_nine_call_reproduction(self) -> None:
        self.assertEqual(self.result["counts"], {"total": 9, "pass": 6, "fail": 3})
        self.assertTrue(self.result["central_reproduction_match"])
        self.assertEqual(self.result["product_integration_gate"], "FAIL")

    def test_unavailable_is_null_and_not_zero(self) -> None:
        case = next(item for item in self.cases["cases"] if item["case"] == "unavailable")
        self.assertIsNone(case["search"]["items"][0]["last_observed_price_twd"])
        self.assertEqual(case["search"]["items"][0]["price_basis"], "UNAVAILABLE")
        self.assertEqual(case["detail"]["history"], [])

    def test_raw_min_and_daily_low_are_distinct(self) -> None:
        case = next(item for item in self.cases["cases"] if item["case"] == "raw_min_mismatch")
        self.assertEqual(case["derived"]["raw_history_min_twd"], 10)
        self.assertEqual(case["derived"]["v2_observation_period_min_twd"], 20)
        self.assertEqual(case["derived"]["v3_daily_period_low_twd"], 20)

    def test_all_fixture_data_is_synthetic(self) -> None:
        self.assertEqual(self.cases["authority"], "AUTHORIZED_SYNTHETIC_OFFLINE_ONLY")
        for case in self.cases["cases"]:
            self.assertTrue(case["test_only"])
            self.assertEqual(case["search"]["data_classification"], "SYNTHETIC_DEMO_ONLY")


if __name__ == "__main__":
    unittest.main()
