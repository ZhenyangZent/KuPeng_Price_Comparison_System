from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.ci_web_g07.a10_gate import evaluate
from tools.ci_web_g07.audit import _b11_fixture_gate, _f06_env_gate


class ControlledExceptionTests(unittest.TestCase):
    def test_f06_env_exception_is_exact(self):
        name = "release/services/affiliate_coupon_gate_v6/.env.example"
        exact = b"# Inert documentation only. This module never loads environment files.\nCDH_AFFILIATE_COUPON_GATE_MODE=disabled\n"
        self.assertTrue(_f06_env_gate({name: exact})["passed"])
        self.assertFalse(_f06_env_gate({name: exact + b"TOKEN=value\n"})["passed"])

    def test_b11_database_exception_requires_authority_hash(self):
        base = "release/services/price_coupon_v4/fixtures/b11_suite"; files = {}; snapshots = []
        for directory in ("active", "expired-source", "revoked-source", "empty-history"):
            db = (directory + " synthetic").encode(); db_sha = hashlib.sha256(db).hexdigest()
            authority = json.dumps({"database_sha256": db_sha, "data_classification": "SYNTHETIC_FIXTURE", "contains_private_data": False}, sort_keys=True).encode()
            files[f"{base}/{directory}/coupon.sqlite3"] = db; files[f"{base}/{directory}/coupon.authority.json"] = authority
            snapshots.append({"directory": directory, "database": "coupon.sqlite3", "database_sha256": db_sha, "authority": "coupon.authority.json", "authority_sha256": hashlib.sha256(authority).hexdigest()})
        files[f"{base}/FIXTURE_MANIFEST.json"] = json.dumps({"classification": "CONTRACT_FIXTURE_TEST_ONLY", "schema_version": "CDH-B11-FIXTURE-SUITE-1", "snapshots": snapshots}).encode()
        self.assertTrue(_b11_fixture_gate(files)["passed"])
        files[f"{base}/active/coupon.sqlite3"] += b"tamper"
        self.assertFalse(_b11_fixture_gate(files)["passed"])


class A10GateTests(unittest.TestCase):
    def test_unacknowledged_candidate_is_not_used(self):
        base = Path.cwd() / "review" / "G07" / "test_tmp"; base.mkdir(parents=True, exist_ok=True)
        candidate = base / "CDH_A_R07_001_REVIEW.zip"; candidate.write_bytes(b"candidate")
        ack = base / "ACK.json"; ack.write_text(json.dumps({"items": [], "not_received": ["A10"]}), encoding="utf-8")
        result = evaluate(candidate=candidate, receipt_ack=ack, explicit_sha256=None, explicit_lock_sha256=None)
        self.assertEqual(result["status"], "NOT_RUN_INPUT_UNAVAILABLE"); self.assertFalse(result["browser_executed"])
        candidate.unlink(); ack.unlink()


if __name__ == "__main__": unittest.main()
