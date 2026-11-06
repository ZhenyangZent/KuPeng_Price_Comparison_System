from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from a01_app.importers import import_csv, import_json
from a01_app.manual_history import local_history_rows


ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = ROOT / "experiments/A03/test_runs"
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)


class ManualImportTests(unittest.TestCase):
    def setUp(self):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="a03-import-", dir=TEST_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.inbox = self.root / "data/exchange/inbox"

    def records(self):
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(self.inbox.glob("submission_*.json"))]

    def test_csv_zero_is_unverified_unknown_and_user_file(self):
        source = self.root / "input.csv"
        source.write_text("product_title,displayed_price_twd,observed_at_utc,url,variant_id\nZero,0,2026-11-04T09:00:00Z,,SKU-Z\n", encoding="utf-8")
        result = import_csv(source, self.inbox, now=NOW)
        self.assertEqual(result[0].status, "IMPORTED")
        record = self.records()[0]
        self.assertEqual(record["source"]["source_kind"], "USER_FILE")
        self.assertEqual(record["offer"]["displayed_price_twd"], 0)
        self.assertEqual((record["offer"]["shipping_status"], record["offer"]["shipping_fee_twd"]), ("UNKNOWN", None))
        self.assertEqual(record["offer"]["account_eligibility_status"], "UNKNOWN")

    def test_csv_replay_is_deterministic_duplicate_noop(self):
        source = self.root / "input.csv"
        source.write_text("product_title,displayed_price_twd,observed_at_utc\nSame,7,2026-11-04T09:00:00Z\n", encoding="utf-8")
        first = import_csv(source, self.inbox, now=NOW)
        second = import_csv(source, self.inbox, now=NOW)
        self.assertEqual((first[0].status, second[0].status), ("IMPORTED", "DUPLICATE_NOOP"))
        self.assertEqual(len(self.records()), 1)

    def test_csv_optional_specification_is_preserved(self):
        source = self.root / "input.csv"
        source.write_text("product_title,displayed_price_twd,observed_at_utc,specification\nSpec,15,2026-11-04T09:00:00Z,紅色 2 入\n", encoding="utf-8")
        import_csv(source, self.inbox, now=NOW)
        record = self.records()[0]
        self.assertEqual(record["offer"]["variant_id"], "紅色 2 入")
        self.assertIn("紅色 2 入", record["offer"]["notes"])

    def test_csv_optional_sku_is_bound_to_variant(self):
        source = self.root / "input.csv"
        source.write_text("product_title,displayed_price_twd,observed_at_utc,sku\nSKU,21,2026-11-04T09:00:00Z,SKU-21\n", encoding="utf-8")
        result = import_csv(source, self.inbox, now=NOW)
        self.assertEqual(result[0].status, "IMPORTED")
        self.assertEqual(self.records()[0]["offer"]["variant_id"], "SKU-21")

    def test_json_rows_are_isolated_and_user_file(self):
        source = self.root / "input.json"
        source.write_text(json.dumps([
            {"product_title": "Good", "displayed_price_twd": 9, "observed_at_utc": "2026-11-04T09:00:00Z"},
            {"product_title": "Bad", "displayed_price_twd": None, "observed_at_utc": "2026-11-04T09:00:00Z"},
        ]), encoding="utf-8")
        result = import_json(source, self.inbox, now=NOW)
        self.assertEqual([item.status for item in result], ["IMPORTED", "REJECTED"])
        self.assertEqual(self.records()[0]["source"]["source_kind"], "USER_FILE")

    def test_json_replay_is_duplicate_noop(self):
        source = self.root / "input.json"
        source.write_text(json.dumps({"product_title": "Same", "displayed_price_twd": 7, "observed_at_utc": "2026-11-04T09:00:00Z"}), encoding="utf-8")
        self.assertEqual(import_json(source, self.inbox, now=NOW)[0].status, "IMPORTED")
        self.assertEqual(import_json(source, self.inbox, now=NOW)[0].status, "DUPLICATE_NOOP")

    def test_json_rejects_contract_injection_fields(self):
        source = self.root / "input.json"
        source.write_text(json.dumps({"product_title": "Bad", "displayed_price_twd": 1, "observed_at_utc": "2026-11-04T09:00:00Z", "source_kind": "SYNTHETIC_TEST"}), encoding="utf-8")
        result = import_json(source, self.inbox, now=NOW)
        self.assertEqual(result[0].status, "REJECTED")
        self.assertFalse(self.inbox.exists())

    def test_invalid_utf8_json_is_explicit(self):
        source = self.root / "input.json"; source.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            import_json(source, self.inbox, now=NOW)

    def test_json_nonfinite_number_is_explicit(self):
        source = self.root / "input.json"
        source.write_text('{"product_title":"Bad","displayed_price_twd":NaN,"observed_at_utc":"2026-11-04T09:00:00Z"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "有效 UTF-8"):
            import_json(source, self.inbox, now=NOW)

    def test_history_marks_pending_and_unverified(self):
        source = self.root / "input.json"
        source.write_text(json.dumps({"product_title": "History", "displayed_price_twd": 0, "observed_at_utc": "2026-11-04T09:00:00Z"}), encoding="utf-8")
        import_json(source, self.inbox, now=NOW)
        rows = local_history_rows(self.inbox, None, self.root / "missing-receipt.json")
        self.assertEqual((rows[0].sync_state, rows[0].source_kind), ("等待本地同步", "USER_FILE"))
        self.assertIn("UNVERIFIED", rows[0].verification)
        self.assertIn("運費 UNKNOWN", rows[0].verification)


if __name__ == "__main__":
    unittest.main()
