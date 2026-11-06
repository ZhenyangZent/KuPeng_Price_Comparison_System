from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/d01"))
sys.path.insert(0, str(ROOT / "apps/d03"))

from cdh_d01.database import connect, migrate  # noqa: E402
from cdh_d01.sync import SyncPaths  # noqa: E402
from cdh_d03.identity import hash_optional, inspect_database, sha256_file  # noqa: E402
from cdh_d03.operator import LocalOperator  # noqa: E402


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def payload(*, source_kind: str, price: int) -> dict[str, object]:
    stamp = utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "schema_version": "CDH-EXCHANGE-1",
        "submission_id": str(uuid.uuid4()),
        "record_type": "USER_PRICE_OBSERVATION",
        "created_at_utc": stamp,
        "observed_at_utc": stamp,
        "source": {
            "source_kind": source_kind,
            "permission_scope": "USER_PROVIDED_ONLY",
            "url": "https://www.tw.coupang.com/vp/products/ISOLATED-D03",
            "note": "isolated synthetic simulation of explicit local user input",
        },
        "offer": {
            "platform": "TW_COUPANG",
            "product_title": "D03 ISOLATED SYNTHETIC USER-INPUT SIMULATION",
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
            "notes": "never use as a real product observation",
        },
        "is_synthetic": False,
    }


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode(
        "utf-8"
    )


def initialize(workspace: Path) -> tuple[LocalOperator, SyncPaths]:
    workspace.mkdir(parents=True)
    paths = SyncPaths.for_root(workspace)
    connection = connect(paths.database)
    try:
        migrate(connection)
    finally:
        connection.close()
    return LocalOperator(code_root=ROOT, project_root=workspace, isolated_test=True), paths


def write_submission(paths: SyncPaths, value: dict[str, object]) -> None:
    paths.inbox.mkdir(parents=True, exist_ok=True)
    (paths.inbox / f"submission_{value['submission_id']}.json").write_bytes(encoded(value))


def scalar(path: Path, sql: str):
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql).fetchone()[0]
    finally:
        connection.close()


def slim(response: dict[str, object]) -> dict[str, object]:
    return {
        "command": response["command"],
        "result": response["result"],
        "plan_id": response["plan_id"],
        "counts": response["counts"],
        "receipt": response["receipt"],
        "snapshot": response["snapshot"],
        "backup": response["backup"],
        "error_codes": [item["code"] for item in response["errors"]],
        "generated_at": response["generated_at"],
    }


def main() -> int:
    base = ROOT / "experiments/D03/001"
    if base.exists():
        raise SystemExit(f"refusing to overwrite existing evidence workspace: {base}")
    formal_db = ROOT / "data/d01/observations.sqlite3"
    formal_snapshot = ROOT / "data/exchange/snapshots/latest.json"
    formal_d02 = ROOT / "review/releases/CDH_D02_001_REVIEW.zip"
    protected_before = {
        "database": sha256_file(formal_db),
        "snapshot": sha256_file(formal_snapshot),
        "d02_release": sha256_file(formal_d02),
        "runtime_receipt_exists": (ROOT / "data/exchange/receipts/latest.json").exists(),
    }

    failure_root = base / "failure_workspace"
    failure_operator, failure_paths = initialize(failure_root)
    write_submission(failure_paths, payload(source_kind="USER_ENTERED", price=7))
    failure_dry = failure_operator.dry_run()
    failure_execute = failure_operator.execute(
        plan_id=str(failure_dry["plan_id"]),
        operator_confirmed=True,
        _sync_fault="AFTER_DATABASE_COMMIT",
    )
    backup_relative = str(failure_execute["backup"]["path"])
    restore_target = failure_root / "restore_evidence/restored.sqlite3"
    restore = failure_operator.restore_backup_for_isolated_test(backup_relative, restore_target)
    backup_database = failure_root / backup_relative / "observations.sqlite3"

    success_root = base / "success_workspace"
    success_operator, success_paths = initialize(success_root)
    write_submission(success_paths, payload(source_kind="USER_ENTERED", price=0))
    write_submission(success_paths, payload(source_kind="USER_FILE", price=42))
    success_status = success_operator.status()
    success_preflight = success_operator.preflight()
    success_dry = success_operator.dry_run()
    success_execute = success_operator.execute(plan_id=str(success_dry["plan_id"]), operator_confirmed=True)
    success_verify = success_operator.verify()

    protected_after = {
        "database": sha256_file(formal_db),
        "snapshot": sha256_file(formal_snapshot),
        "d02_release": sha256_file(formal_d02),
        "runtime_receipt_exists": (ROOT / "data/exchange/receipts/latest.json").exists(),
    }
    evidence = {
        "task_id": "CDH-D03-LOCAL-OPERATOR-001",
        "scope": "ISOLATED_SYNTHETIC_USER_INPUT_SIMULATION_ONLY",
        "failure_result": failure_execute["result"],
        "failure_live_observations_after_commit": scalar(failure_paths.database, "SELECT COUNT(*) FROM observations"),
        "backup": {
            "path": backup_database.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(backup_database),
            "integrity_check": inspect_database(backup_database)["integrity_check"],
            "observations": scalar(backup_database, "SELECT COUNT(*) FROM observations"),
        },
        "restore": {
            **restore,
            "path": restore_target.relative_to(ROOT).as_posix(),
            "observations": scalar(restore_target, "SELECT COUNT(*) FROM observations"),
        },
        "formal_before": protected_before,
        "formal_after": protected_after,
        "formal_preservation_gate": "PASS" if protected_before == protected_after else "FAIL",
    }
    operations = {
        "task_id": "CDH-D03-LOCAL-OPERATOR-001",
        "scope": "ISOLATED_SYNTHETIC_USER_INPUT_SIMULATION_ONLY",
        "commands": [
            slim(success_status),
            slim(success_preflight),
            slim(success_dry),
            slim(success_execute),
            slim(success_verify),
        ],
        "database": {
            "sha256": sha256_file(success_paths.database),
            "integrity_check": inspect_database(success_paths.database)["integrity_check"],
            "observations": scalar(success_paths.database, "SELECT COUNT(*) FROM observations"),
            "zero_price_unverified_count": scalar(
                success_paths.database,
                "SELECT COUNT(*) FROM observations WHERE displayed_price_twd=0 AND qualification_state='UNVERIFIED' AND shipping_status='UNKNOWN' AND shipping_fee_twd IS NULL",
            ),
        },
        "receipt_sha256": hash_optional(success_paths.receipts / "latest.json"),
        "snapshot_sha256": hash_optional(success_paths.snapshots / "latest.json"),
        "source_status": "SOURCE_BLOCKED",
    }
    (base / "BACKUP_RESTORE_EVIDENCE.json").write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (base / "OPERATOR_MILESTONE_EVIDENCE.json").write_text(
        json.dumps(operations, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({"backup_restore": evidence, "operations": operations}, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["formal_preservation_gate"] == "PASS" and success_verify["result"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
