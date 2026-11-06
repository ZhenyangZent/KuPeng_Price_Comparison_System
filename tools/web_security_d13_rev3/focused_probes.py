from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from targeted_suite import NOW, BatchImportApp, BatchObservationStore, confirm, file_body, observation, request  # noqa: E402


def preview(app, rows):
    return request(app, "/api/private-observations/v1/batch-preview", method="POST", body=file_body(rows), csrf=True)


def save(app, value):
    return request(app, "/api/private-observations/v1/batch-confirm", method="POST", body=confirm(value), csrf=True)


def main() -> int:
    work = ROOT / "review/D13/003/focused_probes"
    if work.exists():
        if not work.resolve().is_relative_to((ROOT / "review/D13/003").resolve()):
            raise RuntimeError("unsafe cleanup")
        shutil.rmtree(work)
    work.mkdir(parents=True)
    rows = [observation(), observation("SUB-D13-R3-2", "2026-11-04T12:00:00+08:00", 950, None)]

    class FailSecond(BatchObservationStore):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs); self.calls = 0; self.failed = False

        def _insert_record(self, connection, normalized, *, batch_id, created):
            self.calls += 1
            if not self.failed and self.calls == 2:
                self.failed = True
                raise sqlite3.OperationalError("D13 REV3 focused failure")
            return super()._insert_record(connection, normalized, batch_id=batch_id, created=created)

    recovery_store = FailSecond(work / "recovery", allowed_project_root=work, clock=lambda: NOW)
    recovery_app = BatchImportApp(recovery_store, baselines={}, clock=lambda: NOW, csrf_token="csrf-recovery")
    first_preview_status, first_preview, _ = preview(recovery_app, rows)
    failure_status, failure, _ = save(recovery_app, first_preview)
    retry_status, retry, _ = save(recovery_app, first_preview)
    connection = sqlite3.connect(recovery_store.database)
    try:
        tables = sorted(row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        observation_count_after_failure = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        audit_count_after_failure = connection.execute("SELECT COUNT(*) FROM commit_audit").fetchone()[0]
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        connection.close()
    fresh_preview_status, fresh_preview, _ = preview(recovery_app, rows)
    fresh_confirm_status, fresh_confirm, _ = save(recovery_app, fresh_preview)

    class ToggleFail(BatchObservationStore):
        fail = False

        def _insert_record(self, connection, normalized, *, batch_id, created):
            if self.fail:
                raise sqlite3.OperationalError("D13 REV3 existing failure")
            return super()._insert_record(connection, normalized, batch_id=batch_id, created=created)

    existing_store = ToggleFail(work / "existing", allowed_project_root=work, clock=lambda: NOW)
    existing_app = BatchImportApp(existing_store, baselines={}, clock=lambda: NOW, csrf_token="csrf-existing")
    first = preview(existing_app, [rows[0]])[1]
    save(existing_app, first)
    existing_store.fail = True
    second = preview(existing_app, [rows[1]])[1]
    existing_failure_status = save(existing_app, second)[0]
    connection = sqlite3.connect(existing_store.database)
    existing_rows = connection.execute("SELECT submission_id FROM observations").fetchall()
    existing_quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    connection.close()
    backup_files = list(existing_store.backup_root.glob("*.sqlite3"))
    backup_integrity = []
    for backup in backup_files:
        connection = sqlite3.connect(backup)
        backup_integrity.append(connection.execute("PRAGMA integrity_check").fetchone()[0])
        connection.close()

    entered = threading.Event(); release = threading.Event()

    class BlockingStore(BatchObservationStore):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs); self.entries = 0; self.guard = threading.Lock()

        def commit_batch(self, records, *, file_sha256, duplicate_input_count):
            with self.guard:
                self.entries += 1; number = self.entries
            if number == 1:
                entered.set(); release.wait(timeout=5)
            return super().commit_batch(records, file_sha256=file_sha256, duplicate_input_count=duplicate_input_count)

    race_store = BlockingStore(work / "race", allowed_project_root=work, clock=lambda: NOW)
    race_app = BatchImportApp(race_store, baselines={}, clock=lambda: NOW, csrf_token="csrf-race")
    race_preview = preview(race_app, [rows[0]])[1]
    race_results = []
    worker = lambda: race_results.append(save(race_app, race_preview))
    one = threading.Thread(target=worker); two = threading.Thread(target=worker)
    one.start(); entered.wait(timeout=5); two.start(); two.join(timeout=3)
    second_rejected_before_release = not two.is_alive()
    release.set(); one.join(timeout=5); two.join(timeout=5)

    result = {
        "schema_version": "CDH-D13-B16-REV3-FOCUSED-PROBES-1",
        "b16_rev3_sha256": "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7",
        "first_write_failure": {"preview_status": first_preview_status, "confirm_status": failure_status, "confirm_code": failure["error"]["code"], "same_token_retry_status": retry_status, "same_token_retry_code": retry["error"]["code"], "tables_after_failure": tables, "observation_count_after_failure": observation_count_after_failure, "audit_count_after_failure": audit_count_after_failure, "quick_check": quick_check, "fresh_preview_status": fresh_preview_status, "fresh_confirm_status": fresh_confirm_status, "fresh_inserted_count": fresh_confirm["inserted_count"], "final_observation_count": recovery_store.observation_count()},
        "existing_database": {"failure_status": existing_failure_status, "preserved_submission_ids": [row[0] for row in existing_rows], "quick_check": existing_quick_check, "backup_count": len(backup_files), "backup_integrity": backup_integrity},
        "concurrency": {"statuses": sorted(item[0] for item in race_results), "error_codes": sorted(item[1].get("error", {}).get("code") for item in race_results if item[0] >= 400), "second_rejected_before_release": second_rejected_before_release, "store_entry_count": race_store.entries, "observation_count": race_store.observation_count()},
    }
    recovery_gate = result["first_write_failure"] == {"preview_status": 200, "confirm_status": 500, "confirm_code": "PRIVATE_STORE_TRANSACTION_FAILED", "same_token_retry_status": 409, "same_token_retry_code": "CONFIRMATION_FAILED_NEW_PREVIEW_REQUIRED", "tables_after_failure": ["b15_schema", "commit_audit", "observations"], "observation_count_after_failure": 0, "audit_count_after_failure": 0, "quick_check": "ok", "fresh_preview_status": 200, "fresh_confirm_status": 201, "fresh_inserted_count": 2, "final_observation_count": 2}
    existing_gate = existing_failure_status == 500 and result["existing_database"]["preserved_submission_ids"] == ["SUB-D13-R3-1"] and existing_quick_check == "ok" and len(backup_files) >= 1 and all(item == "ok" for item in backup_integrity)
    race_gate = result["concurrency"] == {"statuses": [201, 409], "error_codes": ["CONFIRMATION_ALREADY_IN_PROGRESS"], "second_rejected_before_release": True, "store_entry_count": 1, "observation_count": 1}
    result["first_write_recovery_gate"] = "PASS" if recovery_gate else "FAIL"
    result["existing_database_preservation_gate"] = "PASS" if existing_gate else "FAIL"
    result["concurrent_token_gate"] = "PASS" if race_gate else "FAIL"
    result["gate"] = "PASS" if recovery_gate and existing_gate and race_gate else "FAIL"
    evidence = ROOT / "review/D13/003/evidence/FOCUSED_PROBES.json"
    evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
