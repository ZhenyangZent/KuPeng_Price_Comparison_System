from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path

from research.coupon_b10_mapping_c08.fixture_builder import build_case, load_pack
from research.coupon_b10_mapping_c08.mapping import MappingError, admit_batch, assess_import, dedupe_key
from research.coupon_b10_mapping_c08.validate_all import check_expected

ROOT = Path(__file__).resolve().parents[2]
PACK_PATH = ROOT / "research/coupon_b10_mapping_c08/B10_MAPPING_FIXTURES.json"
PACK = load_pack(PACK_PATH)
NOW = datetime.fromisoformat(PACK["evaluation_time"].replace("Z", "+00:00"))


def base_record() -> dict:
    return copy.deepcopy(PACK["base_import"])


def make_case(case_id: str):
    def test(self):
        record, expected, revoked = build_case(PACK, case_id)
        if "error" in expected:
            with self.assertRaisesRegex(MappingError, expected["error"]):
                assess_import(record, now=NOW, revoked_evidence_hashes=revoked)
        else:
            result = assess_import(record, now=NOW, revoked_evidence_hashes=revoked)
            check_expected(result, expected)
            self.assertFalse(result["runtime_authorized"])
            self.assertFalse(result["cta_enabled"])
            self.assertIsNone(result["click_url"])
    return test


class FixtureMappingTests(unittest.TestCase):
    pass


for case in PACK["cases"]:
    setattr(FixtureMappingTests, "test_" + case["id"].lower(), make_case(case["id"]))


class StructuralTests(unittest.TestCase):
    def reject(self, record):
        with self.assertRaises(MappingError):
            assess_import(record, now=NOW)

    def test_wrong_import_schema(self):
        r=base_record();r["schema_version"]="OTHER";self.reject(r)
    def test_extra_top_field(self):
        r=base_record();r["extra"]=1;self.reject(r)
    def test_missing_top_field(self):
        r=base_record();del r["review"];self.reject(r)
    def test_invalid_import_id(self):
        r=base_record();r["import_id"]="";self.reject(r)
    def test_invalid_wire_kind(self):
        r=base_record();r["wire_kind"]="OTHER";self.reject(r)
    def test_wrong_envelope_schema(self):
        r=base_record();r["wire_envelope"]["schema_version"]="OTHER";self.reject(r)
    def test_wrong_envelope_classification(self):
        r=base_record();r["wire_envelope"]["data_classification"]="OTHER";self.reject(r)
    def test_missing_data_version(self):
        r=base_record();r["wire_envelope"]["data_version"]="";self.reject(r)
    def test_detail_series_selection_mismatch(self):
        r=base_record();r["selected_series_key"]="other";self.reject(r)
    def test_product_extra_field_rejected(self):
        r=base_record();r["wire_envelope"]["product"]["x"]=1;self.reject(r)
    def test_identity_missing_field(self):
        r=base_record();del r["expected_identity"]["seller_id"];self.reject(r)
    def test_identity_wrong_platform(self):
        r=base_record();r["expected_identity"]["platform"]="OTHER";self.reject(r)
    def test_provenance_hash_invalid(self):
        r=base_record();r["c07_provenance"]["source_document_sha256"]="ABC";self.reject(r)
    def test_right_missing(self):
        r=base_record();del r["c07_provenance"]["rights"]["product_price_access"];self.reject(r)
    def test_verified_right_without_locator(self):
        r=base_record();r["c07_provenance"]["rights"]["product_price_access"]["evidence_locator"]=None;self.reject(r)
    def test_unverified_right_with_locator(self):
        r=base_record();r["c07_provenance"]["rights"]["affiliate_url_conversion"]["evidence_locator"]="bad";self.reject(r)
    def test_revoked_without_time(self):
        r=base_record();r["revocation"]={"state":"REVOKED","effective_at":None,"reason":"x"};self.reject(r)
    def test_revoked_without_reason(self):
        r=base_record();r["revocation"]={"state":"REVOKED","effective_at":"2026-11-05T00:00:00Z","reason":None};self.reject(r)
    def test_preapproved_review(self):
        r=base_record();r["review"]["central_approval"]="APPROVED";self.reject(r)
    def test_runtime_true(self):
        r=base_record();r["review"]["runtime_authorized"]=True;self.reject(r)
    def test_cta_true(self):
        r=base_record();r["review"]["cta_enabled"]=True;self.reject(r)
    def test_click_url_present(self):
        r=base_record();r["review"]["click_url"]="https://example.test";self.reject(r)
    def test_secret_key_present(self):
        r=base_record();r["review"]["token"]="x";self.reject(r)
    def test_naive_valid_until(self):
        r=base_record();r["c07_provenance"]["valid_until"]="2026-11-30T00:00:00";self.reject(r)


class DedupeTests(unittest.TestCase):
    def test_key_is_stable(self):
        self.assertEqual(dedupe_key(base_record()), dedupe_key(base_record()))
    def test_identical_duplicate_is_noop(self):
        r=base_record();out=admit_batch([r,r],now=NOW);self.assertEqual([x["admission"] for x in out],["ADMITTED_TEST_ONLY","DUPLICATE_NOOP"])
    def test_same_key_different_record_is_conflict(self):
        a=base_record();b=base_record();b["import_id"]="other";out=admit_batch([a,b],now=NOW);self.assertEqual(out[1]["admission"],"DEDUPE_CONFLICT");self.assertTrue(all(not x["allowed"] for x in out[1]["permissions"].values()))
    def test_data_version_changes_key(self):
        a=base_record();b=base_record();b["wire_envelope"]["data_version"]="other";self.assertNotEqual(dedupe_key(a),dedupe_key(b))
    def test_observed_time_changes_key(self):
        a=base_record();b=base_record();b["wire_envelope"]["product"]["observed_at"]="2026-11-04T03:00:00Z";self.assertNotEqual(dedupe_key(a),dedupe_key(b))


class CliArtifactTests(unittest.TestCase):
    def test_cli_fixture(self):
        p=subprocess.run([sys.executable,"-m","research.coupon_b10_mapping_c08.cli",str(PACK_PATH),"--case","DETAIL_DUAL_HISTORY_ALLOWED_TEST_ONLY","--now",PACK["evaluation_time"]],cwd=ROOT,capture_output=True,text=True,check=False);self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout)["permissions"]["read_display"]["state"],"TEST_ONLY_ALLOWED")
    def test_validate_all(self):
        p=subprocess.run([sys.executable,"-m","research.coupon_b10_mapping_c08.validate_all"],cwd=ROOT,capture_output=True,text=True,check=False);self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout)["status"],"VALID")
    def test_fixture_ids_unique(self):
        ids=[x["id"] for x in PACK["cases"]];self.assertEqual(len(ids),len(set(ids)))
    def test_four_permission_dimensions(self):
        result=assess_import(base_record(),now=NOW);self.assertEqual(set(result["permissions"]),{"read_display","history_retention","deal_notification","affiliate_cta"})


if __name__ == "__main__":
    unittest.main()
