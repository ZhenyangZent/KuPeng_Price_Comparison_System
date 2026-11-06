from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path

from research.import_provenance_c10.fixture_builder import build_case, load_pack
from research.import_provenance_c10.intake import (
    DECISION_SCHEMA,
    MAX_JSON_BYTES,
    PINNED_C09_GATE_SHA256,
    PINNED_C09_RELEASE_SHA256,
    evaluate_intake,
    verify_json,
)

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "research" / "import_provenance_c10"
PACK = load_pack(BASE / "C10_INTAKE_FIXTURES.json")
NOW = datetime.fromisoformat(PACK["evaluation_time"].replace("Z", "+00:00"))


class FixtureTests(unittest.TestCase):
    pass


def _fixture_test(case_id: str):
    def test(self: unittest.TestCase) -> None:
        intake, expected = build_case(PACK, case_id, project_root=ROOT)
        result = evaluate_intake(intake, now=NOW)
        self.assertEqual(expected["decision"], result["decision"])
        self.assertTrue(set(expected["codes"]).issubset(result["reason_codes"]))
        self.assertEqual("SOURCE_BLOCKED", result["source_state"])
        self.assertFalse(result["canonical_write_authorized"])
        self.assertFalse(result["runtime_authorized"])
        self.assertFalse(result["public_display_authorized"])
        self.assertFalse(result["cta_enabled"])
        self.assertIsNone(result["click_url"])
    return test


for _case in PACK["cases"]:
    setattr(FixtureTests, f"test_fixture_{_case['id'].lower()}", _fixture_test(_case["id"]))


class IntakeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intake, _ = build_case(PACK, "ALLOW_SYNTHETIC_MANUAL_INTAKE", project_root=ROOT)

    def test_exact_c09_gate_hash(self) -> None:
        path = ROOT / "research" / "import_provenance_c09" / "gate.py"
        self.assertEqual(PINNED_C09_GATE_SHA256, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_pinned_c09_release_hash_in_contract(self) -> None:
        contract = json.loads((BASE / "INTERFACE_CONTRACT.json").read_text(encoding="utf-8"))
        self.assertEqual(PINNED_C09_RELEASE_SHA256, contract["pinned_c09_release_sha256"])

    def test_allow_permissions_are_separate(self) -> None:
        result = evaluate_intake(self.intake, now=NOW)
        self.assertTrue(result["permissions"]["collection"]["allowed"])
        self.assertTrue(result["permissions"]["history_retention"]["allowed"])
        self.assertTrue(result["permissions"]["local_display"]["allowed"])
        self.assertFalse(result["permissions"]["link_disclosure"]["allowed"])

    def test_raw_input_is_not_echoed(self) -> None:
        result = evaluate_intake(self.intake, now=NOW)
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn("synthetic:c09:source-001", encoded)
        self.assertNotIn("EVIDENCE:C09:001", encoded)

    def test_input_not_mutated(self) -> None:
        before = copy.deepcopy(self.intake)
        evaluate_intake(self.intake, now=NOW)
        self.assertEqual(before, self.intake)

    def test_deterministic(self) -> None:
        self.assertEqual(evaluate_intake(self.intake, now=NOW), evaluate_intake(self.intake, now=NOW))

    def test_naive_now_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_intake(self.intake, now=datetime(2026, 11, 5, 6, 0, 0))

    def test_non_object_denied(self) -> None:
        result = evaluate_intake([], now=NOW)
        self.assertEqual("DENY", result["decision"])
        self.assertIn("C10_TYPE_MISMATCH", result["reason_codes"])

    def test_c09_verifier_exception_denied(self) -> None:
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic test")
        result = evaluate_intake(self.intake, now=NOW, c09_verifier=fail)
        self.assertIn("C10_C09_VERIFIER_EXCEPTION", result["reason_codes"])

    def test_weakened_c09_decision_denied(self) -> None:
        def weak(*args, **kwargs):
            return {"decision": "ALLOW_SYNTHETIC_PREFLIGHT", "source_state": "SOURCE_BLOCKED", "fixture_only": True,
                    "canonical_write_authorized": True, "b11_mutation_authorized": False, "runtime_authorized": False,
                    "cta_enabled": False, "click_url": None, "reason_codes": []}
        result = evaluate_intake(self.intake, now=NOW, c09_verifier=weak)
        self.assertIn("C10_C09_NOT_ALLOWED", result["reason_codes"])

    def test_decision_schema(self) -> None:
        self.assertEqual(DECISION_SCHEMA, evaluate_intake(self.intake, now=NOW)["schema_version"])

    def test_lifecycle_is_minimized(self) -> None:
        result = evaluate_intake(self.intake, now=NOW)
        self.assertEqual({"mode", "retention_days", "delete_at"}, set(result["data_lifecycle"]))

    def test_denied_has_no_permissions(self) -> None:
        self.intake["privacy"]["contains_personal_data"] = True
        result = evaluate_intake(self.intake, now=NOW)
        self.assertTrue(all(not value["allowed"] for value in result["permissions"].values()))

    def test_only_one_fixture_allows(self) -> None:
        decisions = [
            evaluate_intake(build_case(PACK, case["id"], project_root=ROOT)[0], now=NOW)["decision"]
            for case in PACK["cases"]
        ]
        self.assertEqual(1, decisions.count("ALLOW_SYNTHETIC_PREFLIGHT"))

    def test_source_class_criteria_exact(self) -> None:
        value = json.loads((BASE / "SOURCE_CLASS_CRITERIA.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {"SYNTHETIC_PREFLIGHT", "USER_MANUAL_ENTRY", "USER_FILE", "OFFICIAL_LICENSED_SOURCE"},
            {item["id"] for item in value["classes"]},
        )

    def test_reason_catalog_sorted_unique(self) -> None:
        codes = json.loads((BASE / "REASON_CODES.json").read_text(encoding="utf-8"))["codes"]
        self.assertEqual(sorted(set(codes)), codes)


class StrictJsonTests(unittest.TestCase):
    def valid_payload(self) -> bytes:
        intake, _ = build_case(PACK, "ALLOW_SYNTHETIC_MANUAL_INTAKE", project_root=ROOT)
        return json.dumps(intake, separators=(",", ":")).encode()

    def test_valid_payload(self) -> None:
        self.assertEqual("ALLOW_SYNTHETIC_PREFLIGHT", verify_json(self.valid_payload(), now=NOW)["decision"])

    def test_bytes_required(self) -> None:
        self.assertIn("C10_PAYLOAD_TYPE_INVALID", verify_json("{}", now=NOW)["reason_codes"])  # type: ignore[arg-type]

    def test_size_limit(self) -> None:
        self.assertIn("C10_PAYLOAD_TOO_LARGE", verify_json(b" " * (MAX_JSON_BYTES + 1), now=NOW)["reason_codes"])

    def test_utf8_required(self) -> None:
        self.assertIn("C10_UTF8_INVALID", verify_json(b"\xff", now=NOW)["reason_codes"])

    def test_invalid_json(self) -> None:
        self.assertIn("C10_JSON_INVALID", verify_json(b"{", now=NOW)["reason_codes"])

    def test_duplicate_json_key(self) -> None:
        result = verify_json(b'{"schema_version":"x","schema_version":"y"}', now=NOW)
        self.assertIn("C10_DUPLICATE_JSON_KEY", result["reason_codes"])


class ArtifactTests(unittest.TestCase):
    def test_validator(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "research.import_provenance_c10.validate_all"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        self.assertIn('"status": "VALID"', completed.stdout)

    def test_cli_allow(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "research.import_provenance_c10.cli", str(BASE / "C10_INTAKE_FIXTURES.json"),
             "--now", PACK["evaluation_time"], "--fixture-case", "ALLOW_SYNTHETIC_MANUAL_INTAKE"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)

    def test_cli_deny(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "research.import_provenance_c10.cli", str(BASE / "C10_INTAKE_FIXTURES.json"),
             "--now", PACK["evaluation_time"], "--fixture-case", "USER_FILE_DENIED"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(3, completed.returncode, completed.stderr + completed.stdout)


if __name__ == "__main__":
    unittest.main()
