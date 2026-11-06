from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = ROOT / "experiments/A04/test_tmp"
sys.path.insert(0, str(ROOT / "apps/a01/tools"))

from a04_d03_e2e import execute


class ActualFrozenD03CliTests(unittest.TestCase):
    def test_full_daily_cycle_and_negative_recovery_paths(self):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        base = Path(tempfile.mkdtemp(prefix="actual-cli-", dir=TEST_ROOT))
        result = execute(base / "run")
        self.assertTrue(result["pass"], result["gates"])
        self.assertEqual(result["steps"]["execute"]["stdout"]["counts"]["imported"], 1)
        self.assertEqual(result["steps"]["verify"]["stdout"]["source_status"], "SOURCE_BLOCKED")


if __name__ == "__main__":
    unittest.main()
