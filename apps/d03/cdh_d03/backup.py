from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .identity import assert_beneath, hash_optional, inspect_database, open_readonly, sha256_file


class BackupError(RuntimeError):
    pass


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _copy_optional(source: Path, destination: Path) -> dict[str, object]:
    if not source.is_file():
        return {"state": "MISSING", "path": None, "sha256": None}
    if source.is_symlink():
        raise BackupError(f"backup source cannot be a symlink: {source}")
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    source_hash = sha256_file(source)
    copied_hash = sha256_file(destination)
    if source_hash != copied_hash:
        raise BackupError(f"backup copy hash mismatch: {source.name}")
    return {"state": "VERIFIED", "path": destination.name, "sha256": copied_hash}


def create_verified_backup(
    *,
    project_root: Path,
    database: Path,
    snapshot: Path,
    receipt: Path,
    plan_id: str,
    generated_at: str,
    fault: str | None = None,
) -> dict[str, object]:
    project_root = project_root.resolve()
    backup_root = project_root / "data/backups/d03"
    assert_beneath(project_root, backup_root)
    stamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = backup_root / f"{stamp}_{plan_id[:12]}"
    if directory.exists():
        raise BackupError("backup directory collision")
    directory.mkdir(parents=True)
    backup_db = directory / "observations.sqlite3"
    if fault == "BEFORE_DATABASE":
        raise BackupError("injected backup failure before database copy")
    source = open_readonly(database)
    destination = sqlite3.connect(backup_db)
    try:
        source.backup(destination)
        destination.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        destination.commit()
    except sqlite3.Error as exc:
        raise BackupError(f"SQLite Online Backup API failed: {exc}") from exc
    finally:
        destination.close()
        source.close()
    if fault == "AFTER_DATABASE":
        raise BackupError("injected backup failure after database copy")
    backup_info = inspect_database(backup_db)
    if backup_info["integrity_check"] != ["ok"] or backup_info["foreign_key_violation_count"] != 0:
        raise BackupError("backup database integrity verification failed")
    snapshot_info = _copy_optional(snapshot, directory / "snapshot_latest.json")
    receipt_info = _copy_optional(receipt, directory / "receipt_latest.json")
    manifest = {
        "contract": "CDH-D03-BACKUP-1",
        "created_at": generated_at,
        "plan_id": plan_id,
        "database": {
            "path": "observations.sqlite3",
            "sha256": sha256_file(backup_db),
            "logical_sha256": backup_info["logical_sha256"],
            "integrity_check": backup_info["integrity_check"],
            "foreign_key_violation_count": backup_info["foreign_key_violation_count"],
        },
        "snapshot": snapshot_info,
        "receipt": receipt_info,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _atomic_write(directory / "backup_manifest.json", manifest_bytes)
    return {
        "state": "VERIFIED",
        "path": directory.relative_to(project_root).as_posix(),
        "sha256": manifest["database"]["sha256"],
        "logical_sha256": manifest["database"]["logical_sha256"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "database_path": backup_db,
    }


def restore_backup_to(
    *,
    project_root: Path,
    backup_database: Path,
    target: Path,
    allowed_root: Path,
) -> dict[str, object]:
    project_root = project_root.resolve()
    allowed_root = allowed_root.resolve()
    assert_beneath(project_root, backup_database, allow_missing=False)
    assert_beneath(allowed_root, target)
    if target.exists():
        raise BackupError("restore target must not already exist")
    target.parent.mkdir(parents=True, exist_ok=True)
    source = open_readonly(backup_database)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()
    restored = inspect_database(target)
    backup = inspect_database(backup_database)
    if restored["logical_sha256"] != backup["logical_sha256"] or restored["integrity_check"] != ["ok"]:
        raise BackupError("restored database does not match verified backup")
    return {
        "state": "VERIFIED",
        "backup_sha256": hash_optional(backup_database),
        "restored_sha256": hash_optional(target),
        "logical_sha256": restored["logical_sha256"],
        "integrity_check": restored["integrity_check"],
    }
