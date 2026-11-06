from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def observation(*, submission_id: str, source_kind: str = "USER_ENTERED") -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "schema_version": "CDH-EXCHANGE-1", "submission_id": submission_id,
        "record_type": "USER_PRICE_OBSERVATION", "created_at_utc": now, "observed_at_utc": now,
        "source": {"source_kind": source_kind, "permission_scope": "USER_PROVIDED_ONLY", "url": None, "note": "A04 synthetic E2E only"},
        "offer": {"platform": "TW_COUPANG", "product_title": "A04 合成日用品", "product_id": "A04-SYNTHETIC", "variant_id": "SKU-1", "seller_id": "SELLER-1", "displayed_price_twd": 199, "price_basis": "DISPLAYED_UNKNOWN", "minimum_purchase_quantity": 1, "shipping_status": "UNKNOWN", "shipping_fee_twd": None, "stock_status": "UNKNOWN", "coupon_status": "UNKNOWN", "account_eligibility_status": "UNKNOWN", "mandatory_fee_status": "UNKNOWN", "notes": "synthetic; no purchase"},
        "is_synthetic": False,
    }


def prepare_code_root(target: Path) -> None:
    for relative in ("apps/d01", "apps/d03", "scripts/d03"):
        source = ROOT / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    release = target / "review/releases/CDH_D02_001_REVIEW.zip"
    release.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "review/releases/CDH_D02_001_REVIEW.zip", release)


def initialize_database(code_root: Path) -> None:
    sys.path.insert(0, str(code_root / "apps/d01"))
    from cdh_d01.database import connect, migrate
    database = code_root / "data/d01/observations.sqlite3"
    connection = connect(database)
    try:
        migrate(connection)
    finally:
        connection.close()


def run_cli(code_root: Path, command: str, *extra: str) -> dict[str, object]:
    arguments = [str(Path(sys.executable).resolve()), str(code_root / "scripts/d03/local_operator.py"), command, "--project-root", str(code_root), "--json", *extra]
    completed = subprocess.run(arguments, cwd=code_root, shell=False, capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=120)
    value = json.loads(completed.stdout)
    return {"command": command, "arguments": arguments[2:], "returncode": completed.returncode, "stdout": value, "stderr": completed.stderr}


def execute(output_root: Path) -> dict[str, object]:
    output_root = output_root.resolve()
    code_root = output_root / "code_root"
    output_root.mkdir(parents=True, exist_ok=False)
    prepare_code_root(code_root)
    initialize_database(code_root)
    inbox = code_root / "data/exchange/inbox"; inbox.mkdir(parents=True, exist_ok=True)
    submission_id = str(uuid.uuid4())
    (inbox / f"submission_{submission_id}.json").write_bytes(canonical(observation(submission_id=submission_id)) + b"\n")

    steps: dict[str, dict[str, object]] = {}
    steps["status"] = run_cli(code_root, "status")
    steps["preflight"] = run_cli(code_root, "preflight")

    lock = code_root / "data/exchange/.d02_sync.lock"; lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0: handle.write(b"\0"); handle.flush()
        handle.seek(0)
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        try: steps["locked_preflight"] = run_cli(code_root, "preflight")
        finally:
            handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    steps["dry_run"] = run_cli(code_root, "dry-run")
    plan_id = str(steps["dry_run"]["stdout"]["plan_id"])
    plan_file = code_root / f"reports/D03/001/plans/{plan_id}.json"
    expired = json.loads(plan_file.read_text(encoding="utf-8")); expired.pop("plan_id"); expired["expires_at"] = "2000-01-01T00:00:00Z"
    expired_id = hashlib.sha256(canonical(expired)).hexdigest(); expired["plan_id"] = expired_id
    (plan_file.parent / f"{expired_id}.json").write_bytes(json.dumps(expired, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
    steps["expired_execute"] = run_cli(code_root, "execute", "--plan-id", expired_id, "--operator-confirmed")
    steps["execute"] = run_cli(code_root, "execute", "--plan-id", plan_id, "--operator-confirmed")
    steps["duplicate_execute"] = run_cli(code_root, "execute", "--plan-id", plan_id, "--operator-confirmed")
    steps["verify"] = run_cli(code_root, "verify")

    bad_id = str(uuid.uuid4())
    (inbox / f"submission_{bad_id}.json").write_bytes(canonical(observation(submission_id=bad_id, source_kind="PUBLIC_NOTICE_MANUAL")) + b"\n")
    steps["unknown_source_preflight"] = run_cli(code_root, "preflight")

    expected = {
        "status": (0, "READY"), "preflight": (0, "READY"), "locked_preflight": (2, "BLOCKED"),
        "dry_run": (0, "NEEDS_OPERATOR_CONFIRMATION"), "expired_execute": (2, "BLOCKED"),
        "execute": (0, "EXECUTED"), "duplicate_execute": (2, "BLOCKED"), "verify": (0, "READY"),
        "unknown_source_preflight": (2, "BLOCKED"),
    }
    gates = {name: step["returncode"] == code and step["stdout"]["result"] == result for name, step in steps.items() for code, result in [expected[name]]}
    error_codes = {name: [item["code"] for item in step["stdout"].get("errors", [])] for name, step in steps.items()}
    gates.update({
        "lock_error": "SINGLE_WRITER_BUSY" in error_codes["locked_preflight"],
        "expiry_error": "PLAN_EXPIRED" in error_codes["expired_execute"],
        "duplicate_error": "PLAN_ALREADY_CONSUMED" in error_codes["duplicate_execute"],
        "source_error": "SOURCE_KIND_NOT_USER_PROVIDED" in error_codes["unknown_source_preflight"],
        "backup_verified": steps["execute"]["stdout"]["backup"]["state"] == "VERIFIED",
        "receipt_ready": steps["verify"]["stdout"]["receipt"]["state"] == "READY",
        "snapshot_ready": steps["verify"]["stdout"]["snapshot"]["state"] == "READY",
    })
    result = {"task_id": "CDH-A04-WINDOWS-DAILY-APP-001", "source_status": "SOURCE_BLOCKED", "workspace": str(code_root), "steps": steps, "gates": gates, "pass": all(gates.values())}
    (output_root / "E2E_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = execute(args.output)
    print(json.dumps({"pass": result["pass"], "workspace": result["workspace"], "gates": result["gates"]}, ensure_ascii=False, sort_keys=True))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
