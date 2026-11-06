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
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "import_staging_b12"))

from import_staging_b12.cli import main as cli_main  # noqa: E402
from import_staging_b12.c09_adapter import C09ModuleVerifier, load_verified_c09_verifier, verify_c09_release_source  # noqa: E402
from import_staging_b12.provenance import ProvenanceContractError, ProvenanceResult  # noqa: E402
from import_staging_b12.staging import (  # noqa: E402
    CSV_FIELDS,
    ImportStagingError,
    dry_run,
    load_records,
    record_sha256,
    validate_record,
)

NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)
FIXTURE = ROOT / "services" / "import_staging_b12" / "fixtures" / "synthetic_valid.json"
BRIDGE_FIXTURE = ROOT / "services" / "import_staging_b12" / "fixtures" / "synthetic_c09_bridge.json"
BRIDGE_BUNDLE = ROOT / "services" / "import_staging_b12" / "fixtures" / "synthetic_c09_request_bundle.json"
B11_SHA256 = "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"
C09_SHA256 = "a8367fed73efce99e93941a6475f386def7dfa25de27b0e2889d4fe00b1ed0d7"
C09_RELEASE = ROOT / "review" / "releases" / "CDH_C_R08_001_REVIEW.zip"
if not C09_RELEASE.is_file():
    C09_RELEASE = ROOT / "upstream" / "C09" / "CDH_C_R08_001_REVIEW.zip"


class AllowSyntheticTestVerifier:
    def verify(self, record, *, input_sha256, record_sha256):
        del record, input_sha256, record_sha256
        return ProvenanceResult(True, "C09-SYNTHETIC-TEST-DOUBLE", "ALLOW_STAGING_PREVIEW", ("SYNTHETIC_TEST_ONLY",))


def flatten(record: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name in CSV_FIELDS:
        if "." in name:
            group, field = name.split(".", 1)
            nested = record[group]
            assert isinstance(nested, dict)
            value = nested[field]
        else:
            value = record[name]
        if isinstance(value, bool):
            value = "true" if value else "false"
        elif value is None:
            value = ""
        result[name] = value
    return result


class B12StagingTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "review" / "B12" / "tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix="case-", dir=base))
        self.records, self.input_sha = load_records(FIXTURE, allowed_root=FIXTURE.parent.parent)
        self.records = copy.deepcopy(self.records)
        self.bridge_records, self.bridge_sha = load_records(BRIDGE_FIXTURE, allowed_root=BRIDGE_FIXTURE.parent.parent)
        self.bridge_records = copy.deepcopy(self.bridge_records)

    def tearDown(self):
        shutil.rmtree(self.temp)

    def test_default_verifier_denies_every_valid_record(self):
        report = dry_run(self.records, input_sha256=self.input_sha, as_of=NOW)
        self.assertEqual(report["counts"]["DENIED_PROVENANCE"], 2)
        self.assertEqual(report["database_write_count"], 0)
        self.assertFalse(report["collection_authorized"])

    def test_exact_c09_release_source_is_hash_bound(self):
        result = verify_c09_release_source(C09_RELEASE, expected_sha256=C09_SHA256, project_root=ROOT)
        self.assertEqual(result["source_gate"], "PASS")
        with self.assertRaises(ProvenanceContractError):
            verify_c09_release_source(C09_RELEASE, expected_sha256="0" * 64, project_root=ROOT)

    def test_actual_c09_module_accepts_exact_cross_bound_bridge(self):
        verifier = load_verified_c09_verifier(BRIDGE_BUNDLE, expected_input_sha256=self.bridge_sha, c09_release=C09_RELEASE, project_root=ROOT)
        report = dry_run(self.bridge_records, input_sha256=self.bridge_sha, as_of=datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc), verifier=verifier)
        self.assertEqual(report["counts"]["ACCEPTED_FOR_STAGING_PREVIEW"], 1)
        preview = report["outcomes"][0]["price_preview"]
        self.assertEqual((preview["before_coupon_price_twd"], preview["display_price_twd"]), (99, 49))

    def test_c09_record_hash_mismatch_denies(self):
        bundle = json.loads(BRIDGE_BUNDLE.read_text(encoding="utf-8"))
        bundle["bindings"][0]["record_sha256"] = "0" * 64
        path = self.temp / "bundle.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        verifier = load_verified_c09_verifier(path, expected_input_sha256=self.bridge_sha, c09_release=C09_RELEASE, project_root=ROOT)
        report = dry_run(self.bridge_records, input_sha256=self.bridge_sha, as_of=datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc), verifier=verifier)
        self.assertEqual(report["outcomes"][0]["status"], "DENIED_PROVENANCE")
        self.assertIn("RECORD_SHA256_MISMATCH", report["outcomes"][0]["reasons"])

    def test_missing_fields_fail_closed(self):
        self.assertIn("TOP_LEVEL_FIELDS_MISMATCH", validate_record({"record_id": "x"}, as_of=NOW))

    def test_zero_is_not_null_and_unknown_shipping_total_is_null(self):
        zero = copy.deepcopy(self.records[1])
        zero["record_id"] = "zero"
        zero["series_key"] = "zero"
        zero["base_price_twd"] = 0
        zero["shipping"] = {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None}
        report = dry_run([zero], input_sha256=self.input_sha, as_of=NOW, verifier=AllowSyntheticTestVerifier())
        preview = report["outcomes"][0]["price_preview"]
        self.assertEqual(preview["display_price_twd"], 0)
        self.assertIsNone(preview["required_total_twd"])
        invalid = copy.deepcopy(zero)
        invalid["base_price_twd"] = None
        self.assertIn("BASE_PRICE_INVALID", validate_record(invalid, as_of=NOW))

    def test_duplicate_is_noop_and_different_content_is_conflict(self):
        original = copy.deepcopy(self.records[1])
        changed = copy.deepcopy(original)
        changed["base_price_twd"] = 130
        report = dry_run([original, copy.deepcopy(original), changed], input_sha256=self.input_sha, as_of=NOW, verifier=AllowSyntheticTestVerifier())
        self.assertEqual([item["status"] for item in report["outcomes"]], ["ACCEPTED_FOR_STAGING_PREVIEW", "NOOP_DUPLICATE", "CONFLICT"])
        self.assertEqual(len(report["timelines"][original["series_key"]]), 1)

    def test_future_observation_is_invalid(self):
        record = copy.deepcopy(self.records[1])
        record["observed_at"] = "2026-11-06T00:00:00Z"
        self.assertIn("OBSERVED_AT_FUTURE", validate_record(record, as_of=NOW))

    def test_expired_confirmed_coupon_is_invalid(self):
        record = copy.deepcopy(self.records[0])
        record["coupon"]["valid_until"] = "2026-11-03T00:00:00Z"
        self.assertIn("CONFIRMED_COUPON_NOT_VALID_AT_OBSERVATION", validate_record(record, as_of=NOW))

    def test_coupon_identity_mismatch_is_invalid(self):
        record = copy.deepcopy(self.records[0])
        record["coupon"]["target_sku_id"] = "OTHER"
        self.assertIn("CONFIRMED_COUPON_IDENTITY_MISMATCH", validate_record(record, as_of=NOW))

    def test_same_series_key_cannot_merge_different_sku(self):
        first = copy.deepcopy(self.records[1])
        second = copy.deepcopy(self.records[0])
        second["identity"]["sku_id"] = "DIFFERENT-SKU"
        second["coupon"]["target_sku_id"] = "DIFFERENT-SKU"
        report = dry_run([first, second], input_sha256=self.input_sha, as_of=NOW, verifier=AllowSyntheticTestVerifier())
        self.assertEqual(report["outcomes"][1]["status"], "CONFLICT")
        self.assertEqual(report["outcomes"][1]["reasons"], ["SERIES_IDENTITY_MISMATCH"])

    def test_claim_required_never_becomes_confirmed_discount(self):
        record = copy.deepcopy(self.records[0])
        record["record_id"] = "claim-required"
        record["coupon"]["status"] = "CLAIM_REQUIRED"
        report = dry_run([record], input_sha256=self.input_sha, as_of=NOW, verifier=AllowSyntheticTestVerifier())
        preview = report["outcomes"][0]["price_preview"]
        self.assertEqual(preview["display_basis"], "BASE_PRICE")
        self.assertEqual(preview["display_price_twd"], 99)
        self.assertIsNone(preview["confirmed_coupon_price_twd"])

    def test_c09_cross_binding_sku_mismatch_denies_before_verifier(self):
        from research.import_provenance_c09 import verify_request

        record = copy.deepcopy(self.bridge_records[0])
        record["identity"]["sku_id"] = "SKU:C09:OTHER"
        record["coupon"]["target_sku_id"] = "SKU:C09:OTHER"
        bundle = json.loads(BRIDGE_BUNDLE.read_text(encoding="utf-8"))
        bundle["bindings"][0]["record_sha256"] = record_sha256(record)
        path = self.temp / "bundle.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        verifier = C09ModuleVerifier(path, expected_input_sha256=self.bridge_sha, expected_c09_release_sha256=C09_SHA256, verify_request=verify_request)
        report = dry_run([record], input_sha256=self.bridge_sha, as_of=datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc), verifier=verifier)
        self.assertIn("C09_BINDING_SKU_ID_MISMATCH", report["outcomes"][0]["reasons"])

    def test_c09_denial_and_exception_fail_closed(self):
        from research.import_provenance_c09 import verify_request

        bundle = json.loads(BRIDGE_BUNDLE.read_text(encoding="utf-8"))
        bundle["bindings"][0]["request"]["provenance"]["revocation"] = {"revoked": True, "revoked_at": "2026-11-05T05:30:00Z", "reason": "TEST_REVOCATION"}
        denied_path = self.temp / "denied.json"
        denied_path.write_text(json.dumps(bundle), encoding="utf-8")
        denied = C09ModuleVerifier(denied_path, expected_input_sha256=self.bridge_sha, expected_c09_release_sha256=C09_SHA256, verify_request=verify_request)
        report = dry_run(self.bridge_records, input_sha256=self.bridge_sha, as_of=datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc), verifier=denied)
        self.assertIn("EVIDENCE_REVOKED", report["outcomes"][0]["reasons"])

        def broken(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("synthetic verifier failure")

        broken_verifier = C09ModuleVerifier(BRIDGE_BUNDLE, expected_input_sha256=self.bridge_sha, expected_c09_release_sha256=C09_SHA256, verify_request=broken)
        report = dry_run(self.bridge_records, input_sha256=self.bridge_sha, as_of=datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc), verifier=broken_verifier)
        self.assertIn("C09_VERIFIER_EXCEPTION", report["outcomes"][0]["reasons"])

    def test_already_included_does_not_double_discount(self):
        record = copy.deepcopy(self.records[0])
        record["record_id"] = "included"
        record["base_price_twd"] = 49
        record["coupon"]["already_included_in_base"] = True
        record["coupon"]["pre_coupon_comparison_price_twd"] = 99
        record["coupon"]["pre_coupon_comparison_evidence_id"] = "EV-COMPARE"
        report = dry_run([record], input_sha256=self.input_sha, as_of=NOW, verifier=AllowSyntheticTestVerifier())
        preview = report["outcomes"][0]["price_preview"]
        self.assertEqual((preview["before_coupon_price_twd"], preview["display_price_twd"]), (99, 49))

    def test_order_total_quantity_math(self):
        record = copy.deepcopy(self.records[0])
        record["record_id"] = "quantity-two"
        record["base_price_twd"] = 100
        record["minimum_purchase_quantity"] = 2
        record["coupon"]["discount_twd"] = 50
        record["coupon"]["discount_scope"] = "ORDER_TOTAL"
        report = dry_run([record], input_sha256=self.input_sha, as_of=NOW, verifier=AllowSyntheticTestVerifier())
        preview = report["outcomes"][0]["price_preview"]
        self.assertEqual((preview["display_price_twd"], preview["minimum_item_spend_twd"]), (75, 150))

    def test_no_invented_history_backfill(self):
        report = dry_run(self.records, input_sha256=self.input_sha, as_of=NOW, verifier=AllowSyntheticTestVerifier())
        self.assertEqual(sum(len(items) for items in report["timelines"].values()), report["counts"]["ACCEPTED_FOR_STAGING_PREVIEW"])
        self.assertEqual({item["evidence_id"] for item in report["timelines"]["synthetic-product-1"]}, {"EV-EARLY", "EV-LATE"})

    def test_csv_exact_headers_parse_and_missing_header_rejected(self):
        target = self.temp / "records.csv"
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerow(flatten(self.records[1]))
        records, _ = load_records(target, allowed_root=self.temp)
        self.assertEqual(records[0]["base_price_twd"], 129)
        bad = self.temp / "bad.csv"
        bad.write_text("record_id\nx\n", encoding="utf-8")
        with self.assertRaises(ImportStagingError):
            load_records(bad, allowed_root=self.temp)

    def test_input_outside_root_and_oversize_are_refused(self):
        with self.assertRaises(ImportStagingError):
            load_records(FIXTURE, allowed_root=self.temp)
        huge = self.temp / "huge.json"
        huge.write_bytes(b" " * (2 * 1024 * 1024 + 1))
        with self.assertRaises(ImportStagingError):
            load_records(huge, allowed_root=self.temp)

    def test_cli_default_deny_and_require_all_exit_codes(self):
        local_input = self.temp / "input.json"
        shutil.copyfile(FIXTURE, local_input)
        args = ["--input", str(local_input), "--allowed-root", str(self.temp), "--as-of", "2026-11-05T04:00:00Z"]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(args), 0)
        self.assertEqual(json.loads(output.getvalue())["counts"]["DENIED_PROVENANCE"], 2)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli_main([*args, "--require-all-accepted"]), 3)

    def test_cli_accepts_exact_hash_bound_c09_bridge(self):
        local_input = self.temp / "input.json"
        local_bundle = self.temp / "bundle.json"
        local_release = self.temp / "c09.zip"
        shutil.copyfile(BRIDGE_FIXTURE, local_input)
        shutil.copyfile(BRIDGE_BUNDLE, local_bundle)
        shutil.copyfile(C09_RELEASE, local_release)
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli_main(["--input", str(local_input), "--allowed-root", str(self.temp), "--as-of", "2026-11-05T06:00:00Z", "--c09-request-bundle", str(local_bundle), "--c09-release", str(local_release), "--require-all-accepted"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["counts"]["ACCEPTED_FOR_STAGING_PREVIEW"], 1)

    def test_schemas_are_valid_json_and_b11_release_is_unchanged(self):
        schema_root = ROOT / "services" / "import_staging_b12" / "schema"
        for path in schema_root.glob("*.json"):
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)
        release = ROOT / "review" / "releases" / "CDH_B_R07_001_REVIEW.zip"
        if not release.is_file():
            release = ROOT / "upstream" / "B11" / "CDH_B_R07_001_REVIEW.zip"
        self.assertEqual(hashlib.sha256(release.read_bytes()).hexdigest(), B11_SHA256)


if __name__ == "__main__":
    unittest.main()
