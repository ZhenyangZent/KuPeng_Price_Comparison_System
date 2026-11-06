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

from tools.web_security_d12.archive import B15_MANIFEST_SHA256, B15_SHA256, verify_b15

ROOT = Path(__file__).resolve().parents[3]
B15_ROOTS = (
    ROOT / "review/D12/input_b15/CDH_B_R11_001_REVIEW",
    ROOT / "review/B15/verify_extract/CDH_B_R11_001_REVIEW",
)
B15_ROOT = next((item for item in B15_ROOTS if item.is_dir()), None)
if B15_ROOT is None:
    raise RuntimeError("EXACT_B15_EXTRACTION_MISSING")
sys.path.insert(0, str(B15_ROOT / "services/private_observation_b15"))

from private_observation_b15.api import PendingPreviews, PrivateObservationApp  # noqa: E402
from private_observation_b15.store import ObservationStore  # noqa: E402
from private_observation_b15.validation import parse_and_validate  # noqa: E402

NOW = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)
BASELINE_HASHES = {
    "CDH_B_R10_001_REVIEW.zip": "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9",
    "CDH_C_R10_002_REVIEW.zip": "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa",
    "CDH_B_R07_001_REVIEW.zip": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
}


def releases() -> Path:
    packaged = ROOT / "target_inputs/review/releases"
    return packaged if packaged.is_dir() else ROOT / "review/releases"


def observation(*, submission: str = "SUB-D12-0001", observed: str = "2026-11-03T12:00:00+08:00", before: int = 1000, reported: int | None = 900) -> dict[str, object]:
    has_coupon = reported is not None
    return {
        "schema_version": "CDH-B15-MANUAL-OBSERVATION-1", "submission_id": submission,
        "title": "D12 synthetic private product",
        "identity": {"platform": "COUPANG_TW", "product_id": "PROD-D12", "sku_id": "SKU-D12", "seller_id": "SELLER-D12", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD"},
        "observed_at": observed, "quantity": 1, "before_coupon_price_twd": before,
        "user_reported_coupon": {"status": "USER_REPORTED" if has_coupon else "NONE", "price_twd": reported, "eligibility": "USER_ASSERTED_ELIGIBLE" if has_coupon else "UNKNOWN", "evidence_level": "USER_DESCRIPTION" if has_coupon else "NONE", "evidence_note": "D12 local description" if has_coupon else None, "valid_from": "2026-11-01T00:00:00+08:00" if has_coupon else None, "valid_until": "2026-11-30T23:59:59+08:00" if has_coupon else None},
        "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None},
        "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "D12 private source note"},
    }


def raw(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def request(app, path: str, *, method: str = "GET", body: object | bytes | None = None, headers: dict[str, str] | None = None):
    values = dict(headers or {})
    payload = b"" if body is None else body if isinstance(body, bytes) else raw(body)
    path_info, _, query = path.partition("?")
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path_info, "QUERY_STRING": query, "wsgi.input": io.BytesIO(payload), "CONTENT_LENGTH": str(len(payload)), "CONTENT_TYPE": values.pop("Content-Type", "application/json")}
    for name, value in values.items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value
    captured: dict[str, object] = {}
    def start_response(status, response_headers):
        captured["status"] = int(status.split()[0]); captured["headers"] = dict(response_headers)
    response = b"".join(app(environ, start_response))
    return int(captured["status"]), json.loads(response) if response else None, captured["headers"]


class D12FocusedSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        base = ROOT / "review/D12/tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix="case-", dir=base))
        self.store = ObservationStore(self.temp / "private-data", clock=lambda: NOW)
        self.app = PrivateObservationApp(self.store, baselines=BASELINE_HASHES, clock=lambda: NOW, csrf_token="d12-csrf-token", allowed_origins=("http://127.0.0.1:4173",))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp)

    def preview(self, value: object | None = None):
        status, body, _ = request(self.app, "/api/private-observations/v1/preview", method="POST", body=observation() if value is None else value, headers={"Host": "127.0.0.1:8785", "Origin": "http://127.0.0.1:4173", "X-CDH-CSRF-Token": "d12-csrf-token"})
        self.assertEqual(status, 200)
        return body

    def confirm(self, preview):
        return request(self.app, "/api/private-observations/v1/confirm", method="POST", body={"preview_id": preview["preview_id"], "confirm_token": preview["confirm_token"], "explicit_confirm": True}, headers={"Host": "127.0.0.1:8785", "Origin": "http://127.0.0.1:4173", "X-CDH-CSRF-Token": "d12-csrf-token"})

    def test_01_exact_b15_archive_crc_and_manifest(self):
        result = verify_b15(releases() / "CDH_B_R11_001_REVIEW.zip")
        self.assertEqual((result["zip_sha256"], result["manifest_sha256"]), (B15_SHA256, B15_MANIFEST_SHA256))
        self.assertEqual((result["missing"], result["mismatch"], result["undeclared"], result["duplicates"]), (0, 0, 0, 0))

    def test_02_host_origin_csrf_and_content_type_fail_closed(self):
        self.assertEqual(request(self.app, "/api/private-observations/v1/session", headers={"Host": "evil.invalid"})[0], 400)
        self.assertEqual(request(self.app, "/api/private-observations/v1/session", headers={"Host": "127.0.0.1:8785", "Origin": "https://evil.invalid"})[0], 403)
        self.assertEqual(request(self.app, "/api/private-observations/v1/preview", method="POST", body=observation(), headers={"Host": "127.0.0.1:8785"})[0], 403)
        self.assertEqual(request(self.app, "/api/private-observations/v1/preview", method="POST", body=observation(), headers={"Host": "127.0.0.1:8785", "X-CDH-CSRF-Token": "d12-csrf-token", "Content-Type": "text/plain"})[0], 400)

    def test_03_missing_host_is_accepted_reproducing_p2(self):
        status, body, _ = request(self.app, "/api/private-observations/v1/session")
        self.assertEqual(status, 200)
        self.assertIn("csrf_token", body)

    def test_04_duplicate_json_mutations_rejected_without_echo(self):
        cases = (
            b'{"schema_version":"A","schema_version":"B"}',
            b'{"identity":{"sku_id":"A","sku_id":"B"}}',
            b'{"identity":{"sku_id":"A","sku_\\u0069d":"B"}}',
            b'{"source":{"note":"secret-A","note":"secret-B"}}',
        )
        for payload in cases:
            with self.subTest(payload=hashlib.sha256(payload).hexdigest()):
                status, body, _ = request(self.app, "/api/private-observations/v1/preview", method="POST", body=payload, headers={"Host": "127.0.0.1:8785", "X-CDH-CSRF-Token": "d12-csrf-token"})
                rendered = json.dumps(body)
                self.assertEqual((status, body["error"]["code"], body["error"]["input_sha256"]), (400, "JSON_DUPLICATE_KEY", hashlib.sha256(payload).hexdigest()))
                self.assertNotIn("secret-A", rendered); self.assertNotIn("secret-B", rendered)

    def test_05_oversize_xss_sql_url_and_database_path_rejected_without_write(self):
        oversized = b" " * (128 * 1024 + 1)
        status, body, _ = request(self.app, "/api/private-observations/v1/preview", method="POST", body=oversized, headers={"Host": "127.0.0.1:8785", "X-CDH-CSRF-Token": "d12-csrf-token"})
        self.assertEqual((status, body["error"]["code"]), (400, "REQUEST_BODY_TOO_LARGE"))
        cases = []
        xss = observation(); xss["title"] = "<img src=x onerror=alert(1)>"; cases.append(xss)
        sql = observation(); sql["identity"]["product_id"] = "X' OR 1=1--"; cases.append(sql)
        url = observation(); url["source"]["note"] = "https://example.invalid/private"; cases.append(url)
        path = observation(); path["database_path"] = "C:/outside.sqlite3"; cases.append(path)
        for value in cases:
            with self.subTest(case=list(value)[-1]):
                status, body, _ = request(self.app, "/api/private-observations/v1/preview", method="POST", body=value, headers={"Host": "127.0.0.1:8785", "X-CDH-CSRF-Token": "d12-csrf-token"})
                self.assertEqual(status, 400); self.assertFalse(body["error"]["raw_content_included"])
        self.assertFalse(self.store.database.exists())

    def test_06_explicit_confirmation_one_time_token_and_idempotency(self):
        preview = self.preview()
        invalid = {"preview_id": preview["preview_id"], "confirm_token": preview["confirm_token"], "explicit_confirm": False}
        self.assertEqual(request(self.app, "/api/private-observations/v1/confirm", method="POST", body=invalid, headers={"Host": "127.0.0.1:8785", "X-CDH-CSRF-Token": "d12-csrf-token"})[0], 400)
        first = self.confirm(preview); self.assertEqual(first[0], 201)
        self.assertEqual(self.confirm(preview)[0], 400)
        replay = self.confirm(self.preview()); self.assertEqual(replay[0], 200)
        self.assertTrue(replay[1]["idempotent_replay"]); self.assertEqual(self.store.observation_count(), 1)

    def test_07_submission_conflict_does_not_add_observation(self):
        self.assertEqual(self.confirm(self.preview())[0], 201)
        changed = observation(before=999)
        status, body, _ = self.confirm(self.preview(changed))
        self.assertEqual((status, body["error"]["code"], self.store.observation_count()), (409, "SUBMISSION_ID_CONTENT_CONFLICT", 1))

    def test_08_private_coupon_never_escalates_and_readback_does_not_leak_note(self):
        preview = self.preview()
        self.assertIsNone(preview["will_save"]["confirmed_after_coupon_price_twd"])
        self.assertEqual(self.confirm(preview)[0], 201)
        status, search, _ = request(self.app, "/api/private-observations/v1/products", headers={"Host": "127.0.0.1:8785"})
        self.assertEqual(status, 200); series = search["items"][0]["series_key"]
        status, detail, _ = request(self.app, "/api/private-observations/v1/products/" + series, headers={"Host": "127.0.0.1:8785"})
        rendered = json.dumps(detail, ensure_ascii=False)
        self.assertEqual(status, 200); self.assertEqual(detail["history"]["confirmed_after_coupon"], [])
        self.assertEqual(detail["history"]["user_reported_after_coupon"][0]["price_twd"], 900)
        self.assertNotIn("D12 private source note", rendered)
        self.assertFalse(detail["product"]["cta_enabled"]); self.assertIsNone(detail["product"]["click_url"])

    def test_09_unknown_shipping_never_becomes_zero_total(self):
        normalized = self.preview()["will_save"]
        self.assertIsNone(normalized["required_total_twd"]); self.assertIsNone(normalized["user_reported_required_total_twd"])

    def test_10_transaction_failure_rolls_back_observation_and_audit(self):
        self.assertEqual(self.confirm(self.preview())[0], 201)
        connection = sqlite3.connect(self.store.database)
        connection.execute("CREATE TRIGGER fail_d12 BEFORE INSERT ON observations WHEN NEW.submission_id='SUB-D12-FAIL' BEGIN SELECT RAISE(ABORT,'d12 synthetic failure'); END")
        connection.commit(); connection.close()
        value = parse_and_validate(raw(observation(submission="SUB-D12-FAIL", observed="2026-11-04T12:00:00+08:00")), now=NOW)
        with self.assertRaises(sqlite3.IntegrityError): self.store.commit(value)
        connection = sqlite3.connect(self.store.database)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM commit_audit").fetchone()[0], 1)
        connection.close()

    def test_11_baseline_release_hashes_unchanged_after_commit(self):
        paths = {name: releases() / name for name in BASELINE_HASHES}
        before = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
        self.assertEqual(before, BASELINE_HASHES)
        self.assertEqual(self.confirm(self.preview())[0], 201)
        self.assertEqual(before, {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()})

    def test_12_expired_pending_previews_accumulate_reproducing_p2(self):
        monotonic = [1.0]
        pending = PendingPreviews(ttl_seconds=1, clock=lambda: monotonic[0])
        normalized = parse_and_validate(raw(observation()), now=NOW)
        for _ in range(32): pending.create(copy.deepcopy(normalized))
        monotonic[0] = 100.0
        self.assertEqual(len(pending._items), 32)

    def test_13_each_unique_commit_retains_full_backup_reproducing_p2(self):
        for index in range(4):
            value = observation(submission=f"SUB-D12-BACKUP-{index:02d}", observed=f"2026-11-0{index + 1}T12:00:00+08:00", before=1000 - index, reported=None)
            self.assertEqual(self.confirm(self.preview(value))[0], 201)
        backups = list(self.store.backup_root.glob("*.sqlite3"))
        self.assertEqual(len(backups), 3)
        self.assertGreater(sum(item.stat().st_size for item in backups), self.store.database.stat().st_size)

    def test_14_actual_reparse_escape_evidence_is_bound_to_vulnerable_source(self):
        evidence = json.loads((ROOT / "review/D12/REPARSE_ESCAPE_EVIDENCE.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["finding"], "P1_ANCESTOR_REPARSE_PROJECT_ESCAPE")
        self.assertTrue(evidence["escaped_nominal_project"] and evidence["landed_in_junction_target"] and evidence["database_created"])
        self.assertEqual((evidence["sqlite_integrity"], evidence["observation_count"]), ("ok", 1))
        source = (B15_ROOT / "services/private_observation_b15/private_observation_b15/store.py").read_text(encoding="utf-8")
        self.assertIn("if raw_root.exists() and _is_reparse(raw_root)", source)
        self.assertNotIn("for part in raw_root", source)


if __name__ == "__main__":
    unittest.main()
