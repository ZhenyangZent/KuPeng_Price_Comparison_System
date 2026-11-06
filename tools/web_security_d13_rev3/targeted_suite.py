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
B16 = ROOT / "review/D13/003/input/CDH_B_R12_003_REVIEW"
sys.path.insert(0, str(B16 / "services/private_batch_import_b16"))
sys.path.insert(0, str(B16 / "services/private_observation_b15"))
from private_batch_import_b16.api import BatchImportApp  # noqa: E402
from private_batch_import_b16.store import BatchObservationStore  # noqa: E402
from private_observation_b15.store import StoreError  # noqa: E402


NOW = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)


def observation(submission="SUB-D13-R3-1", observed="2026-11-03T12:00:00+08:00", before=1000, reported=900):
    coupon = reported is not None
    return {"schema_version": "CDH-B15-MANUAL-OBSERVATION-1", "submission_id": submission, "title": "D13 REV3 synthetic", "identity": {"platform": "COUPANG_TW", "product_id": "PROD-D13-R3", "sku_id": "SKU-D13-R3", "seller_id": "SELLER-D13", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD"}, "observed_at": observed, "quantity": 1, "before_coupon_price_twd": before, "user_reported_coupon": {"status": "USER_REPORTED" if coupon else "NONE", "price_twd": reported, "eligibility": "USER_ASSERTED_ELIGIBLE" if coupon else "UNKNOWN", "evidence_level": "USER_DESCRIPTION" if coupon else "NONE", "evidence_note": "D13 REV3 synthetic" if coupon else None, "valid_from": None, "valid_until": None}, "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None}, "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "D13 REV3 synthetic"}}


def file_body(rows):
    data = json.dumps({"schema_version": "CDH-B16-BATCH-FILE-1", "observations": rows}, separators=(",", ":")).encode("utf-8")
    return {"schema_version": "CDH-B16-BATCH-PREVIEW-REQUEST-1", "filename": "observations.json", "media_type": "application/json", "content_base64": base64.b64encode(data).decode("ascii")}


def request(app, path, *, method="GET", body=None, csrf=False, host="127.0.0.1", origin=None):
    raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body, separators=(",", ":")).encode("utf-8"))
    path_info, _, query = path.partition("?")
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path_info, "QUERY_STRING": query, "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    if host is not None:
        environ["HTTP_HOST"] = host
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    if csrf:
        environ["HTTP_X_CDH_CSRF_TOKEN"] = app.csrf_token
    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0]); captured["headers"] = dict(headers)

    payload = b"".join(app(environ, start_response))
    return captured["status"], json.loads(payload) if payload else None, captured["headers"]


def confirm(preview):
    return {"schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": preview["preview_id"], "confirm_token": preview["confirm_token"], "explicit_confirm": True}


class D13Rev3Tests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "review/D13/003/tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix="case-", dir=base))
        self.rows = [observation(), observation("SUB-D13-R3-2", "2026-11-04T12:00:00+08:00", 950, None)]

    def tearDown(self):
        shutil.rmtree(self.temp)

    def app(self, store=None):
        target = store or BatchObservationStore(self.temp / "private-data", allowed_project_root=self.temp, clock=lambda: NOW)
        return target, BatchImportApp(target, baselines={}, clock=lambda: NOW, csrf_token="csrf-d13-r3", allowed_origins=("http://127.0.0.1:4173",))

    @staticmethod
    def preview(app, rows):
        return request(app, "/api/private-observations/v1/batch-preview", method="POST", body=file_body(rows), csrf=True)

    @staticmethod
    def save(app, preview):
        return request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=confirm(preview), csrf=True)

    def test_01_first_transaction_failure_retains_schema_and_fresh_preview_recovers(self):
        class FailSecondInsert(BatchObservationStore):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs); self.calls = 0; self.failed = False

            def _insert_record(self, connection, normalized, *, batch_id, created):
                self.calls += 1
                if not self.failed and self.calls == 2:
                    self.failed = True
                    raise sqlite3.OperationalError("D13 REV3 injected second insert failure")
                return super()._insert_record(connection, normalized, batch_id=batch_id, created=created)

        store = FailSecondInsert(self.temp / "first-failure", allowed_project_root=self.temp, clock=lambda: NOW)
        _store, app = self.app(store)
        preview = self.preview(app, self.rows)[1]
        status, body, _ = self.save(app, preview)
        self.assertEqual((status, body["error"]["code"]), (500, "PRIVATE_STORE_TRANSACTION_FAILED"))
        status, body, _ = self.save(app, preview)
        self.assertEqual((status, body["error"]["code"]), (409, "CONFIRMATION_FAILED_NEW_PREVIEW_REQUIRED"))
        connection = sqlite3.connect(store.database)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts = (connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], connection.execute("SELECT COUNT(*) FROM commit_audit").fetchone()[0])
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            connection.close()
        self.assertTrue({"b15_schema", "observations", "commit_audit"}.issubset(tables))
        self.assertEqual((*counts, integrity), (0, 0, "ok"))
        status, fresh, _ = self.preview(app, self.rows)
        self.assertEqual(status, 200)
        status, saved, _ = self.save(app, fresh)
        self.assertEqual((status, saved["inserted_count"]), (201, 2))
        status, replay, _ = self.preview(app, self.rows)
        self.assertEqual(status, 200)
        status, replayed, _ = self.save(app, replay)
        self.assertEqual((status, replayed["inserted_count"], replayed["idempotent_replay"]), (200, 0, True))

    def test_02_existing_database_and_backup_survive_failed_new_batch(self):
        class ToggleFailStore(BatchObservationStore):
            fail = False

            def _insert_record(self, connection, normalized, *, batch_id, created):
                if self.fail:
                    raise sqlite3.OperationalError("D13 REV3 existing DB failure")
                return super()._insert_record(connection, normalized, batch_id=batch_id, created=created)

        store = ToggleFailStore(self.temp / "existing-data", allowed_project_root=self.temp, clock=lambda: NOW)
        _store, app = self.app(store)
        first = self.preview(app, [self.rows[0]])[1]
        self.assertEqual(self.save(app, first)[0], 201)
        connection = sqlite3.connect(store.database)
        original = connection.execute("SELECT submission_id FROM observations").fetchone()[0]
        connection.close()
        store.fail = True
        pending = self.preview(app, [self.rows[1]])[1]
        self.assertEqual(self.save(app, pending)[0], 500)
        self.assertTrue(store.database.is_file())
        backups = list(store.backup_root.glob("*.sqlite3"))
        self.assertGreaterEqual(len(backups), 1)
        connection = sqlite3.connect(store.database)
        self.assertEqual(connection.execute("SELECT submission_id FROM observations").fetchall(), [(original,)])
        self.assertEqual(connection.execute("PRAGMA quick_check").fetchone()[0], "ok")
        connection.close()
        for backup in backups:
            check = sqlite3.connect(backup)
            self.assertEqual(check.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            check.close()

    def test_03_concurrent_token_still_allows_one_store_entry(self):
        entered = threading.Event(); release = threading.Event()

        class BlockingStore(BatchObservationStore):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs); self.entries = 0; self.guard = threading.Lock()

            def commit_batch(self, records, *, file_sha256, duplicate_input_count):
                with self.guard:
                    self.entries += 1; number = self.entries
                if number == 1:
                    entered.set(); release.wait(timeout=5)
                return super().commit_batch(records, file_sha256=file_sha256, duplicate_input_count=duplicate_input_count)

        store = BlockingStore(self.temp / "race", allowed_project_root=self.temp, clock=lambda: NOW)
        _store, app = self.app(store)
        preview = self.preview(app, [self.rows[0]])[1]
        results = []
        worker = lambda: results.append(self.save(app, preview))
        one = threading.Thread(target=worker); two = threading.Thread(target=worker)
        one.start(); self.assertTrue(entered.wait(timeout=5)); two.start(); two.join(timeout=3)
        self.assertFalse(two.is_alive()); release.set(); one.join(timeout=5)
        self.assertEqual(sorted(item[0] for item in results), [201, 409])
        self.assertEqual(store.entries, 1)
        self.assertEqual(store.observation_count(), 1)

    def test_04_csrf_host_origin_source_and_json_boundaries(self):
        store, app = self.app()
        body = file_body(self.rows)
        path = "/api/private-observations/v1/batch-preview"
        self.assertEqual(request(app, path, method="POST", body=body)[0], 403)
        self.assertEqual(request(app, path, method="POST", body=body, csrf=True, host=None)[0], 400)
        self.assertEqual(request(app, path, method="POST", body=body, csrf=True, host="evil.invalid")[0], 400)
        self.assertEqual(request(app, path, method="POST", body=body, csrf=True, origin="https://evil.invalid")[0], 403)
        hostile = copy.deepcopy(self.rows); hostile[0]["source"]["source_class"] = "PUBLIC_WEB"
        self.assertEqual(self.preview(app, hostile)[0], 422)
        duplicate = b'{"schema_version":"CDH-B16-BATCH-FILE-1","schema_version":"CDH-B16-BATCH-FILE-1","observations":[]}'
        duplicate_body = {"schema_version": "CDH-B16-BATCH-PREVIEW-REQUEST-1", "filename": "x.json", "media_type": "application/json", "content_base64": base64.b64encode(duplicate).decode("ascii")}
        self.assertEqual(request(app, path, method="POST", body=duplicate_body, csrf=True)[0], 400)
        self.assertFalse(store.database.exists())

    def test_05_private_coupon_readback_remains_unverified(self):
        store, app = self.app()
        preview = self.preview(app, self.rows)[1]
        self.assertEqual(self.save(app, preview)[0], 201)
        products = request(app, "/api/private-observations/v1/products?q=D13")[1]
        detail = request(app, "/api/private-observations/v1/products/" + products["items"][0]["series_key"])[1]
        self.assertEqual(detail["history"]["confirmed_after_coupon"], [])
        self.assertEqual([item["price_twd"] for item in detail["history"]["before_coupon"]], [1000, 950])
        self.assertTrue(all(item["platform_verified"] is False for item in detail["history"]["user_reported_after_coupon"]))

    def test_06_lexical_escape_is_rejected(self):
        outside = self.temp.parent / (self.temp.name + "-outside")
        with self.assertRaises(StoreError):
            BatchObservationStore(outside, allowed_project_root=self.temp, clock=lambda: NOW)
        self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
