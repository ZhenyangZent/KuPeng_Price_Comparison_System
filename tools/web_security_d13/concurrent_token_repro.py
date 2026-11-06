from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
B16 = ROOT / "review" / "D13" / "001" / "input" / "CDH_B_R12_001_REVIEW"
sys.path.insert(0, str(B16 / "services" / "private_batch_import_b16"))
sys.path.insert(0, str(B16 / "services" / "private_observation_b15"))

from private_batch_import_b16.api import BatchImportApp  # noqa: E402
from private_batch_import_b16.store import BatchObservationStore  # noqa: E402


NOW = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)


def call(app, path: str, body: dict[str, object]):
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "HTTP_HOST": "127.0.0.1",
        "HTTP_X_CDH_CSRF_TOKEN": app.csrf_token,
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
    }
    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])

    response = json.loads(b"".join(app(environ, start_response)))
    return captured["status"], response


def main() -> int:
    barrier = threading.Barrier(2)

    class BarrierStore(BatchObservationStore):
        def commit_batch(self, records, *, file_sha256, duplicate_input_count):
            barrier.wait(timeout=5)
            return super().commit_batch(records, file_sha256=file_sha256, duplicate_input_count=duplicate_input_count)

    root = ROOT / "review" / "D13" / "001" / "race_repro"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=root) as directory:
        store = BarrierStore(Path(directory) / "private-data", allowed_project_root=Path(directory), clock=lambda: NOW)
        app = BatchImportApp(store, baselines={}, clock=lambda: NOW, csrf_token="csrf-d13-race")
        observation = {
            "schema_version": "CDH-B15-MANUAL-OBSERVATION-1",
            "submission_id": "SUB-D13-RACE-0001",
            "title": "D13 race synthetic",
            "identity": {"platform": "COUPANG_TW", "product_id": "PROD-D13-RACE", "sku_id": "SKU-D13-RACE", "seller_id": "SELLER-D13", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD"},
            "observed_at": "2026-11-03T12:00:00+08:00",
            "quantity": 1,
            "before_coupon_price_twd": 1000,
            "user_reported_coupon": {"status": "NONE", "price_twd": None, "eligibility": "UNKNOWN", "evidence_level": "NONE", "evidence_note": None, "valid_from": None, "valid_until": None},
            "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None},
            "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "D13 race synthetic"},
        }
        import base64

        file_bytes = json.dumps({"schema_version": "CDH-B16-BATCH-FILE-1", "observations": [observation]}, separators=(",", ":")).encode("utf-8")
        preview_request = {
            "schema_version": "CDH-B16-BATCH-PREVIEW-REQUEST-1",
            "filename": "race.json",
            "media_type": "application/json",
            "content_base64": base64.b64encode(file_bytes).decode("ascii"),
        }
        preview_status, preview = call(app, "/api/private-observations/v1/batch-preview", preview_request)
        confirm_request = {
            "schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1",
            "preview_id": preview["preview_id"],
            "confirm_token": preview["confirm_token"],
            "explicit_confirm": True,
        }
        results: list[tuple[int, dict[str, object]]] = []

        def worker():
            results.append(call(app, "/api/private-observations/v1/batch-confirm", confirm_request))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        statuses = sorted(status for status, _body in results)
        result = {
            "schema_version": "CDH-D13-CONCURRENT-TOKEN-MIN-REPRO-1",
            "b16_sha256": "d2149952fe1693381f74ac639a770b393b8703a368df68eea990cd5e231cf23b",
            "preview_status": preview_status,
            "concurrent_confirm_statuses": statuses,
            "inserted_counts": sorted(int(body.get("inserted_count", -1)) for _status, body in results),
            "database_observation_count": store.observation_count(),
            "one_time_token_gate": "FAIL" if statuses == [200, 201] else "NOT_REPRODUCED",
            "duplicate_row_gate": "PASS" if store.observation_count() == 1 else "FAIL",
            "root_cause": "PendingBatches.get() does not atomically consume or claim the token; consume() runs only after commit_batch().",
        }
    evidence = ROOT / "review" / "D13" / "001" / "evidence" / "CONCURRENT_TOKEN_MIN_REPRO.json"
    evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["one_time_token_gate"] == "FAIL" and result["duplicate_row_gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
