from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from research.affiliate_readiness_c05.validator import (
    DecisionError,
    validate_decision,
    validate_document_diff,
    validate_fixture_pack,
    validate_source_ledger,
    validate_traceability,
)

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "research" / "affiliate_readiness_c05"


def load(name: str) -> dict:
    return json.loads((BASE / name).read_text(encoding="utf-8"))


class DecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.decision = load("CAPABILITY_DECISION.json")
        self.ledger = load("OFFICIAL_SOURCE_LEDGER.json")

    def validate(self) -> None:
        validate_decision(self.decision, self.ledger)

    def test_current_decision_is_valid(self) -> None:
        self.validate()

    def test_capability_set_has_twelve_entries(self) -> None:
        self.validate()
        self.assertEqual(len(self.decision["capabilities"]), 12)

    def test_only_two_concept_capabilities_are_document_verified(self) -> None:
        states = [item["document_state"] for item in self.decision["capabilities"].values()]
        self.assertEqual(states.count("DOCS_VERIFIED"), 2)

    def test_ten_technical_capabilities_are_source_blocked(self) -> None:
        states = [item["document_state"] for item in self.decision["capabilities"].values()]
        self.assertEqual(states.count("SOURCE_BLOCKED"), 10)

    def test_technical_capability_cannot_be_promoted(self) -> None:
        item = self.decision["capabilities"]["api_link_generation"]
        item["document_state"] = "DOCS_VERIFIED"
        with self.assertRaisesRegex(DecisionError, "technical capabilities"):
            self.validate()

    def test_concept_requires_exact_evidence(self) -> None:
        self.decision["capabilities"]["partners_program_presence"]["evidence_ids"] = []
        with self.assertRaisesRegex(DecisionError, "exact official support"):
            self.validate()

    def test_runtime_cta_cannot_enable(self) -> None:
        self.decision["runtime_authority"]["cta_enabled"] = True
        with self.assertRaisesRegex(DecisionError, "boolean gates"):
            self.validate()

    def test_runtime_click_url_must_be_null(self) -> None:
        self.decision["runtime_authority"]["click_url"] = "https://example.invalid"
        with self.assertRaisesRegex(DecisionError, "runtime values"):
            self.validate()

    def test_runtime_endpoint_must_be_null(self) -> None:
        self.decision["runtime_authority"]["endpoint"] = "https://example.invalid/api"
        with self.assertRaisesRegex(DecisionError, "runtime values"):
            self.validate()

    def test_runtime_allowlist_must_be_empty(self) -> None:
        self.decision["runtime_authority"]["output_host_allowlist"] = ["partners.tw.coupang.com"]
        with self.assertRaisesRegex(DecisionError, "allowlists"):
            self.validate()

    def test_all_data_rights_remain_false(self) -> None:
        self.decision["data_rights"]["derived_price_history"] = True
        with self.assertRaisesRegex(DecisionError, "data rights"):
            self.validate()

    def test_account_credentials_cannot_be_present(self) -> None:
        self.decision["account_authority"]["credentials_present"] = True
        with self.assertRaisesRegex(DecisionError, "credentials"):
            self.validate()

    def test_source_authorization_requirement_cannot_be_removed(self) -> None:
        self.decision["source_authorization_required"] = False
        with self.assertRaisesRegex(DecisionError, "source authorization"):
            self.validate()

    def test_automatic_promotion_cannot_enable(self) -> None:
        self.decision["automatic_promotion"] = True
        with self.assertRaisesRegex(DecisionError, "no-auto-promotion"):
            self.validate()

    def test_technical_state_ceiling_is_candidate(self) -> None:
        self.decision["technical_state_ceiling"] = "DOCS_VERIFIED"
        with self.assertRaisesRegex(DecisionError, "ceiling"):
            self.validate()

    def test_link_capability_cannot_unlock_data_rights(self) -> None:
        self.decision["state_model"]["link_capability_never_unlocks_data_rights"] = False
        with self.assertRaisesRegex(DecisionError, "independence"):
            self.validate()

    def test_inquiry_must_remain_unsent(self) -> None:
        self.decision["inquiry_send_status"] = "SENT"
        with self.assertRaisesRegex(DecisionError, "NOT_SENT"):
            self.validate()

    def test_secret_key_is_rejected_anywhere(self) -> None:
        self.decision["runtime_authority"]["api_key"] = "synthetic"
        with self.assertRaisesRegex(DecisionError, "secret-bearing"):
            self.validate()


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = load("OFFICIAL_SOURCE_LEDGER.json")

    def test_current_ledger_has_seven_valid_sources(self) -> None:
        indexed = validate_source_ledger(self.ledger)
        self.assertEqual(len(indexed), 7)

    def test_seller_source_cannot_support_partners(self) -> None:
        self.ledger["sources"][2]["supports_exactly"] = ["api_link_generation"]
        with self.assertRaises(DecisionError):
            validate_source_ledger(self.ledger)

    def test_korean_source_cannot_support_tw(self) -> None:
        self.ledger["sources"][-1]["supports_exactly"] = ["api_link_generation"]
        with self.assertRaises(DecisionError):
            validate_source_ledger(self.ledger)

    def test_supporting_source_requires_version(self) -> None:
        self.ledger["sources"][0]["version"] = None
        with self.assertRaisesRegex(DecisionError, "version and effective date"):
            validate_source_ledger(self.ledger)

    def test_verified_byte_identity_requires_hash(self) -> None:
        self.ledger["sources"][0]["byte_identity_verified"] = True
        with self.assertRaisesRegex(DecisionError, "content hash"):
            validate_source_ledger(self.ledger)

    def test_nonofficial_source_host_is_rejected(self) -> None:
        self.ledger["sources"][0]["url"] = "https://example.invalid/document"
        with self.assertRaisesRegex(DecisionError, "official HTTPS"):
            validate_source_ledger(self.ledger)


class FixturePackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = load("F03_SYNTHETIC_FIXTURES.json")

    def test_current_fixture_pack_is_valid(self) -> None:
        validate_fixture_pack(self.pack)
        self.assertEqual(len(self.pack["cases"]), 14)

    def test_fixtures_cannot_promote_automatically(self) -> None:
        self.pack["automatic_promotion"] = True
        with self.assertRaisesRegex(DecisionError, "non-promoting"):
            validate_fixture_pack(self.pack)

    def test_fixtures_cannot_contain_click_url(self) -> None:
        self.pack["runtime_invariants"]["click_url"] = "https://example.invalid"
        with self.assertRaisesRegex(DecisionError, "click_url"):
            validate_fixture_pack(self.pack)

    def test_fixtures_cannot_authorize_runtime(self) -> None:
        self.pack["runtime_invariants"]["runtime_authorized"] = True
        with self.assertRaisesRegex(DecisionError, "authorize runtime"):
            validate_fixture_pack(self.pack)

    def test_required_fixture_cannot_be_removed(self) -> None:
        self.pack["cases"] = [item for item in self.pack["cases"] if item["id"] != "wrong_variant"]
        with self.assertRaisesRegex(DecisionError, "required fixture"):
            validate_fixture_pack(self.pack)

    def test_duplicate_fixture_is_rejected(self) -> None:
        self.pack["cases"].append(copy.deepcopy(self.pack["cases"][0]))
        with self.assertRaisesRegex(DecisionError, "duplicate fixture"):
            validate_fixture_pack(self.pack)


class DocumentDiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.diff = load("DOCUMENT_UPDATE_DIFF.json")

    def test_current_diff_is_valid(self) -> None:
        validate_document_diff(self.diff)

    def test_core_delta_cannot_claim_new_authority(self) -> None:
        self.diff["core_delta"] = "NEW_RUNTIME_AUTHORITY"
        with self.assertRaisesRegex(DecisionError, "NO_CHANGE"):
            validate_document_diff(self.diff)

    def test_automatic_reenable_must_remain_false(self) -> None:
        self.diff["recheck_rules"]["automatic_reenable"] = True
        with self.assertRaisesRegex(DecisionError, "fail closed"):
            validate_document_diff(self.diff)


class TraceabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = load("TRACEABLE_CITATIONS.json")

    def test_current_traceability_hashes_match(self) -> None:
        validate_traceability(self.index, ROOT)

    def test_traceability_hash_mismatch_is_rejected(self) -> None:
        self.index["artifacts"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(DecisionError, "hash mismatch"):
            validate_traceability(self.index, ROOT)

    def test_unsafe_traceability_path_is_rejected(self) -> None:
        self.index["artifacts"][0]["path"] = "../outside"
        with self.assertRaisesRegex(DecisionError, "unsafe"):
            validate_traceability(self.index, ROOT)


class CliTests(unittest.TestCase):
    def test_validate_all_cli(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "research.affiliate_readiness_c05.validate_all", "--root", str(ROOT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["status"], "VALID")
        self.assertEqual(parsed["fixture_count"], 14)


if __name__ == "__main__":
    unittest.main()
