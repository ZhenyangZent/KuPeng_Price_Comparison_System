from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from a01_app.display import money_text, shipping_text, snapshot_rows
from a01_app.snapshot import SnapshotCache, read_snapshot


NOW = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)


def fixture(generated="2026-11-02T13:01:00Z"):
    return {
        "schema_version": "CDH-EXCHANGE-1", "snapshot_generated_at_utc": generated, "source": "D01_LOCAL_LEDGER",
        "counts": {"total_entries": 2, "real_observations": 1, "synthetic_observations": 1, "unverified_leads": 0},
        "items": [
            {"submission_id":"2d3e3329-78c0-4bd3-aef3-3d8c36576502","record_type":"USER_PRICE_OBSERVATION","observed_at_utc":"2026-11-02T12:58:00Z","product_title":"Synthetic","displayed_price_twd":5,"is_synthetic":True,"qualification_state":"UNVERIFIED","source_kind":"SYNTHETIC_TEST","source_url":None},
            {"submission_id":"3d3e3329-78c0-4bd3-aef3-3d8c36576503","record_type":"USER_PRICE_OBSERVATION","observed_at_utc":"2026-11-02T12:59:00Z","product_title":"User entry","displayed_price_twd":0,"is_synthetic":False,"qualification_state":"UNVERIFIED","source_kind":"USER_ENTERED","source_url":None},
        ],
        "source_status": {"live_coupang_discovery":"SOURCE_BLOCKED","permission_checked_at_utc":None},
    }


class SnapshotDisplayTests(unittest.TestCase):
    def _write(self, folder: Path, value) -> Path:
        path = folder / "latest.json"; path.write_text(json.dumps(value), encoding="utf-8"); return path

    def test_t01_display_null_not_zero(self):
        self.assertEqual(money_text(None), "未知"); self.assertEqual(money_text(0), "NT$ 0")

    def test_t02_unknown_shipping_not_confirmed(self):
        self.assertIn("未確認", shipping_text({"shipping_status":"UNKNOWN","shipping_fee_twd":None}))

    def test_t03_synthetic_is_visibly_marked_and_filterable(self):
        rows = snapshot_rows(fixture(), include_synthetic=True)
        self.assertEqual({row["synthetic"] for row in rows}, {"合成測試", "使用者觀測"})
        filtered = snapshot_rows(fixture(), include_synthetic=False)
        self.assertEqual(len(filtered), 1); self.assertEqual(filtered[0]["synthetic"], "使用者觀測")

    def test_t05_missing_snapshot_waits(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = read_snapshot(Path(temporary) / "missing.json", now=NOW)
            self.assertEqual(result.state, "WAITING"); self.assertIsNone(result.data)

    def test_t05_corrupt_snapshot_faults_without_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "latest.json"; path.write_text("{", encoding="utf-8")
            result = read_snapshot(path, now=NOW)
            self.assertEqual(result.state, "FAULT"); self.assertIsNone(result.data)

    def test_t06_older_snapshot_does_not_replace_newer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            newer = read_snapshot(self._write(root, fixture("2026-11-02T13:01:00Z")), now=NOW)
            older = read_snapshot(self._write(root, fixture("2026-11-02T12:01:00Z")), now=NOW)
            cache = SnapshotCache(); self.assertTrue(cache.accept(newer)); self.assertFalse(cache.accept(older))
            self.assertEqual(cache.current.generated_at, newer.generated_at)

    def test_equal_snapshot_does_not_replace(self):
        with tempfile.TemporaryDirectory() as temporary:
            value = read_snapshot(self._write(Path(temporary), fixture()), now=NOW)
            cache = SnapshotCache(); self.assertTrue(cache.accept(value)); self.assertFalse(cache.accept(value))

    def test_stale_snapshot_marked(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = read_snapshot(self._write(Path(temporary), fixture("2026-10-30T13:01:00Z")), now=NOW)
            self.assertEqual(result.state, "STALE"); self.assertTrue(result.stale)

    def test_future_snapshot_faults(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = read_snapshot(self._write(Path(temporary), fixture("2026-11-02T15:01:00Z")), now=NOW)
            self.assertEqual(result.state, "FAULT")

    def test_source_must_remain_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            value = fixture(); value["source_status"]["live_coupang_discovery"] = "AVAILABLE"
            self.assertEqual(read_snapshot(self._write(Path(temporary), value), now=NOW).state, "FAULT")

    def test_snapshot_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "latest.json"
            with path.open("wb") as stream: stream.truncate(50 * 1024 * 1024 + 1)
            self.assertEqual(read_snapshot(path, now=NOW).state, "FAULT")
