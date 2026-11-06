from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "import_staging_b13"))
sys.path.insert(0, str(ROOT / "services" / "import_staging_b12"))

from import_staging_b12.staging import CSV_FIELDS, record_sha256  # noqa: E402
from import_staging_b13.api import PreviewStatusApp  # noqa: E402
from import_staging_b13.cli import main as cli_main  # noqa: E402
from import_staging_b13.preview import PreviewError, build_preview  # noqa: E402
from import_staging_b13.server import main as server_main  # noqa: E402

NOW = datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc)
B12_SERVICE = ROOT / "services" / "import_staging_b12"
BRIDGE = B12_SERVICE / "fixtures" / "synthetic_c09_bridge.json"
BUNDLE = B12_SERVICE / "fixtures" / "synthetic_c09_request_bundle.json"
DEPENDENCY_ROOT = ROOT / "review" / "releases"
if not (DEPENDENCY_ROOT / "CDH_B_R08_001_REVIEW.zip").is_file():
    DEPENDENCY_ROOT = ROOT / "upstream"
B12_RELEASE = DEPENDENCY_ROOT / ("CDH_B_R08_001_REVIEW.zip" if DEPENDENCY_ROOT.name == "releases" else "B12/CDH_B_R08_001_REVIEW.zip")
C09_RELEASE = DEPENDENCY_ROOT / ("CDH_C_R08_001_REVIEW.zip" if DEPENDENCY_ROOT.name == "releases" else "C09/CDH_C_R08_001_REVIEW.zip")
B11_RELEASE = DEPENDENCY_ROOT / ("CDH_B_R07_001_REVIEW.zip" if DEPENDENCY_ROOT.name == "releases" else "B11/CDH_B_R07_001_REVIEW.zip")


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


def flatten(record):
    result = {}
    for name in CSV_FIELDS:
        if "." in name:
            group, field = name.split(".", 1)
            value = record[group][field]
        else:
            value = record[name]
        if value is None:
            value = ""
        elif isinstance(value, bool):
            value = "true" if value else "false"
        result[name] = value
    return result


class B13PreviewTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "review" / "B13" / "tmp_tests"
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
            "b12_release": B12_RELEASE,
            "c09_release": C09_RELEASE,
            "b11_release": B11_RELEASE,
            "as_of": NOW,
            "project_root": ROOT,
            "c09_request_bundle": bundle_path,
        }

    def write_case(self, records, *, mutate_request=None):
        input_path = self.temp / "input.json"
        input_path.write_text(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        bundle = copy.deepcopy(self.bundle)
        bundle["input_sha256"] = hashlib.sha256(input_path.read_bytes()).hexdigest()
        bundle["bindings"][0]["record_id"] = records[0]["record_id"]
        bundle["bindings"][0]["record_sha256"] = record_sha256(records[0])
        if mutate_request:
            mutate_request(bundle["bindings"][0]["request"])
        bundle_path = self.temp / "bundle.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return input_path, bundle_path

    def actual_preview(self):
        return build_preview(BRIDGE, **self.kwargs())

    def test_actual_b12_c09_exact_preview(self):
        value = self.actual_preview()
        self.assertEqual(value["summary"]["ACCEPTED_FOR_STAGING_PREVIEW"], 1)
        item = value["records"][0]
        self.assertEqual((item["price_preview"]["before_coupon_price_twd"], item["price_preview"]["display_price_twd"]), (99, 49))
        self.assertEqual(item["field_errors"], [])
        self.assertFalse(item["raw_content_included"])
        self.assertEqual(value["dependencies"]["b11_sha256_before"], value["dependencies"]["b11_sha256_after"])
        self.assertEqual(value["safety"]["database_write_count"], 0)

    def test_missing_c09_bundle_defaults_to_deny_and_preserves_source_metadata(self):
        kwargs = self.kwargs(bundle_path=None)
        value = build_preview(BRIDGE, **kwargs)
        item = value["records"][0]
        self.assertEqual(item["status"], "DENIED_PROVENANCE")
        self.assertIn("C09_VERIFIER_UNAVAILABLE", item["reasons"])
        self.assertEqual(item["source"]["evidence_id"], "EVIDENCE:C09:001")
        self.assertNotIn("observations", json.dumps(item["source"]))

    def test_csv_formula_injection_is_per_record_invalid(self):
        target = self.temp / "formula.csv"
        row = flatten(self.record)
        row["title"] = "=HYPERLINK(\"https://example.invalid\")"
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerow(row)
        value = build_preview(target, **self.kwargs(input_path=target, bundle_path=None))
        item = value["records"][0]
        self.assertEqual(item["status"], "INVALID_RECORD")
        self.assertIn("CSV_FORMULA_INJECTION", item["reasons"])
        self.assertEqual(value["summary"]["formula_injection_count"], 1)
        self.assertNotIn("HYPERLINK", json.dumps(value))

    def test_all_csv_formula_prefixes_and_extra_columns_are_invalid(self):
        for prefix in ("=", "+", "-", "@"):
            target = self.temp / f"formula-{ord(prefix)}.csv"
            row = flatten(self.record)
            row["title"] = prefix + "unsafe"
            with target.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
                writer.writeheader()
                writer.writerow(row)
            value = build_preview(target, **self.kwargs(input_path=target, bundle_path=None))
            self.assertIn("CSV_FORMULA_INJECTION", value["records"][0]["reasons"])
        extra = self.temp / "extra.csv"
        extra.write_text(",".join(CSV_FIELDS) + "\n" + ",".join(str(flatten(self.record)[name]) for name in CSV_FIELDS) + ",UNDECLARED\n", encoding="utf-8")
        value = build_preview(extra, **self.kwargs(input_path=extra, bundle_path=None))
        self.assertEqual(value["records"][0]["status"], "INVALID_RECORD")
        self.assertIn("CSV_EXTRA_COLUMN", value["records"][0]["reasons"])

    def test_zero_is_distinct_from_null_with_actual_c09(self):
        record = copy.deepcopy(self.record)
        record["base_price_twd"] = 0
        record["coupon"]["discount_twd"] = 0
        path, bundle = self.write_case([record])
        value = build_preview(path, **self.kwargs(input_path=path, bundle_path=bundle))
        price = value["records"][0]["price_preview"]
        self.assertEqual(price["display_price_twd"], 0)
        self.assertIsNone(price["required_total_twd"])

    def test_quantity_two_order_discount_with_actual_c09(self):
        record = copy.deepcopy(self.record)
        record["base_price_twd"] = 100
        record["minimum_purchase_quantity"] = 2
        record["coupon"]["discount_twd"] = 50
        record["coupon"]["discount_scope"] = "ORDER_TOTAL"
        path, bundle = self.write_case([record], mutate_request=lambda req: req["staged_record"]["identity"].update({"quantity": 2}))
        value = build_preview(path, **self.kwargs(input_path=path, bundle_path=bundle))
        price = value["records"][0]["price_preview"]
        self.assertEqual((price["display_price_twd"], price["minimum_item_spend_twd"]), (75, 150))

    def test_duplicate_is_noop_and_history_has_one_observation(self):
        path, bundle = self.write_case([copy.deepcopy(self.record), copy.deepcopy(self.record)])
        value = build_preview(path, **self.kwargs(input_path=path, bundle_path=bundle))
        self.assertEqual([item["status"] for item in value["records"]], ["ACCEPTED_FOR_STAGING_PREVIEW", "NOOP_DUPLICATE"])
        self.assertEqual(value["history_candidates"][0]["observation_count"], 1)

    def test_same_series_different_sku_is_conflict_not_merge(self):
        second = copy.deepcopy(self.record)
        second["record_id"] = "REC:C09:002"
        second["identity"]["sku_id"] = "SKU:C09:002"
        second["coupon"]["target_sku_id"] = "SKU:C09:002"
        second["source"]["evidence_id"] = "EVIDENCE:C09:002"
        second["observed_at"] = "2026-11-05T05:10:00Z"
        path, bundle = self.write_case([copy.deepcopy(self.record), second])
        value = build_preview(path, **self.kwargs(input_path=path, bundle_path=bundle))
        self.assertEqual(value["records"][1]["status"], "CONFLICT")
        self.assertIn("SERIES_IDENTITY_MISMATCH", value["records"][1]["reasons"])

    def test_user_file_never_becomes_allowed(self):
        record = copy.deepcopy(self.record)
        record["source"]["data_classification"] = "USER_PROVIDED_OBSERVATION"

        def mutate(request_value):
            request_value["provenance"]["source"]["source_class"] = "USER_FILE"
            request_value["provenance"]["source"]["declared_source_class"] = "USER_FILE"

        path, bundle = self.write_case([record], mutate_request=mutate)
        value = build_preview(path, **self.kwargs(input_path=path, bundle_path=bundle))
        self.assertEqual(value["records"][0]["status"], "DENIED_PROVENANCE")
        self.assertFalse(value["safety"]["live_source_authorized"])

    def test_expired_coupon_and_future_timestamp_fail_closed(self):
        expired = copy.deepcopy(self.record)
        expired["coupon"]["valid_until"] = "2026-11-05T05:00:00Z"
        future = copy.deepcopy(self.record)
        future["record_id"] = "REC:C09:002"
        future["observed_at"] = "2026-11-06T00:00:00Z"
        path, bundle = self.write_case([expired, future])
        value = build_preview(path, **self.kwargs(input_path=path, bundle_path=bundle))
        self.assertEqual([item["status"] for item in value["records"]], ["INVALID_RECORD", "INVALID_RECORD"])

    def test_large_record_count_and_outside_path_are_refused(self):
        too_many = self.temp / "too_many.json"
        too_many.write_text("[" + ",".join("{}" for _ in range(10001)) + "]", encoding="utf-8")
        with self.assertRaises(PreviewError):
            build_preview(too_many, **self.kwargs(input_path=too_many, bundle_path=None))
        outside = self.temp / "outside.json"
        outside.write_text("[]", encoding="utf-8")
        with self.assertRaises(PreviewError):
            build_preview(outside, **self.kwargs(input_path=BRIDGE, bundle_path=None))

    def test_two_mibibyte_limit_is_enforced(self):
        oversized = self.temp / "oversized.json"
        oversized.write_bytes(b" " * (2 * 1024 * 1024 + 1))
        with self.assertRaises(PreviewError):
            build_preview(oversized, **self.kwargs(input_path=oversized, bundle_path=None))

    def test_negative_price_and_refund_field_fail_closed(self):
        negative = copy.deepcopy(self.record)
        negative["base_price_twd"] = -1
        refund = copy.deepcopy(self.record)
        refund["record_id"] = "REC:C09:002"
        refund["refund_twd"] = 10
        path, _ = self.write_case([negative, refund])
        value = build_preview(path, **self.kwargs(input_path=path, bundle_path=None))
        self.assertEqual([item["status"] for item in value["records"]], ["INVALID_RECORD", "INVALID_RECORD"])
        self.assertIn("BASE_PRICE_INVALID", value["records"][0]["reasons"])
        self.assertIn("TOP_LEVEL_FIELDS_MISMATCH", value["records"][1]["reasons"])

    def test_tampered_b12_release_is_rejected(self):
        dependency = self.temp / "deps"
        dependency.mkdir()
        bad = dependency / "b12.zip"
        data = bytearray(B12_RELEASE.read_bytes())
        data[-1] ^= 1
        bad.write_bytes(data)
        c09 = dependency / "c09.zip"
        b11 = dependency / "b11.zip"
        shutil.copyfile(C09_RELEASE, c09)
        shutil.copyfile(B11_RELEASE, b11)
        with self.assertRaises(PreviewError):
            build_preview(BRIDGE, input_root=B12_SERVICE, dependency_root=dependency, b12_release=bad, c09_release=c09, b11_release=b11, as_of=NOW, project_root=ROOT, c09_request_bundle=None)

    def test_sensitive_invalid_values_are_not_echoed(self):
        record = copy.deepcopy(self.record)
        secret = "Bearer " + "x" * 32
        record["source"]["source_candidate_id"] = secret
        path, _ = self.write_case([record])
        value = build_preview(path, **self.kwargs(input_path=path, bundle_path=None))
        serialized = json.dumps(value)
        self.assertNotIn(secret, serialized)
        self.assertIsNone(value["records"][0]["source"]["source_candidate_id"])

    def test_preview_is_deterministic(self):
        self.assertEqual(self.actual_preview(), self.actual_preview())

    def test_status_api_paginates_and_applies_security(self):
        app = PreviewStatusApp(self.actual_preview())
        status, body, headers = request(app, "/api/import-preview/v1/status?page=1&limit=1", headers={"Host": "127.0.0.1:8773"})
        self.assertEqual(status, 200)
        self.assertEqual((body["page"], body["limit"], body["total"]), (1, 1, 1))
        self.assertEqual(len(body["records"]), 1)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        etag = headers["ETag"]
        self.assertEqual(request(app, "/api/import-preview/v1/status", headers={"If-None-Match": etag})[0], 304)
        self.assertEqual(request(app, "/missing", headers={"If-None-Match": etag})[0], 404)
        self.assertEqual(request(app, "/api/import-preview/v1/status", headers={"Host": "evil.invalid"})[0], 400)
        self.assertEqual(request(app, "/api/import-preview/v1/status", headers={"Origin": "https://evil.invalid"})[0], 403)
        self.assertEqual(request(app, "/api/import-preview/v1/status", method="POST")[0], 405)

    def test_history_api_uses_exact_identity_key(self):
        preview = self.actual_preview()
        key = preview["history_candidates"][0]["identity_key"]
        app = PreviewStatusApp(preview)
        status, body, _ = request(app, f"/api/import-preview/v1/history/{key}")
        self.assertEqual(status, 200)
        self.assertEqual((body["total"], body["observations"][0]["confirmed_coupon_price_twd"]), (1, 49))
        self.assertEqual(request(app, "/api/import-preview/v1/history/not-a-key")[0], 404)

    def test_api_query_bounds_and_unknown_path(self):
        app = PreviewStatusApp(self.actual_preview())
        self.assertEqual(request(app, "/api/import-preview/v1/status?limit=101")[0], 400)
        self.assertEqual(request(app, "/api/import-preview/v1/status?x=1")[0], 400)
        self.assertEqual(request(app, "/api/import-preview/v1/status?page=1&page=2")[0], 400)
        self.assertEqual(request(app, "/api/import-preview/v1/status?x=" + "a" * 2050)[0], 400)
        self.assertEqual(request(app, "/missing")[0], 404)

    def test_cli_exact_and_default_deny_exit_codes(self):
        common = ["--input", str(BRIDGE), "--input-root", str(B12_SERVICE), "--dependency-root", str(DEPENDENCY_ROOT), "--b12-release", str(B12_RELEASE), "--c09-release", str(C09_RELEASE), "--b11-release", str(B11_RELEASE), "--as-of", "2026-11-05T06:00:00Z"]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main([*common, "--c09-request-bundle", str(BUNDLE), "--require-all-accepted"]), 0)
        self.assertEqual(json.loads(output.getvalue())["summary"]["ACCEPTED_FOR_STAGING_PREVIEW"], 1)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli_main([*common, "--require-all-accepted"]), 3)

    def test_server_check_and_nonloopback_rejection(self):
        common = ["--input", str(BRIDGE), "--input-root", str(B12_SERVICE), "--dependency-root", str(DEPENDENCY_ROOT), "--b12-release", str(B12_RELEASE), "--c09-release", str(C09_RELEASE), "--b11-release", str(B11_RELEASE), "--c09-request-bundle", str(BUNDLE), "--as-of", "2026-11-05T06:00:00Z", "--check"]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(server_main(common), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "READY")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            server_main([*common, "--host", "0.0.0.0"])

    def test_no_database_files_created_and_releases_unchanged(self):
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (B12_RELEASE, C09_RELEASE, B11_RELEASE)}
        self.actual_preview()
        after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before}
        self.assertEqual(before, after)
        databases = [path for path in (ROOT / "services" / "import_staging_b13").rglob("*") if path.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}]
        self.assertEqual(databases, [])


if __name__ == "__main__":
    unittest.main()
