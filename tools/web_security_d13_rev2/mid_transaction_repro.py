from __future__ import annotations

import base64
import io
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
B16 = ROOT / "review" / "D13" / "002" / "input" / "CDH_B_R12_002_REVIEW"
sys.path.insert(0, str(B16 / "services" / "private_batch_import_b16"))
sys.path.insert(0, str(B16 / "services" / "private_observation_b15"))

from private_batch_import_b16.api import BatchImportApp  # noqa: E402
from private_batch_import_b16.store import BatchObservationStore  # noqa: E402


NOW = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)


def call(app, path, body):
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    environ = {"REQUEST_METHOD": "POST", "PATH_INFO": path, "QUERY_STRING": "", "HTTP_HOST": "127.0.0.1", "HTTP_X_CDH_CSRF_TOKEN": app.csrf_token, "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])

    payload = json.loads(b"".join(app(environ, start_response)))
    return captured["status"], payload


def observation(submission, observed, before):
    return {"schema_version": "CDH-B15-MANUAL-OBSERVATION-1", "submission_id": submission, "title": "D13 REV2 rollback repro", "identity": {"platform": "COUPANG_TW", "product_id": "PROD-D13-R2-ROLLBACK", "sku_id": "SKU-D13-R2", "seller_id": "SELLER-D13", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD"}, "observed_at": observed, "quantity": 1, "before_coupon_price_twd": before, "user_reported_coupon": {"status": "NONE", "price_twd": None, "eligibility": "UNKNOWN", "evidence_level": "NONE", "evidence_note": None, "valid_from": None, "valid_until": None}, "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None}, "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "D13 REV2 rollback repro"}}


def main() -> int:
    work = ROOT / "review" / "D13" / "002" / "mid_transaction_repro"
    if work.exists():
        resolved = work.resolve()
        parent = (ROOT / "review" / "D13" / "002").resolve()
        if not resolved.is_relative_to(parent):
            raise RuntimeError("unsafe cleanup target")
        shutil.rmtree(work)
    work.mkdir(parents=True)

    class FailingStore(BatchObservationStore):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.insert_calls = 0

        def _insert_record(self, connection, normalized, *, batch_id, created):
            self.insert_calls += 1
            if self.insert_calls == 2:
                raise sqlite3.OperationalError("D13 injected second insert failure")
            return super()._insert_record(connection, normalized, batch_id=batch_id, created=created)

    store = FailingStore(work / "private-data", allowed_project_root=work, clock=lambda: NOW)
    app = BatchImportApp(store, baselines={}, clock=lambda: NOW, csrf_token="csrf-d13-mid-transaction")
    rows = [observation("SUB-D13-R2-RB-1", "2026-11-03T12:00:00+08:00", 1000), observation("SUB-D13-R2-RB-2", "2026-11-04T12:00:00+08:00", 950)]
    file_bytes = json.dumps({"schema_version": "CDH-B16-BATCH-FILE-1", "observations": rows}, separators=(",", ":")).encode("utf-8")
    envelope = {"schema_version": "CDH-B16-BATCH-PREVIEW-REQUEST-1", "filename": "rollback.json", "media_type": "application/json", "content_base64": base64.b64encode(file_bytes).decode("ascii")}
    preview_status, preview = call(app, "/api/private-observations/v1/batch-preview", envelope)
    confirm = {"schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": preview["preview_id"], "confirm_token": preview["confirm_token"], "explicit_confirm": True}
    confirm_status, confirm_response = call(app, "/api/private-observations/v1/batch-confirm", confirm)
    retry_status, retry_response = call(app, "/api/private-observations/v1/batch-confirm", confirm)
    database_exists = store.database.exists()
    database_bytes_before_inspection = store.database.stat().st_size if database_exists else None
    connection = sqlite3.connect(store.database)
    try:
        tables = sorted(row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        observations = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] if "observations" in tables else 0
        audits = connection.execute("SELECT COUNT(*) FROM commit_audit").fetchone()[0] if "commit_audit" in tables else 0
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        connection.close()
    fresh_status, fresh_response = call(app, "/api/private-observations/v1/batch-preview", envelope)
    result = {
        "schema_version": "CDH-D13-B16-REV2-MID-TRANSACTION-REPRO-1",
        "b16_rev2_sha256": "6904b7ab2ffd6daac0325be75a119cd906c67c7c479a4607760ce24739444ed6",
        "preview_status": preview_status,
        "confirm_status": confirm_status,
        "confirm_code": confirm_response.get("error", {}).get("code"),
        "same_token_retry_status": retry_status,
        "same_token_retry_code": retry_response.get("error", {}).get("code"),
        "database_exists_after_rollback": database_exists,
        "database_bytes_before_inspection": database_bytes_before_inspection,
        "tables_after_rollback": tables,
        "observation_count": observations,
        "audit_count": audits,
        "sqlite_quick_check": integrity,
        "fresh_preview_status": fresh_status,
        "fresh_preview_code": fresh_response.get("error", {}).get("code"),
        "token_terminalization_gate": "PASS" if (retry_status, retry_response.get("error", {}).get("code")) == (409, "CONFIRMATION_FAILED_NEW_PREVIEW_REQUIRED") else "FAIL",
        "transaction_rollback_gate": "PASS" if observations == 0 and audits == 0 and integrity == "ok" else "FAIL",
        "fresh_preview_recovery_gate": "PASS" if fresh_status == 200 else "FAIL",
        "root_cause": "A new SQLite file survives a rolled-back first transaction without schema tables; classify_batch treats the file as an existing database and rejects the next preview as PRIVATE_STORE_REJECTED.",
    }
    evidence = ROOT / "review" / "D13" / "002" / "evidence" / "MID_TRANSACTION_FAILURE_REPRO.json"
    evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["token_terminalization_gate"] == "PASS" and result["transaction_rollback_gate"] == "PASS" and result["fresh_preview_recovery_gate"] == "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
