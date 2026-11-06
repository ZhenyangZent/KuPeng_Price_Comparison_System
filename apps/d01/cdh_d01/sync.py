from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .database import connect, migrate
from .ingest import IngestResult, _quarantine, ingest_validated
from .model import ValidationError, utc_now_text
from .snapshot import build_snapshot, write_snapshot
from .validation import MAX_JSON_BYTES, decode_json_bytes, validate_record


RECEIPT_VERSION = "CDH-D01-RECEIPT-1"
EXCHANGE_VERSION = "CDH-EXCHANGE-1"
SOURCE_STATUS = "SOURCE_BLOCKED"
MAX_DIRECTORY_ENTRIES = 5_000
MAX_RECEIPT_ENTRIES = 1_000
MAX_RECEIPT_BYTES = 2 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_VERSIONED_RECEIPTS = 32
MAX_VERSIONED_SNAPSHOTS = 32
CANONICAL_FILENAME = re.compile(
    r"^submission_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.json$"
)
REPARSE_POINT = 0x400


class SyncError(RuntimeError):
    """Base error for a fail-closed local synchronization cycle."""


class ConcurrentSyncError(SyncError):
    pass


class UnsafePathError(SyncError):
    pass


class CapacityError(SyncError):
    pass


@dataclass(frozen=True)
class SyncPaths:
    root: Path
    database: Path
    inbox: Path
    snapshots: Path
    receipts: Path
    lock: Path

    @classmethod
    def for_root(cls, root: Path) -> "SyncPaths":
        root = root.resolve()
        exchange = root / "data" / "exchange"
        return cls(
            root=root,
            database=root / "data" / "d01" / "observations.sqlite3",
            inbox=exchange / "inbox",
            snapshots=exchange / "snapshots",
            receipts=exchange / "receipts",
            lock=exchange / ".d02_sync.lock",
        )


@dataclass(frozen=True)
class ReceiptEntry:
    filename: str
    file_sha256: str
    status: str
    reason_code: str | None


@dataclass(frozen=True)
class SyncResult:
    dry_run: bool
    cutoff_file_count: int
    entries: tuple[ReceiptEntry, ...]
    snapshot_sha256: str | None
    snapshot_written: bool
    receipt_sha256: str | None
    receipt_path: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "cutoff_file_count": self.cutoff_file_count,
            "entries": [asdict(entry) for entry in self.entries],
            "snapshot_sha256": self.snapshot_sha256,
            "snapshot_written": self.snapshot_written,
            "receipt_sha256": self.receipt_sha256,
            "receipt_path": self.receipt_path,
        }


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & REPARSE_POINT)


def _assert_no_reparse_ancestors(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise UnsafePathError(f"path escapes project root: {path}") from exc
    current = root
    if _is_reparse_or_symlink(current):
        raise UnsafePathError(f"project root cannot be a symlink or reparse point: {current}")
    for part in relative.parts:
        current = current / part
        if current.exists() and _is_reparse_or_symlink(current):
            raise UnsafePathError(f"symlink or reparse point rejected: {current}")


def validate_layout(paths: SyncPaths) -> None:
    root = paths.root.resolve()
    if not root.is_dir():
        raise UnsafePathError(f"project root does not exist: {root}")
    expected = SyncPaths.for_root(root)
    for field in ("database", "inbox", "snapshots", "receipts", "lock"):
        actual_path = Path(getattr(paths, field)).absolute()
        expected_path = Path(getattr(expected, field)).absolute()
        if actual_path != expected_path:
            raise UnsafePathError(f"wrong {field} path: {actual_path}")
        _assert_no_reparse_ancestors(root, actual_path)
    if not paths.database.is_file():
        raise UnsafePathError(f"existing D01 database is required: {paths.database}")


class SingleWriterLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> "SingleWriterLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if _is_reparse_or_symlink(self.path):
            raise UnsafePathError(f"lock path cannot be a symlink or reparse point: {self.path}")
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"\0")
            self.handle.flush()
            os.fsync(self.handle.fileno())
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise ConcurrentSyncError("another D02 synchronization cycle holds the writer lock") from exc
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def _capture_cutoff(inbox: Path) -> list[str]:
    if not inbox.exists():
        return []
    if not inbox.is_dir() or _is_reparse_or_symlink(inbox):
        raise UnsafePathError(f"inbox must be a normal directory: {inbox}")
    selected: list[str] = []
    seen_casefold: set[str] = set()
    with os.scandir(inbox) as iterator:
        for count, entry in enumerate(iterator, 1):
            if count > MAX_DIRECTORY_ENTRIES:
                raise CapacityError(f"inbox exceeds {MAX_DIRECTORY_ENTRIES} directory entries")
            if not (entry.name.startswith("submission_") and entry.name.endswith(".json")):
                continue
            folded = entry.name.casefold()
            if folded in seen_casefold:
                raise UnsafePathError(f"case-colliding inbox filename: {entry.name}")
            seen_casefold.add(folded)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SyncError(f"cannot inspect inbox entry {entry.name}: {exc}") from exc
            attributes = getattr(info, "st_file_attributes", 0)
            if entry.is_symlink() or bool(attributes & REPARSE_POINT) or not stat.S_ISREG(info.st_mode):
                raise UnsafePathError(f"inbox entry is not a normal file: {entry.name}")
            selected.append(entry.name)
            if len(selected) > MAX_RECEIPT_ENTRIES:
                raise CapacityError(f"receipt cutoff exceeds {MAX_RECEIPT_ENTRIES} submission files")
    return sorted(selected)


def _stable_read(path: Path) -> tuple[bytes, bool]:
    if _is_reparse_or_symlink(path):
        raise UnsafePathError(f"inbox symlink or reparse point rejected: {path.name}")
    try:
        before = path.lstat()
    except OSError as exc:
        raise SyncError(f"cannot stat cutoff file {path.name}: {exc}") from exc
    if not stat.S_ISREG(before.st_mode):
        raise UnsafePathError(f"cutoff entry is not a normal file: {path.name}")
    if before.st_size > MAX_JSON_BYTES:
        raise CapacityError(f"{path.name} exceeds {MAX_JSON_BYTES} bytes")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            data = handle.read(MAX_JSON_BYTES + 1)
    except OSError as exc:
        raise SyncError(f"cannot read cutoff file {path.name}: {exc}") from exc
    if len(data) > MAX_JSON_BYTES:
        raise CapacityError(f"{path.name} exceeds {MAX_JSON_BYTES} bytes")
    try:
        after = path.lstat()
    except OSError:
        return data, False
    stable = (
        stat.S_ISREG(after.st_mode)
        and before.st_size == opened.st_size == after.st_size == len(data)
        and before.st_mtime_ns == opened.st_mtime_ns == after.st_mtime_ns
        and getattr(before, "st_ino", 0) == getattr(opened, "st_ino", 0) == getattr(after, "st_ino", 0)
    )
    return data, stable


def _cached_outcome(conn: sqlite3.Connection, filename: str, digest: str) -> ReceiptEntry | None:
    row = conn.execute(
        """SELECT status, reason_code FROM sync_file_outcomes
        WHERE filename=? AND file_sha256=? ORDER BY outcome_id LIMIT 1""",
        (filename, digest),
    ).fetchone()
    if row is None:
        return None
    if row["status"] in {"IMPORTED", "DUPLICATE_NOOP"}:
        return ReceiptEntry(filename, digest, "DUPLICATE_NOOP", "IDENTICAL_REPLAY")
    return ReceiptEntry(filename, digest, row["status"], row["reason_code"])


def _record_quarantine(
    conn: sqlite3.Connection,
    *,
    source_path: str,
    digest: str,
    submission_id: str | None,
    reason_code: str,
    reason_detail: str,
) -> IngestResult:
    return _quarantine(
        conn,
        source_path=source_path,
        raw_sha256=digest,
        submission_id=submission_id,
        reason_code=reason_code,
        reason_detail=reason_detail,
        manage_transaction=False,
    )


def _process_file(conn: sqlite3.Connection, inbox: Path, filename: str) -> ReceiptEntry:
    data, stable = _stable_read(inbox / filename)
    digest = hashlib.sha256(data).hexdigest()
    if not stable:
        return ReceiptEntry(filename, digest, "RETRY_NEEDED", "FILE_CHANGED_DURING_SCAN")
    cached = _cached_outcome(conn, filename, digest)
    if cached is not None:
        return cached
    match = CANONICAL_FILENAME.fullmatch(filename)
    source_path = f"data/exchange/inbox/{filename}"
    with conn:
        if match is None:
            result = _record_quarantine(
                conn,
                source_path=source_path,
                digest=digest,
                submission_id=None,
                reason_code="INVALID_SUBMISSION_FILENAME",
                reason_detail="filename must be submission_<canonical-uuid>.json",
            )
        else:
            filename_id = match.group(1)
            try:
                if str(uuid.UUID(filename_id)) != filename_id:
                    raise ValueError("UUID is not canonical")
                payload = decode_json_bytes(data)
                record = validate_record(payload)
                if record.submission_id != filename_id:
                    result = _record_quarantine(
                        conn,
                        source_path=source_path,
                        digest=digest,
                        submission_id=record.submission_id,
                        reason_code="FILENAME_SUBMISSION_ID_MISMATCH",
                        reason_detail="filename UUID must equal payload submission_id",
                    )
                else:
                    result = ingest_validated(
                        conn,
                        record,
                        raw_bytes=data,
                        source_path=source_path,
                        manage_transaction=False,
                    )
            except (ValidationError, ValueError) as exc:
                if isinstance(exc, ValidationError):
                    reason_code, reason_detail = exc.code, exc.detail
                else:
                    reason_code, reason_detail = "INVALID_SUBMISSION_FILENAME", str(exc)
                result = _record_quarantine(
                    conn,
                    source_path=source_path,
                    digest=digest,
                    submission_id=None,
                    reason_code=reason_code,
                    reason_detail=reason_detail,
                )
        conn.execute(
            """INSERT INTO sync_file_outcomes
            (filename,file_sha256,submission_id,status,reason_code,reason_detail,processed_at_utc)
            VALUES(?,?,?,?,?,?,?)""",
            (
                filename,
                digest,
                result.submission_id,
                result.status,
                result.reason_code,
                result.reason_detail,
                utc_now_text(),
            ),
        )
    return ReceiptEntry(filename, digest, result.status, result.reason_code)


def _read_json_file(path: Path, limit: int) -> tuple[bytes, dict[str, object]] | None:
    if not path.is_file() or _is_reparse_or_symlink(path):
        return None
    if path.stat().st_size > limit:
        return None
    try:
        data = path.read_bytes()
        value = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return (data, value) if isinstance(value, dict) else None


def _snapshot_equivalent(conn: sqlite3.Connection, latest: Path) -> tuple[str, bool] | None:
    current = _read_json_file(latest, MAX_SNAPSHOT_BYTES)
    if current is None:
        return None
    data, value = current
    candidate = build_snapshot(conn, generated_at_utc=str(value.get("snapshot_generated_at_utc", utc_now_text())))
    if value != candidate:
        return None
    return hashlib.sha256(data).hexdigest(), False


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(path.parents) < 4 or path.parents[2].name != "data" or path.parents[1].name != "exchange":
        raise UnsafePathError(f"unexpected exchange output path: {path}")
    _assert_no_reparse_ancestors(path.parents[3], path)
    if _is_reparse_or_symlink(path):
        raise UnsafePathError(f"output target cannot be a symlink or reparse point: {path}")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.005 * (attempt + 1))
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _receipt_bytes(entries: list[ReceiptEntry], snapshot_sha256: str, generated_at: str) -> bytes:
    payload = {
        "receipt_version": RECEIPT_VERSION,
        "exchange_version": EXCHANGE_VERSION,
        "generated_at_utc": generated_at,
        "source_status": SOURCE_STATUS,
        "snapshot_sha256": snapshot_sha256,
        "entries": [asdict(entry) for entry in entries],
    }
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(data) > MAX_RECEIPT_BYTES:
        raise CapacityError(f"receipt exceeds {MAX_RECEIPT_BYTES} bytes")
    return data


def _prune_versions(directory: Path, pattern: str, keep: int) -> None:
    candidates = sorted(
        path for path in directory.glob(pattern) if path.is_file() and not _is_reparse_or_symlink(path)
    )
    for path in candidates[:-keep]:
        path.unlink()


def _publish_receipt(receipts: Path, entries: list[ReceiptEntry], snapshot_sha256: str) -> tuple[Path, str]:
    generated_at = utc_now_text()
    data = _receipt_bytes(entries, snapshot_sha256, generated_at)
    digest = hashlib.sha256(data).hexdigest()
    stamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    version = receipts / f"receipt_{stamp.strftime('%Y%m%dT%H%M%SZ')}_{digest}.json"
    if version.exists():
        if version.read_bytes() != data:
            raise SyncError(f"receipt filename collision: {version.name}")
    else:
        _atomic_write(version, data)
    latest = receipts / "latest.json"
    _atomic_write(latest, data)
    if hashlib.sha256(latest.read_bytes()).hexdigest() != digest:
        raise SyncError("receipt readback SHA-256 mismatch")
    _prune_versions(receipts, "receipt_*.json", MAX_VERSIONED_RECEIPTS)
    return latest, digest


def _open_dry_run_copy(database: Path) -> sqlite3.Connection:
    source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(":memory:")
    target.row_factory = sqlite3.Row
    try:
        source.backup(target)
    finally:
        source.close()
    target.execute("PRAGMA foreign_keys=ON")
    migrate(target)
    return target


def _process_cutoff(
    conn: sqlite3.Connection,
    paths: SyncPaths,
    cutoff: list[str],
) -> list[ReceiptEntry]:
    return [_process_file(conn, paths.inbox, filename) for filename in cutoff]


def run_sync(
    paths: SyncPaths,
    *,
    dry_run: bool = False,
    _after_cutoff: Callable[[], None] | None = None,
    _fault: str | None = None,
) -> SyncResult:
    """Run one explicit filesystem-only cycle; test hooks are intentionally not exposed by the CLI."""
    validate_layout(paths)
    if dry_run:
        cutoff = _capture_cutoff(paths.inbox)
        if _after_cutoff is not None:
            _after_cutoff()
        conn = _open_dry_run_copy(paths.database)
        try:
            entries = _process_cutoff(conn, paths, cutoff)
        finally:
            conn.close()
        return SyncResult(True, len(cutoff), tuple(entries), None, False, None, None)

    with SingleWriterLock(paths.lock):
        paths.snapshots.mkdir(parents=True, exist_ok=True)
        paths.receipts.mkdir(parents=True, exist_ok=True)
        _assert_no_reparse_ancestors(paths.root, paths.snapshots)
        _assert_no_reparse_ancestors(paths.root, paths.receipts)
        cutoff = _capture_cutoff(paths.inbox)
        if _after_cutoff is not None:
            _after_cutoff()
        conn = connect(paths.database)
        try:
            migrate(conn)
            entries = _process_cutoff(conn, paths, cutoff)
            if _fault == "AFTER_DATABASE_COMMIT":
                raise SyncError("injected failure after database commit")
            equivalent = _snapshot_equivalent(conn, paths.snapshots / "latest.json")
            if equivalent is None:
                _, snapshot_sha = write_snapshot(conn, paths.snapshots)
                snapshot_written = True
            else:
                snapshot_sha, snapshot_written = equivalent
            actual_snapshot_sha = hashlib.sha256((paths.snapshots / "latest.json").read_bytes()).hexdigest()
            if snapshot_sha != actual_snapshot_sha:
                raise SyncError("snapshot readback SHA-256 mismatch")
            if _fault == "AFTER_SNAPSHOT":
                raise SyncError("injected failure after snapshot before receipt")
            receipt_path, receipt_sha = _publish_receipt(paths.receipts, entries, snapshot_sha)
            _prune_versions(paths.snapshots, "snapshot_*.json", MAX_VERSIONED_SNAPSHOTS)
        finally:
            conn.close()
    return SyncResult(
        False,
        len(cutoff),
        tuple(entries),
        snapshot_sha,
        snapshot_written,
        receipt_sha,
        str(receipt_path),
    )
