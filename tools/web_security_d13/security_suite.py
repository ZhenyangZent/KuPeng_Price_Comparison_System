from __future__ import annotations

import base64
import copy
import csv
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
B16 = ROOT / "review" / "D13" / "001" / "input" / "CDH_B_R12_001_REVIEW"
sys.path.insert(0, str(B16 / "services" / "private_batch_import_b16"))
sys.path.insert(0, str(B16 / "services" / "private_observation_b15"))

from private_batch_import_b16.api import BatchImportApp  # noqa: E402
from private_batch_import_b16.parser import (  # noqa: E402
    CSV_HEADERS,
    FILE_SCHEMA,
    MAX_FILE_BYTES,
    MAX_ROWS,
    REQUEST_SCHEMA,
)
from private_batch_import_b16.pending import PendingBatches  # noqa: E402
from private_batch_import_b16.store import BatchObservationStore  # noqa: E402
from private_observation_b15.store import StoreError  # noqa: E402


NOW = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)
BASELINES = {
    "b13": "961439922ca767b07a5ef115da993fe9fe93da4c5c46248e4bfa2718a1741af4",
    "b14": "2212e7b63b9ab5e7d149da97bfeb68c292c1ad2ef1280bcd3e615cdfc50d149c",
    "c11_rev2": "f7dbcf555db08793daf02ac6bf6e2a80e11700b0380fbf57af4ad2b015782260",
    "b15_rev2": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
}


def observation(
    *,
    submission: str = "SUB-D13-0001",
    observed: str = "2026-11-03T12:00:00+08:00",
    before: int = 1000,
    reported: int | None = 900,
) -> dict[str, object]:
    has_coupon = reported is not None
    return {
        "schema_version": "CDH-B15-MANUAL-OBSERVATION-1",
        "submission_id": submission,
        "title": "D13 synthetic batch product",
        "identity": {
            "platform": "COUPANG_TW",
            "product_id": "PROD-D13-001",
            "sku_id": "SKU-D13-RED",
            "seller_id": "SELLER-D13",
            "condition": "NEW",
            "package_signature": "EACH-1",
            "currency": "TWD",
        },
        "observed_at": observed,
        "quantity": 1,
        "before_coupon_price_twd": before,
        "user_reported_coupon": {
            "status": "USER_REPORTED" if has_coupon else "NONE",
            "price_twd": reported,
            "eligibility": "USER_ASSERTED_ELIGIBLE" if has_coupon else "UNKNOWN",
            "evidence_level": "USER_DESCRIPTION" if has_coupon else "NONE",
            "evidence_note": "D13 synthetic user note" if has_coupon else None,
            "valid_from": "2026-11-01T00:00:00+08:00" if has_coupon else None,
            "valid_until": "2026-11-05T23:59:59+08:00" if has_coupon else None,
        },
        "shipping": {
            "status": "UNKNOWN",
            "shipping_fee_twd": None,
            "mandatory_fee_twd": None,
        },
        "source": {
            "source_class": "USER_ENTERED",
            "visibility": "PRIVATE_LOCAL",
            "note": "D13 synthetic private batch input",
        },
    }


def json_file(items: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {"schema_version": FILE_SCHEMA, "observations": items},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def csv_file(items: list[dict[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS, lineterminator="\n")
    writer.writeheader()
    for item in items:
        identity = item["identity"]
        coupon = item["user_reported_coupon"]
        shipping = item["shipping"]
        source = item["source"]
        writer.writerow(
            {
                "submission_id": item["submission_id"],
                "title": item["title"],
                "platform": identity["platform"],
                "product_id": identity["product_id"],
                "sku_id": identity["sku_id"],
                "seller_id": identity["seller_id"],
                "condition": identity["condition"],
                "package_signature": identity["package_signature"],
                "currency": identity["currency"],
                "observed_at": item["observed_at"],
                "quantity": item["quantity"],
                "before_coupon_price_twd": item["before_coupon_price_twd"],
                "coupon_status": coupon["status"],
                "coupon_price_twd": "" if coupon["price_twd"] is None else coupon["price_twd"],
                "coupon_eligibility": coupon["eligibility"],
                "coupon_evidence_level": coupon["evidence_level"],
                "coupon_evidence_note": "" if coupon["evidence_note"] is None else coupon["evidence_note"],
                "coupon_valid_from": "" if coupon["valid_from"] is None else coupon["valid_from"],
                "coupon_valid_until": "" if coupon["valid_until"] is None else coupon["valid_until"],
                "shipping_status": shipping["status"],
                "shipping_fee_twd": "" if shipping["shipping_fee_twd"] is None else shipping["shipping_fee_twd"],
                "mandatory_fee_twd": "" if shipping["mandatory_fee_twd"] is None else shipping["mandatory_fee_twd"],
                "source_class": source["source_class"],
                "visibility": source["visibility"],
                "source_note": source["note"],
            }
        )
    return output.getvalue().encode("utf-8")


def envelope(content: bytes, *, filename: str = "observations.json", media_type: str = "application/json") -> dict[str, object]:
    return {
        "schema_version": REQUEST_SCHEMA,
        "filename": filename,
        "media_type": media_type,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def request(
    app,
    path: str,
    *,
    method: str = "GET",
    body: object | bytes | None = None,
    csrf: bool = False,
    host: str | None = "127.0.0.1",
    origin: str | None = None,
):
    raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body, separators=(",", ":")).encode("utf-8"))
    path_info, _, query = path.partition("?")
    environ: dict[str, object] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path_info,
        "QUERY_STRING": query,
        "wsgi.input": io.BytesIO(raw),
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
    }
    if host is not None:
        environ["HTTP_HOST"] = host
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    if csrf:
        environ["HTTP_X_CDH_CSRF_TOKEN"] = app.csrf_token
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(headers)

    payload = b"".join(app(environ, start_response))
    return int(captured["status"]), json.loads(payload) if payload else None, captured["headers"]


class D13SecurityTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "review" / "D13" / "001" / "tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix="case-", dir=base))
        self.store = BatchObservationStore(self.temp / "private-data", allowed_project_root=self.temp, clock=lambda: NOW)
        self.app = BatchImportApp(
            self.store,
            baselines=BASELINES,
            clock=lambda: NOW,
            csrf_token="csrf-d13-test",
            allowed_origins=("http://127.0.0.1:4173",),
        )
        self.two = [
            observation(),
            observation(submission="SUB-D13-0002", observed="2026-11-04T12:00:00+08:00", before=950, reported=None),
        ]

    def tearDown(self):
        shutil.rmtree(self.temp)

    def preview(self, content: bytes | None = None, *, filename: str = "observations.json", media_type: str = "application/json"):
        return request(
            self.app,
            "/api/private-observations/v1/batch-preview",
            method="POST",
            body=envelope(content or json_file(self.two), filename=filename, media_type=media_type),
            csrf=True,
        )

    @staticmethod
    def confirm_body(preview: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1",
            "preview_id": preview["preview_id"],
            "confirm_token": preview["confirm_token"],
            "explicit_confirm": True,
        }

    def confirm(self, preview: dict[str, object]):
        return request(
            self.app,
            "/api/private-observations/v1/batch-confirm",
            method="POST",
            body=self.confirm_body(preview),
            csrf=True,
        )

    def test_01_duplicate_json_keys_in_envelope_and_file_are_rejected(self):
        encoded = base64.b64encode(json_file(self.two)).decode("ascii")
        raw = (
            '{"schema_version":"CDH-B16-BATCH-PREVIEW-REQUEST-1","filename":"a.json",'
            '"filename":"b.json","media_type":"application/json","content_base64":"'
            + encoded
            + '"}'
        ).encode("utf-8")
        status, body, _ = request(self.app, "/api/private-observations/v1/batch-preview", method="POST", body=raw, csrf=True)
        self.assertEqual((status, body["error"]["code"]), (400, "JSON_DUPLICATE_KEY"))
        duplicate_file = b'{"schema_version":"CDH-B16-BATCH-FILE-1","schema_version":"CDH-B16-BATCH-FILE-1","observations":[]}'
        status, body, _ = self.preview(duplicate_file)
        self.assertEqual((status, body["error"]["code"]), (400, "JSON_DUPLICATE_KEY"))
        self.assertFalse(self.store.database.exists())

    def test_02_csv_exact_header_duplicate_header_and_shape_gate(self):
        valid = csv_file(self.two)
        status, body, _ = self.preview(valid, filename="observations.csv", media_type="text/csv")
        self.assertEqual((status, body["unique_record_count"]), (200, 2))
        duplicated = valid.replace(b"submission_id,title", b"submission_id,submission_id", 1)
        status, body, _ = self.preview(duplicated, filename="bad.csv", media_type="text/csv")
        self.assertEqual((status, body["error"]["code"]), (400, "CSV_HEADERS_MISMATCH"))
        extra = valid.replace(b",source_note\n", b",source_note,unexpected\n", 1)
        status, body, _ = self.preview(extra, filename="bad.csv", media_type="text/csv")
        self.assertEqual((status, body["error"]["code"]), (400, "CSV_HEADERS_MISMATCH"))
        self.assertFalse(self.store.database.exists())

    def test_03_file_and_row_limits_are_enforced(self):
        status, body, _ = self.preview(b"x" * (MAX_FILE_BYTES + 1))
        self.assertEqual((status, body["error"]["code"]), (400, "FILE_TOO_LARGE"))
        rows = [observation(submission=f"SUB-D13-LIMIT-{index:04d}") for index in range(MAX_ROWS + 1)]
        status, body, _ = self.preview(json_file(rows))
        self.assertEqual((status, body["error"]["code"]), (400, "ROW_COUNT_INVALID"))
        status, body, _ = self.preview(json_file(rows[:MAX_ROWS]))
        self.assertEqual((status, body["row_count"]), (200, MAX_ROWS))
        self.assertFalse(self.store.database.exists())

    def test_04_csrf_host_origin_method_and_source_admission(self):
        payload = envelope(json_file(self.two))
        path = "/api/private-observations/v1/batch-preview"
        self.assertEqual(request(self.app, path, method="POST", body=payload)[0], 403)
        self.assertEqual(request(self.app, path, method="POST", body=payload, csrf=True, host=None)[0], 400)
        self.assertEqual(request(self.app, path, method="POST", body=payload, csrf=True, host="evil.invalid")[0], 400)
        self.assertEqual(request(self.app, path, method="POST", body=payload, csrf=True, origin="https://evil.invalid")[0], 403)
        self.assertEqual(request(self.app, path, method="PUT", body=payload, csrf=True)[0], 405)
        hostile = copy.deepcopy(self.two)
        hostile[0]["source"]["source_class"] = "PUBLIC_WEB"
        status, body, _ = self.preview(json_file(hostile))
        self.assertEqual((status, body["row_errors"][0]["error"]), (422, "SOURCE_CLASS_NOT_ALLOWED"))
        self.assertFalse(self.store.database.exists())

    def test_05_preview_is_no_write_and_explicit_confirm_is_required(self):
        status, preview, _ = self.preview()
        self.assertEqual((status, preview["database_write_count"]), (200, 0))
        self.assertFalse(self.store.database.exists())
        bad = self.confirm_body(preview)
        bad["explicit_confirm"] = False
        status, body, _ = request(self.app, "/api/private-observations/v1/batch-confirm", method="POST", body=bad, csrf=True)
        self.assertEqual((status, body["error"]["code"]), (400, "EXPLICIT_CONFIRM_REQUIRED"))
        self.assertFalse(self.store.database.exists())

    def test_06_expired_and_sequentially_replayed_token_are_rejected(self):
        ticks = [100.0]
        pending = PendingBatches(ttl_seconds=1, clock=lambda: ticks[0])
        app = BatchImportApp(self.store, baselines=BASELINES, clock=lambda: NOW, csrf_token="csrf-d13-test", pending=pending)
        path = "/api/private-observations/v1/batch-preview"
        status, expiring, _ = request(app, path, method="POST", body=envelope(json_file(self.two)), csrf=True)
        self.assertEqual(status, 200)
        ticks[0] = 102.0
        status, body, _ = request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=self.confirm_body(expiring), csrf=True)
        self.assertEqual((status, body["error"]["code"]), (400, "CONFIRMATION_TOKEN_INVALID_OR_EXPIRED"))
        ticks[0] = 200.0
        preview = request(app, path, method="POST", body=envelope(json_file(self.two)), csrf=True)[1]
        self.assertEqual(request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=self.confirm_body(preview), csrf=True)[0], 201)
        status, body, _ = request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=self.confirm_body(preview), csrf=True)
        self.assertEqual((status, body["error"]["code"]), (400, "CONFIRMATION_TOKEN_INVALID_OR_EXPIRED"))
        self.assertEqual(self.store.observation_count(), 2)

    def test_07_one_time_token_rejects_second_concurrent_confirmation(self):
        barrier = threading.Barrier(2)

        class BarrierStore(BatchObservationStore):
            def commit_batch(self, records, *, file_sha256, duplicate_input_count):
                barrier.wait(timeout=5)
                return super().commit_batch(
                    records,
                    file_sha256=file_sha256,
                    duplicate_input_count=duplicate_input_count,
                )

        store = BarrierStore(self.temp / "concurrent", allowed_project_root=self.temp, clock=lambda: NOW)
        app = BatchImportApp(store, baselines=BASELINES, clock=lambda: NOW, csrf_token="csrf-d13-race")
        preview = request(
            app,
            "/api/private-observations/v1/batch-preview",
            method="POST",
            body=envelope(json_file(self.two)),
            csrf=True,
        )[1]
        results: list[tuple[int, object, object]] = []
        errors: list[BaseException] = []

        def worker():
            try:
                results.append(
                    request(
                        app,
                        "/api/private-observations/v1/batch-confirm",
                        method="POST",
                        body=self.confirm_body(preview),
                        csrf=True,
                    )
                )
            except BaseException as exc:  # evidence capture for worker failures
                errors.append(exc)

        threads = [threading.Thread(target=worker, name=f"d13-confirm-{index}") for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(errors)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        statuses = sorted(item[0] for item in results)
        self.assertEqual(store.observation_count(), 2, "concurrent confirms must never duplicate rows")
        self.assertEqual(
            statuses,
            [201, 400],
            "B16 advertises a one-time confirm token; exactly one concurrent use must be rejected",
        )

    def test_08_whole_file_reimport_is_idempotent_with_fresh_preview(self):
        self.assertEqual(self.confirm(self.preview()[1])[0], 201)
        status, body, _ = self.confirm(self.preview()[1])
        self.assertEqual((status, body["inserted_count"], body["existing_idempotent_count"]), (200, 0, 2))
        self.assertEqual(self.store.observation_count(), 2)

    def test_09_submission_conflict_blocks_entire_batch(self):
        preview = self.preview()[1]
        first_only = [observation(submission="SUB-D13-0001", before=777, reported=None)]
        alternate = self.preview(json_file(first_only))[1]
        self.assertEqual(self.confirm(alternate)[0], 201)
        status, body, _ = self.confirm(preview)
        self.assertEqual((status, body["error"]["code"]), (409, "SUBMISSION_ID_CONTENT_CONFLICT"))
        self.assertEqual(self.store.observation_count(), 1)

    def test_10_transaction_failure_rolls_back_observation_and_audit_rows(self):
        class FailingStore(BatchObservationStore):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.calls = 0

            def _insert_record(self, connection, normalized, *, batch_id, created):
                self.calls += 1
                if self.calls == 2:
                    raise sqlite3.OperationalError("D13 injected second-row failure")
                return super()._insert_record(connection, normalized, batch_id=batch_id, created=created)

        store = FailingStore(self.temp / "rollback", allowed_project_root=self.temp, clock=lambda: NOW)
        app = BatchImportApp(store, baselines=BASELINES, clock=lambda: NOW, csrf_token="csrf-d13-rollback")
        preview = request(app, "/api/private-observations/v1/batch-preview", method="POST", body=envelope(json_file(self.two)), csrf=True)[1]
        status, body, _ = request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=self.confirm_body(preview), csrf=True)
        self.assertEqual((status, body["error"]["code"]), (500, "PRIVATE_STORE_TRANSACTION_FAILED"))
        connection = sqlite3.connect(store.database)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            observation_count = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] if "observations" in tables else 0
            audit_count = connection.execute("SELECT COUNT(*) FROM commit_audit").fetchone()[0] if "commit_audit" in tables else 0
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual((observation_count, audit_count, integrity), (0, 0, "ok"))

    def test_11_existing_database_gets_integrity_checked_backup(self):
        first = [self.two[0]]
        second = [self.two[1]]
        self.assertEqual(self.confirm(self.preview(json_file(first))[1])[0], 201)
        status, body, _ = self.confirm(self.preview(json_file(second))[1])
        self.assertEqual((status, body["backup_created"]), (201, True))
        backups = list(self.store.backup_root.glob("*.sqlite3"))
        self.assertEqual(len(backups), 1)
        connection = sqlite3.connect(backups[0])
        self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1)
        connection.close()
        self.assertEqual(self.store.observation_count(), 2)

    def test_12_private_and_coupon_evidence_never_escalate(self):
        self.assertEqual(self.confirm(self.preview()[1])[0], 201)
        connection = sqlite3.connect(self.store.database)
        rows = connection.execute(
            "SELECT source_class,visibility,confirmed_after_coupon_price_twd,platform_verified,coupon_status "
            "FROM observations ORDER BY observed_at_utc"
        ).fetchall()
        connection.close()
        self.assertEqual(
            rows,
            [
                ("USER_ENTERED", "PRIVATE_LOCAL", None, 0, "USER_REPORTED"),
                ("USER_ENTERED", "PRIVATE_LOCAL", None, 0, "NONE"),
            ],
        )
        products = request(self.app, "/api/private-observations/v1/products?q=D13")[1]
        detail = request(self.app, "/api/private-observations/v1/products/" + products["items"][0]["series_key"])[1]
        self.assertEqual(detail["data_classification"], "PRIVATE_LOCAL_USER_ENTERED")
        self.assertEqual(detail["history"]["confirmed_after_coupon"], [])
        self.assertTrue(all(point["platform_verified"] is False for point in detail["history"]["user_reported_after_coupon"]))

    def test_13_lexical_path_escape_is_rejected_without_creation(self):
        outside = self.temp.parent / (self.temp.name + "-outside")
        self.assertFalse(outside.exists())
        with self.assertRaises(StoreError):
            BatchObservationStore(outside, allowed_project_root=self.temp, clock=lambda: NOW)
        self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
