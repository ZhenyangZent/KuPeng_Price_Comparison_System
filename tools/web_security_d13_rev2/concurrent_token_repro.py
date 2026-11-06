from __future__ import annotations

import base64
import io
import json
import shutil
import sys
import threading
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


def main() -> int:
    work = ROOT / "review" / "D13" / "002" / "concurrent_repro"
    if work.exists():
        if not work.resolve().is_relative_to((ROOT / "review" / "D13" / "002").resolve()):
            raise RuntimeError("unsafe cleanup target")
        shutil.rmtree(work)
    work.mkdir(parents=True)
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

    store = BlockingStore(work / "private-data", allowed_project_root=work, clock=lambda: NOW)
    app = BatchImportApp(store, baselines={}, clock=lambda: NOW, csrf_token="csrf-d13-r2-race")
    row = {"schema_version": "CDH-B15-MANUAL-OBSERVATION-1", "submission_id": "SUB-D13-R2-RACE", "title": "D13 REV2 race", "identity": {"platform": "COUPANG_TW", "product_id": "PROD-D13-R2-RACE", "sku_id": "SKU-D13-R2", "seller_id": "SELLER-D13", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD"}, "observed_at": "2026-11-03T12:00:00+08:00", "quantity": 1, "before_coupon_price_twd": 1000, "user_reported_coupon": {"status": "NONE", "price_twd": None, "eligibility": "UNKNOWN", "evidence_level": "NONE", "evidence_note": None, "valid_from": None, "valid_until": None}, "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None}, "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "D13 REV2 race"}}
    file_bytes = json.dumps({"schema_version": "CDH-B16-BATCH-FILE-1", "observations": [row]}, separators=(",", ":")).encode("utf-8")
    preview_request = {"schema_version": "CDH-B16-BATCH-PREVIEW-REQUEST-1", "filename": "race.json", "media_type": "application/json", "content_base64": base64.b64encode(file_bytes).decode("ascii")}
    preview_status, preview = call(app, "/api/private-observations/v1/batch-preview", preview_request)
    confirm = {"schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1", "preview_id": preview["preview_id"], "confirm_token": preview["confirm_token"], "explicit_confirm": True}
    results = []

    def worker():
        results.append(call(app, "/api/private-observations/v1/batch-confirm", confirm))

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    if not entered.wait(timeout=5):
        raise RuntimeError("first request did not enter store")
    second.start()
    second.join(timeout=3)
    second_rejected_before_release = not second.is_alive()
    release.set()
    first.join(timeout=5)
    second.join(timeout=5)
    statuses = sorted(status for status, _body in results)
    codes = sorted(body.get("error", {}).get("code") for status, body in results if status >= 400)
    result = {"schema_version": "CDH-D13-B16-REV2-CONCURRENT-TOKEN-REPRO-1", "b16_rev2_sha256": "6904b7ab2ffd6daac0325be75a119cd906c67c7c479a4607760ce24739444ed6", "preview_status": preview_status, "concurrent_confirm_statuses": statuses, "error_codes": codes, "second_rejected_before_first_release": second_rejected_before_release, "store_commit_entry_count": store.commit_entry_count, "database_observation_count": store.observation_count(), "gate": "PASS" if statuses == [201, 409] and codes == ["CONFIRMATION_ALREADY_IN_PROGRESS"] and second_rejected_before_release and store.commit_entry_count == 1 and store.observation_count() == 1 else "FAIL"}
    evidence = ROOT / "review" / "D13" / "002" / "evidence" / "CONCURRENT_TOKEN_REPRO.json"
    evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
