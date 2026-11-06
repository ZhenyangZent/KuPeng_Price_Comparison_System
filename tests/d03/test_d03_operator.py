from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/d01"))
sys.path.insert(0, str(ROOT / "apps/d03"))
sys.path.insert(0, str(ROOT / "scripts/d03"))

import local_operator
from cdh_d01.database import connect, migrate
from cdh_d01.ingest import ingest_json_bytes
from cdh_d01.sync import SingleWriterLock, SyncPaths
from cdh_d03.identity import D02_RELEASE_SHA256, D02_SOURCE_SHA256, inspect_database, sha256_file
from cdh_d03.operator import CONTRACT, LocalOperator


FIXED_NOW = datetime(2026, 11, 4, 2, 0, 0, tzinfo=timezone.utc)


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode(
        "utf-8"
    )


def observation(
    *,
    submission_id: str | None = None,
    price: int = 5,
    source_kind: str = "USER_ENTERED",
    synthetic: bool = False,
    title: str = "D03 隔離測試商品",
) -> dict[str, object]:
    stamp = FIXED_NOW.isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "schema_version": "CDH-EXCHANGE-1",
        "submission_id": submission_id or str(uuid.uuid4()),
        "record_type": "USER_PRICE_OBSERVATION",
        "created_at_utc": stamp,
        "observed_at_utc": stamp,
        "source": {
            "source_kind": source_kind,
            "permission_scope": "SYNTHETIC_ONLY" if synthetic else "USER_PROVIDED_ONLY",
            "url": "https://www.tw.coupang.com/vp/products/123?itemId=9",
            "note": "isolated test only",
        },
        "offer": {
            "platform": "TW_COUPANG",
            "product_title": title,
            "product_id": None,
            "variant_id": None,
            "seller_id": None,
            "displayed_price_twd": price,
            "price_basis": "DISPLAYED_UNKNOWN",
            "minimum_purchase_quantity": None,
            "shipping_status": "UNKNOWN",
            "shipping_fee_twd": None,
            "stock_status": "UNKNOWN",
            "coupon_status": "UNKNOWN",
            "account_eligibility_status": "UNKNOWN",
            "mandatory_fee_status": "UNKNOWN",
            "notes": "",
        },
        "is_synthetic": synthetic,
    }


def announcement() -> dict[str, object]:
    value = observation(source_kind="PUBLIC_NOTICE_MANUAL")
    value["record_type"] = "PROMO_CLUE"
    value["promo_claim"] = "synthetic announcement clue"
    value["published_at_utc"] = value["observed_at_utc"]
    value["offer"]["displayed_price_twd"] = None
    value["source"]["permission_scope"] = "DOCUMENT_RESEARCH_ONLY"
    value["source"]["url"] = "https://tw.coupangcorp.com/archives/6698/"
    return value


class D03Case(unittest.TestCase):
    def setUp(self) -> None:
        base = ROOT / "experiments/D03/test_tmp"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name).resolve()
        self.paths = SyncPaths.for_root(self.root)
        connection = connect(self.paths.database)
        try:
            migrate(connection)
        finally:
            connection.close()
        self.now = datetime.now(timezone.utc)
        self.operator = LocalOperator(
            code_root=ROOT,
            project_root=self.root,
            isolated_test=True,
            now_fn=lambda: self.now,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def put(self, value: dict[str, object]) -> Path:
        self.paths.inbox.mkdir(parents=True, exist_ok=True)
        target = self.paths.inbox / f"submission_{value['submission_id']}.json"
        target.write_bytes(encoded(value))
        return target

    def db_scalar(self, sql: str):
        connection = sqlite3.connect(self.paths.database)
        try:
            return connection.execute(sql).fetchone()[0]
        finally:
            connection.close()

    @staticmethod
    def db_scalar_at(path: Path, sql: str):
        connection = sqlite3.connect(path)
        try:
            return connection.execute(sql).fetchone()[0]
        finally:
            connection.close()

    def plan(self, value: dict[str, object] | None = None) -> tuple[dict[str, object], str]:
        if value is not None:
            self.put(value)
        result = self.operator.dry_run()
        self.assertEqual(result["result"], "NEEDS_OPERATOR_CONFIRMATION", result)
        self.assertIsInstance(result["plan_id"], str)
        return result, str(result["plan_id"])

    def execute_one(self, value: dict[str, object] | None = None) -> dict[str, object]:
        _, plan_id = self.plan(value)
        result = self.operator.execute(plan_id=plan_id, operator_confirmed=True)
        self.assertEqual(result["result"], "EXECUTED", result)
        return result

    def test_common_schema_status_preflight_dry_run_and_verify(self):
        for output in (self.operator.status(), self.operator.preflight(), self.operator.dry_run(), self.operator.verify()):
            self.assertEqual(output["contract"], CONTRACT)
            for field in (
                "command",
                "result",
                "source_status",
                "data_scope",
                "plan_id",
                "database_kind",
                "dry_run",
                "counts",
                "receipt",
                "snapshot",
                "backup",
                "errors",
                "generated_at",
            ):
                self.assertIn(field, output)

    def test_status_is_read_only(self):
        before = sha256_file(self.paths.database)
        self.assertEqual(self.operator.status()["result"], "READY")
        self.assertEqual(sha256_file(self.paths.database), before)
        self.assertFalse((self.root / "reports/D03/001").exists())

    def test_preflight_is_read_only(self):
        self.put(observation())
        before = sha256_file(self.paths.database)
        result = self.operator.preflight()
        self.assertEqual(result["result"], "READY")
        self.assertEqual(result["counts"]["scanned"], 1)
        self.assertEqual(sha256_file(self.paths.database), before)
        self.assertFalse((self.root / "reports/D03/001").exists())

    def test_empty_inbox_dry_run_is_no_changes_without_plan(self):
        before = sha256_file(self.paths.database)
        result = self.operator.dry_run()
        self.assertEqual(result["result"], "NO_CHANGES")
        self.assertIsNone(result["plan_id"])
        self.assertEqual(sha256_file(self.paths.database), before)
        self.assertFalse(self.paths.snapshots.exists())
        self.assertFalse(self.paths.receipts.exists())

    def test_valid_dry_run_creates_bound_plan_without_formal_data_change(self):
        self.put(observation())
        db_before = sha256_file(self.paths.database)
        result = self.operator.dry_run()
        self.assertEqual(result["result"], "NEEDS_OPERATOR_CONFIRMATION")
        self.assertEqual(result["counts"]["imported"], 1)
        self.assertEqual(sha256_file(self.paths.database), db_before)
        self.assertFalse(self.paths.snapshots.exists())
        self.assertFalse(self.paths.receipts.exists())
        self.assertTrue((self.root / f"reports/D03/001/plans/{result['plan_id']}.json").is_file())

    def test_execute_requires_operator_confirmation(self):
        _, plan_id = self.plan(observation())
        result = self.operator.execute(plan_id=plan_id, operator_confirmed=False)
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["errors"][0]["code"], "OPERATOR_CONFIRMATION_REQUIRED")
        self.assertEqual(self.db_scalar("SELECT COUNT(*) FROM observations"), 0)

    def test_execute_requires_plan_id(self):
        result = self.operator.execute(plan_id=None, operator_confirmed=True)
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["errors"][0]["code"], "PLAN_ID_REQUIRED")

    def test_first_execute_imports_and_creates_verified_backup_receipt_snapshot(self):
        result = self.execute_one(observation(price=19))
        self.assertEqual(result["counts"]["imported"], 1)
        self.assertEqual(result["backup"]["state"], "VERIFIED")
        self.assertEqual(self.db_scalar("SELECT displayed_price_twd FROM observations"), 19)
        self.assertTrue((self.paths.snapshots / "latest.json").is_file())
        self.assertTrue((self.paths.receipts / "latest.json").is_file())
        backup_db = self.root / str(result["backup"]["path"]) / "observations.sqlite3"
        self.assertEqual(inspect_database(backup_db)["integrity_check"], ["ok"])
        self.assertEqual(self.db_scalar_at(backup_db, "SELECT COUNT(*) FROM observations"), 0)

    def test_verify_after_execute_is_ready(self):
        executed = self.execute_one(observation())
        verified = self.operator.verify()
        self.assertEqual(verified["result"], "READY", verified)
        self.assertEqual(verified["plan_id"], executed["plan_id"])
        self.assertEqual(verified["receipt"]["sha256"], executed["receipt"]["sha256"])

    def test_verify_without_execution_is_blocked_and_read_only(self):
        before = sha256_file(self.paths.database)
        result = self.operator.verify()
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("NO_SUCCESSFUL_EXECUTION", {item["code"] for item in result["errors"]})
        self.assertEqual(sha256_file(self.paths.database), before)

    def test_duplicate_execute_does_not_duplicate_observation(self):
        value = observation()
        self.execute_one(value)
        second_plan = self.operator.dry_run()
        self.assertEqual(second_plan["counts"]["duplicate"], 1)
        second = self.operator.execute(plan_id=second_plan["plan_id"], operator_confirmed=True)
        self.assertEqual(second["result"], "EXECUTED", second)
        self.assertEqual(second["counts"]["duplicate"], 1)
        self.assertEqual(self.db_scalar("SELECT COUNT(*) FROM observations"), 1)

    def test_changed_same_uuid_is_blocked_as_quarantine_preview(self):
        identifier = str(uuid.uuid4())
        path = self.put(observation(submission_id=identifier, price=5))
        first = self.operator.dry_run()
        self.assertEqual(self.operator.execute(plan_id=first["plan_id"], operator_confirmed=True)["result"], "EXECUTED")
        path.write_bytes(encoded(observation(submission_id=identifier, price=6)))
        result = self.operator.dry_run()
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["counts"]["quarantined"], 1)
        self.assertEqual(self.db_scalar("SELECT displayed_price_twd FROM observations"), 5)

    def test_malformed_json_blocks_without_partial_success(self):
        self.paths.inbox.mkdir(parents=True)
        identifier = str(uuid.uuid4())
        (self.paths.inbox / f"submission_{identifier}.json").write_bytes(b"{bad")
        result = self.operator.dry_run()
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["counts"]["quarantined"], 1)
        self.assertEqual(self.db_scalar("SELECT COUNT(*) FROM observations"), 0)

    def test_valid_plus_malformed_batch_has_no_partial_formal_write(self):
        self.put(observation())
        identifier = str(uuid.uuid4())
        (self.paths.inbox / f"submission_{identifier}.json").write_bytes(b"{bad")
        result = self.operator.dry_run()
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["counts"]["imported"], 1)
        self.assertEqual(result["counts"]["quarantined"], 1)
        self.assertEqual(self.db_scalar("SELECT COUNT(*) FROM observations"), 0)

    def test_bulk_100_user_files_execute_with_exact_count(self):
        for index in range(100):
            self.put(observation(source_kind="USER_FILE", price=index))
        plan = self.operator.dry_run()
        self.assertEqual(plan["result"], "NEEDS_OPERATOR_CONFIRMATION")
        self.assertEqual(plan["counts"]["scanned"], 100)
        self.assertEqual(plan["counts"]["imported"], 100)
        executed = self.operator.execute(plan_id=plan["plan_id"], operator_confirmed=True)
        self.assertEqual(executed["result"], "EXECUTED", executed)
        self.assertEqual(executed["counts"]["imported"], 100)
        self.assertEqual(self.db_scalar("SELECT COUNT(*) FROM observations"), 100)

    def test_synthetic_source_is_blocked(self):
        self.put(observation(source_kind="SYNTHETIC_TEST", synthetic=True))
        result = self.operator.dry_run()
        self.assertEqual(result["result"], "BLOCKED")
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("SYNTHETIC_INPUT_FORBIDDEN", codes)
        self.assertEqual(self.db_scalar("SELECT COUNT(*) FROM observations"), 0)

    def test_public_announcement_is_blocked_from_price_observations(self):
        self.put(announcement())
        result = self.operator.preflight()
        self.assertEqual(result["result"], "BLOCKED")
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("NON_OBSERVATION_INPUT_FORBIDDEN", codes)
        self.assertIn("SOURCE_KIND_NOT_USER_PROVIDED", codes)

    def test_zero_price_stays_unverified_and_unknown(self):
        self.execute_one(observation(price=0))
        connection = sqlite3.connect(self.paths.database)
        try:
            row = connection.execute(
                "SELECT displayed_price_twd,qualification_state,shipping_status,shipping_fee_twd FROM observations"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row, (0, "UNVERIFIED", "UNKNOWN", None))

    def test_user_file_source_kind_is_preserved(self):
        self.execute_one(observation(source_kind="USER_FILE"))
        self.assertEqual(self.db_scalar("SELECT source_kind FROM observations"), "USER_FILE")

    def test_plan_expiry_blocks_execute(self):
        _, plan_id = self.plan(observation())
        self.now = self.now + timedelta(minutes=11)
        result = self.operator.execute(plan_id=plan_id, operator_confirmed=True)
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["errors"][0]["code"], "PLAN_EXPIRED")

    def test_input_change_after_plan_blocks_execute(self):
        value = observation(price=5)
        path = self.put(value)
        plan = self.operator.dry_run()
        value["offer"]["displayed_price_twd"] = 6
        path.write_bytes(encoded(value))
        result = self.operator.execute(plan_id=plan["plan_id"], operator_confirmed=True)
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("PLAN_STATE_CHANGED", {item["code"] for item in result["errors"]})
        self.assertEqual(self.db_scalar("SELECT COUNT(*) FROM observations"), 0)

    def test_database_change_after_plan_blocks_execute(self):
        _, plan_id = self.plan(observation())
        connection = connect(self.paths.database)
        try:
            other = observation()
            ingest_json_bytes(connection, encoded(other), source_path="isolated-direct-change.json")
        finally:
            connection.close()
        result = self.operator.execute(plan_id=plan_id, operator_confirmed=True)
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("PLAN_STATE_CHANGED", {item["code"] for item in result["errors"]})

    def test_tampered_plan_is_rejected(self):
        _, plan_id = self.plan(observation())
        path = self.root / f"reports/D03/001/plans/{plan_id}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["counts"]["imported"] = 99
        path.write_text(json.dumps(document), encoding="utf-8")
        result = self.operator.execute(plan_id=plan_id, operator_confirmed=True)
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["errors"][0]["code"], "PLAN_INTEGRITY_FAILED")

    def test_consumed_plan_cannot_execute_twice(self):
        _, plan_id = self.plan(observation())
        self.assertEqual(self.operator.execute(plan_id=plan_id, operator_confirmed=True)["result"], "EXECUTED")
        result = self.operator.execute(plan_id=plan_id, operator_confirmed=True)
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["errors"][0]["code"], "PLAN_ALREADY_CONSUMED")

    def test_backup_failure_refuses_sync(self):
        _, plan_id = self.plan(observation())
        result = self.operator.execute(
            plan_id=plan_id,
            operator_confirmed=True,
            _backup_fault="BEFORE_DATABASE",
        )
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["backup"]["state"], "FAILED")
        self.assertEqual(self.db_scalar("SELECT COUNT(*) FROM observations"), 0)
        self.assertFalse((self.paths.receipts / "latest.json").exists())

    def test_sync_failure_after_database_commit_keeps_verified_restore_point(self):
        _, plan_id = self.plan(observation())
        result = self.operator.execute(
            plan_id=plan_id,
            operator_confirmed=True,
            _sync_fault="AFTER_DATABASE_COMMIT",
        )
        self.assertEqual(result["result"], "FAILED")
        self.assertEqual(result["backup"]["state"], "VERIFIED")
        self.assertEqual(self.db_scalar("SELECT COUNT(*) FROM observations"), 1)
        self.assertFalse((self.paths.receipts / "latest.json").exists())
        target = self.root / "restore_evidence/restored.sqlite3"
        restored = self.operator.restore_backup_for_isolated_test(str(result["backup"]["path"]), target)
        self.assertEqual(restored["state"], "VERIFIED")
        self.assertEqual(self.db_scalar_at(target, "SELECT COUNT(*) FROM observations"), 0)

    def test_sync_failure_after_snapshot_never_reports_executed(self):
        _, plan_id = self.plan(observation())
        result = self.operator.execute(plan_id=plan_id, operator_confirmed=True, _sync_fault="AFTER_SNAPSHOT")
        self.assertEqual(result["result"], "FAILED")
        self.assertEqual(result["backup"]["state"], "VERIFIED")
        self.assertTrue((self.paths.snapshots / "latest.json").exists())
        self.assertFalse((self.paths.receipts / "latest.json").exists())

    def test_insufficient_backup_space_blocks_preflight(self):
        operator = LocalOperator(
            code_root=ROOT,
            project_root=self.root,
            isolated_test=True,
            now_fn=lambda: self.now,
            disk_free_override=0,
        )
        result = operator.preflight()
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("BACKUP_SPACE_INSUFFICIENT", {item["code"] for item in result["errors"]})

    def test_single_writer_contention_blocks_preflight(self):
        with SingleWriterLock(self.paths.lock):
            result = self.operator.preflight()
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("SINGLE_WRITER_BUSY", {item["code"] for item in result["errors"]})

    def test_receipt_snapshot_mismatch_is_syncing_and_blocked(self):
        self.execute_one(observation())
        snapshot = json.loads((self.paths.snapshots / "latest.json").read_text(encoding="utf-8"))
        snapshot["counts"]["total_entries"] = 999
        (self.paths.snapshots / "latest.json").write_text(json.dumps(snapshot), encoding="utf-8")
        result = self.operator.status()
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["receipt"]["state"], "SYNCING")
        self.assertIn("RECEIPT_SNAPSHOT_MISMATCH", {item["code"] for item in result["errors"]})

    def test_tampered_receipt_blocks_verify(self):
        self.execute_one(observation())
        (self.paths.receipts / "latest.json").write_text("{}", encoding="utf-8")
        result = self.operator.verify()
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("RECEIPT_CHANGED_AFTER_EXECUTION", {item["code"] for item in result["errors"]})

    def test_restart_consistency_reads_same_execution(self):
        executed = self.execute_one(observation())
        restarted = LocalOperator(
            code_root=ROOT,
            project_root=self.root,
            isolated_test=True,
            now_fn=lambda: self.now,
        )
        verified = restarted.verify()
        self.assertEqual(verified["result"], "READY")
        self.assertEqual(verified["plan_id"], executed["plan_id"])

    def test_second_backup_captures_existing_snapshot_and_receipt(self):
        self.execute_one(observation())
        plan = self.operator.dry_run()
        second = self.operator.execute(plan_id=plan["plan_id"], operator_confirmed=True)
        manifest = json.loads(
            (self.root / str(second["backup"]["path"]) / "backup_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["snapshot"]["state"], "VERIFIED")
        self.assertEqual(manifest["receipt"]["state"], "VERIFIED")

    def test_approved_automatic_source_row_blocks_preflight(self):
        connection = sqlite3.connect(self.paths.database)
        try:
            connection.execute(
                """INSERT INTO source_permissions
                (source_id,operation,evidence_url,evidence_summary,scope,reviewed_at_utc,status,quota)
                VALUES('unexpected','AUTOMATED_INGEST',NULL,'test','test','2026-11-04T00:00:00Z','APPROVED','UNKNOWN')"""
            )
            connection.commit()
        finally:
            connection.close()
        result = self.operator.preflight()
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("AUTOMATIC_SOURCE_APPROVAL_PRESENT", {item["code"] for item in result["errors"]})
        self.assertEqual(result["source_status"], "SOURCE_BLOCKED")

    def test_capacity_limit_fails_closed(self):
        self.put(observation())
        self.put(observation())
        with mock.patch("cdh_d01.sync.MAX_RECEIPT_ENTRIES", 1):
            result = self.operator.preflight()
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("INBOX_SCAN_FAILED", {item["code"] for item in result["errors"]})

    def test_file_changed_during_preflight_is_blocked(self):
        value = observation()
        path = self.put(value)
        data = path.read_bytes()
        with mock.patch("cdh_d01.sync._stable_read", return_value=(data, False)):
            result = self.operator.preflight()
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("INBOX_FILE_CHANGED", {item["code"] for item in result["errors"]})

    def test_cli_status_emits_one_json_object_and_zero_exit(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = local_operator.main(
                ["status", "--project-root", str(self.root), "--json"],
                canonical_root=self.root,
                code_root=ROOT,
                isolated_test=True,
            )
        value = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(value["contract"], CONTRACT)
        self.assertEqual(value["command"], "status")

    def test_cli_rejects_external_root_and_shell_metacharacters(self):
        output = io.StringIO()
        malicious = self.root.parent / "outside&calc"
        with contextlib.redirect_stdout(output):
            exit_code = local_operator.main(
                ["status", "--project-root", str(malicious), "--json"],
                canonical_root=self.root,
                code_root=ROOT,
                isolated_test=True,
            )
        value = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(value["result"], "BLOCKED")
        self.assertEqual(value["errors"][0]["code"], "CLI_USAGE_ERROR")
        self.assertFalse(malicious.exists())

    def test_cli_unknown_command_returns_json_error(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = local_operator.main(
                ["destroy", "--project-root", str(self.root), "--json"],
                canonical_root=self.root,
                code_root=ROOT,
                isolated_test=True,
            )
        value = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(value["result"], "BLOCKED")
        self.assertEqual(value["errors"][0]["code"], "CLI_USAGE_ERROR")

    def test_logs_and_plan_do_not_contain_product_text_or_secrets(self):
        sentinel = "SECRET_SENTINEL_PRODUCT_TOKEN"
        self.plan(observation(title=sentinel))
        text = "\n".join(path.read_text(encoding="utf-8") for path in (self.root / "reports/D03/001").rglob("*.json*"))
        self.assertNotIn(sentinel, text)

    def test_d02_frozen_identity_is_exact(self):
        self.assertEqual(sha256_file(ROOT / "review/releases/CDH_D02_001_REVIEW.zip"), D02_RELEASE_SHA256)
        for relative, expected in D02_SOURCE_SHA256.items():
            self.assertEqual(sha256_file(ROOT / relative), expected)
        self.assertEqual(self.operator.status()["d02"]["state"], "VERIFIED")

    def test_no_network_browser_registry_scheduler_or_commerce_code(self):
        runtime_files = list((ROOT / "apps/d03").rglob("*.py")) + [ROOT / "scripts/d03/local_operator.py"]
        runtime = "\n".join(path.read_text(encoding="utf-8").lower() for path in runtime_files)
        for forbidden in (
            "import requests",
            "urllib.request",
            "selenium",
            "playwright",
            "webbrowser",
            "winreg",
            "schtasks",
            "shell=true",
        ):
            self.assertNotIn(forbidden, runtime)


if __name__ == "__main__":
    unittest.main(verbosity=2)
