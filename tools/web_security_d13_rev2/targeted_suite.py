from __future__ import annotations

import base64
import copy
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
B16 = ROOT / "review" / "D13" / "002" / "input" / "CDH_B_R12_002_REVIEW"
sys.path.insert(0, str(B16 / "services" / "private_batch_import_b16"))
sys.path.insert(0, str(B16 / "services" / "private_observation_b15"))

from private_batch_import_b16.api import BatchImportApp  # noqa: E402
from private_batch_import_b16.parser import FILE_SCHEMA, REQUEST_SCHEMA  # noqa: E402
from private_batch_import_b16.store import BatchObservationStore  # noqa: E402
from private_observation_b15.store import StoreError  # noqa: E402


NOW = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)


def observation(*, submission: str = "SUB-D13-R2-0001", observed: str = "2026-11-03T12:00:00+08:00", before: int = 1000, reported: int | None = 900):
    coupon = reported is not None
    return {
        "schema_version": "CDH-B15-MANUAL-OBSERVATION-1",
        "submission_id": submission,
        "title": "D13 REV2 synthetic product",
        "identity": {"platform": "COUPANG_TW", "product_id": "PROD-D13-R2", "sku_id": "SKU-D13-R2", "seller_id": "SELLER-D13", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD"},
        "observed_at": observed,
        "quantity": 1,
        "before_coupon_price_twd": before,
        "user_reported_coupon": {"status": "USER_REPORTED" if coupon else "NONE", "price_twd": reported, "eligibility": "USER_ASSERTED_ELIGIBLE" if coupon else "UNKNOWN", "evidence_level": "USER_DESCRIPTION" if coupon else "NONE", "evidence_note": "D13 REV2 synthetic" if coupon else None, "valid_from": None, "valid_until": None},
        "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None},
        "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "D13 REV2 synthetic"},
    }


def json_file(items):
    return json.dumps({"schema_version": FILE_SCHEMA, "observations": items}, separators=(",", ":")).encode("utf-8")


def envelope(content: bytes):
    return {"schema_version": REQUEST_SCHEMA, "filename": "observations.json", "media_type": "application/json", "content_base64": base64.b64encode(content).decode("ascii")}


def request(app, path: str, *, method="GET", body=None, csrf=False, host="127.0.0.1", origin=None):
    raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body, separators=(",", ":")).encode("utf-8"))
    path_info, _, query = path.partition("?")
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path_info, "QUERY_STRING": query, "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)), "CONTENT_TYPE": "application/json"}
    if host is not None:
        environ["HTTP_HOST"] = host
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    if csrf:
        environ["HTTP_X_CDH_CSRF_TOKEN"] = app.csrf_token
    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(headers)

    payload = b"".join(app(environ, start_response))
    return captured["status"], json.loads(payload) if payload else None, captured["headers"]


def confirm_body(preview):
    return {"schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": preview["preview_id"], "confirm_token": preview["confirm_token"], "explicit_confirm": True}


class D13Rev2TargetedTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "review" / "D13" / "002" / "tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix="case-", dir=base))
        self.store = BatchObservationStore(self.temp / "private-data", allowed_project_root=self.temp, clock=lambda: NOW)
        self.app = BatchImportApp(self.store, baselines={}, clock=lambda: NOW, csrf_token="csrf-d13-rev2", allowed_origins=("http://127.0.0.1:4173",))
        self.rows = [observation(), observation(submission="SUB-D13-R2-0002", observed="2026-11-04T12:00:00+08:00", before=950, reported=None)]

    def tearDown(self):
        shutil.rmtree(self.temp)

    def preview(self, app=None, rows=None):
        target = app or self.app
        return request(target, "/api/private-observations/v1/batch-preview", method="POST", body=envelope(json_file(rows or self.rows)), csrf=True)

    def confirm(self, preview, app=None):
        target = app or self.app
        return request(target, "/api/private-observations/v1/batch-confirm", method="POST", body=confirm_body(preview), csrf=True)

    def test_01_concurrent_same_token_allows_one_store_entry_and_returns_201_409(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingStore(BatchObservationStore):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.commit_entry_count = 0
                self.entry_lock = threading.Lock()

            def commit_batch(self, records, *, file_sha256, duplicate_input_count):
                with self.entry_lock:
                    self.commit_entry_count += 1
                    number = self.commit_entry_count
                if number == 1:
                    entered.set()
                    if not release.wait(timeout=5):
                        raise RuntimeError("D13 barrier timeout")
                return super().commit_batch(records, file_sha256=file_sha256, duplicate_input_count=duplicate_input_count)

        store = BlockingStore(self.temp / "race-data", allowed_project_root=self.temp, clock=lambda: NOW)
        app = BatchImportApp(store, baselines={}, clock=lambda: NOW, csrf_token="csrf-d13-race")
        preview = self.preview(app=app)[1]
        results = []

        def worker():
            results.append(self.confirm(preview, app=app))

        first = threading.Thread(target=worker, name="d13-first")
        second = threading.Thread(target=worker, name="d13-second")
        first.start()
        self.assertTrue(entered.wait(timeout=5))
        second.start()
        second.join(timeout=3)
        self.assertFalse(second.is_alive(), "second request must be rejected before entering SQLite")
        release.set()
        first.join(timeout=5)
        self.assertFalse(first.is_alive())
        statuses = sorted(item[0] for item in results)
        self.assertEqual(statuses, [201, 409])
        rejected = next(body for status, body, _headers in results if status == 409)
        self.assertEqual(rejected["error"]["code"], "CONFIRMATION_ALREADY_IN_PROGRESS")
        self.assertEqual(store.commit_entry_count, 1)
        self.assertEqual(store.observation_count(), 2)

    def test_02_failed_commit_terminalizes_token_and_fresh_preview_recovers(self):
        class FailingOnceStore(BatchObservationStore):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.insert_calls = 0
                self.failed = False

            def _insert_record(self, connection, normalized, *, batch_id, created):
                self.insert_calls += 1
                if not self.failed and self.insert_calls == 2:
                    self.failed = True
                    raise sqlite3.OperationalError("D13 REV2 injected failure")
                return super()._insert_record(connection, normalized, batch_id=batch_id, created=created)

        store = FailingOnceStore(self.temp / "failure-data", allowed_project_root=self.temp, clock=lambda: NOW)
        app = BatchImportApp(store, baselines={}, clock=lambda: NOW, csrf_token="csrf-d13-failure")
        first_preview = self.preview(app=app)[1]
        status, body, _ = self.confirm(first_preview, app=app)
        self.assertEqual((status, body["error"]["code"]), (500, "PRIVATE_STORE_TRANSACTION_FAILED"))
        status, body, _ = self.confirm(first_preview, app=app)
        self.assertEqual((status, body["error"]["code"]), (409, "CONFIRMATION_FAILED_NEW_PREVIEW_REQUIRED"))
        connection = sqlite3.connect(store.database)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            observations = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] if "observations" in tables else 0
            audits = connection.execute("SELECT COUNT(*) FROM commit_audit").fetchone()[0] if "commit_audit" in tables else 0
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual((observations, audits, integrity), (0, 0, "ok"))
        fresh_status, fresh, _ = self.preview(app=app)
        self.assertEqual(
            fresh_status,
            200,
            f"new preview must recover after transactional rollback; got {fresh}",
        )
        status, body, _ = self.confirm(fresh, app=app)
        self.assertEqual((status, body["inserted_count"], body["idempotent_replay"]), (201, 2, False))
        replay = self.preview(app=app)[1]
        status, body, _ = self.confirm(replay, app=app)
        self.assertEqual((status, body["inserted_count"], body["existing_idempotent_count"], body["idempotent_replay"]), (200, 0, 2, True))
        self.assertEqual(store.observation_count(), 2)

    def test_03_csrf_host_origin_method_and_source_regression(self):
        payload = envelope(json_file(self.rows))
        path = "/api/private-observations/v1/batch-preview"
        self.assertEqual(request(self.app, path, method="POST", body=payload)[0], 403)
        self.assertEqual(request(self.app, path, method="POST", body=payload, csrf=True, host=None)[0], 400)
        self.assertEqual(request(self.app, path, method="POST", body=payload, csrf=True, host="evil.invalid")[0], 400)
        self.assertEqual(request(self.app, path, method="POST", body=payload, csrf=True, origin="https://evil.invalid")[0], 403)
        self.assertEqual(request(self.app, path, method="PUT", body=payload, csrf=True)[0], 405)
        hostile = copy.deepcopy(self.rows)
        hostile[0]["source"]["source_class"] = "PUBLIC_WEB"
        status, body, _ = self.preview(rows=hostile)
        self.assertEqual((status, body["row_errors"][0]["error"]), (422, "SOURCE_CLASS_NOT_ALLOWED"))
        self.assertFalse(self.store.database.exists())

    def test_04_duplicate_json_and_explicit_confirm_regression(self):
        duplicate = b'{"schema_version":"CDH-B16-BATCH-FILE-1","schema_version":"CDH-B16-BATCH-FILE-1","observations":[]}'
        status, body, _ = request(self.app, "/api/private-observations/v1/batch-preview", method="POST", body=envelope(duplicate), csrf=True)
        self.assertEqual((status, body["error"]["code"]), (400, "JSON_DUPLICATE_KEY"))
        preview = self.preview()[1]
        invalid = confirm_body(preview)
        invalid["explicit_confirm"] = False
        status, body, _ = request(self.app, "/api/private-observations/v1/batch-confirm", method="POST", body=invalid, csrf=True)
        self.assertEqual((status, body["error"]["code"]), (400, "EXPLICIT_CONFIRM_REQUIRED"))
        self.assertFalse(self.store.database.exists())

    def test_05_fresh_preview_readback_preserves_private_coupon_identity(self):
        preview = self.preview()[1]
        self.assertEqual(self.confirm(preview)[0], 201)
        restarted_store = BatchObservationStore(self.temp / "private-data", allowed_project_root=self.temp, clock=lambda: NOW)
        restarted = BatchImportApp(restarted_store, baselines={}, clock=lambda: NOW, csrf_token="csrf-restart")
        products = request(restarted, "/api/private-observations/v1/products?q=D13")[1]
        detail = request(restarted, "/api/private-observations/v1/products/" + products["items"][0]["series_key"])[1]
        self.assertEqual(detail["data_classification"], "PRIVATE_LOCAL_USER_ENTERED")
        self.assertEqual(detail["history"]["confirmed_after_coupon"], [])
        self.assertEqual([point["price_twd"] for point in detail["history"]["before_coupon"]], [1000, 950])
        self.assertEqual([point["price_twd"] for point in detail["history"]["user_reported_after_coupon"]], [900])
        self.assertTrue(all(point["platform_verified"] is False for point in detail["history"]["user_reported_after_coupon"]))

    def test_06_lexical_path_escape_remains_rejected(self):
        outside = self.temp.parent / (self.temp.name + "-outside")
        with self.assertRaises(StoreError):
            BatchObservationStore(outside, allowed_project_root=self.temp, clock=lambda: NOW)
        self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
