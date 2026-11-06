from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tools.web_security_d12_rev2.archive import B15_MANIFEST_SHA256, B15_SHA256, verify_b15

ROOT = Path(__file__).resolve().parents[3]
B15_ROOT = ROOT / "review/D12/002/input/CDH_B_R11_002_REVIEW"
if not B15_ROOT.is_dir():
    raise RuntimeError("EXACT_B15_REV2_EXTRACTION_MISSING")
sys.path.insert(0, str(B15_ROOT / "services/private_observation_b15"))

from private_observation_b15.api import PendingPreviews, PrivateObservationApp  # noqa: E402
from private_observation_b15.store import ObservationStore, StoreError  # noqa: E402
from private_observation_b15.validation import ValidationError, parse_and_validate  # noqa: E402

NOW = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)


def observation(*, submission: str = "SUB-D12-REV2-0001", observed: str = "2026-11-03T12:00:00+08:00", before: int = 1000, reported: int | None = 900) -> dict[str, object]:
    has_coupon = reported is not None
    return {
        "schema_version": "CDH-B15-MANUAL-OBSERVATION-1",
        "submission_id": submission,
        "title": "D12 REV2 synthetic private product",
        "identity": {"platform": "COUPANG_TW", "product_id": "PROD-D12-REV2", "sku_id": "SKU-D12-REV2", "seller_id": "SELLER-D12", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD"},
        "observed_at": observed,
        "quantity": 1,
        "before_coupon_price_twd": before,
        "user_reported_coupon": {"status": "USER_REPORTED" if has_coupon else "NONE", "price_twd": reported, "eligibility": "USER_ASSERTED_ELIGIBLE" if has_coupon else "UNKNOWN", "evidence_level": "USER_DESCRIPTION" if has_coupon else "NONE", "evidence_note": "D12 isolated description" if has_coupon else None, "valid_from": "2026-11-01T00:00:00+08:00" if has_coupon else None, "valid_until": "2026-11-30T23:59:59+08:00" if has_coupon else None},
        "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None},
        "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "D12 isolated private source"},
    }


def raw(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


_DEFAULT_HOST = object()


def request(app, path: str, *, method: str = "GET", body: object | bytes | None = None, headers: dict[str, str] | None = None, host: object = _DEFAULT_HOST):
    values = dict(headers or {})
    payload = b"" if body is None else body if isinstance(body, bytes) else raw(body)
    path_info, _, query = path.partition("?")
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path_info, "QUERY_STRING": query, "wsgi.input": io.BytesIO(payload), "CONTENT_LENGTH": str(len(payload)), "CONTENT_TYPE": values.pop("Content-Type", "application/json")}
    if host is _DEFAULT_HOST:
        environ["HTTP_HOST"] = "127.0.0.1:8785"
    elif host is not None:
        environ["HTTP_HOST"] = str(host)
    for name, value in values.items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value
    captured: dict[str, object] = {}

    def start_response(status, response_headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(response_headers)

    response = b"".join(app(environ, start_response))
    return int(captured["status"]), json.loads(response) if response else None, captured["headers"]


class D12Rev2SecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        base = ROOT / "review/D12/002/tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix="case-", dir=base))
        self.store = ObservationStore(self.temp / "private-data", allowed_project_root=self.temp, clock=lambda: NOW)
        self.app = PrivateObservationApp(self.store, baselines={"B15_REV2": B15_SHA256}, clock=lambda: NOW, csrf_token="d12-rev2-csrf", allowed_origins=("http://127.0.0.1:4173",))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp)

    def preview(self, value: object | None = None):
        status, body, _ = request(self.app, "/api/private-observations/v1/preview", method="POST", body=observation() if value is None else value, headers={"X-CDH-CSRF-Token": "d12-rev2-csrf"})
        self.assertEqual(status, 200)
        return body

    def confirm(self, preview):
        return request(self.app, "/api/private-observations/v1/confirm", method="POST", body={"preview_id": preview["preview_id"], "confirm_token": preview["confirm_token"], "explicit_confirm": True}, headers={"X-CDH-CSRF-Token": "d12-rev2-csrf"})

    def test_01_exact_archive_crc_manifest_and_payloads(self):
        result = verify_b15(ROOT / "review/releases/CDH_B_R11_002_REVIEW.zip")
        self.assertEqual((result["zip_sha256"], result["manifest_sha256"]), (B15_SHA256, B15_MANIFEST_SHA256))
        self.assertEqual((result["missing"], result["mismatch"], result["undeclared"], result["duplicates"]), (0, 0, 0, 0))

    def test_02_host_origin_csrf_and_duplicate_json_fail_closed(self):
        status, body, _ = request(self.app, "/api/private-observations/v1/session", host=None)
        self.assertEqual((status, body["error"]["code"]), (400, "HOST_REQUIRED"))
        self.assertEqual(request(self.app, "/api/private-observations/v1/session", headers={"Origin": "https://evil.invalid"})[0], 403)
        self.assertEqual(request(self.app, "/api/private-observations/v1/preview", method="POST", body=observation())[0], 403)
        duplicate = b'{"identity":{"sku_id":"A","sku_\\u0069d":"B"}}'
        status, body, _ = request(self.app, "/api/private-observations/v1/preview", method="POST", body=duplicate, headers={"X-CDH-CSRF-Token": "d12-rev2-csrf"})
        self.assertEqual((status, body["error"]["code"], body["error"]["input_sha256"]), (400, "JSON_DUPLICATE_KEY", hashlib.sha256(duplicate).hexdigest()))
        self.assertFalse(self.store.database.exists())

    def test_03_identity_and_coupon_elevation_are_rejected_or_separated(self):
        wrong = observation()
        wrong["source"] = {"source_class": "PLATFORM_VERIFIED", "visibility": "PUBLIC", "note": "forged"}
        self.assertEqual(request(self.app, "/api/private-observations/v1/preview", method="POST", body=wrong, headers={"X-CDH-CSRF-Token": "d12-rev2-csrf"})[0], 400)
        preview = self.preview()
        self.assertIsNone(preview["will_save"]["confirmed_after_coupon_price_twd"])
        self.assertEqual(self.confirm(preview)[0], 201)
        search = request(self.app, "/api/private-observations/v1/products?q=PROD-D12-REV2&page=1&limit=20")[1]
        detail = request(self.app, "/api/private-observations/v1/products/" + search["items"][0]["series_key"])[1]
        self.assertEqual(detail["history"]["confirmed_after_coupon"], [])
        self.assertEqual(detail["history"]["user_reported_after_coupon"][0]["price_twd"], 900)

    def test_04_preview_count_byte_capacity_and_ttl_are_enforced(self):
        tick = [1.0]
        normalized = parse_and_validate(raw(observation()), now=NOW)
        size = len(raw(normalized))
        pending = PendingPreviews(ttl_seconds=1, clock=lambda: tick[0], max_items=2, max_total_bytes=max(1024, size * 2 + 16))
        pending.create(copy.deepcopy(normalized))
        pending.create(copy.deepcopy(normalized))
        with self.assertRaises(ValidationError) as raised:
            pending.create(copy.deepcopy(normalized))
        self.assertEqual(raised.exception.code, "PREVIEW_CAPACITY_EXCEEDED")
        tick[0] = 3.0
        self.assertEqual(pending.retained_count(), 0)
        byte_limited = PendingPreviews(ttl_seconds=60, max_items=8, max_total_bytes=max(1024, size + 16))
        byte_limited.create(copy.deepcopy(normalized))
        with self.assertRaises(ValidationError):
            byte_limited.create(copy.deepcopy(normalized))

    def test_05_backup_count_and_capacity_fail_closed(self):
        bounded = ObservationStore(self.temp / "bounded", allowed_project_root=self.temp, clock=lambda: NOW, max_backups=3, min_backups_to_keep=2)
        for index in range(5):
            value = observation(submission=f"SUB-D12-BOUND-{index:04d}", observed=f"2026-11-0{index + 1}T01:00:00+08:00", before=1000 - index, reported=None)
            bounded.commit(parse_and_validate(raw(value), now=NOW))
        backups = list(bounded.backup_root.glob("*.sqlite3"))
        self.assertGreaterEqual(len(backups), 2)
        self.assertLessEqual(len(backups), 3)
        capacity = ObservationStore(self.temp / "capacity", allowed_project_root=self.temp, clock=lambda: NOW, max_backups=2, min_backups_to_keep=1, max_backup_bytes=1)
        capacity.commit(parse_and_validate(raw(observation(submission="SUB-D12-CAP-0001", reported=None)), now=NOW))
        with self.assertRaises(StoreError):
            capacity.commit(parse_and_validate(raw(observation(submission="SUB-D12-CAP-0002", observed="2026-11-04T01:00:00+08:00", reported=None)), now=NOW))
        self.assertEqual(capacity.observation_count(), 1)
        self.assertEqual(list(capacity.backup_root.glob("*.sqlite3")), [])

    def test_06_transaction_failure_leaves_no_partial_rows_or_outside_database(self):
        self.assertEqual(self.confirm(self.preview())[0], 201)
        connection = sqlite3.connect(self.store.database)
        connection.execute("CREATE TRIGGER fail_d12_rev2 BEFORE INSERT ON observations WHEN NEW.submission_id='SUB-D12-REV2-FAIL' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        connection.commit()
        connection.close()
        failed = parse_and_validate(raw(observation(submission="SUB-D12-REV2-FAIL", observed="2026-11-04T12:00:00+08:00")), now=NOW)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.commit(failed)
        connection = sqlite3.connect(self.store.database)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM commit_audit").fetchone()[0], 1)
        connection.close()
        outside = self.temp.parent / (self.temp.name + "-outside")
        with self.assertRaises(StoreError):
            ObservationStore(outside, allowed_project_root=self.temp)
        injected = observation()
        injected["database_path"] = str(outside / "escape.sqlite3")
        self.assertEqual(request(self.app, "/api/private-observations/v1/preview", method="POST", body=injected, headers={"X-CDH-CSRF-Token": "d12-rev2-csrf"})[0], 400)
        self.assertFalse(outside.exists())

    def test_07_windows_junction_probe_evidence_passes_without_outside_sqlite(self):
        evidence = json.loads((ROOT / "review/D12/002/evidence/WINDOWS_JUNCTION_PROBE.json").read_text(encoding="utf-8"))
        self.assertEqual((evidence["platform"], evidence["gate"]), ("win32", "PASS"))
        self.assertTrue(evidence["constructor_rejected"])
        self.assertEqual(evidence["outside_sqlite_created_count"], 0)

    def test_08_actual_loopback_http_evidence_passes(self):
        evidence = json.loads((ROOT / "review/D12/002/evidence/ACTUAL_HTTP_PROBE.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["status_gate"], "PASS")
        self.assertEqual(evidence["statuses"], [400, 403, 400, 403, 200, 201])
        self.assertEqual((evidence["external_request_count"], evidence["observation_count"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
