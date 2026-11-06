from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "import_staging_b14"))
sys.path.insert(0, str(ROOT / "services" / "import_staging_b12"))

from import_staging_b12.staging import record_sha256  # noqa: E402
from import_staging_b14.api import PreviewStatusApp  # noqa: E402
from import_staging_b14.cli import main as cli_main  # noqa: E402
from import_staging_b14.preview import StrictIngressError, build_preview  # noqa: E402


NOW = datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc)
B12_SERVICE = ROOT / "services" / "import_staging_b12"
BRIDGE = B12_SERVICE / "fixtures" / "synthetic_c09_bridge.json"
BUNDLE = B12_SERVICE / "fixtures" / "synthetic_c09_request_bundle.json"
DEPENDENCY_ROOT = ROOT / "review" / "releases"
if not (DEPENDENCY_ROOT / "CDH_B_R09_001_REVIEW.zip").is_file():
    DEPENDENCY_ROOT = ROOT / "upstream"


def dependency(name: str, role: str) -> Path:
    if DEPENDENCY_ROOT.name == "releases":
        return DEPENDENCY_ROOT / name
    return DEPENDENCY_ROOT / role / name


B13_RELEASE = dependency("CDH_B_R09_001_REVIEW.zip", "B13")
B12_RELEASE = dependency("CDH_B_R08_001_REVIEW.zip", "B12")
C09_RELEASE = dependency("CDH_C_R08_001_REVIEW.zip", "C09")
B11_RELEASE = dependency("CDH_B_R07_001_REVIEW.zip", "B11")


def request(app, path, *, method="GET", headers=None):
    headers = headers or {}
    path_info, _, query = path.partition("?")
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path_info, "QUERY_STRING": query}
    for name, value in headers.items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(response_headers)

    raw = b"".join(app(environ, start_response))
    return captured["status"], json.loads(raw) if raw else None, captured["headers"]


class B14StrictIngressTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "review" / "B14" / "tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix="case-", dir=base))
        self.record = json.loads(BRIDGE.read_text(encoding="utf-8"))[0]
        self.bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))

    def tearDown(self):
        shutil.rmtree(self.temp)

    def kwargs(self, input_path=BRIDGE, bundle_path=BUNDLE):
        return {
            "input_root": input_path.parent if input_path != BRIDGE else B12_SERVICE,
            "dependency_root": DEPENDENCY_ROOT,
            "b13_release": B13_RELEASE,
            "b12_release": B12_RELEASE,
            "c09_release": C09_RELEASE,
            "b11_release": B11_RELEASE,
            "as_of": NOW,
            "project_root": ROOT,
            "c09_request_bundle": bundle_path,
        }

    def raw_case(self, text: str) -> Path:
        path = self.temp / "input.json"
        path.write_text(text, encoding="utf-8")
        return path

    def write_case(self, records, *, with_bundle=True):
        path = self.raw_case(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        if not with_bundle:
            return path, None
        bundle = copy.deepcopy(self.bundle)
        bundle["input_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        bundle["bindings"][0]["record_id"] = records[0]["record_id"]
        bundle["bindings"][0]["record_sha256"] = record_sha256(records[0])
        bundle_path = self.temp / "bundle.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path, bundle_path

    def assert_duplicate(self, text: str):
        path = self.raw_case(text)
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(StrictIngressError) as raised:
            build_preview(path, **self.kwargs(input_path=path, bundle_path=None))
        self.assertEqual(raised.exception.code, "JSON_DUPLICATE_KEY")
        self.assertEqual(raised.exception.input_sha256, expected)
        self.assertNotIn("sku", str(raised.exception))

    def actual_preview(self):
        return build_preview(BRIDGE, **self.kwargs())

    def test_exact_b13_b12_c09_preview_is_preserved(self):
        value = self.actual_preview()
        self.assertEqual(value["summary"]["ACCEPTED_FOR_STAGING_PREVIEW"], 1)
        self.assertEqual((value["records"][0]["price_preview"]["before_coupon_price_twd"], value["records"][0]["price_preview"]["display_price_twd"]), (99, 49))
        self.assertEqual(value["dependencies"]["b13_release_sha256"], "aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638")
        self.assertEqual(value["input"]["strict_json_duplicate_gate"], "PASS")

    def test_top_level_duplicate_is_rejected(self):
        self.assert_duplicate('[{"record_id":"A","record_id":"B"}]')

    def test_identity_source_coupon_and_shipping_duplicates_are_rejected(self):
        cases = (
            '[{"identity":{"sku_id":"A","sku_id":"B"}}]',
            '[{"source":{"evidence_id":"A","evidence_id":"B"}}]',
            '[{"coupon":{"status":"NONE","status":"UNKNOWN"}}]',
            '[{"shipping":{"status":"UNKNOWN","status":"KNOWN"}}]',
        )
        for text in cases:
            with self.subTest(text=text):
                self.assert_duplicate(text)

    def test_three_level_nested_duplicate_is_rejected(self):
        self.assert_duplicate('[{"outer":{"middle":{"secret":"A","secret":"B"}}}]')

    def test_unicode_escaped_duplicate_is_rejected(self):
        self.assert_duplicate('[{"identity":{"sku_id":"A","sku_\\u0069d":"B"}}]')

    def test_duplicate_with_same_value_is_rejected(self):
        self.assert_duplicate('[{"identity":{"sku_id":"A","sku_id":"A"}}]')

    def test_case_different_keys_are_not_ingress_duplicates(self):
        path = self.raw_case('[{"x":1,"X":2}]')
        value = build_preview(path, **self.kwargs(input_path=path, bundle_path=None))
        self.assertEqual(value["records"][0]["status"], "INVALID_RECORD")
        self.assertEqual(value["input"]["strict_json_duplicate_gate"], "PASS")

    def test_same_fields_across_records_are_not_ingress_duplicates(self):
        path = self.raw_case('[{"x":1},{"x":2}]')
        value = build_preview(path, **self.kwargs(input_path=path, bundle_path=None))
        self.assertEqual(value["input"]["record_count"], 2)
        self.assertEqual(value["summary"]["INVALID_RECORD"], 2)

    def test_duplicate_gate_precedes_b12_dependency_and_semantics(self):
        path = self.raw_case('[{"identity":{"sku_id":"A","sku_id":"B"}}]')
        kwargs = self.kwargs(input_path=path, bundle_path=None)
        kwargs["b12_release"] = self.temp / "missing-b12.zip"
        with self.assertRaises(StrictIngressError) as raised:
            build_preview(path, **kwargs)
        self.assertEqual(raised.exception.code, "JSON_DUPLICATE_KEY")

    def test_two_mibibyte_boundary_and_overflow(self):
        exact = self.temp / "exact.json"
        exact.write_bytes(b"[]" + b" " * (2 * 1024 * 1024 - 2))
        value = build_preview(exact, **self.kwargs(input_path=exact, bundle_path=None))
        self.assertEqual((value["input"]["bytes"], value["input"]["record_count"]), (2 * 1024 * 1024, 0))
        oversized = self.temp / "oversized.json"
        oversized.write_bytes(b"[]" + b" " * (2 * 1024 * 1024 - 1))
        with self.assertRaises(StrictIngressError) as raised:
            build_preview(oversized, **self.kwargs(input_path=oversized, bundle_path=None))
        self.assertEqual(raised.exception.code, "INPUT_SIZE_LIMIT_EXCEEDED")
        self.assertEqual(raised.exception.input_sha256, hashlib.sha256(oversized.read_bytes()).hexdigest())

    def test_nonstandard_json_number_is_rejected(self):
        path = self.raw_case('[{"x":NaN}]')
        with self.assertRaises(StrictIngressError) as raised:
            build_preview(path, **self.kwargs(input_path=path, bundle_path=None))
        self.assertEqual(raised.exception.code, "JSON_INVALID")

    def test_duplicate_in_c09_bundle_is_rejected(self):
        input_path = self.temp / "valid.json"
        shutil.copyfile(BRIDGE, input_path)
        bundle = self.temp / "bundle.json"
        bundle.write_text('{"schema":"A","schema":"B"}', encoding="utf-8")
        with self.assertRaises(StrictIngressError) as raised:
            build_preview(input_path, **self.kwargs(input_path=input_path, bundle_path=bundle))
        self.assertEqual(raised.exception.code, "C09_BUNDLE_JSON_DUPLICATE_KEY")

    def test_default_source_remains_denied(self):
        value = build_preview(BRIDGE, **self.kwargs(bundle_path=None))
        self.assertEqual(value["records"][0]["status"], "DENIED_PROVENANCE")
        self.assertFalse(value["safety"]["live_source_authorized"])

    def test_expired_coupon_remains_invalid(self):
        record = copy.deepcopy(self.record)
        record["coupon"]["valid_until"] = "2026-11-05T05:00:00Z"
        path, bundle = self.write_case([record])
        value = build_preview(path, **self.kwargs(input_path=path, bundle_path=bundle))
        self.assertEqual(value["records"][0]["status"], "INVALID_RECORD")

    def test_unauthorized_url_is_not_dereferenced_or_echoed(self):
        record = copy.deepcopy(self.record)
        url = "https://example.invalid/not-authorized"
        record["source"]["source_candidate_id"] = url
        path, _ = self.write_case([record], with_bundle=False)
        value = build_preview(path, **self.kwargs(input_path=path, bundle_path=None))
        self.assertEqual(value["records"][0]["status"], "DENIED_PROVENANCE")
        self.assertNotIn(url, json.dumps(value))
        self.assertEqual(value["summary"]["redacted_url_metadata_count"], 1)
        self.assertEqual(value["safety"]["external_request_count"], 0)

    def test_cli_duplicate_error_is_hash_only(self):
        secret_key = "do_not_echo_secret_key"
        secret_value = "do_not_echo_secret_value"
        path = self.raw_case('[{"' + secret_key + '":"A","' + secret_key + '":"' + secret_value + '"}]')
        args = [
            "--input", str(path), "--input-root", str(self.temp), "--dependency-root", str(DEPENDENCY_ROOT),
            "--b13-release", str(B13_RELEASE), "--b12-release", str(B12_RELEASE),
            "--c09-release", str(C09_RELEASE), "--b11-release", str(B11_RELEASE),
            "--as-of", "2026-11-05T06:00:00Z",
        ]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(args), 2)
        body = output.getvalue()
        self.assertNotIn(secret_key, body)
        self.assertNotIn(secret_value, body)
        parsed = json.loads(body)
        self.assertEqual(parsed["code"], "JSON_DUPLICATE_KEY")
        self.assertEqual(parsed["input_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_v2_api_is_get_only_loopback_and_paginated(self):
        app = PreviewStatusApp(self.actual_preview())
        status, body, headers = request(app, "/api/import-preview/v2/status?page=1&limit=1", headers={"Host": "127.0.0.1:8774"})
        self.assertEqual(status, 200)
        self.assertEqual((body["page"], body["limit"], body["total"]), (1, 1, 1))
        self.assertFalse(body["ingress_policy"]["duplicate_json_keys_allowed"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(request(app, "/api/import-preview/v2/status", method="POST")[0], 405)
        self.assertEqual(request(app, "/api/import-preview/v2/status", headers={"Host": "evil.invalid"})[0], 400)
        self.assertEqual(request(app, "/api/import-preview/v2/status", headers={"Origin": "https://evil.invalid"})[0], 403)

    def test_v2_history_and_etag(self):
        preview = self.actual_preview()
        app = PreviewStatusApp(preview)
        status, body, headers = request(app, "/api/import-preview/v2/status")
        self.assertEqual(status, 200)
        self.assertEqual(request(app, "/api/import-preview/v2/status", headers={"If-None-Match": headers["ETag"]})[0], 304)
        key = preview["history_candidates"][0]["identity_key"]
        status, history, _ = request(app, f"/api/import-preview/v2/history/{key}")
        self.assertEqual(status, 200)
        self.assertEqual(history["observations"][0]["confirmed_coupon_price_twd"], 49)

    def test_releases_and_database_state_remain_unchanged(self):
        releases = (B13_RELEASE, B12_RELEASE, C09_RELEASE, B11_RELEASE)
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in releases}
        self.actual_preview()
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in releases})
        databases = [path for path in (ROOT / "services" / "import_staging_b14").rglob("*") if path.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}]
        self.assertEqual(databases, [])


if __name__ == "__main__":
    unittest.main()
