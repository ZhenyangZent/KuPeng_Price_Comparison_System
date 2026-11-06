from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from a01_app.d03_client import (
    D03Busy,
    D03Client,
    D03CommandError,
    D03ProtocolError,
    plan_is_current,
)


ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = ROOT / "experiments/A04/test_tmp"
PLAN = "b" * 64


def payload(command: str, *, result: str = "READY", plan_id=None, errors=None, dry_run=False, generated_at=None):
    return {
        "contract": "CDH-LOCAL-MANUAL-SYNC-1", "command": command, "result": result,
        "source_status": "SOURCE_BLOCKED", "data_scope": "USER_PROVIDED_LOCAL_ONLY", "plan_id": plan_id,
        "database_kind": "USER_LOCAL", "dry_run": dry_run,
        "counts": {"scanned": 1, "imported": 0, "duplicate": 0, "quarantined": 0, "pending": 1},
        "receipt": {"state": "UNKNOWN", "sha256": None}, "snapshot": {"state": "UNKNOWN", "sha256": None},
        "backup": {"state": "NOT_REQUIRED", "path": None, "sha256": None}, "errors": errors or [],
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


class D03ClientHardeningTests(unittest.TestCase):
    def setUp(self):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="client-", dir=TEST_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        cli = self.root / "scripts/d03/local_operator.py"
        cli.parent.mkdir(parents=True)
        cli.write_text("# synthetic test stub\n", encoding="utf-8")

    def client(self, value, *, code=0):
        def runner(arguments, *, cwd, timeout):
            return subprocess.CompletedProcess(arguments, code, json.dumps(value), "")
        return D03Client(self.root, python_executable=Path(__file__), runner=runner)

    def test_dry_run_plan_has_bounded_expiry(self):
        stamp = datetime.now(timezone.utc).replace(microsecond=0)
        reply = self.client(payload("dry-run", result="NEEDS_OPERATOR_CONFIRMATION", plan_id=PLAN, dry_run=True, generated_at=stamp.isoformat().replace("+00:00", "Z"))).run("dry-run")
        self.assertEqual(reply.expires_at, stamp + timedelta(minutes=10))
        self.assertTrue(plan_is_current(reply, now=stamp + timedelta(minutes=9)))
        self.assertFalse(plan_is_current(reply, now=stamp + timedelta(minutes=11)))

    def test_nonzero_json_preserves_machine_readable_error(self):
        value = payload("execute", result="BLOCKED", errors=[{"code": "PLAN_EXPIRED", "detail": "synthetic expiry"}])
        client = self.client(value, code=2)
        with self.assertRaises(D03CommandError) as caught:
            client.run("execute", plan_id=PLAN, operator_confirmed=True)
        self.assertEqual(caught.exception.reply.errors[0]["code"], "PLAN_EXPIRED")
        self.assertIn("synthetic expiry", str(caught.exception))

    def test_error_strings_are_rejected_at_trust_boundary(self):
        value = payload("status", result="BLOCKED", errors=["not-an-error-object"])
        with self.assertRaisesRegex(D03ProtocolError, "errors"):
            self.client(value, code=2).run("status")

    def test_blocked_without_reason_is_rejected(self):
        value = payload("status", result="BLOCKED", errors=[])
        with self.assertRaisesRegex(D03ProtocolError, "錯誤原因"):
            self.client(value, code=2).run("status")

    def test_in_process_guard_rejects_concurrent_clients(self):
        entered, release = threading.Event(), threading.Event()
        first_result = []
        def slow(arguments, *, cwd, timeout):
            entered.set(); release.wait(2)
            return subprocess.CompletedProcess(arguments, 0, json.dumps(payload("status")), "")
        first = D03Client(self.root, python_executable=Path(__file__), runner=slow)
        second = self.client(payload("status"))
        thread = threading.Thread(target=lambda: first_result.append(first.run("status")))
        thread.start(); self.assertTrue(entered.wait(1))
        with self.assertRaises(D03Busy):
            second.run("status")
        release.set(); thread.join(2)
        self.assertEqual(first_result[0].result, "READY")


if __name__ == "__main__":
    unittest.main()
