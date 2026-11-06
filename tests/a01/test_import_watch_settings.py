from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from a01_app.importers import import_csv
from a01_app.settings import SettingsStore
from a01_app.watchlist import WatchlistStore


NOW = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)


class ImportWatchSettingsTests(unittest.TestCase):
    def test_csv_rows_are_isolated_and_blank_not_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / "data.csv"; inbox = root / "inbox"
            source.write_text("product_title,displayed_price_twd,observed_at_utc,url\nGood,0,2026-11-02T13:00:00Z,\nBlank,,2026-11-02T13:00:00Z,\n", encoding="utf-8")
            results = import_csv(source, inbox, now=NOW)
            self.assertEqual([r.status for r in results], ["IMPORTED", "REJECTED"])
            self.assertEqual(len(list(inbox.glob("submission_*.json"))), 1)

    def test_csv_formula_injection_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / "data.csv"
            source.write_text("product_title,displayed_price_twd,observed_at_utc,url\n=cmd,5,2026-11-02T13:00:00Z,\n", encoding="utf-8")
            result = import_csv(source, root / "inbox", now=NOW)
            self.assertEqual(result[0].status, "REJECTED"); self.assertIn("公式", result[0].detail)

    def test_csv_invalid_utf8_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.csv"; path.write_bytes(b"\xff\xfe\x00")
            with self.assertRaisesRegex(ValueError, "UTF-8"): import_csv(path, Path(temporary) / "inbox", now=NOW)

    def test_t08_watchlist_is_local_preview_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = WatchlistStore(Path(temporary) / "watchlist.json")
            entry = store.add("Example", "100")
            self.assertEqual(entry["scope"], "A01_PREVIEW_ONLY_NOT_CORE_POLICY")
            self.assertEqual(store.list()[0]["target_total_twd"], 100)

    def test_watchlist_persists_on_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "watchlist.json"
            first = WatchlistStore(path); first.add("Persistent", "42")
            second = WatchlistStore(path)
            self.assertEqual(second.list()[0]["title"], "Persistent")

    def test_settings_user_declared_is_not_confirmed(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SettingsStore(Path(temporary) / "settings.json")
            data = store.save(wow_active=True, paid_shipping_threshold=25)
            self.assertEqual(data["wow_membership"], "USER_DECLARED_ACTIVE")
            self.assertEqual(data["first_purchase_eligibility"], "UNKNOWN")
            self.assertEqual(data["scope"], "A01_PREVIEW_ONLY_NOT_CORE_POLICY")

    def test_settings_persist(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            SettingsStore(path).save(wow_active=True, paid_shipping_threshold=None)
            self.assertEqual(SettingsStore(path).load()["wow_membership"], "USER_DECLARED_ACTIVE")
