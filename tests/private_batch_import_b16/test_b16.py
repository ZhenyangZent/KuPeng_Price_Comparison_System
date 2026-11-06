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
sys.path.insert(0, str(ROOT / "services" / "private_batch_import_b16"))
sys.path.insert(0, str(ROOT / "services" / "private_observation_b15"))

from private_batch_import_b16.api import BatchImportApp  # noqa: E402
from private_batch_import_b16.baselines import EXPECTED, verify_baselines  # noqa: E402
from private_batch_import_b16.parser import CSV_HEADERS, FILE_SCHEMA, MAX_FILE_BYTES, REQUEST_SCHEMA  # noqa: E402
from private_batch_import_b16.pending import PendingBatches  # noqa: E402
from private_batch_import_b16.store import BatchObservationStore  # noqa: E402
from private_observation_b15.validation import parse_and_validate  # noqa: E402


NOW = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)
BASELINE_ROOT = Path(os.environ.get("CDH_B16_BASELINE_ROOT", ROOT / "review" / "releases"))


def observation(*, submission: str = "SUB-B16-0001", observed: str = "2026-11-03T12:00:00+08:00", before: int = 1000, reported: int | None = 900) -> dict[str, object]:
    coupon = reported is not None
    return {
        "schema_version": "CDH-B15-MANUAL-OBSERVATION-1",
        "submission_id": submission,
        "title": "Synthetic batch product",
        "identity": {
            "platform": "COUPANG_TW", "product_id": "PROD-B16-001", "sku_id": "SKU-B16-RED",
            "seller_id": "SELLER-B16", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD",
        },
        "observed_at": observed,
        "quantity": 1,
        "before_coupon_price_twd": before,
        "user_reported_coupon": {
            "status": "USER_REPORTED" if coupon else "NONE",
            "price_twd": reported,
            "eligibility": "USER_ASSERTED_ELIGIBLE" if coupon else "UNKNOWN",
            "evidence_level": "USER_DESCRIPTION" if coupon else "NONE",
            "evidence_note": "Synthetic user note" if coupon else None,
            "valid_from": "2026-11-01T00:00:00+08:00" if coupon else None,
            "valid_until": "2026-11-05T23:59:59+08:00" if coupon else None,
        },
        "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None},
        "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "Synthetic private batch input"},
    }


def json_file(items: list[dict[str, object]]) -> bytes:
    return json.dumps({"schema_version": FILE_SCHEMA, "observations": items}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def csv_file(items: list[dict[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS, lineterminator="\n")
    writer.writeheader()
    for item in items:
        identity = item["identity"]
        coupon = item["user_reported_coupon"]
        shipping = item["shipping"]
        source = item["source"]
        writer.writerow({
            "submission_id": item["submission_id"], "title": item["title"], "platform": identity["platform"],
            "product_id": identity["product_id"], "sku_id": identity["sku_id"], "seller_id": identity["seller_id"],
            "condition": identity["condition"], "package_signature": identity["package_signature"], "currency": identity["currency"],
            "observed_at": item["observed_at"], "quantity": item["quantity"], "before_coupon_price_twd": item["before_coupon_price_twd"],
            "coupon_status": coupon["status"], "coupon_price_twd": "" if coupon["price_twd"] is None else coupon["price_twd"],
            "coupon_eligibility": coupon["eligibility"], "coupon_evidence_level": coupon["evidence_level"],
            "coupon_evidence_note": "" if coupon["evidence_note"] is None else coupon["evidence_note"],
            "coupon_valid_from": "" if coupon["valid_from"] is None else coupon["valid_from"],
            "coupon_valid_until": "" if coupon["valid_until"] is None else coupon["valid_until"],
            "shipping_status": shipping["status"], "shipping_fee_twd": "" if shipping["shipping_fee_twd"] is None else shipping["shipping_fee_twd"],
            "mandatory_fee_twd": "" if shipping["mandatory_fee_twd"] is None else shipping["mandatory_fee_twd"],
            "source_class": source["source_class"], "visibility": source["visibility"], "source_note": source["note"],
        })
    return output.getvalue().encode("utf-8")


def envelope(content: bytes, *, filename: str, media_type: str) -> dict[str, object]:
    return {"schema_version": REQUEST_SCHEMA, "filename": filename, "media_type": media_type, "content_base64": base64.b64encode(content).decode("ascii")}


def request(app, path: str, *, method: str = "GET", body: object | bytes | None = None, csrf: bool = False, host: str | None = "127.0.0.1", origin: str | None = None):
    raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    path_info, _, query = path.partition("?")
    environ: dict[str, object] = {
        "REQUEST_METHOD": method, "PATH_INFO": path_info, "QUERY_STRING": query, "wsgi.input": io.BytesIO(raw),
        "CONTENT_LENGTH": str(len(raw)), "CONTENT_TYPE": "application/json",
    }
    if host is not None:
        environ["HTTP_HOST"] = host
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    if csrf:
        environ["HTTP_X_CDH_CSRF_TOKEN"] = app.csrf_token
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0]); captured["headers"] = dict(headers)

    payload = b"".join(app(environ, start_response))
    return captured["status"], json.loads(payload) if payload else None, captured["headers"]


class B16Tests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "review" / "B16" / "tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix="case-", dir=base))
        self.store = BatchObservationStore(self.temp / "private-data", allowed_project_root=self.temp, clock=lambda: NOW)
        self.baselines = verify_baselines(BASELINE_ROOT)
        self.app = BatchImportApp(self.store, baselines=self.baselines, clock=lambda: NOW, csrf_token="csrf-b16-test", allowed_origins=("http://127.0.0.1:4173",))
        self.two = [observation(), observation(submission="SUB-B16-0002", observed="2026-11-04T12:00:00+08:00", before=950, reported=None)]

    def tearDown(self):
        shutil.rmtree(self.temp)

    def preview(self, content: bytes | None = None, *, filename: str = "observations.json", media_type: str = "application/json"):
        return request(self.app, "/api/private-observations/v1/batch-preview", method="POST", body=envelope(content or json_file(self.two), filename=filename, media_type=media_type), csrf=True)

    def confirm(self, preview: dict[str, object]):
        return request(self.app, "/api/private-observations/v1/batch-confirm", method="POST", body={
            "schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": preview["preview_id"],
            "confirm_token": preview["confirm_token"], "explicit_confirm": True,
        }, csrf=True)

    def test_exact_pinned_baselines(self):
        self.assertEqual(self.baselines, {name: digest for name, (_file, digest) in EXPECTED.items()})

    def test_json_preview_is_no_write_and_has_two_days(self):
        status, body, _ = self.preview()
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "PREVIEW_READY_NO_DATABASE_WRITE")
        self.assertEqual([row["taipei_date"] for row in body["rows"]], ["2026-11-03", "2026-11-04"])
        self.assertEqual(body["database_write_count"], 0)
        self.assertFalse(self.store.database.exists())

    def test_csv_preview_and_confirm_atomic_success(self):
        status, preview, _ = self.preview(csv_file(self.two), filename="observations.csv", media_type="text/csv")
        self.assertEqual((status, preview["unique_record_count"]), (200, 2))
        status, result, _ = self.confirm(preview)
        self.assertEqual((status, result["inserted_count"]), (201, 2))
        self.assertEqual(self.store.observation_count(), 2)

    def test_restart_reads_imported_history_without_reimport(self):
        preview = self.preview()[1]
        self.assertEqual(self.confirm(preview)[0], 201)
        restarted_store = BatchObservationStore(self.temp / "private-data", allowed_project_root=self.temp, clock=lambda: NOW)
        restarted = BatchImportApp(restarted_store, baselines=self.baselines, clock=lambda: NOW, csrf_token="new-session")
        status, products, _ = request(restarted, "/api/private-observations/v1/products?q=Synthetic")
        self.assertEqual((status, products["total"]), (200, 1))
        status, detail, _ = request(restarted, "/api/private-observations/v1/products/" + products["items"][0]["series_key"])
        self.assertEqual(status, 200)
        self.assertEqual([point["price_twd"] for point in detail["history"]["before_coupon"]], [1000, 950])
        self.assertEqual([point["price_twd"] for point in detail["history"]["user_reported_after_coupon"]], [900])
        self.assertEqual(detail["history"]["confirmed_after_coupon"], [])
        self.assertEqual([point["sample_count"] for point in detail["history_quality"]["before_coupon"]["daily_representatives"]], [1, 1])

    def test_invalid_row_returns_422_without_confirmation_or_write(self):
        bad = copy.deepcopy(self.two)
        bad[1].pop("identity")
        status, body, _ = self.preview(json_file(bad))
        self.assertEqual((status, body["can_confirm"], body["error_count"]), (422, False, 1))
        self.assertNotIn("preview_id", body)
        self.assertFalse(self.store.database.exists())

    def test_duplicate_json_member_is_rejected(self):
        content = b'{"schema_version":"CDH-B16-BATCH-FILE-1","schema_version":"CDH-B16-BATCH-FILE-1","observations":[]}'
        status, body, _ = self.preview(content)
        self.assertEqual((status, body["error"]["code"]), (400, "JSON_DUPLICATE_KEY"))

    def test_duplicate_envelope_member_is_rejected(self):
        encoded = base64.b64encode(json_file(self.two)).decode("ascii")
        raw = ('{"schema_version":"CDH-B16-BATCH-PREVIEW-REQUEST-1","filename":"a.json","filename":"b.json","media_type":"application/json","content_base64":"' + encoded + '"}').encode()
        status, body, _ = request(self.app, "/api/private-observations/v1/batch-preview", method="POST", body=raw, csrf=True)
        self.assertEqual((status, body["error"]["code"]), (400, "JSON_DUPLICATE_KEY"))

    def test_csv_missing_header_is_rejected(self):
        content = csv_file(self.two).replace(b",source_note\n", b"\n", 1)
        status, body, _ = self.preview(content, filename="bad.csv", media_type="text/csv")
        self.assertEqual((status, body["error"]["code"]), (400, "CSV_HEADERS_MISMATCH"))

    def test_csv_incomplete_integer_is_row_error(self):
        content = csv_file(self.two).replace(b",1000,USER_REPORTED", b",,USER_REPORTED", 1)
        status, body, _ = self.preview(content, filename="bad.csv", media_type="text/csv")
        self.assertEqual((status, body["can_confirm"]), (422, False))
        self.assertEqual(body["row_errors"][0]["error"], "BEFORE_COUPON_PRICE_INVALID")

    def test_source_admission_is_private_user_entered_only(self):
        bad = copy.deepcopy(self.two)
        bad[0]["source"]["source_class"] = "PUBLIC_WEB"
        status, body, _ = self.preview(json_file(bad))
        self.assertEqual((status, body["row_errors"][0]["error"]), (422, "SOURCE_CLASS_NOT_ALLOWED"))

    def test_identity_platform_and_currency_are_rejected(self):
        bad = copy.deepcopy(self.two)
        bad[0]["identity"]["platform"] = "OTHER"
        status, body, _ = self.preview(json_file(bad))
        self.assertEqual((status, body["row_errors"][0]["error"]), (422, "PLATFORM_OR_CURRENCY_NOT_ALLOWED"))

    def test_future_date_and_bad_price_are_rejected(self):
        bad = [observation(observed="2026-11-07T12:00:00+08:00"), observation(submission="SUB-B16-BAD2", before=100, reported=200)]
        status, body, _ = self.preview(json_file(bad))
        self.assertEqual(status, 422)
        self.assertEqual({item["error"] for item in body["row_errors"]}, {"OBSERVED_AT_FUTURE", "USER_REPORTED_COUPON_PRICE_INVALID"})

    def test_coupon_evidence_never_promotes_to_confirmed(self):
        preview = self.preview()[1]
        self.assertTrue(all(row["confirmed_after_coupon_price_twd"] is None for row in preview["rows"]))
        self.confirm(preview)
        connection = sqlite3.connect(self.store.database)
        values = connection.execute("SELECT confirmed_after_coupon_price_twd,platform_verified,coupon_status FROM observations ORDER BY observed_at_utc").fetchall()
        connection.close()
        self.assertEqual(values, [(None, 0, "USER_REPORTED"), (None, 0, "NONE")])

    def test_duplicate_rows_are_skipped_in_preview_and_commit(self):
        items = [self.two[0], copy.deepcopy(self.two[0]), self.two[1]]
        status, preview, _ = self.preview(json_file(items))
        self.assertEqual((status, preview["unique_record_count"], preview["duplicate_input_count"]), (200, 2, 1))
        status, result, _ = self.confirm(preview)
        self.assertEqual((status, result["inserted_count"], result["duplicate_input_count"]), (201, 2, 1))

    def test_repeated_whole_file_is_idempotent(self):
        self.assertEqual(self.confirm(self.preview()[1])[0], 201)
        second = self.preview()[1]
        status, result, _ = self.confirm(second)
        self.assertEqual((status, result["inserted_count"], result["existing_idempotent_count"], result["idempotent_replay"]), (200, 0, 2, True))
        self.assertEqual(self.store.observation_count(), 2)

    def test_submission_conflict_inside_file_blocks_preview(self):
        bad = [self.two[0], observation(submission="SUB-B16-0001", observed="2026-11-04T12:00:00+08:00", before=777, reported=None)]
        status, body, _ = self.preview(json_file(bad))
        self.assertEqual((status, body["can_confirm"]), (422, False))
        self.assertEqual(body["row_errors"][0]["error"], "SUBMISSION_ID_CONTENT_CONFLICT_IN_FILE")

    def test_state_change_conflict_before_confirm_writes_nothing_from_batch(self):
        pending = self.preview()[1]
        direct = parse_and_validate(json.dumps(observation(submission="SUB-B16-0001", before=888, reported=None), separators=(",", ":")).encode(), now=NOW)
        self.store.commit(direct)
        status, body, _ = self.confirm(pending)
        self.assertEqual((status, body["error"]["code"]), (409, "SUBMISSION_ID_CONTENT_CONFLICT"))
        self.assertEqual(self.store.observation_count(), 1)

    def test_transaction_failure_rolls_back_all_batch_rows(self):
        class FailingStore(BatchObservationStore):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs); self.calls = 0

            def _insert_record(self, connection, normalized, *, batch_id, created):
                self.calls += 1
                if self.calls == 2:
                    raise sqlite3.OperationalError("synthetic failure")
                return super()._insert_record(connection, normalized, batch_id=batch_id, created=created)

        store = FailingStore(self.temp / "rollback", allowed_project_root=self.temp, clock=lambda: NOW)
        records = [parse_and_validate(json.dumps(item, separators=(",", ":")).encode(), now=NOW) for item in self.two]
        with self.assertRaises(sqlite3.OperationalError):
            store.commit_batch(records, file_sha256="a" * 64, duplicate_input_count=0)
        connection = sqlite3.connect(store.database)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        count = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] if "observations" in tables else 0
        audit_count = connection.execute("SELECT COUNT(*) FROM commit_audit").fetchone()[0] if "commit_audit" in tables else 0
        connection.close()
        self.assertEqual((count, audit_count), (0, 0))
        self.assertTrue({"b15_schema", "observations", "commit_audit"}.issubset(tables))

    def test_first_mid_transaction_failure_allows_fresh_preview_recovery(self):
        class FailSecondInsertOnce(BatchObservationStore):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs); self.calls = 0; self.failed = False

            def _insert_record(self, connection, normalized, *, batch_id, created):
                self.calls += 1
                if self.calls == 2 and not self.failed:
                    self.failed = True
                    raise sqlite3.OperationalError("D13 injected second insert failure")
                return super()._insert_record(connection, normalized, batch_id=batch_id, created=created)

        store = FailSecondInsertOnce(self.temp / "first-failure", allowed_project_root=self.temp, clock=lambda: NOW)
        app = BatchImportApp(store, baselines=self.baselines, clock=lambda: NOW, csrf_token="csrf-first-failure")
        content = envelope(json_file(self.two), filename="rollback.json", media_type="application/json")
        preview_status, preview, _ = request(app, "/api/private-observations/v1/batch-preview", method="POST", body=content, csrf=True)
        confirm_body = {"schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": preview["preview_id"], "confirm_token": preview["confirm_token"], "explicit_confirm": True}
        failed_status, failed, _ = request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=confirm_body, csrf=True)
        retry_status, retry, _ = request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=confirm_body, csrf=True)
        connection = sqlite3.connect(store.database)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = (connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], connection.execute("SELECT COUNT(*) FROM commit_audit").fetchone()[0])
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        connection.close()
        fresh_status, fresh, _ = request(app, "/api/private-observations/v1/batch-preview", method="POST", body=content, csrf=True)
        fresh_body = {"schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": fresh["preview_id"], "confirm_token": fresh["confirm_token"], "explicit_confirm": True}
        recovered_status, recovered, _ = request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=fresh_body, csrf=True)
        self.assertEqual((preview_status, failed_status, failed["error"]["code"]), (200, 500, "PRIVATE_STORE_TRANSACTION_FAILED"))
        self.assertEqual((retry_status, retry["error"]["code"]), (409, "CONFIRMATION_FAILED_NEW_PREVIEW_REQUIRED"))
        self.assertTrue({"b15_schema", "observations", "commit_audit"}.issubset(tables))
        self.assertEqual((counts, integrity, fresh_status), ((0, 0), "ok", 200))
        self.assertEqual((recovered_status, recovered["inserted_count"], store.observation_count()), (201, 2, 2))

    def test_existing_database_and_backup_survive_injected_batch_failure(self):
        initial = parse_and_validate(json.dumps(observation(submission="SUB-B16-EXISTING", observed="2026-11-02T12:00:00+08:00", before=1100, reported=None), separators=(",", ":")).encode(), now=NOW)
        self.store.commit(initial)

        class ExistingFailStore(BatchObservationStore):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs); self.calls = 0

            def _insert_record(self, connection, normalized, *, batch_id, created):
                self.calls += 1
                if self.calls == 2:
                    raise sqlite3.OperationalError("synthetic existing-db failure")
                return super()._insert_record(connection, normalized, batch_id=batch_id, created=created)

        store = ExistingFailStore(self.temp / "private-data", allowed_project_root=self.temp, clock=lambda: NOW)
        records = [parse_and_validate(json.dumps(item, separators=(",", ":")).encode(), now=NOW) for item in self.two]
        with self.assertRaises(sqlite3.OperationalError):
            store.commit_batch(records, file_sha256="b" * 64, duplicate_input_count=0)
        self.assertTrue(store.database.is_file())
        self.assertEqual(store.observation_count(), 1)
        self.assertGreaterEqual(len(list(store.backup_root.glob("*.sqlite3"))), 1)

    def test_file_size_limit_and_extension_media_match(self):
        status, body, _ = self.preview(b"x" * (MAX_FILE_BYTES + 1))
        self.assertEqual((status, body["error"]["code"]), (400, "FILE_TOO_LARGE"))
        status, body, _ = self.preview(json_file(self.two), filename="wrong.csv", media_type="application/json")
        self.assertEqual((status, body["error"]["code"]), (400, "FILE_EXTENSION_MEDIA_TYPE_MISMATCH"))

    def test_csrf_host_and_origin_default_deny(self):
        body = envelope(json_file(self.two), filename="a.json", media_type="application/json")
        self.assertEqual(request(self.app, "/api/private-observations/v1/batch-preview", method="POST", body=body)[0], 403)
        self.assertEqual(request(self.app, "/api/private-observations/v1/batch-preview", method="POST", body=body, csrf=True, host=None)[0], 400)
        self.assertEqual(request(self.app, "/api/private-observations/v1/batch-preview", method="POST", body=body, csrf=True, origin="https://evil.invalid")[0], 403)

    def test_filename_path_is_rejected(self):
        status, body, _ = self.preview(json_file(self.two), filename="../escape.json")
        self.assertEqual((status, body["error"]["code"]), (400, "FILENAME_INVALID"))

    def test_expired_confirmation_is_rejected(self):
        ticks = [100.0]
        pending = PendingBatches(ttl_seconds=1, clock=lambda: ticks[0])
        app = BatchImportApp(self.store, baselines=self.baselines, clock=lambda: NOW, csrf_token="csrf-b16-test", pending=pending)
        preview = request(app, "/api/private-observations/v1/batch-preview", method="POST", body=envelope(json_file(self.two), filename="a.json", media_type="application/json"), csrf=True)[1]
        ticks[0] = 102.0
        status, body, _ = request(app, "/api/private-observations/v1/batch-confirm", method="POST", body={
            "schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": preview["preview_id"], "confirm_token": preview["confirm_token"], "explicit_confirm": True,
        }, csrf=True)
        self.assertEqual((status, body["error"]["code"]), (400, "CONFIRMATION_TOKEN_INVALID_OR_EXPIRED"))
        self.assertFalse(self.store.database.exists())

    def test_concurrent_confirmation_token_has_one_atomic_claimant(self):
        entered = threading.Event()
        release = threading.Event()

        class HoldingStore(BatchObservationStore):
            def commit_batch(self, records, *, file_sha256, duplicate_input_count):
                entered.set()
                if not release.wait(timeout=5):
                    raise sqlite3.OperationalError("synthetic hold timeout")
                return super().commit_batch(records, file_sha256=file_sha256, duplicate_input_count=duplicate_input_count)

        store = HoldingStore(self.temp / "concurrent", allowed_project_root=self.temp, clock=lambda: NOW)
        app = BatchImportApp(store, baselines=self.baselines, clock=lambda: NOW, csrf_token="csrf-concurrent")
        preview = request(app, "/api/private-observations/v1/batch-preview", method="POST", body=envelope(json_file([self.two[0]]), filename="race.json", media_type="application/json"), csrf=True)[1]
        confirm_body = {
            "schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": preview["preview_id"],
            "confirm_token": preview["confirm_token"], "explicit_confirm": True,
        }
        first: list[tuple[int, object, object]] = []
        worker = threading.Thread(target=lambda: first.append(request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=confirm_body, csrf=True)))
        worker.start()
        self.assertTrue(entered.wait(timeout=5))
        second = request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=confirm_body, csrf=True)
        release.set(); worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(first[0][0], 201)
        self.assertEqual((second[0], second[1]["error"]["code"]), (409, "CONFIRMATION_ALREADY_IN_PROGRESS"))
        self.assertEqual(store.observation_count(), 1)

    def test_failed_commit_terminalizes_token_and_new_preview_recovers(self):
        class FailOnceStore(BatchObservationStore):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs); self.failed = False

            def commit_batch(self, records, *, file_sha256, duplicate_input_count):
                if not self.failed:
                    self.failed = True
                    raise sqlite3.OperationalError("synthetic pre-commit failure")
                return super().commit_batch(records, file_sha256=file_sha256, duplicate_input_count=duplicate_input_count)

        store = FailOnceStore(self.temp / "fail-once", allowed_project_root=self.temp, clock=lambda: NOW)
        app = BatchImportApp(store, baselines=self.baselines, clock=lambda: NOW, csrf_token="csrf-fail")
        content = envelope(json_file([self.two[0]]), filename="retry.json", media_type="application/json")
        preview = request(app, "/api/private-observations/v1/batch-preview", method="POST", body=content, csrf=True)[1]
        confirm_body = {"schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": preview["preview_id"], "confirm_token": preview["confirm_token"], "explicit_confirm": True}
        self.assertEqual(request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=confirm_body, csrf=True)[0], 500)
        failed_retry = request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=confirm_body, csrf=True)
        self.assertEqual((failed_retry[0], failed_retry[1]["error"]["code"]), (409, "CONFIRMATION_FAILED_NEW_PREVIEW_REQUIRED"))
        fresh = request(app, "/api/private-observations/v1/batch-preview", method="POST", body=content, csrf=True)[1]
        fresh_body = {"schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": fresh["preview_id"], "confirm_token": fresh["confirm_token"], "explicit_confirm": True}
        self.assertEqual(request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=fresh_body, csrf=True)[0], 201)
        replay = request(app, "/api/private-observations/v1/batch-preview", method="POST", body=content, csrf=True)[1]
        replay_body = {"schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": replay["preview_id"], "confirm_token": replay["confirm_token"], "explicit_confirm": True}
        self.assertEqual(request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=replay_body, csrf=True)[0], 200)
        self.assertEqual(store.observation_count(), 1)

    def test_wrong_token_does_not_cancel_available_preview(self):
        preview = self.preview(json_file([self.two[0]]))[1]
        wrong = {"schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": preview["preview_id"], "confirm_token": "wrong-token", "explicit_confirm": True}
        self.assertEqual(request(self.app, "/api/private-observations/v1/batch-confirm", method="POST", body=wrong, csrf=True)[0], 400)
        self.assertEqual(self.confirm(preview)[0], 201)
        self.assertEqual(self.store.observation_count(), 1)

    def test_existing_b15_single_record_route_remains_available(self):
        status, body, _ = request(self.app, "/api/private-observations/v1/session")
        self.assertEqual(status, 200)
        self.assertEqual(body["storage_scope"], "PRIVATE_LOCAL_ONLY")


if __name__ == "__main__":
    unittest.main()

