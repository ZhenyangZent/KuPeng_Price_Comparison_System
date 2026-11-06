from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


D02_RELEASE_SHA256 = "1931bc7da435f55154190925e046bf684427347f06d987fa4594d769ce765886"
D02_SOURCE_SHA256 = {
    "apps/d01/cdh_d01/sync.py": "4557ff07da249dabf44aa0dbd63fee085115164279ab36ecf695c6a842a80419",
    "apps/d01/cdh_d01/database.py": "14a32bb13e4ab2c1c0a0773bc1468674974c160a089e40a7067344c985d3ecf2",
    "apps/d01/cdh_d01/ingest.py": "abdd1b6fa42f2540fa21444120e10d94ab93015cf99ccaceb31d4d5821055ecf",
    "apps/d01/cdh_d01/snapshot.py": "9223209afdcece4d13925a2415778bcd590f43c82f224fda36a6c0376ea58198",
    "apps/d01/cdh_d01/validation.py": "56f83ff6cab291a998c09275429227185c36f52925d2c5bd52678acdf69e294d",
}
REQUIRED_TABLES = {
    "schema_migrations",
    "raw_submissions",
    "observations",
    "leads",
    "ingest_attempts",
    "quarantine",
    "source_permissions",
    "snapshots",
}
REPARSE_POINT = 0x400


class IdentityError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_optional(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() else None


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & REPARSE_POINT)


def assert_beneath(root: Path, path: Path, *, allow_missing: bool = True) -> None:
    root = root.resolve()
    absolute = path.absolute()
    try:
        relative = absolute.relative_to(root)
    except ValueError as exc:
        raise IdentityError(f"path escapes project root: {path}") from exc
    current = root
    if _is_reparse(current):
        raise IdentityError(f"project root cannot be a symlink or reparse point: {root}")
    for part in relative.parts:
        current = current / part
        if current.exists() and _is_reparse(current):
            raise IdentityError(f"symlink or reparse point rejected: {current}")
    if not allow_missing and not absolute.exists():
        raise IdentityError(f"required path is missing: {absolute}")


def verify_d02_identity(code_root: Path, imported_sync_file: Path) -> dict[str, object]:
    code_root = code_root.resolve()
    release = code_root / "review/releases/CDH_D02_001_REVIEW.zip"
    errors: list[dict[str, str]] = []
    source_hashes: dict[str, str | None] = {}
    release_hash = hash_optional(release)
    if release_hash != D02_RELEASE_SHA256:
        errors.append({"code": "D02_RELEASE_IDENTITY_MISMATCH", "detail": "frozen D02 release SHA-256 mismatch"})
    for relative, expected in D02_SOURCE_SHA256.items():
        path = code_root / relative
        actual = hash_optional(path)
        source_hashes[relative] = actual
        if actual != expected:
            errors.append({"code": "D02_SOURCE_IDENTITY_MISMATCH", "detail": f"protected module mismatch: {relative}"})
    expected_module = (code_root / "apps/d01/cdh_d01/sync.py").resolve()
    if imported_sync_file.resolve() != expected_module:
        errors.append({"code": "D02_MODULE_PATH_MISMATCH", "detail": "cdh_d01.sync imported from an unexpected path"})
    return {
        "state": "VERIFIED" if not errors else "INVALID",
        "release_sha256": release_hash,
        "source_hashes": source_hashes,
        "module_path": imported_sync_file.resolve().relative_to(code_root).as_posix()
        if imported_sync_file.resolve().is_relative_to(code_root)
        else str(imported_sync_file.resolve()),
        "errors": errors,
    }


def open_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=2000")
    return connection


def logical_database_sha256(path: Path) -> str:
    source = open_readonly(path)
    memory = sqlite3.connect(":memory:")
    try:
        source.backup(memory)
        if hasattr(memory, "serialize"):
            payload = memory.serialize()
        else:  # pragma: no cover - Python 3.11+ provides serialize
            payload = "\n".join(memory.iterdump()).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    finally:
        memory.close()
        source.close()


def inspect_database(path: Path) -> dict[str, object]:
    if not path.is_file() or _is_reparse(path):
        raise IdentityError(f"existing normal SQLite database is required: {path}")
    connection = open_readonly(path)
    try:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        foreign = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        migrations = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
        approved = connection.execute("SELECT COUNT(*) FROM source_permissions WHERE status='APPROVED'").fetchone()[0]
        counts = {
            "observations": connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
            "raw_submissions": connection.execute("SELECT COUNT(*) FROM raw_submissions").fetchone()[0],
            "quarantine": connection.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0],
        }
    finally:
        connection.close()
    return {
        "file_sha256": sha256_file(path),
        "logical_sha256": logical_database_sha256(path),
        "bytes": path.stat().st_size,
        "integrity_check": integrity,
        "foreign_key_violation_count": len(foreign),
        "required_tables_present": REQUIRED_TABLES.issubset(tables),
        "schema_migrations": migrations,
        "approved_permission_count": approved,
        "counts": counts,
    }
