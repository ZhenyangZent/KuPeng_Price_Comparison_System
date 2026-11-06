from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from a01_app.d04_report import read_d04_report


ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = ROOT / "experiments/A04/test_tmp"


class D04ReadOnlyReportTests(unittest.TestCase):
    def setUp(self):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="d04-", dir=TEST_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "latest.json"

    def test_missing_is_explicitly_not_enabled(self):
        status = read_d04_report(self.path)
        self.assertEqual(status.state, "NOT_ENABLED")
        self.assertEqual(status.detail, "歷史報表尚未啟用")

    def test_valid_proposal_contract_is_read_only(self):
        self.path.write_text(json.dumps({"contract": "CDH-D04-PRICE-HISTORY-1", "source_status": "SOURCE_BLOCKED", "generated_at": "2026-11-04T10:00:00Z", "items": [{"title": "synthetic"}]}), encoding="utf-8")
        before = self.path.read_bytes()
        status = read_d04_report(self.path)
        self.assertEqual((status.state, status.item_count), ("READY", 1))
        self.assertEqual(self.path.read_bytes(), before)

    def test_authority_upgrade_and_bad_contract_are_rejected(self):
        for contract, source, expected in (("CDH-D04-PRICE-HISTORY-2", "SOURCE_BLOCKED", "INCOMPATIBLE"), ("CDH-D04-PRICE-HISTORY-1", "APPROVED", "INVALID")):
            with self.subTest(contract=contract, source=source):
                self.path.write_text(json.dumps({"contract": contract, "source_status": source, "generated_at": "2026-11-04T10:00:00Z", "items": []}), encoding="utf-8")
                self.assertEqual(read_d04_report(self.path).state, expected)


if __name__ == "__main__":
    unittest.main()
