from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import cdh_d01.sync as d02_sync
from cdh_d01.model import ValidationError
from cdh_d01.validation import decode_json_bytes, validate_record

from .backup import BackupError, create_verified_backup, restore_backup_to
from .identity import IdentityError, assert_beneath, hash_optional, inspect_database, sha256_file, verify_d02_identity


CONTRACT = "CDH-LOCAL-MANUAL-SYNC-1"
SOURCE_STATUS = "SOURCE_BLOCKED"
DATA_SCOPE = "USER_PROVIDED_LOCAL_ONLY"
DATABASE_KIND = "USER_LOCAL"
TASK_ID = "CDH-D03-LOCAL-OPERATOR-001"
ALLOWED_USER_SOURCES = {"USER_ENTERED", "USER_FILE"}
PLAN_TTL = timedelta(minutes=10)
MAX_STATE_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_AGE = timedelta(hours=24)
PLAN_ID = re.compile(r"^[0-9a-f]{64}$")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _error(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _empty_counts() -> dict[str, int]:
    return {"scanned": 0, "imported": 0, "duplicate": 0, "quarantined": 0, "pending": 0}


class LocalOperator:
    def __init__(
        self,
        *,
        code_root: Path,
        project_root: Path,
        isolated_test: bool = False,
        now_fn: Callable[[], datetime] | None = None,
        disk_free_override: int | None = None,
    ) -> None:
        self.code_root = code_root.resolve()
        self.project_root = project_root.resolve()
        self.isolated_test = isolated_test
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.disk_free_override = disk_free_override
        if isolated_test:
            allowed = (self.code_root / "experiments/D03").resolve()
            if not self.project_root.is_relative_to(allowed):
                raise IdentityError("isolated test workspace must be below experiments/D03")
        elif self.project_root != self.code_root:
            raise IdentityError("production project root must equal the unique installed project root")
        if not self.project_root.is_dir():
            raise IdentityError("project root does not exist")
        self.paths = d02_sync.SyncPaths.for_root(self.project_root)
        self.state_root = self.project_root / "reports/D03/001"
        self.plan_root = self.state_root / "plans"
        self.consumed_root = self.state_root / "consumed_plans"
        self.last_execution = self.state_root / "last_execution.json"
        self.last_attempt = self.state_root / "last_attempt.json"
        self.operator_log = self.state_root / "OPERATOR_WORKLOG.ndjson"
        for path in (
            self.paths.database,
            self.paths.inbox,
            self.paths.snapshots,
            self.paths.receipts,
            self.paths.lock,
            self.state_root,
        ):
            assert_beneath(self.project_root, path)

    def _now(self) -> datetime:
        value = self.now_fn().astimezone(timezone.utc)
        if value.tzinfo is None:
            raise ValueError("now_fn must return timezone-aware datetime")
        return value

    def _now_text(self) -> str:
        return self._now().isoformat(timespec="seconds").replace("+00:00", "Z")

    def _base(self, command: str, *, dry_run: bool) -> dict[str, object]:
        return {
            "contract": CONTRACT,
            "command": command,
            "result": "FAILED",
            "source_status": SOURCE_STATUS,
            "data_scope": DATA_SCOPE,
            "plan_id": None,
            "database_kind": DATABASE_KIND,
            "dry_run": dry_run,
            "counts": _empty_counts(),
            "receipt": {"state": "UNKNOWN", "sha256": None},
            "snapshot": {"state": "UNKNOWN", "sha256": None},
            "backup": {"state": "NOT_REQUIRED", "path": None, "sha256": None},
            "errors": [],
            "generated_at": self._now_text(),
        }

    def _safe_json(self, path: Path) -> tuple[dict[str, object], bytes] | None:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_STATE_BYTES:
            return None
        try:
            data = path.read_bytes()
            value = json.loads(data.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return (value, data) if isinstance(value, dict) else None

    def _freshness_state(self, value: object, ready_state: str = "READY") -> str:
        if not isinstance(value, str):
            return "INVALID"
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                return "INVALID"
            age = self._now() - stamp.astimezone(timezone.utc)
        except ValueError:
            return "INVALID"
        if age < timedelta(minutes=-5):
            return "INVALID"
        return "STALE" if age > MAX_RECEIPT_AGE else ready_state

    def _inspect_inbox(self) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
        entries: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []
        try:
            cutoff = d02_sync._capture_cutoff(self.paths.inbox)
        except Exception as exc:
            return [], [_error("INBOX_SCAN_FAILED", str(exc))]
        for filename in cutoff:
            path = self.paths.inbox / filename
            try:
                data, stable = d02_sync._stable_read(path)
            except Exception as exc:
                errors.append(_error("INBOX_FILE_READ_FAILED", f"{filename}: {exc}"))
                continue
            digest = hashlib.sha256(data).hexdigest()
            entry: dict[str, object] = {
                "filename": filename,
                "file_sha256": digest,
                "bytes": len(data),
                "source_kind": "UNKNOWN",
                "submission_id": None,
            }
            entries.append(entry)
            if not stable:
                errors.append(_error("INBOX_FILE_CHANGED", f"{filename} changed during inspection"))
                continue
            match = d02_sync.CANONICAL_FILENAME.fullmatch(filename)
            if match is None:
                errors.append(_error("INVALID_SUBMISSION_FILENAME", filename))
                continue
            try:
                record = validate_record(decode_json_bytes(data))
            except ValidationError as exc:
                errors.append(_error(exc.code, f"{filename}: {exc.detail}"))
                continue
            entry["source_kind"] = record.source_kind
            entry["submission_id"] = record.submission_id
            if record.submission_id != match.group(1):
                errors.append(_error("FILENAME_SUBMISSION_ID_MISMATCH", filename))
            if record.source_kind not in ALLOWED_USER_SOURCES:
                errors.append(_error("SOURCE_KIND_NOT_USER_PROVIDED", f"{filename}: {record.source_kind}"))
            if record.is_synthetic:
                errors.append(_error("SYNTHETIC_INPUT_FORBIDDEN", filename))
            if record.record_type != "USER_PRICE_OBSERVATION":
                errors.append(_error("NON_OBSERVATION_INPUT_FORBIDDEN", f"{filename}: {record.record_type}"))
        return entries, errors

    def _d02_identity(self) -> dict[str, object]:
        return verify_d02_identity(self.code_root, Path(d02_sync.__file__))

    def _receipt_snapshot(self, inbox_entries: list[dict[str, object]]) -> dict[str, object]:
        snapshot_path = self.paths.snapshots / "latest.json"
        receipt_path = self.paths.receipts / "latest.json"
        snapshot_loaded = self._safe_json(snapshot_path)
        receipt_loaded = self._safe_json(receipt_path)
        errors: list[dict[str, str]] = []
        snapshot = {"state": "MISSING", "sha256": None}
        receipt = {"state": "MISSING", "sha256": None}
        snapshot_hash = hash_optional(snapshot_path)
        receipt_hash = hash_optional(receipt_path)
        if snapshot_loaded is not None:
            snapshot_doc, _ = snapshot_loaded
            snapshot = {
                "state": self._freshness_state(snapshot_doc.get("snapshot_generated_at_utc")),
                "sha256": snapshot_hash,
                "generated_at": snapshot_doc.get("snapshot_generated_at_utc"),
            }
            source = snapshot_doc.get("source_status")
            if not isinstance(source, dict) or source.get("live_coupang_discovery") != SOURCE_STATUS:
                snapshot["state"] = "INVALID"
                errors.append(_error("SNAPSHOT_SOURCE_STATUS_INVALID", "snapshot must preserve SOURCE_BLOCKED"))
        elif snapshot_path.exists():
            snapshot = {"state": "INVALID", "sha256": snapshot_hash}
            errors.append(_error("SNAPSHOT_INVALID", "snapshot is malformed, unsafe, or too large"))

        receipt_entries: list[dict[str, object]] = []
        if receipt_loaded is not None:
            receipt_doc, _ = receipt_loaded
            state = self._freshness_state(receipt_doc.get("generated_at_utc"))
            if (
                receipt_doc.get("receipt_version") != "CDH-D01-RECEIPT-1"
                or receipt_doc.get("exchange_version") != "CDH-EXCHANGE-1"
                or receipt_doc.get("source_status") != SOURCE_STATUS
                or not isinstance(receipt_doc.get("entries"), list)
            ):
                state = "INVALID"
                errors.append(_error("RECEIPT_INVALID", "receipt contract or source status mismatch"))
            else:
                receipt_entries = receipt_doc["entries"]
                expected_snapshot = receipt_doc.get("snapshot_sha256")
                if not isinstance(expected_snapshot, str) or expected_snapshot != snapshot_hash:
                    state = "SYNCING"
                    errors.append(_error("RECEIPT_SNAPSHOT_MISMATCH", "receipt does not bind the actual snapshot bytes"))
            receipt = {
                "state": state,
                "sha256": receipt_hash,
                "generated_at": receipt_doc.get("generated_at_utc"),
                "snapshot_sha256": receipt_doc.get("snapshot_sha256"),
            }
        elif receipt_path.exists():
            receipt = {"state": "INVALID", "sha256": receipt_hash}
            errors.append(_error("RECEIPT_INVALID", "receipt is malformed, unsafe, or too large"))

        current = {str(item["filename"]): str(item["file_sha256"]) for item in inbox_entries}
        processed: set[str] = set()
        counts = _empty_counts()
        counts["scanned"] = len(inbox_entries)
        for item in receipt_entries:
            if not isinstance(item, dict):
                errors.append(_error("RECEIPT_ENTRY_INVALID", "receipt entry must be an object"))
                continue
            filename = item.get("filename")
            digest = item.get("file_sha256")
            status = item.get("status")
            if not isinstance(filename, str) or not isinstance(digest, str) or current.get(filename) != digest:
                continue
            if status == "IMPORTED":
                counts["imported"] += 1
                processed.add(filename)
            elif status == "DUPLICATE_NOOP":
                counts["duplicate"] += 1
                processed.add(filename)
            elif status == "QUARANTINED":
                counts["quarantined"] += 1
            elif status != "RETRY_NEEDED":
                errors.append(_error("RECEIPT_STATUS_INVALID", f"unsupported status for {filename}"))
        counts["pending"] = len(current) - len(processed)
        chain_valid = (
            receipt["state"] in {"READY", "STALE"}
            and snapshot["state"] in {"READY", "STALE"}
            and receipt.get("snapshot_sha256") == snapshot_hash
        )
        return {"receipt": receipt, "snapshot": snapshot, "counts": counts, "errors": errors, "chain_valid": chain_valid}

    def _lock_probe(self) -> tuple[str, list[dict[str, str]]]:
        path = self.paths.lock
        if not path.exists():
            return "AVAILABLE", []
        if not path.is_file() or path.is_symlink():
            return "INVALID", [_error("LOCK_PATH_INVALID", "D02 lock path is not a normal file")]
        handle = None
        try:
            handle = path.open("r+b")
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return "AVAILABLE", []
        except OSError:
            return "BUSY", [_error("SINGLE_WRITER_BUSY", "another local sync holds the D02 lock")]
        finally:
            if handle is not None:
                handle.close()

    def _disk_space(self, database_bytes: int) -> dict[str, object]:
        required = max(32 * 1024 * 1024, database_bytes * 3)
        free = self.disk_free_override
        if free is None:
            free = shutil.disk_usage(self.paths.database.parent).free
        return {"required_bytes": required, "free_bytes": free, "state": "READY" if free >= required else "INSUFFICIENT"}

    def _state_identity(self, database: dict[str, object], inbox: list[dict[str, object]], d02: dict[str, object]) -> dict[str, object]:
        return {
            "database_file_sha256": database["file_sha256"],
            "database_logical_sha256": database["logical_sha256"],
            "inbox": [
                {
                    "filename": item["filename"],
                    "file_sha256": item["file_sha256"],
                    "source_kind": item["source_kind"],
                }
                for item in inbox
            ],
            "snapshot_sha256": hash_optional(self.paths.snapshots / "latest.json"),
            "receipt_sha256": hash_optional(self.paths.receipts / "latest.json"),
            "d02_release_sha256": d02["release_sha256"],
            "d02_source_hashes": d02["source_hashes"],
        }

    def _collect(self) -> dict[str, object]:
        errors: list[dict[str, str]] = []
        try:
            d02 = self._d02_identity()
            errors.extend(d02["errors"])
        except Exception as exc:
            d02 = {"state": "INVALID", "release_sha256": None, "source_hashes": {}, "errors": []}
            errors.append(_error("D02_IDENTITY_CHECK_FAILED", str(exc)))
        try:
            database = inspect_database(self.paths.database)
            if database["integrity_check"] != ["ok"]:
                errors.append(_error("DATABASE_INTEGRITY_FAILED", "PRAGMA integrity_check did not return ok"))
            if database["foreign_key_violation_count"]:
                errors.append(_error("DATABASE_FOREIGN_KEY_FAILED", "foreign key violations detected"))
            if not database["required_tables_present"]:
                errors.append(_error("DATABASE_SCHEMA_MISSING", "required D01 tables are missing"))
            if database["approved_permission_count"]:
                errors.append(_error("AUTOMATIC_SOURCE_APPROVAL_PRESENT", "D03 requires zero approved automatic sources"))
        except Exception as exc:
            database = {
                "file_sha256": None,
                "logical_sha256": None,
                "bytes": 0,
                "integrity_check": [],
                "foreign_key_violation_count": -1,
                "required_tables_present": False,
                "approved_permission_count": -1,
                "schema_migrations": [],
            }
            errors.append(_error("DATABASE_CHECK_FAILED", str(exc)))
        inbox, inbox_errors = self._inspect_inbox()
        errors.extend(inbox_errors)
        exchange = self._receipt_snapshot(inbox)
        errors.extend(exchange["errors"])
        lock_state, lock_errors = self._lock_probe()
        errors.extend(lock_errors)
        disk = self._disk_space(int(database.get("bytes", 0)))
        if disk["state"] != "READY":
            errors.append(_error("BACKUP_SPACE_INSUFFICIENT", "not enough free space for verified SQLite backup"))
        identity = self._state_identity(database, inbox, d02)
        return {
            "d02": d02,
            "database": database,
            "inbox": inbox,
            "exchange": exchange,
            "lock_state": lock_state,
            "disk": disk,
            "identity": identity,
            "errors": errors,
        }

    def status(self) -> dict[str, object]:
        response = self._base("status", dry_run=False)
        collected = self._collect()
        response.update(
            {
                "result": "READY" if not collected["errors"] else "BLOCKED",
                "counts": collected["exchange"]["counts"],
                "receipt": collected["exchange"]["receipt"],
                "snapshot": collected["exchange"]["snapshot"],
                "errors": collected["errors"],
                "d02": collected["d02"],
                "database": collected["database"],
            }
        )
        return response

    def preflight(self) -> dict[str, object]:
        response = self._base("preflight", dry_run=False)
        collected = self._collect()
        response.update(
            {
                "result": "READY" if not collected["errors"] else "BLOCKED",
                "counts": collected["exchange"]["counts"],
                "receipt": collected["exchange"]["receipt"],
                "snapshot": collected["exchange"]["snapshot"],
                "errors": collected["errors"],
                "preflight": {
                    "d02_state": collected["d02"]["state"],
                    "database_integrity": collected["database"]["integrity_check"],
                    "schema_migrations": collected["database"].get("schema_migrations", []),
                    "source_kinds": sorted({str(item["source_kind"]) for item in collected["inbox"]}),
                    "writer_lock": collected["lock_state"],
                    "backup_space": collected["disk"],
                    "requires_operator_confirmation": bool(collected["inbox"]),
                },
            }
        )
        return response

    def _preview(self) -> tuple[d02_sync.SyncResult | None, list[dict[str, str]]]:
        try:
            return d02_sync.run_sync(self.paths, dry_run=True), []
        except Exception as exc:
            return None, [_error("D02_DRY_RUN_FAILED", str(exc))]

    @staticmethod
    def _counts_from_entries(entries: object) -> dict[str, int]:
        values = list(entries)
        counts = _empty_counts()
        counts["scanned"] = len(values)
        for entry in values:
            if entry.status == "IMPORTED":
                counts["imported"] += 1
            elif entry.status == "DUPLICATE_NOOP":
                counts["duplicate"] += 1
            elif entry.status == "QUARANTINED":
                counts["quarantined"] += 1
        counts["pending"] = sum(1 for entry in values if entry.status in {"QUARANTINED", "RETRY_NEEDED"})
        return counts

    @staticmethod
    def _preview_rows(result: d02_sync.SyncResult) -> list[dict[str, object]]:
        return [
            {
                "filename": entry.filename,
                "file_sha256": entry.file_sha256,
                "status": entry.status,
                "reason_code": entry.reason_code,
            }
            for entry in result.entries
        ]

    def _atomic_state(self, path: Path, value: object) -> None:
        assert_beneath(self.project_root, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def _append_log(self, *, event: str, result: str, plan_id: str | None, detail: dict[str, object]) -> None:
        self.operator_log.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "utc_time": self._now_text(),
            "task_id": TASK_ID,
            "event": event,
            "scope": "LOCAL_USER_PROVIDED_ONLY",
            "result": result,
            "plan_id": plan_id,
            **detail,
        }
        with self.operator_log.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _plan_body(
        self,
        *,
        collected: dict[str, object],
        preview: d02_sync.SyncResult,
        generated_at: str,
    ) -> dict[str, object]:
        generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        return {
            "contract": CONTRACT,
            "task_id": TASK_ID,
            "generated_at": generated_at,
            "expires_at": (generated + PLAN_TTL).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "state_identity": collected["identity"],
            "preview": self._preview_rows(preview),
            "counts": self._counts_from_entries(preview.entries),
        }

    def _save_plan(self, body: dict[str, object]) -> str:
        plan_id = hashlib.sha256(_canonical_bytes(body)).hexdigest()
        document = {**body, "plan_id": plan_id}
        self._atomic_state(self.plan_root / f"{plan_id}.json", document)
        return plan_id

    def dry_run(self) -> dict[str, object]:
        response = self._base("dry-run", dry_run=True)
        collected_before = self._collect()
        preview, preview_errors = self._preview()
        collected_after = self._collect()
        errors = list(collected_before["errors"]) + preview_errors
        if preview is not None and any(entry.status in {"QUARANTINED", "RETRY_NEEDED"} for entry in preview.entries):
            errors.append(_error("DRY_RUN_UNRESOLVED_ENTRIES", "quarantined or retry-needed inputs must be corrected before execute"))
        if collected_before["identity"] != collected_after["identity"]:
            errors.append(_error("STATE_CHANGED_DURING_DRY_RUN", "database or inbox changed during preview"))
        counts = self._counts_from_entries(preview.entries) if preview is not None else collected_before["exchange"]["counts"]
        plan_id = None
        result = "BLOCKED" if errors else "NO_CHANGES" if counts["scanned"] == 0 else "NEEDS_OPERATOR_CONFIRMATION"
        if result == "NEEDS_OPERATOR_CONFIRMATION" and preview is not None:
            body = self._plan_body(collected=collected_before, preview=preview, generated_at=response["generated_at"])
            plan_id = self._save_plan(body)
            self._append_log(
                event="DRY_RUN_PLAN_CREATED",
                result=result,
                plan_id=plan_id,
                detail={"counts": counts, "state_identity_sha256": hashlib.sha256(_canonical_bytes(collected_before["identity"])).hexdigest()},
            )
        response.update(
            {
                "result": result,
                "plan_id": plan_id,
                "counts": counts,
                "receipt": collected_before["exchange"]["receipt"],
                "snapshot": collected_before["exchange"]["snapshot"],
                "errors": errors,
                "preview": self._preview_rows(preview) if preview is not None else [],
            }
        )
        return response

    def _load_plan(self, plan_id: str) -> tuple[dict[str, object] | None, list[dict[str, str]]]:
        if not PLAN_ID.fullmatch(plan_id):
            return None, [_error("PLAN_ID_INVALID", "plan_id must be 64 lowercase hex characters")]
        path = self.plan_root / f"{plan_id}.json"
        loaded = self._safe_json(path)
        if loaded is None:
            return None, [_error("PLAN_NOT_FOUND", "dry-run plan does not exist or is invalid")]
        document, _ = loaded
        stored_id = document.pop("plan_id", None)
        actual = hashlib.sha256(_canonical_bytes(document)).hexdigest()
        document["plan_id"] = stored_id
        if stored_id != plan_id or actual != plan_id:
            return None, [_error("PLAN_INTEGRITY_FAILED", "plan content does not match plan_id")]
        try:
            expires = datetime.fromisoformat(str(document["expires_at"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        except (KeyError, ValueError):
            return None, [_error("PLAN_EXPIRY_INVALID", "plan expiry is missing or malformed")]
        if self._now() > expires:
            return None, [_error("PLAN_EXPIRED", "run dry-run again before executing")]
        if (self.consumed_root / f"{plan_id}.json").exists():
            return None, [_error("PLAN_ALREADY_CONSUMED", "plan may be executed only once")]
        return document, []

    def _record_attempt(self, value: dict[str, object]) -> None:
        self._atomic_state(self.last_attempt, value)
        self._append_log(
            event="EXECUTE_ATTEMPT",
            result=str(value["result"]),
            plan_id=value.get("plan_id") if isinstance(value.get("plan_id"), str) else None,
            detail={"counts": value.get("counts", _empty_counts()), "error_codes": [item.get("code") for item in value.get("errors", [])]},
        )

    def execute(
        self,
        *,
        plan_id: str | None,
        operator_confirmed: bool,
        _sync_fault: str | None = None,
        _backup_fault: str | None = None,
    ) -> dict[str, object]:
        response = self._base("execute", dry_run=False)
        response["plan_id"] = plan_id
        if not operator_confirmed:
            response.update({"result": "BLOCKED", "errors": [_error("OPERATOR_CONFIRMATION_REQUIRED", "GUI operator confirmation is required")]})
            return response
        if plan_id is None:
            response.update({"result": "BLOCKED", "errors": [_error("PLAN_ID_REQUIRED", "execute requires a dry-run plan_id")]})
            return response
        plan, plan_errors = self._load_plan(plan_id)
        if plan is None:
            response.update({"result": "BLOCKED", "errors": plan_errors})
            return response
        collected = self._collect()
        errors = list(collected["errors"])
        preview, preview_errors = self._preview()
        errors.extend(preview_errors)
        if collected["identity"] != plan.get("state_identity"):
            errors.append(_error("PLAN_STATE_CHANGED", "database, inbox, snapshot, receipt, or D02 identity changed after dry-run"))
        if preview is not None and self._preview_rows(preview) != plan.get("preview"):
            errors.append(_error("PLAN_PREVIEW_CHANGED", "effective dry-run result no longer matches the plan"))
        if errors:
            response.update(
                {
                    "result": "BLOCKED",
                    "counts": self._counts_from_entries(preview.entries) if preview is not None else collected["exchange"]["counts"],
                    "receipt": collected["exchange"]["receipt"],
                    "snapshot": collected["exchange"]["snapshot"],
                    "errors": errors,
                }
            )
            self._record_attempt(response)
            return response
        try:
            backup = create_verified_backup(
                project_root=self.project_root,
                database=self.paths.database,
                snapshot=self.paths.snapshots / "latest.json",
                receipt=self.paths.receipts / "latest.json",
                plan_id=plan_id,
                generated_at=response["generated_at"],
                fault=_backup_fault,
            )
        except Exception as exc:
            response.update(
                {
                    "result": "BLOCKED",
                    "counts": self._counts_from_entries(preview.entries),
                    "receipt": collected["exchange"]["receipt"],
                    "snapshot": collected["exchange"]["snapshot"],
                    "backup": {"state": "FAILED", "path": None, "sha256": None},
                    "errors": [_error("BACKUP_FAILED", str(exc))],
                }
            )
            self._record_attempt(response)
            return response
        response["backup"] = {key: backup[key] for key in ("state", "path", "sha256", "manifest_sha256")}
        after_backup = self._collect()
        if after_backup["identity"] != plan.get("state_identity"):
            response.update(
                {
                    "result": "BLOCKED",
                    "counts": self._counts_from_entries(preview.entries),
                    "receipt": after_backup["exchange"]["receipt"],
                    "snapshot": after_backup["exchange"]["snapshot"],
                    "errors": [_error("STATE_CHANGED_DURING_BACKUP", "state changed while the verified backup was created")],
                }
            )
            self._record_attempt(response)
            return response
        try:
            sync_result = d02_sync.run_sync(self.paths, _fault=_sync_fault)
        except Exception as exc:
            failed_state = self._collect()
            response.update(
                {
                    "result": "FAILED",
                    "counts": self._counts_from_entries(preview.entries),
                    "receipt": failed_state["exchange"]["receipt"],
                    "snapshot": failed_state["exchange"]["snapshot"],
                    "errors": [_error("SYNC_EXECUTION_FAILED", str(exc))],
                }
            )
            self._record_attempt(response)
            return response
        completed = self._collect()
        actual_counts = self._counts_from_entries(sync_result.entries)
        completion_errors = list(completed["errors"])
        if not completed["exchange"]["chain_valid"]:
            completion_errors.append(_error("POST_EXECUTION_CHAIN_INVALID", "receipt does not bind the actual snapshot"))
        if completion_errors:
            result = "FAILED"
        else:
            result = "EXECUTED"
        response.update(
            {
                "result": result,
                "counts": actual_counts,
                "receipt": completed["exchange"]["receipt"],
                "snapshot": completed["exchange"]["snapshot"],
                "errors": completion_errors,
            }
        )
        record = {
            "contract": CONTRACT,
            "task_id": TASK_ID,
            "plan_id": plan_id,
            "result": result,
            "generated_at": response["generated_at"],
            "counts": actual_counts,
            "backup": response["backup"],
            "database_before_logical_sha256": plan["state_identity"]["database_logical_sha256"],
            "database_after_logical_sha256": completed["database"]["logical_sha256"],
            "receipt_sha256": completed["exchange"]["receipt"].get("sha256"),
            "snapshot_sha256": completed["exchange"]["snapshot"].get("sha256"),
            "error_codes": [item["code"] for item in completion_errors],
        }
        self._record_attempt(response)
        if result == "EXECUTED":
            self._atomic_state(self.last_execution, record)
            self._atomic_state(self.consumed_root / f"{plan_id}.json", {"plan_id": plan_id, "executed_at": response["generated_at"]})
        return response

    def verify(self) -> dict[str, object]:
        response = self._base("verify", dry_run=False)
        loaded = self._safe_json(self.last_execution)
        collected = self._collect()
        errors = list(collected["errors"])
        if loaded is None:
            errors.append(_error("NO_SUCCESSFUL_EXECUTION", "no successful D03 execution record exists"))
            last = None
        else:
            last, _ = loaded
            if last.get("result") != "EXECUTED":
                errors.append(_error("LAST_EXECUTION_INVALID", "last execution record is not successful"))
            if last.get("receipt_sha256") != collected["exchange"]["receipt"].get("sha256"):
                errors.append(_error("RECEIPT_CHANGED_AFTER_EXECUTION", "current receipt differs from last execution"))
            if last.get("snapshot_sha256") != collected["exchange"]["snapshot"].get("sha256"):
                errors.append(_error("SNAPSHOT_CHANGED_AFTER_EXECUTION", "current snapshot differs from last execution"))
            if not collected["exchange"]["chain_valid"]:
                errors.append(_error("RECEIPT_SNAPSHOT_CHAIN_INVALID", "receipt does not bind the actual snapshot"))
        response.update(
            {
                "result": "READY" if not errors else "BLOCKED",
                "plan_id": last.get("plan_id") if isinstance(last, dict) else None,
                "counts": collected["exchange"]["counts"],
                "receipt": collected["exchange"]["receipt"],
                "snapshot": collected["exchange"]["snapshot"],
                "backup": last.get("backup", response["backup"]) if isinstance(last, dict) else response["backup"],
                "errors": errors,
                "database": collected["database"],
            }
        )
        return response

    def restore_backup_for_isolated_test(self, backup_relative: str, target: Path) -> dict[str, object]:
        if not self.isolated_test:
            raise BackupError("restore helper is restricted to isolated D03 tests")
        backup_database = self.project_root / backup_relative / "observations.sqlite3"
        allowed = (self.project_root / "restore_evidence").resolve()
        return restore_backup_to(
            project_root=self.project_root,
            backup_database=backup_database,
            target=target,
            allowed_root=allowed,
        )
