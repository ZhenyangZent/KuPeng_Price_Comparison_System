from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from a01_app.d03_client import D03Client, D03ProtocolError, D03Unavailable


ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = ROOT / "experiments/A03/test_runs"
PLAN = "a" * 64


def reply(command: str, *, result: str = "READY", plan_id=None, dry_run=False, source="SOURCE_BLOCKED"):
    return {
        "contract": "CDH-LOCAL-MANUAL-SYNC-1", "command": command, "result": result,
        "source_status": source, "data_scope": "USER_PROVIDED_LOCAL_ONLY", "plan_id": plan_id,
        "database_kind": "USER_LOCAL", "dry_run": dry_run,
        "counts": {"scanned": 1, "imported": 0, "duplicate": 0, "quarantined": 0, "pending": 1},
        "receipt": {"state": "UNKNOWN", "sha256": None}, "snapshot": {"state": "UNKNOWN", "sha256": None},
        "backup": {"state": "NOT_REQUIRED", "path": None, "sha256": None}, "errors": [],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


class D03ClientTests(unittest.TestCase):
    def setUp(self):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="a03-d03-", dir=TEST_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def make_client(self, value, *, returncode=0, stderr=""):
        cli = self.root / "scripts/d03/local_operator.py"; cli.parent.mkdir(parents=True, exist_ok=True); cli.write_text("# synthetic stub; never executed\n", encoding="utf-8")
        calls = []
        def runner(arguments, *, cwd, timeout):
            calls.append((arguments, cwd, timeout))
            output = value if isinstance(value, str) else json.dumps(value)
            return subprocess.CompletedProcess(arguments, returncode, output, stderr)
        return D03Client(self.root, python_executable=Path(__file__), runner=runner), calls

    def test_missing_component_is_explicit(self):
        client = D03Client(self.root)
        self.assertFalse(client.available)
        with self.assertRaisesRegex(D03Unavailable, "尚未完成"):
            client.run("status")

    def test_fixed_argument_list_has_no_shell_string(self):
        client, calls = self.make_client(reply("status"))
        client.run("status")
        args = calls[0][0]
        self.assertIsInstance(args, list)
        self.assertEqual(args[2:6], ["status", "--project-root", str(self.root.resolve()), "--json"])
        self.assertNotIn(";", "".join(args))

    def test_dry_run_contract_and_plan(self):
        client, _ = self.make_client(reply("dry-run", result="NEEDS_OPERATOR_CONFIRMATION", plan_id=PLAN, dry_run=True))
        result = client.run("dry-run")
        self.assertTrue(result.data["dry_run"]); self.assertEqual(result.plan_id, PLAN)

    def test_execute_requires_plan_and_confirmation(self):
        client, _ = self.make_client(reply("execute", result="EXECUTED", plan_id=PLAN))
        with self.assertRaises(D03ProtocolError): client.run("execute")
        result = client.run("execute", plan_id=PLAN, operator_confirmed=True)
        self.assertEqual(result.result, "EXECUTED")

    def test_noncanonical_plan_id_is_rejected(self):
        client, _ = self.make_client(reply("dry-run", result="NEEDS_OPERATOR_CONFIRMATION", plan_id="plan-12345678", dry_run=True))
        with self.assertRaisesRegex(D03ProtocolError, "plan_id"):
            client.run("dry-run")

    def test_unknown_command_rejected_without_runner(self):
        client, calls = self.make_client(reply("status"))
        with self.assertRaises(D03ProtocolError): client.run("rm -rf")
        self.assertEqual(calls, [])

    def test_source_authority_upgrade_rejected(self):
        client, _ = self.make_client(reply("status", source="APPROVED"))
        with self.assertRaisesRegex(D03ProtocolError, "提升來源權限"):
            client.run("status")

    def test_malformed_or_extra_stdout_rejected(self):
        for output in ("not-json", json.dumps(reply("status")) + "\nextra"):
            with self.subTest(output=output):
                client, _ = self.make_client(output)
                with self.assertRaisesRegex(D03ProtocolError, "單一 JSON"):
                    client.run("status")

    def test_command_mismatch_rejected(self):
        client, _ = self.make_client(reply("verify"))
        with self.assertRaisesRegex(D03ProtocolError, "command"):
            client.run("status")

    def test_nonzero_return_never_becomes_success(self):
        client, _ = self.make_client(reply("status"), returncode=3, stderr="synthetic failure")
        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            client.run("status")


if __name__ == "__main__":
    unittest.main()
