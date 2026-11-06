from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "private_observation_b15"))

from private_observation_b15.api import PendingPreviews, PrivateObservationApp  # noqa: E402
from private_observation_b15.baselines import EXPECTED, verify_baselines  # noqa: E402
from private_observation_b15.store import ObservationStore, StoreConflict, StoreError  # noqa: E402
from private_observation_b15.validation import ValidationError, parse_and_validate  # noqa: E402


NOW = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)
BASELINE_ROOT = Path(os.environ.get("CDH_B15_BASELINE_ROOT", ROOT / "review" / "releases"))


def observation(*, submission="SUB-B15-0001", observed="2026-11-03T12:00:00+08:00", before=1000, reported=900, shipping="UNKNOWN"):
    has_coupon = reported is not None
    return {
        "schema_version": "CDH-B15-MANUAL-OBSERVATION-1",
        "submission_id": submission,
        "title": "Synthetic private test product",
        "identity": {"platform": "COUPANG_TW", "product_id": "PROD-B15-001", "sku_id": "SKU-B15-RED", "seller_id": "SELLER-B15", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD"},
        "observed_at": observed,
        "quantity": 1,
        "before_coupon_price_twd": before,
        "user_reported_coupon": {
            "status": "USER_REPORTED" if has_coupon else "NONE",
            "price_twd": reported,
            "eligibility": "USER_ASSERTED_ELIGIBLE" if has_coupon else "UNKNOWN",
            "evidence_level": "USER_DESCRIPTION" if has_coupon else "NONE",
            "evidence_note": "Synthetic local description" if has_coupon else None,
            "valid_from": "2026-11-01T00:00:00+08:00" if has_coupon else None,
            "valid_until": "2026-11-30T23:59:59+08:00" if has_coupon else None,
        },
        "shipping": {"status": shipping, "shipping_fee_twd": 60 if shipping == "KNOWN" else None, "mandatory_fee_twd": 10 if shipping == "KNOWN" else None},
        "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "Typed manually for a private synthetic test"},
    }


def raw(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def request(app, path, *, method="GET", body=None, headers=None):
    headers = headers or {}
    body_bytes = b"" if body is None else (body if isinstance(body, bytes) else raw(body))
    path_info, _, query = path.partition("?")
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path_info, "QUERY_STRING": query, "wsgi.input": io.BytesIO(body_bytes), "CONTENT_LENGTH": str(len(body_bytes)), "CONTENT_TYPE": headers.pop("Content-Type", "application/json"), "HTTP_HOST": "127.0.0.1"}
    for name, value in headers.items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = int(status.split()[0]); captured["headers"] = dict(response_headers)

    output = b"".join(app(environ, start_response))
    return captured["status"], json.loads(output) if output else None, captured["headers"]


class B15Tests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "review" / "B15" / "tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix="case-", dir=base))
        self.store = ObservationStore(self.temp / "private-data", allowed_project_root=self.temp, clock=lambda: NOW)
        self.baselines = verify_baselines(BASELINE_ROOT)
        self.app = PrivateObservationApp(self.store, baselines=self.baselines, clock=lambda: NOW, csrf_token="csrf-test-token", allowed_origins=("http://127.0.0.1:4173",))

    def tearDown(self):
        shutil.rmtree(self.temp)

    def preview(self, value=None):
        status, body, _ = request(self.app, "/api/private-observations/v1/preview", method="POST", body=observation() if value is None else value, headers={"X-CDH-CSRF-Token": "csrf-test-token"})
        self.assertEqual(status, 200)
        return body

    def confirm(self, preview):
        return request(self.app, "/api/private-observations/v1/confirm", method="POST", body={"preview_id": preview["preview_id"], "confirm_token": preview["confirm_token"], "explicit_confirm": True}, headers={"X-CDH-CSRF-Token": "csrf-test-token"})

    def test_exact_baselines(self):
        self.assertEqual(self.baselines, {role: digest for role, (_name, digest) in EXPECTED.items()})

    def test_preview_does_not_create_database(self):
        result = self.preview()
        self.assertEqual(result["database_write_count"], 0)
        self.assertFalse(self.store.database.exists())
        self.assertEqual(result["will_save"]["confirmed_after_coupon_price_twd"], None)

    def test_explicit_confirm_creates_isolated_database(self):
        status, body, _ = self.confirm(self.preview())
        self.assertEqual(status, 201)
        self.assertEqual(body["status"], "SAVED_PRIVATE_LOCAL")
        self.assertTrue(self.store.database.is_file())
        self.assertEqual(self.store.observation_count(), 1)

    def test_confirm_false_or_missing_is_rejected_without_write(self):
        preview = self.preview()
        status, body, _ = request(self.app, "/api/private-observations/v1/confirm", method="POST", body={"preview_id": preview["preview_id"], "confirm_token": preview["confirm_token"], "explicit_confirm": False}, headers={"X-CDH-CSRF-Token": "csrf-test-token"})
        self.assertEqual((status, body["error"]["code"]), (400, "EXPLICIT_CONFIRM_REQUIRED"))
        self.assertFalse(self.store.database.exists())

    def test_two_dates_search_detail_raw_and_daily(self):
        first = self.preview(observation())
        self.assertEqual(self.confirm(first)[0], 201)
        second_value = observation(submission="SUB-B15-0002", observed="2026-11-04T12:00:00+08:00", before=950, reported=None)
        second = self.preview(second_value)
        self.assertEqual(self.confirm(second)[0], 201)
        status, search, _ = request(self.app, "/api/private-observations/v1/products?q=PROD-B15")
        self.assertEqual((status, search["total"]), (200, 1))
        self.assertEqual(search["items"][0]["data_classification"], "PRIVATE_LOCAL_USER_ENTERED")
        series = search["items"][0]["series_key"]
        status, detail, _ = request(self.app, "/api/private-observations/v1/products/" + series)
        self.assertEqual(status, 200)
        self.assertEqual([item["price_twd"] for item in detail["history"]["before_coupon"]], [1000, 950])
        self.assertEqual(detail["history"]["confirmed_after_coupon"], [])
        self.assertEqual([item["price_twd"] for item in detail["history"]["user_reported_after_coupon"]], [900])
        self.assertEqual([item["taipei_date"] for item in detail["history_quality"]["before_coupon"]["daily_representatives"]], ["2026-11-03", "2026-11-04"])

    def test_unknown_shipping_keeps_totals_null(self):
        value = self.preview()["will_save"]
        self.assertIsNone(value["required_total_twd"])
        self.assertIsNone(value["user_reported_required_total_twd"])

    def test_known_shipping_computes_separate_totals(self):
        value = self.preview(observation(shipping="KNOWN"))["will_save"]
        self.assertEqual((value["required_total_twd"], value["user_reported_required_total_twd"]), (1070, 970))

    def test_same_submission_replay_is_idempotent(self):
        first = self.preview(); first_status, first_body, _ = self.confirm(first)
        second = self.preview(); second_status, second_body, _ = self.confirm(second)
        self.assertEqual((first_status, second_status), (201, 200))
        self.assertEqual(first_body["observation_id"], second_body["observation_id"])
        self.assertTrue(second_body["idempotent_replay"])
        self.assertEqual(self.store.observation_count(), 1)

    def test_different_submission_same_content_is_idempotent_by_fingerprint(self):
        self.assertEqual(self.confirm(self.preview())[0], 201)
        value = observation(submission="SUB-B15-9999")
        status, body, _ = self.confirm(self.preview(value))
        self.assertEqual(status, 200)
        self.assertTrue(body["idempotent_replay"])
        self.assertEqual(self.store.observation_count(), 1)

    def test_submission_id_content_conflict(self):
        self.assertEqual(self.confirm(self.preview())[0], 201)
        changed = observation(before=999)
        status, body, _ = self.confirm(self.preview(changed))
        self.assertEqual((status, body["error"]["code"]), (409, "SUBMISSION_ID_CONTENT_CONFLICT"))
        self.assertEqual(self.store.observation_count(), 1)

    def test_duplicate_json_is_rejected_before_write(self):
        duplicate = b'{"schema_version":"A","schema_version":"B"}'
        status, body, _ = request(self.app, "/api/private-observations/v1/preview", method="POST", body=duplicate, headers={"X-CDH-CSRF-Token": "csrf-test-token"})
        self.assertEqual((status, body["error"]["code"]), (400, "JSON_DUPLICATE_KEY"))
        self.assertEqual(body["error"]["input_sha256"], hashlib.sha256(duplicate).hexdigest())
        self.assertFalse(self.store.database.exists())

    def test_nested_duplicate_json_is_rejected(self):
        value = raw(observation()).decode("utf-8").replace('"sku_id":"SKU-B15-RED"', '"sku_id":"A","sku_id":"B"')
        status, body, _ = request(self.app, "/api/private-observations/v1/preview", method="POST", body=value.encode(), headers={"X-CDH-CSRF-Token": "csrf-test-token"})
        self.assertEqual((status, body["error"]["code"]), (400, "JSON_DUPLICATE_KEY"))

    def test_user_file_source_is_rejected(self):
        value = observation(); value["source"]["source_class"] = "USER_FILE"
        status, body, _ = request(self.app, "/api/private-observations/v1/preview", method="POST", body=value, headers={"X-CDH-CSRF-Token": "csrf-test-token"})
        self.assertEqual((status, body["error"]["code"]), (400, "SOURCE_CLASS_NOT_ALLOWED"))

    def test_url_xss_and_sql_text_are_rejected(self):
        cases = []
        url = observation(); url["source"]["note"] = "https://example.invalid"
        xss = observation(); xss["title"] = "<script>alert(1)</script>"
        sql = observation(); sql["identity"]["product_id"] = "X' OR 1=1--"
        cases.extend((url, xss, sql))
        for value in cases:
            with self.subTest(value=value):
                status, _, _ = request(self.app, "/api/private-observations/v1/preview", method="POST", body=value, headers={"X-CDH-CSRF-Token": "csrf-test-token"})
                self.assertEqual(status, 400)

    def test_oversized_body_is_rejected(self):
        value = b" " * (128 * 1024 + 1)
        status, body, _ = request(self.app, "/api/private-observations/v1/preview", method="POST", body=value, headers={"X-CDH-CSRF-Token": "csrf-test-token"})
        self.assertEqual((status, body["error"]["code"]), (400, "REQUEST_BODY_TOO_LARGE"))

    def test_csrf_host_origin_and_content_type(self):
        self.assertEqual(request(self.app, "/api/private-observations/v1/preview", method="POST", body=observation())[0], 403)
        self.assertEqual(request(self.app, "/api/private-observations/v1/session", headers={"Host": "evil.invalid"})[0], 400)
        self.assertEqual(request(self.app, "/api/private-observations/v1/session", headers={"Origin": "https://evil.invalid"})[0], 403)
        self.assertEqual(request(self.app, "/api/private-observations/v1/preview", method="POST", body=observation(), headers={"X-CDH-CSRF-Token": "csrf-test-token", "Content-Type": "text/plain"})[0], 400)

    def test_missing_host_is_rejected(self):
        status, body, _ = request(self.app, "/api/private-observations/v1/session", headers={"Host": ""})
        self.assertEqual((status, body["error"]["code"]), (400, "HOST_REQUIRED"))

    def test_allowed_origin_and_preflight(self):
        status, _, headers = request(self.app, "/api/private-observations/v1/session", headers={"Origin": "http://127.0.0.1:4173"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://127.0.0.1:4173")
        self.assertEqual(request(self.app, "/api/private-observations/v1/session", method="OPTIONS", headers={"Origin": "http://127.0.0.1:4173"})[0], 204)

    def test_invalid_or_expired_confirmation_token(self):
        preview = self.preview()
        status, _, _ = request(self.app, "/api/private-observations/v1/confirm", method="POST", body={"preview_id": preview["preview_id"], "confirm_token": "wrong", "explicit_confirm": True}, headers={"X-CDH-CSRF-Token": "csrf-test-token"})
        self.assertEqual(status, 400)
        self.assertFalse(self.store.database.exists())
        monotonic = [10.0]
        pending = PendingPreviews(ttl_seconds=1, clock=lambda: monotonic[0])
        app = PrivateObservationApp(self.store, baselines=self.baselines, clock=lambda: NOW, csrf_token="csrf-test-token", pending=pending)
        status, body, _ = request(app, "/api/private-observations/v1/preview", method="POST", body=observation(), headers={"X-CDH-CSRF-Token": "csrf-test-token"})
        self.assertEqual(status, 200); monotonic[0] = 12.0
        self.assertEqual(request(app, "/api/private-observations/v1/confirm", method="POST", body={"preview_id": body["preview_id"], "confirm_token": body["confirm_token"], "explicit_confirm": True}, headers={"X-CDH-CSRF-Token": "csrf-test-token"})[0], 400)

    def test_second_new_commit_creates_integrity_checked_backup(self):
        self.assertEqual(self.confirm(self.preview())[0], 201)
        second = observation(submission="SUB-B15-0002", observed="2026-11-04T12:00:00+08:00", before=950, reported=None)
        status, body, _ = self.confirm(self.preview(second))
        self.assertEqual(status, 201)
        self.assertTrue(body["backup_created"])
        backups = list(self.store.backup_root.glob("*.sqlite3"))
        self.assertEqual(len(backups), 1)
        connection = sqlite3.connect(backups[0]); self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok"); connection.close()
        connection = sqlite3.connect(backups[0]); self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1); connection.close()

    def test_transaction_failure_rolls_back_observation_and_audit(self):
        self.assertEqual(self.confirm(self.preview())[0], 201)
        connection = sqlite3.connect(self.store.database)
        connection.execute("CREATE TRIGGER fail_b15 BEFORE INSERT ON observations WHEN NEW.submission_id='SUB-FAIL-0001' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        connection.commit(); connection.close()
        value = parse_and_validate(raw(observation(submission="SUB-FAIL-0001", observed="2026-11-04T12:00:00+08:00")), now=NOW)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.commit(value)
        self.assertEqual(self.store.observation_count(), 1)
        connection = sqlite3.connect(self.store.database)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM commit_audit").fetchone()[0], 1)
        connection.close()

    def test_missing_database_readback_is_empty(self):
        self.assertEqual(self.store.search(""), {"schema_version": "CDH-PRIVATE-PRICE-V1", "data_classification": "PRIVATE_LOCAL_USER_ENTERED", "items": [], "page": 1, "limit": 20, "total": 0, "data_version": '"private-empty"'})
        self.assertFalse(self.store.database.exists())

    def test_request_cannot_select_database_path(self):
        value = observation(); value["database_path"] = "C:/outside.sqlite3"
        status, body, _ = request(self.app, "/api/private-observations/v1/preview", method="POST", body=value, headers={"X-CDH-CSRF-Token": "csrf-test-token"})
        self.assertEqual((status, body["error"]["code"]), (400, "TOP_LEVEL_FIELDS_MISMATCH"))
        with self.assertRaises(Exception):
            ObservationStore(self.temp, allowed_project_root=self.temp, database_name="../outside.sqlite3")

    def test_data_root_must_be_below_explicit_project_root(self):
        outside = self.temp.parent / (self.temp.name + "-outside")
        with self.assertRaises(Exception):
            ObservationStore(outside, allowed_project_root=self.temp)

    def test_preview_retention_is_bounded_and_expired_items_are_swept(self):
        tick = [1.0]
        pending = PendingPreviews(ttl_seconds=1, clock=lambda: tick[0], max_items=2, max_total_bytes=100_000)
        normalized = parse_and_validate(raw(observation()), now=NOW)
        pending.create(normalized); pending.create(normalized)
        with self.assertRaises(ValidationError) as raised:
            pending.create(normalized)
        self.assertEqual(raised.exception.code, "PREVIEW_CAPACITY_EXCEEDED")
        tick[0] = 3.0
        self.assertEqual(pending.retained_count(), 0)

    def test_backup_retention_count_is_bounded(self):
        store = ObservationStore(self.temp / "bounded", allowed_project_root=self.temp, clock=lambda: NOW, max_backups=3, min_backups_to_keep=2)
        for index in range(5):
            value = observation(submission=f"SUB-BOUND-{index:04d}", observed=f"2026-11-0{index + 1}T01:00:00+08:00", before=1000 - index, reported=None)
            store.commit(parse_and_validate(raw(value), now=NOW))
        backups = list(store.backup_root.glob("*.sqlite3"))
        self.assertLessEqual(len(backups), 3)
        self.assertGreaterEqual(len(backups), 2)

    def test_backup_capacity_limit_fails_closed_before_new_commit(self):
        store = ObservationStore(self.temp / "capacity", allowed_project_root=self.temp, clock=lambda: NOW, max_backups=2, min_backups_to_keep=1, max_backup_bytes=1)
        first = parse_and_validate(raw(observation(submission="SUB-CAP-0001", reported=None)), now=NOW)
        second = parse_and_validate(raw(observation(submission="SUB-CAP-0002", observed="2026-11-04T01:00:00+08:00", reported=None)), now=NOW)
        store.commit(first)
        with self.assertRaises(StoreError):
            store.commit(second)
        self.assertEqual(store.observation_count(), 1)
        self.assertEqual(list(store.backup_root.glob("*.sqlite3")), [])

    def test_historical_releases_remain_unchanged(self):
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (BASELINE_ROOT / "CDH_B_R10_001_REVIEW.zip", BASELINE_ROOT / "CDH_C_R10_002_REVIEW.zip", BASELINE_ROOT / "CDH_B_R07_001_REVIEW.zip")}
        self.confirm(self.preview())
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before})


if __name__ == "__main__":
    unittest.main()
