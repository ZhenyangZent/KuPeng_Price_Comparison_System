from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from research.affiliate_intake.readiness import ReadinessError, merge_candidate, validate_readiness
from research.affiliate_intake.validator import IntakeValidationError, evaluate_candidate, verify_evidence_file

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
READINESS = ROOT / "research" / "affiliate_intake" / "CAPABILITY_READINESS.json"
AS_OF = date(2026, 11, 5)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class IntakeDecisionTests(unittest.TestCase):
    def test_positive_documentary_record_becomes_candidate_only(self) -> None:
        decision = evaluate_candidate(load_fixture("positive_documentary_membership.json"), as_of=AS_OF)
        self.assertEqual(decision["decision"], "CANDIDATE_ACCEPTED")
        self.assertEqual(decision["effective_state"], "CANDIDATE")
        self.assertNotEqual(decision["effective_state"], decision["requested_target_state"])
        self.assertTrue(decision["source_authorization_required"])
        self.assertFalse(decision["runtime_enabled"])

    def test_program_existence_cannot_prove_api(self) -> None:
        decision = evaluate_candidate(load_fixture("negative_program_only_claims_api.json"), as_of=AS_OF)
        self.assertEqual(decision["decision"], "REJECTED")
        self.assertIn("claim:PROGRAM_EXISTENCE_DOES_NOT_PROVE_TECHNICAL_CAPABILITY", decision["reasons"])

    def test_korean_document_cannot_prove_tw_partners(self) -> None:
        decision = evaluate_candidate(load_fixture("negative_kr_as_tw.json"), as_of=AS_OF)
        self.assertEqual(decision["decision"], "REJECTED")
        self.assertIn("market:REJECTED_TW_SCOPE", decision["reasons"])
        self.assertIn("claim:KR_NOT_TW_PARTNERS", decision["reasons"])

    def test_seller_api_cannot_prove_partners(self) -> None:
        decision = evaluate_candidate(load_fixture("negative_seller_api.json"), as_of=AS_OF)
        self.assertEqual(decision["decision"], "REJECTED")
        self.assertIn("source:REJECTED_PROVIDER_CLASS", decision["reasons"])
        self.assertIn("claim:SELLER_API_NOT_PARTNERS", decision["reasons"])

    def test_expired_document_fails_closed(self) -> None:
        decision = evaluate_candidate(load_fixture("negative_expired.json"), as_of=AS_OF)
        self.assertIn("source:EXPIRED", decision["reasons"])
        self.assertEqual(decision["effective_state"], "REJECTED")

    def test_revoked_document_fails_closed(self) -> None:
        decision = evaluate_candidate(load_fixture("negative_revoked.json"), as_of=AS_OF)
        self.assertIn("revocation:NOT_ACTIVE", decision["reasons"])

    def test_future_document_is_not_yet_effective(self) -> None:
        record = load_fixture("positive_documentary_membership.json")
        record["source"]["effective_date"] = "2027-01-01"
        decision = evaluate_candidate(record, as_of=AS_OF)
        self.assertIn("source:NOT_YET_EFFECTIVE", decision["reasons"])

    def test_missing_version_is_rejected(self) -> None:
        record = load_fixture("positive_documentary_membership.json")
        record["source"]["document_version"] = ""
        decision = evaluate_candidate(record, as_of=AS_OF)
        self.assertIn("source:DOCUMENT_VERSION_REQUIRED", decision["reasons"])

    def test_invalid_evidence_hash_is_rejected(self) -> None:
        record = load_fixture("positive_documentary_membership.json")
        record["evidence_sha256"] = "short"
        decision = evaluate_candidate(record, as_of=AS_OF)
        self.assertIn("evidence_sha256:INVALID", decision["reasons"])

    def test_capability_must_be_explicitly_supported(self) -> None:
        record = load_fixture("positive_documentary_membership.json")
        record["claim"]["supports_exactly"] = ["link_attribution_concept"]
        decision = evaluate_candidate(record, as_of=AS_OF)
        self.assertIn("claim:CAPABILITY_NOT_EXPLICITLY_SUPPORTED", decision["reasons"])

    def test_rights_scope_must_match_capability(self) -> None:
        record = load_fixture("positive_documentary_membership.json")
        record["rights_scope"]["capability_id"] = "api_link_generation"
        decision = evaluate_candidate(record, as_of=AS_OF)
        self.assertIn("rights_scope:CAPABILITY_MISMATCH", decision["reasons"])

    def test_account_state_requires_user_authorization(self) -> None:
        record = load_fixture("positive_documentary_membership.json")
        record["requested_target_state"] = "ACCOUNT_AUTHORIZED"
        decision = evaluate_candidate(record, as_of=AS_OF)
        self.assertIn("user_authorization:REQUIRED_FOR_ACCOUNT_OR_RUNTIME", decision["reasons"])

    def test_runtime_state_requires_separate_authority(self) -> None:
        record = load_fixture("positive_documentary_membership.json")
        record["requested_target_state"] = "RUNTIME_VERIFIED"
        record["user_authorization"] = {"status": "PRESENT", "supports_exactly": ["membership_program"]}
        decision = evaluate_candidate(record, as_of=AS_OF)
        self.assertIn("runtime_verification:SEPARATE_AUTHORITY_REQUIRED", decision["reasons"])

    def test_central_review_cannot_arrive_preapproved(self) -> None:
        record = load_fixture("positive_documentary_membership.json")
        record["central_review"]["status"] = "APPROVED"
        decision = evaluate_candidate(record, as_of=AS_OF)
        self.assertIn("central_review:MUST_START_PENDING", decision["reasons"])

    def test_invalid_revocation_timestamp_is_rejected(self) -> None:
        record = load_fixture("positive_documentary_membership.json")
        record["revocation"]["checked_at"] = "not-a-timestamp"
        decision = evaluate_candidate(record, as_of=AS_OF)
        self.assertIn("revocation:CHECK_TIMESTAMP_REQUIRED", decision["reasons"])

    def test_secret_key_is_structurally_rejected(self) -> None:
        record = load_fixture("positive_documentary_membership.json")
        record["api_key"] = "synthetic-secret-like-value"
        with self.assertRaisesRegex(IntakeValidationError, "secret/raw-link"):
            evaluate_candidate(record, as_of=AS_OF)

    def test_local_evidence_file_hash_can_be_verified(self) -> None:
        record = load_fixture("positive_documentary_membership.json")
        payload = b"synthetic official document bytes"
        import hashlib

        record["evidence_sha256"] = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "document.bin"
            path.write_bytes(payload)
            self.assertEqual(verify_evidence_file(record, path), record["evidence_sha256"])

    def test_local_evidence_file_hash_mismatch_is_rejected(self) -> None:
        record = load_fixture("positive_documentary_membership.json")
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "document.bin"
            path.write_bytes(b"different synthetic bytes")
            with self.assertRaisesRegex(IntakeValidationError, "SHA-256 mismatch"):
                verify_evidence_file(record, path)


class ManualLinkCandidateTests(unittest.TestCase):
    def test_manual_link_candidate_is_accepted_but_disabled(self) -> None:
        decision = evaluate_candidate(load_fixture("positive_manual_link_candidate.json"), as_of=AS_OF)
        self.assertEqual(decision["decision"], "CANDIDATE_ACCEPTED")
        self.assertEqual(decision["effective_state"], "CANDIDATE")
        self.assertFalse(decision["cta_enabled"])

    def test_ordinary_product_url_is_not_affiliate_evidence(self) -> None:
        decision = evaluate_candidate(load_fixture("negative_normal_product_url.json"), as_of=AS_OF)
        self.assertEqual(decision["decision"], "REJECTED")
        self.assertIn("claim:NORMAL_PRODUCT_URL_NOT_AFFILIATE_EVIDENCE", decision["reasons"])

    def test_manual_tool_does_not_prove_api(self) -> None:
        record = load_fixture("positive_manual_link_candidate.json")
        record["capability_id"] = "api_link_generation"
        record["claim"]["supports_exactly"] = ["api_link_generation"]
        record["rights_scope"]["capability_id"] = "api_link_generation"
        decision = evaluate_candidate(record, as_of=AS_OF)
        self.assertIn("claim:MANUAL_TOOL_DOES_NOT_PROVE_API", decision["reasons"])

    def test_raw_candidate_url_key_is_forbidden(self) -> None:
        record = load_fixture("positive_manual_link_candidate.json")
        record["manual_link_candidate"]["candidate_url"] = "https://example.invalid/forbidden"
        with self.assertRaisesRegex(IntakeValidationError, "raw-link"):
            evaluate_candidate(record, as_of=AS_OF)

    def test_identity_binding_must_be_exact(self) -> None:
        record = load_fixture("positive_manual_link_candidate.json")
        record["manual_link_candidate"]["identity_binding"]["variant"] = False
        decision = evaluate_candidate(record, as_of=AS_OF)
        self.assertIn("manual_link_candidate:EXACT_IDENTITY_NOT_PROVEN", decision["reasons"])

    def test_manual_candidate_cta_must_stay_disabled(self) -> None:
        record = load_fixture("positive_manual_link_candidate.json")
        record["manual_link_candidate"]["cta_enabled"] = True
        decision = evaluate_candidate(record, as_of=AS_OF)
        self.assertIn("manual_link_candidate:CTA_MUST_REMAIN_DISABLED", decision["reasons"])


class ReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.readiness = json.loads(READINESS.read_text(encoding="utf-8"))

    def test_default_readiness_is_valid_and_blocked(self) -> None:
        validate_readiness(self.readiness)
        self.assertEqual(self.readiness["provider_state"], "SOURCE_AUTHORIZATION_REQUIRED")
        self.assertFalse(self.readiness["runtime"]["cta_enabled"])
        self.assertIsNone(self.readiness["runtime"]["click_url"])

    def test_accepted_candidate_merges_without_unlocking_runtime(self) -> None:
        decision = evaluate_candidate(load_fixture("positive_documentary_membership.json"), as_of=AS_OF)
        merged = merge_candidate(self.readiness, decision)
        item = merged["capabilities"]["membership_program"]
        self.assertEqual(item["state"], "CANDIDATE")
        self.assertEqual(item["candidate_evidence_sha256"], ["a" * 64])
        self.assertEqual(merged["provider_state"], "SOURCE_AUTHORIZATION_REQUIRED")
        self.assertFalse(merged["runtime"]["cta_enabled"])

    def test_rejected_candidate_cannot_merge(self) -> None:
        decision = evaluate_candidate(load_fixture("negative_program_only_claims_api.json"), as_of=AS_OF)
        with self.assertRaisesRegex(ReadinessError, "only accepted"):
            merge_candidate(self.readiness, decision)

    def test_readiness_cannot_promote_to_documentary_verified(self) -> None:
        self.readiness["capabilities"]["membership_program"]["state"] = "DOCUMENTARY_VERIFIED"
        with self.assertRaisesRegex(ReadinessError, "UNKNOWN or CANDIDATE"):
            validate_readiness(self.readiness)

    def test_readiness_endpoint_must_remain_null(self) -> None:
        self.readiness["runtime"]["endpoint"] = "https://example.invalid/convert"
        with self.assertRaisesRegex(ReadinessError, "endpoint"):
            validate_readiness(self.readiness)

    def test_readiness_cta_cannot_enable(self) -> None:
        self.readiness["runtime"]["cta_enabled"] = True
        with self.assertRaisesRegex(ReadinessError, "runtime gates"):
            validate_readiness(self.readiness)


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "research.affiliate_intake.cli", *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_cli_accepts_positive_candidate(self) -> None:
        result = self.run_cli(
            "evaluate",
            str(FIXTURES / "positive_documentary_membership.json"),
            "--as-of",
            "2026-11-05",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["decision"], "CANDIDATE_ACCEPTED")

    def test_cli_returns_one_for_negative_candidate(self) -> None:
        result = self.run_cli(
            "evaluate",
            str(FIXTURES / "negative_expired.json"),
            "--as-of",
            "2026-11-05",
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["decision"], "REJECTED")

    def test_cli_validates_default_readiness(self) -> None:
        result = self.run_cli("validate-readiness", str(READINESS))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "VALID")


if __name__ == "__main__":
    unittest.main()
