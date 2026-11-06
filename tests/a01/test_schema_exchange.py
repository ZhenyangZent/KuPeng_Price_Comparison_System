from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from a01_app.exchange import DuplicateSubmissionError, build_submission, safe_write_submission
from a01_app.schema import ValidationError, parse_money_text, safe_product_url, validate_submission


NOW = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)


class SchemaExchangeTests(unittest.TestCase):
    def test_t01_blank_is_not_zero(self):
        with self.assertRaises(ValidationError): parse_money_text("")

    def test_t01_null_is_not_zero(self):
        with self.assertRaises(ValidationError): parse_money_text(None)

    def test_t01_nan_is_not_zero(self):
        for value in ("NaN", "Infinity", "1.0", "-1"):
            with self.subTest(value=value), self.assertRaises(ValidationError): parse_money_text(value)

    def test_t01_explicit_zero_is_allowed(self):
        self.assertEqual(parse_money_text("0"), 0)

    def test_t02_defaults_are_unknown(self):
        record = build_submission(product_title="Example", displayed_price_twd=0, observed_at=NOW, created_at=NOW)
        self.assertEqual(record["offer"]["shipping_status"], "UNKNOWN")
        self.assertIsNone(record["offer"]["shipping_fee_twd"])
        self.assertEqual(record["offer"]["account_eligibility_status"], "UNKNOWN")

    def test_t03_synthetic_namespace_is_bound(self):
        record = build_submission(product_title="Synthetic", displayed_price_twd=5, observed_at=NOW, created_at=NOW, is_synthetic=True)
        self.assertEqual(record["source"]["source_kind"], "SYNTHETIC_TEST")
        record["is_synthetic"] = False
        with self.assertRaises(ValidationError): validate_submission(record, now=NOW)

    def test_t04_unique_atomic_write_and_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            inbox = Path(temporary)
            record = build_submission(product_title="Example", displayed_price_twd=0, observed_at=NOW, created_at=NOW)
            path, digest = safe_write_submission(inbox, record)
            self.assertTrue(path.is_file()); self.assertEqual(len(digest), 64)
            before = path.read_bytes()
            with self.assertRaises(DuplicateSubmissionError): safe_write_submission(inbox, record)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(inbox.glob("*.tmp")), [])

    def test_t07_executable_and_private_urls_rejected(self):
        for url in ("javascript:alert(1)", "http://127.0.0.1/x", "http://10.0.0.1/x", "https://example.com/x"):
            with self.subTest(url=url), self.assertRaises(ValidationError): safe_product_url(url)

    def test_valid_coupang_url_is_only_stored(self):
        self.assertEqual(safe_product_url("https://www.tw.coupang.com/vp/products/EXAMPLE"), "https://www.tw.coupang.com/vp/products/EXAMPLE")

    def test_noncanonical_uuid_rejected(self):
        record = build_submission(product_title="Example", displayed_price_twd=1, observed_at=NOW, created_at=NOW)
        record["submission_id"] = str(uuid.uuid4()).upper()
        with self.assertRaises(ValidationError): validate_submission(record, now=NOW)

    def test_unknown_shipping_cannot_have_numeric_fee(self):
        record = build_submission(product_title="Example", displayed_price_twd=1, observed_at=NOW, created_at=NOW)
        record["offer"]["shipping_fee_twd"] = 0
        with self.assertRaises(ValidationError): validate_submission(record, now=NOW)

    def test_user_file_permission_is_bound(self):
        record = build_submission(product_title="CSV", displayed_price_twd=1, observed_at=NOW, created_at=NOW, source_kind="USER_FILE")
        self.assertEqual(record["source"]["permission_scope"], "USER_PROVIDED_ONLY")

    def test_payload_is_valid_utf8_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            record = build_submission(product_title="中文商品", displayed_price_twd=9, observed_at=NOW, created_at=NOW)
            path, _ = safe_write_submission(Path(temporary), record)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["offer"]["product_title"], "中文商品")
