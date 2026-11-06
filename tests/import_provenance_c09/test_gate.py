from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path

from research.import_provenance_c09.fixture_builder import build_case, load_pack
from research.import_provenance_c09.gate import (
    DECISION_SCHEMA,
    MAX_JSON_BYTES,
    verify_json,
    verify_request,
)

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "research" / "import_provenance_c09"
PACK = load_pack(BASE / "C09_GATE_FIXTURES.json")
NOW = datetime.fromisoformat(PACK["evaluation_time"].replace("Z", "+00:00"))


class FixtureGateTests(unittest.TestCase):
    pass


def _fixture_test(case_id: str):
    def test(self: unittest.TestCase) -> None:
        request, expected = build_case(PACK, case_id)
        result = verify_request(request, now=NOW)
        self.assertEqual(expected["decision"], result["decision"])
        self.assertTrue(set(expected["codes"]).issubset(result["reason_codes"]))
        self.assertEqual("SOURCE_BLOCKED", result["source_state"])
        self.assertFalse(result["runtime_authorized"])
        self.assertFalse(result["cta_enabled"])
        self.assertIsNone(result["click_url"])
    return test


for _case in PACK["cases"]:
    setattr(FixtureGateTests, f"test_fixture_{_case['id'].lower()}", _fixture_test(_case["id"]))


class InterfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = copy.deepcopy(PACK["base_request"])

    def test_valid_permissions_are_separate(self) -> None:
        result = verify_request(self.request, now=NOW)
        self.assertTrue(result["permissions"]["collection"]["allowed"])
        self.assertTrue(result["permissions"]["retention"]["allowed"])
        self.assertTrue(result["permissions"]["display"]["allowed"])
        self.assertFalse(result["permissions"]["link_disclosure"]["allowed"])

    def test_valid_decision_never_grants_runtime_or_write(self) -> None:
        result = verify_request(self.request, now=NOW)
        self.assertFalse(result["canonical_write_authorized"])
        self.assertFalse(result["b11_mutation_authorized"])
        self.assertFalse(result["runtime_authorized"])

    def test_input_is_not_mutated(self) -> None:
        before = copy.deepcopy(self.request)
        verify_request(self.request, now=NOW)
        self.assertEqual(before, self.request)

    def test_decision_is_deterministic(self) -> None:
        self.assertEqual(verify_request(self.request, now=NOW), verify_request(self.request, now=NOW))

    def test_naive_now_rejected(self) -> None:
        with self.assertRaises(ValueError):
            verify_request(self.request, now=datetime(2026, 11, 5, 6, 0, 0))

    def test_non_object_defaults_deny(self) -> None:
        result = verify_request([], now=NOW)
        self.assertEqual("DENY", result["decision"])
        self.assertIn("TYPE_MISMATCH", result["reason_codes"])

    def test_denied_request_has_no_permissions(self) -> None:
        self.request["intent"]["operation"] = "CANONICAL_IMPORT"
        result = verify_request(self.request, now=NOW)
        self.assertTrue(all(not item["allowed"] for item in result["permissions"].values()))

    def test_decision_schema_exact(self) -> None:
        self.assertEqual(DECISION_SCHEMA, verify_request(self.request, now=NOW)["schema_version"])

    def test_reason_catalog_sorted_unique(self) -> None:
        codes = json.loads((BASE / "REASON_CODES.json").read_text(encoding="utf-8"))["codes"]
        self.assertEqual(sorted(set(codes)), codes)

    def test_fixture_ids_unique(self) -> None:
        ids = [case["id"] for case in PACK["cases"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_only_one_fixture_allows(self) -> None:
        decisions = [verify_request(build_case(PACK, case["id"])[0], now=NOW)["decision"] for case in PACK["cases"]]
        self.assertEqual(1, decisions.count("ALLOW_SYNTHETIC_PREFLIGHT"))

    def test_interface_contract_fail_closed(self) -> None:
        contract = json.loads((BASE / "INTERFACE_CONTRACT.json").read_text(encoding="utf-8"))
        self.assertEqual("DENY", contract["default_without_verifier"])
        self.assertFalse(contract["canonical_write_authorized"])


class StrictJsonTests(unittest.TestCase):
    def payload(self) -> bytes:
        return json.dumps(PACK["base_request"], separators=(",", ":")).encode()

    def test_valid_bytes_allow(self) -> None:
        self.assertEqual("ALLOW_SYNTHETIC_PREFLIGHT", verify_json(self.payload(), now=NOW)["decision"])

    def test_payload_must_be_bytes(self) -> None:
        result = verify_json("{}", now=NOW)  # type: ignore[arg-type]
        self.assertIn("PAYLOAD_TYPE_INVALID", result["reason_codes"])

    def test_payload_size_limit(self) -> None:
        result = verify_json(b" " * (MAX_JSON_BYTES + 1), now=NOW)
        self.assertIn("PAYLOAD_TOO_LARGE", result["reason_codes"])

    def test_utf8_required(self) -> None:
        result = verify_json(b"\xff", now=NOW)
        self.assertIn("UTF8_INVALID", result["reason_codes"])

    def test_invalid_json_denied(self) -> None:
        result = verify_json(b"{", now=NOW)
        self.assertIn("JSON_INVALID", result["reason_codes"])

    def test_duplicate_json_key_denied(self) -> None:
        result = verify_json(b'{"schema_version":"x","schema_version":"y"}', now=NOW)
        self.assertIn("DUPLICATE_JSON_KEY", result["reason_codes"])

    def test_json_array_denied(self) -> None:
        result = verify_json(b"[]", now=NOW)
        self.assertEqual("DENY", result["decision"])
        self.assertIn("TYPE_MISMATCH", result["reason_codes"])


class ArtifactTests(unittest.TestCase):
    def test_validator(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "research.import_provenance_c09.validate_all"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        self.assertIn('"status": "VALID"', completed.stdout)

    def test_cli_allow_exit_zero(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "research.import_provenance_c09.cli", str(BASE / "C09_GATE_FIXTURES.json"),
             "--now", PACK["evaluation_time"], "--fixture-case", "ALLOW_SCOPED_SYNTHETIC_PREFLIGHT"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)

    def test_cli_deny_exit_three(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "research.import_provenance_c09.cli", str(BASE / "C09_GATE_FIXTURES.json"),
             "--now", PACK["evaluation_time"], "--fixture-case", "EVIDENCE_REVOKED"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(3, completed.returncode, completed.stderr + completed.stdout)


if __name__ == "__main__":
    unittest.main()
