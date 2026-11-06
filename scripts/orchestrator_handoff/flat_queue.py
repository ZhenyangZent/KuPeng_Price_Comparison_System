#!/usr/bin/env python3
"""Flat, offline review-ZIP upload queue with exact-hash ACK archiving.

This is the E02 primary interface.  It never mutates ``review/releases`` and
performs no network, browser, registry, database, Git, or shopping actions.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat as stat_module
import sys
import tempfile
import time
import unicodedata
import uuid
import zipfile

from handoff_batch import HandoffError, inspect_zip, sha256


RELEASE_RE = re.compile(r"^CDH_[A-Z0-9_]+_REVIEW\.zip$")
STATUS_ONLY_RE = re.compile(r"^CDH_[A-Z0-9_]+_STATUS_ONLY\.zip$")
BATCH_RE = re.compile(r"^CDH_BATCH_[A-Za-z0-9_-]{4,40}_REVIEW\.zip$")
ARCHIVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_QUEUE_ITEMS = 100
MAX_QUEUE_BYTES = 3_000_000_000
MAX_ACK_FILE_BYTES = 1024 * 1024
LOCK_INCOMPLETE_GRACE_SECONDS = 3600.0
LOCK_DEAD_OWNER_GRACE_SECONDS = 1.0
MANIFEST_NAMES = {"manifest.json", "sha256_manifest.json", "review_manifest.json"}
SENSITIVE_COMPONENTS = {".env", ".venv", ".git", ".ssh", "cookies", "credentials", "secrets"}
SENSITIVE_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".db3", ".reg", ".pem", ".key", ".pfx", ".p12"}
SENSITIVE_WORD_RE = re.compile(r"(?:^|[_.-])(token|cookies?|credential|secret)(?:[_.-]|$)")
SECRET_KEY_RE = re.compile(r"(?:token|secret|password|credential|cookie|api[_-]?key)", re.IGNORECASE)
FORBIDDEN_SECRET_VALUE_RE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})"
)
PLACEHOLDER_VALUES = {"", "changeme", "example", "placeholder", "invalid", "not_configured", "none", "null"}


def _delivery_name(name: str) -> bool:
    return bool(RELEASE_RE.fullmatch(name) or STATUS_ONLY_RE.fullmatch(name))


def _fail(code: str, detail: str) -> None:
    raise HandoffError(code, detail)


def _root(root: Path) -> Path:
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        _fail("INVALID_PROJECT_ROOT", "project root must be a directory")
    return resolved


def _inside(root: Path, path: Path, *, must_exist: bool = False) -> Path:
    resolved = path.resolve(strict=must_exist)
    if not resolved.is_relative_to(root):
        _fail("OUTSIDE_PROJECT_ROOT", f"path escapes project root: {path}")
    return resolved


def _ensure_dir(root: Path, relative: str) -> Path:
    candidate = root / relative
    ancestor = candidate
    while not ancestor.exists():
        if ancestor == ancestor.parent:
            _fail("OUTSIDE_PROJECT_ROOT", f"no safe parent for {relative}")
        ancestor = ancestor.parent
    _inside(root, ancestor, must_exist=True)
    deadline = time.monotonic() + 5.0
    while True:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            break
        except PermissionError:
            # Concurrent recursive mkdir on Windows/MSYS can briefly report
            # access denied while the peer-created directory becomes visible.
            if candidate.is_dir():
                break
            if time.monotonic() >= deadline:
                _fail("DIRECTORY_CREATE_FAILED", f"could not create directory: {relative}")
            time.sleep(0.01)
    resolved = _inside(root, candidate, must_exist=True)
    if resolved.is_symlink() or not resolved.is_dir():
        _fail("UNSAFE_DIRECTORY", f"not a regular directory: {relative}")
    return resolved


def _member_sensitive(name: str) -> bool:
    parts = [unicodedata.normalize("NFC", part).casefold() for part in name.split("/")]
    if parts[-1] == ".env.example":
        return False
    if any(part in SENSITIVE_COMPONENTS or part.startswith(".env.") for part in parts):
        return True
    basename = parts[-1]
    return Path(basename).suffix.casefold() in SENSITIVE_SUFFIXES or bool(
        SENSITIVE_WORD_RE.search(basename)
    )


def _validate_env_example(archive: zipfile.ZipFile, name: str) -> None:
    info = archive.getinfo(name)
    if info.file_size > 64 * 1024:
        _fail("ENV_EXAMPLE_TOO_LARGE", f".env.example exceeds 64 KiB: {name}")
    try:
        text = archive.read(name).decode("utf-8")
    except UnicodeDecodeError:
        _fail("ENV_EXAMPLE_NOT_UTF8", f".env.example must be UTF-8: {name}")
    if FORBIDDEN_SECRET_VALUE_RE.search(text):
        _fail("ENV_EXAMPLE_SECRET_PATTERN", f"credential pattern found in .env.example: {name}")
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            _fail("ENV_EXAMPLE_INVALID_LINE", f"invalid .env.example line {line_number}: {name}")
        key, value = line.split("=", 1)
        normalized_value = value.strip().strip("\"'").casefold()
        if SECRET_KEY_RE.search(key) and not (
            normalized_value in PLACEHOLDER_VALUES
            or normalized_value.startswith(("example_", "your_", "<"))
        ):
            _fail("ENV_EXAMPLE_NONPLACEHOLDER_SECRET", f"non-placeholder sensitive value at line {line_number}: {name}")


def _manifest_candidates(archive: zipfile.ZipFile) -> list[str]:
    return [
        name
        for name in archive.namelist()
        if PurePosixPath(name).name.casefold() in MANIFEST_NAMES
    ]


def _select_manifest(candidates: list[str]) -> str | None:
    if not candidates:
        return None

    def priority(name: str) -> tuple[int, int, str]:
        path = PurePosixPath(name)
        depth = len(path.parts)
        basename = path.name.casefold()
        if depth == 1 and basename in {"review_manifest.json", "sha256_manifest.json"}:
            rank = 0
        elif depth == 2 and basename in {"review_manifest.json", "sha256_manifest.json"}:
            rank = 1
        elif depth == 2 and basename == "manifest.json":
            rank = 2
        else:
            rank = 100 + depth
        return rank, depth, name.casefold()

    ordered = sorted(candidates, key=priority)
    best_rank = priority(ordered[0])[0]
    if sum(1 for name in ordered if priority(name)[0] == best_rank) != 1:
        _fail("MANIFEST_SELECTION_AMBIGUOUS", "multiple manifests have the same authoritative priority")
    return ordered[0]


def _record_values(record: dict) -> tuple[str, int | None, str] | None:
    path = record.get("path") or record.get("name")
    digest = record.get("sha256") or record.get("hash")
    size = record.get("bytes")
    if size is None:
        size = record.get("size_bytes")
    if isinstance(path, str) and isinstance(digest, str) and HEX_RE.fullmatch(digest.casefold()):
        return path, size if isinstance(size, int) else None, digest.casefold()
    return None


def _manifest_records(payload: object) -> list[tuple[str, int | None, str]]:
    candidates: object = payload
    if isinstance(payload, dict):
        for key in ("payloads", "files", "entries"):
            if isinstance(payload.get(key), (list, dict)):
                candidates = payload[key]
                break
    records: list[tuple[str, int | None, str]] = []
    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, dict):
                parsed = _record_values(item)
                if parsed:
                    records.append(parsed)
    elif isinstance(candidates, dict):
        for path, digest in candidates.items():
            if isinstance(path, str) and isinstance(digest, str) and HEX_RE.fullmatch(digest.casefold()):
                records.append((path, None, digest.casefold()))
    return records


def _resolve_manifest_path(manifest_name: str, recorded: str, names: set[str]) -> str | None:
    if recorded in names:
        return recorded
    base = PurePosixPath(manifest_name).parent
    combined = (base / recorded).as_posix()
    if combined in names:
        return combined
    return None


def _hash_member(archive: zipfile.ZipFile, name: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with archive.open(name, "r") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def validate_release(
    path: Path,
    *,
    require_manifest: bool = True,
    require_sensitive_clean: bool = True,
    require_no_nested_zip: bool = True,
) -> dict:
    base = inspect_zip(path, reject_sensitive=require_sensitive_clean)
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = set(archive.namelist())
            nested = [name for name in names if name.casefold().endswith(".zip")]
            if nested and require_no_nested_zip:
                _fail("NESTED_ZIP_DENIED", f"flat release contains nested ZIP: {nested[0]}")
            sensitive = [name for name in names if _member_sensitive(name)]
            if sensitive and require_sensitive_clean:
                _fail("SENSITIVE_RELEASE_CONTENT", f"sensitive path denied: {sensitive[0]}")
            env_examples = [
                name for name in names if PurePosixPath(name).name.casefold() == ".env.example"
            ]
            for env_example in env_examples:
                _validate_env_example(archive, env_example)
            manifests = _manifest_candidates(archive)
            manifest_name = _select_manifest(manifests)
            if manifest_name is None and not require_manifest:
                base.update(
                    {
                        "artifact_type": "release",
                        "manifest": None,
                        "manifest_candidate_count": 0,
                        "manifest_records": 0,
                        "manifest_gate": "MISSING_ALLOWED_FOR_EXACT_ACK_ONLY",
                        "nested_zip_gate": (
                            "PASS"
                            if not nested
                            else "PRESENT_ALLOWED_FOR_EXACT_ACK_ONLY"
                        ),
                        "nested_zip_count": len(nested),
                        "env_example_gate": "PASS",
                        "sensitive_content_gate": (
                            "PASS"
                            if not sensitive
                            else "PRESENT_ALLOWED_FOR_EXACT_ACK_ONLY"
                        ),
                        "sensitive_path_count": len(sensitive),
                    }
                )
                return base
            if manifest_name is None:
                _fail("MANIFEST_COUNT_INVALID", "expected an authoritative release manifest")
            try:
                payload = json.loads(archive.read(manifest_name))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                _fail("INVALID_RELEASE_MANIFEST", f"cannot decode manifest: {type(exc).__name__}")
            records = _manifest_records(payload)
            if not records:
                _fail("EMPTY_RELEASE_MANIFEST", "release manifest has no recognizable SHA-256 records")
            seen: set[str] = set()
            for recorded, expected_size, expected_hash in records:
                actual_name = _resolve_manifest_path(manifest_name, recorded, names)
                if actual_name is None:
                    _fail("MANIFEST_FILE_MISSING", f"manifest path missing: {recorded}")
                key = unicodedata.normalize("NFC", actual_name).casefold()
                if key in seen:
                    _fail("MANIFEST_DUPLICATE_PATH", f"duplicate manifest path: {recorded}")
                seen.add(key)
                actual_hash, actual_size = _hash_member(archive, actual_name)
                if actual_hash != expected_hash:
                    _fail("MANIFEST_HASH_MISMATCH", f"manifest hash mismatch: {recorded}")
                if expected_size is not None and actual_size != expected_size:
                    _fail("MANIFEST_SIZE_MISMATCH", f"manifest size mismatch: {recorded}")
    except zipfile.BadZipFile as exc:
        _fail("INVALID_ZIP", f"invalid release ZIP: {exc}")
    base.update(
        {
            "artifact_type": "release",
            "manifest": manifest_name,
            "manifest_candidate_count": len(manifests),
            "manifest_records": len(records),
            "manifest_gate": "PASS",
            "nested_zip_gate": (
                "PASS" if not nested else "PRESENT_ALLOWED_FOR_EXACT_ACK_ONLY"
            ),
            "nested_zip_count": len(nested),
            "env_example_gate": "PASS",
            "sensitive_content_gate": (
                "PASS" if not sensitive else "PRESENT_ALLOWED_FOR_EXACT_ACK_ONLY"
            ),
            "sensitive_path_count": len(sensitive),
        }
    )
    return base


def validate_status_only(
    path: Path,
    *,
    require_sensitive_clean: bool = True,
    require_no_nested_zip: bool = True,
) -> dict:
    """Validate a small, machine-readable status handoff.

    STATUS_ONLY is a real delivery artifact, not an empty placeholder.  It
    requires STATUS.json, SUMMARY.md and MANIFEST.json either at ZIP root or
    inside one canonical top-level artifact directory.  The manifest must
    declare every non-manifest member so concise diagnostic evidence can be
    added without permitting undeclared payloads.
    """
    base = validate_release(
        path,
        require_manifest=True,
        require_sensitive_clean=require_sensitive_clean,
        require_no_nested_zip=require_no_nested_zip,
    )
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = set(archive.namelist())
            required_names = ("STATUS.json", "SUMMARY.md", "MANIFEST.json")
            bases = []
            for prefix in ("",) + tuple(
                sorted(
                    {
                        f"{PurePosixPath(name).parts[0]}/"
                        for name in names
                        if len(PurePosixPath(name).parts) > 1
                    }
                )
            ):
                if all(f"{prefix}{required}" in names for required in required_names):
                    bases.append(prefix)
            if len(bases) != 1:
                _fail(
                    "STATUS_ONLY_REQUIRED_FILE_MISSING",
                    "require exactly one STATUS/SUMMARY/MANIFEST artifact root",
                )
            prefix = bases[0]
            status_name = f"{prefix}STATUS.json"
            summary_name = f"{prefix}SUMMARY.md"
            manifest_name = f"{prefix}MANIFEST.json"
            if base.get("manifest") != manifest_name:
                _fail("STATUS_ONLY_MANIFEST_ROOT_MISMATCH", "authoritative manifest must share the status artifact root")
            try:
                status = json.loads(archive.read(status_name))
                summary = archive.read(summary_name).decode("utf-8")
                manifest = json.loads(archive.read(manifest_name))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                _fail("INVALID_STATUS_ONLY_CONTENT", f"cannot decode status content: {type(exc).__name__}")
            if not isinstance(status, dict):
                _fail("INVALID_STATUS_ONLY_STATUS", "STATUS.json must be an object")
            required_status = ("task_id", "workline", "status")
            for key in required_status:
                if key not in status:
                    _fail("INVALID_STATUS_ONLY_STATUS", f"STATUS.json missing field: {key}")
            if not isinstance(status["task_id"], str) or not status["task_id"].strip():
                _fail("INVALID_STATUS_ONLY_STATUS", "task_id must be a non-empty string")
            if status["workline"] not in tuple("ABCDEFGH"):
                _fail("INVALID_STATUS_ONLY_STATUS", "workline must be A..H")
            if not isinstance(status["status"], str) or not status["status"].strip():
                _fail("INVALID_STATUS_ONLY_STATUS", "status must be a non-empty string")
            generated_at = status.get(
                "generated_at",
                status.get("created_at", status.get("created_at_utc", status.get("timestamp_utc"))),
            )
            if not isinstance(generated_at, str) or not generated_at.strip():
                _fail(
                    "INVALID_STATUS_ONLY_STATUS",
                    "generated_at/created_at/created_at_utc/timestamp_utc must be a non-empty string",
                )
            prerequisites = status.get("prerequisites", status.get("dependencies"))
            if not isinstance(prerequisites, (list, dict)):
                _fail("INVALID_STATUS_ONLY_STATUS", "prerequisites/dependencies must be an array or object")
            if len(summary.strip()) < 20:
                _fail("INVALID_STATUS_ONLY_SUMMARY", "SUMMARY.md must contain a meaningful result")
            records = _manifest_records(manifest)
            declared: set[str] = set()
            for recorded, _, _ in records:
                actual = _resolve_manifest_path(manifest_name, recorded, names)
                if actual is not None:
                    declared.add(actual)
            expected = names - {manifest_name}
            if declared != expected:
                _fail("STATUS_ONLY_MANIFEST_COVERAGE", "manifest must declare every non-manifest member")
    except zipfile.BadZipFile as exc:
        _fail("INVALID_ZIP", f"invalid STATUS_ONLY ZIP: {exc}")
    base["artifact_type"] = "status_only"
    base["status_task_id"] = status["task_id"]
    base["status_workline"] = status["workline"]
    base["status_value"] = status["status"]
    base["status_generated_at"] = generated_at
    return base


def validate_legacy_batch(path: Path) -> dict:
    base = inspect_zip(path, reject_sensitive=False)
    with zipfile.ZipFile(path, "r") as archive:
        names = set(archive.namelist())
        if "BATCH_MANIFEST.json" not in names:
            _fail("BATCH_MANIFEST_MISSING", "legacy batch manifest is missing")
        try:
            manifest = json.loads(archive.read("BATCH_MANIFEST.json"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _fail("INVALID_BATCH_MANIFEST", f"cannot decode batch manifest: {type(exc).__name__}")
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(files, list) or not files:
            _fail("EMPTY_BATCH_MANIFEST", "legacy batch manifest has no files")
        expected = {"BATCH_MANIFEST.json"}
        for record in files:
            parsed = _record_values(record) if isinstance(record, dict) else None
            if parsed is None:
                _fail("INVALID_BATCH_RECORD", "legacy batch record is malformed")
            name, size, digest = parsed
            member = f"packages/{name}"
            expected.add(member)
            if member not in names:
                _fail("BATCH_MEMBER_MISSING", f"batch member missing: {member}")
            actual_hash, actual_size = _hash_member(archive, member)
            if actual_hash != digest or (size is not None and actual_size != size):
                _fail("BATCH_MEMBER_MISMATCH", f"batch member mismatch: {member}")
        if names != expected:
            _fail("UNDECLARED_BATCH_MEMBER", "legacy batch contains undeclared members")
    base.update(
        {
            "artifact_type": "legacy_batch",
            "manifest": "BATCH_MANIFEST.json",
            "manifest_records": len(files),
            "manifest_gate": "PASS",
        }
    )
    return base


def validate_queue_artifact(
    path: Path,
    *,
    require_manifest: bool = True,
    require_sensitive_clean: bool = True,
    require_no_nested_zip: bool = True,
    allow_legacy_status_only_exact_ack: bool = False,
) -> dict:
    if BATCH_RE.fullmatch(path.name):
        return validate_legacy_batch(path)
    if STATUS_ONLY_RE.fullmatch(path.name):
        # Central may ACK a historical STATUS_ONLY produced before the
        # STATUS/SUMMARY/MANIFEST three-file contract was introduced. The
        # archive path explicitly opts into this branch and remains bound to
        # the exact filename/SHA-256. Validate that legacy artifact as a
        # generic release without weakening normal enqueue/list gates.
        if allow_legacy_status_only_exact_ack:
            result = validate_release(
                path,
                require_manifest=False,
                require_sensitive_clean=require_sensitive_clean,
                require_no_nested_zip=require_no_nested_zip,
            )
            result["artifact_type"] = "legacy_status_only_exact_ack"
            return result
        return validate_status_only(
            path,
            require_sensitive_clean=require_sensitive_clean,
            require_no_nested_zip=require_no_nested_zip,
        )
    if RELEASE_RE.fullmatch(path.name) and not path.name.startswith("CDH_BATCH_"):
        return validate_release(
            path,
            require_manifest=require_manifest,
            require_sensitive_clean=require_sensitive_clean,
            require_no_nested_zip=require_no_nested_zip,
        )
    _fail("INVALID_QUEUE_FILENAME", f"not a permitted REVIEW/STATUS_ONLY ZIP filename: {path.name}")


def _queue_files(root: Path) -> list[Path]:
    queue = _ensure_dir(root, "review/00_TO_UPLOAD")
    items = sorted(queue.iterdir(), key=lambda item: item.name.casefold())
    if len(items) > MAX_QUEUE_ITEMS:
        _fail("QUEUE_ITEM_LIMIT", f"queue contains more than {MAX_QUEUE_ITEMS} items")
    total = 0
    result: list[Path] = []
    windows_keys: set[str] = set()
    for item in items:
        if item.name.startswith(".") or item.name.endswith(".partial"):
            _fail("QUEUE_PARTIAL_PRESENT", f"partial/hidden queue item denied: {item.name}")
        if not item.is_file() or item.is_symlink() or item.suffix.casefold() != ".zip":
            _fail("QUEUE_NON_ZIP_PRESENT", f"queue must contain regular ZIPs only: {item.name}")
        windows_key = unicodedata.normalize("NFC", item.name).casefold()
        if windows_key in windows_keys:
            _fail("QUEUE_FILENAME_CASE_COLLISION", f"Windows filename collision: {item.name}")
        windows_keys.add(windows_key)
        total += item.stat().st_size
        if total > MAX_QUEUE_BYTES:
            _fail("QUEUE_SIZE_LIMIT", "queue exceeds configured byte limit")
        result.append(item)
    return result


def list_queue(root: Path) -> dict:
    root = _root(root)
    files = [
        validate_queue_artifact(
            path,
            require_manifest=False,
            require_sensitive_clean=False,
            require_no_nested_zip=False,
        )
        for path in _queue_files(root)
    ]
    return {"schema": "CDH-FLAT-UPLOAD-QUEUE-1", "pending_count": len(files), "files": files}


def _archived_hashes(root: Path) -> dict[str, str]:
    archive_root = root / "review/90_UPLOADED_ARCHIVE"
    hashes: dict[str, str] = {}
    if not archive_root.exists():
        return hashes
    for path in archive_root.rglob("*.zip"):
        if path.is_file() and not path.is_symlink():
            hashes[path.relative_to(root).as_posix()] = sha256(path)
    return hashes


class _QueueLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None
        self.recovered_stale_lock = False

    @staticmethod
    def _pid_is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        if os.name == "nt":
            try:
                import ctypes

                query_limited_information = 0x1000
                handle = ctypes.windll.kernel32.OpenProcess(
                    query_limited_information, False, pid
                )
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return True
                return ctypes.windll.kernel32.GetLastError() == 5
            except (AttributeError, OSError):
                return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _recover_abandoned_lock(self) -> bool:
        try:
            metadata = self.path.lstat()
        except FileNotFoundError:
            return True
        # Use the mode from the same lstat call.  A separate is_file lookup can
        # race with the active owner unlinking the lock and misclassify a
        # normally released regular file as UNSAFE_QUEUE_LOCK.
        if not stat_module.S_ISREG(metadata.st_mode):
            _fail("UNSAFE_QUEUE_LOCK", "queue lock must be a regular file")
        age = max(0.0, time.time() - metadata.st_mtime)
        try:
            payload = json.loads(self.path.read_text(encoding="ascii"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            if age < LOCK_INCOMPLETE_GRACE_SECONDS:
                return False
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("pid"), int):
            if self._pid_is_alive(payload["pid"]):
                return False
            if age < LOCK_DEAD_OWNER_GRACE_SECONDS:
                return False
        elif age < LOCK_INCOMPLETE_GRACE_SECONDS:
            return False
        tombstone = self.path.with_name(
            f".{self.path.name}.stale.{os.getpid()}.{uuid.uuid4().hex}"
        )
        try:
            os.replace(self.path, tombstone)
        except FileNotFoundError:
            return True
        finally:
            if tombstone.exists():
                tombstone.unlink()
        self.recovered_stale_lock = True
        return True

    def __enter__(self) -> "_QueueLock":
        deadline = time.monotonic() + 5.0
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                payload = {
                    "pid": os.getpid(),
                    "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "token": uuid.uuid4().hex,
                }
                os.write(self.fd, json.dumps(payload, sort_keys=True).encode("ascii"))
                os.fsync(self.fd)
                break
            except FileExistsError:
                if self._recover_abandoned_lock():
                    continue
                if time.monotonic() >= deadline:
                    _fail("QUEUE_LOCKED", f"another enqueue/archive operation is active: {self.path.name}")
                time.sleep(0.01)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        # On Windows a waiter can briefly hold a read handle while inspecting
        # the lock.  Retrying avoids leaving an active-PID lock behind after a
        # normal owner exit, which would otherwise block the full timeout.
        deadline = time.monotonic() + 5.0
        while True:
            try:
                self.path.unlink()
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    _fail("QUEUE_LOCK_RELEASE_FAILED", "could not release queue lock")
                time.sleep(0.01)


def _cleanup_stale_partials(staging: Path) -> int:
    removed = 0
    for path in staging.iterdir():
        if (
            path.is_file()
            and not path.is_symlink()
            and path.name.startswith(".")
            and path.name.endswith(".partial")
        ):
            path.unlink()
            removed += 1
    return removed


def _enqueue_releases_locked(root: Path, files: list[str]) -> dict:
    root = _root(root)
    windows_names = [unicodedata.normalize("NFC", name).casefold() for name in files]
    if not files or len(files) > 30 or len(set(windows_names)) != len(files):
        _fail("INVALID_ENQUEUE_SET", "require 1..30 unique release names")
    releases = _inside(root, root / "review/releases", must_exist=True)
    if releases.is_symlink() or not releases.is_dir():
        _fail("UNSAFE_RELEASE_DIRECTORY", "review/releases must be a regular directory")
    queue = _ensure_dir(root, "review/00_TO_UPLOAD")
    staging = _ensure_dir(root, "review/E02/queue_staging")
    stale_partial_cleanup_count = _cleanup_stale_partials(staging)
    current = _queue_files(root)
    hash_locations = {sha256(path): path.name for path in current}
    hash_locations.update(_archived_hashes(root))
    results: list[dict] = []
    for name in files:
        if not _delivery_name(name) or name.startswith("CDH_BATCH_"):
            _fail("INVALID_RELEASE_NAME", f"not a permitted immutable release name: {name}")
        source = _inside(root, releases / name, must_exist=True)
        if source.parent != releases or source.is_symlink() or not source.is_file():
            _fail("INVALID_RELEASE_SOURCE", f"release source is not a regular direct child: {name}")
        validation = validate_queue_artifact(source)
        digest = validation["sha256"]
        destination = queue / name
        if destination.exists():
            if sha256(destination) == digest:
                results.append({"name": name, "sha256": digest, "status": "ALREADY_QUEUED"})
                continue
            _fail("QUEUE_NAME_HASH_CONFLICT", f"queue name exists with a different SHA-256: {name}")
        if digest in hash_locations:
            _fail("DUPLICATE_SHA256", f"same SHA-256 already queued/archived as {hash_locations[digest]}")
        temporary = staging / f".{name}.{os.getpid()}.{uuid.uuid4().hex}.partial"
        try:
            with source.open("rb") as incoming, temporary.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if sha256(temporary) != digest:
                _fail("ENQUEUE_COPY_HASH_MISMATCH", f"copied queue item hash mismatch: {name}")
            # The atomic staging filename intentionally ends in ``.partial``.
            # Select the validator from the already-validated immutable source
            # name instead of weakening canonical queue filename checks.
            if STATUS_ONLY_RE.fullmatch(name):
                validate_status_only(temporary)
            else:
                validate_release(temporary)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        hash_locations[digest] = name
        results.append({"name": name, "sha256": digest, "status": "ENQUEUED"})
    return {
        "enqueued": results,
        "pending_count": len(_queue_files(root)),
        "stale_partial_cleanup_count": stale_partial_cleanup_count,
    }


def enqueue_releases(root: Path, files: list[str]) -> dict:
    root = _root(root)
    locks = _ensure_dir(root, "review/E02/locks")
    with _QueueLock(locks / "flat_queue.lock") as lock:
        result = _enqueue_releases_locked(root, files)
        result["stale_lock_recovered"] = lock.recovered_stale_lock
        return result


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _receipt_record(
    root: Path,
    source: Path,
    destination: Path,
    digest: str,
    archive_id: str,
    recovered: bool,
    acknowledged_filenames: list[str] | None = None,
) -> dict:
    return {
        "schema": "CDH-FLAT-QUEUE-ARCHIVE-RECEIPT-1",
        "record_id": f"{archive_id}:{source.name}:{digest}",
        "acknowledgement": "CENTRAL_ORCHESTRATOR_RECEIVED_EXACT_NAME_AND_SHA256",
        "archive_id": archive_id,
        "filename": source.name,
        "sha256": digest,
        "before_path": source.relative_to(root).as_posix(),
        "after_path": destination.relative_to(root).as_posix(),
        "archived_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "exit_code": 0,
        "recovered_after_completed_move": recovered,
        "immutable_release_mutation_count": 0,
        "central_ack_filenames": sorted(set(acknowledged_filenames or [source.name])),
    }


def _load_receipt(path: Path) -> dict:
    if not path.exists():
        return {"schema": "CDH-FLAT-QUEUE-ARCHIVE-RECEIPT-LEDGER-1", "records": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("INVALID_ARCHIVE_RECEIPT", f"cannot read receipt ledger: {type(exc).__name__}")
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        _fail("INVALID_ARCHIVE_RECEIPT", "receipt ledger schema is invalid")
    return payload


def _append_receipt(path: Path, record: dict) -> None:
    payload = _load_receipt(path)
    identifiers = {item.get("record_id") for item in payload["records"] if isinstance(item, dict)}
    if record["record_id"] not in identifiers:
        payload["records"].append(record)
        _write_json_atomic(path, payload)


def _append_global_ledger(root: Path, record: dict) -> None:
    path = root / "docs/HANDOFF/RECEIPT_LEDGER.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    parsed = [json.loads(line) for line in existing if line.strip()]
    if any(item.get("record_id") == record["record_id"] for item in parsed if isinstance(item, dict)):
        return
    parsed.append(record)
    text = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in parsed)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.partial")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _receipt_record_by_id(path: Path, record_id: str) -> dict | None:
    payload = _load_receipt(path)
    for item in payload["records"]:
        if isinstance(item, dict) and item.get("record_id") == record_id:
            return item
    return None


def _archive_queue_item_locked(
    root: Path,
    name: str,
    expected_sha256: str,
    archive_id: str,
    acknowledged: bool,
    acknowledged_filenames: list[str] | None = None,
) -> dict:
    root = _root(root)
    if not acknowledged:
        _fail("ACKNOWLEDGEMENT_REQUIRED", "exact-name and SHA-256 acknowledgement is required")
    if not (_delivery_name(name) or BATCH_RE.fullmatch(name)):
        _fail("INVALID_QUEUE_FILENAME", f"invalid queue filename: {name}")
    if not HEX_RE.fullmatch(expected_sha256):
        _fail("INVALID_SHA256", "SHA-256 must be 64 lowercase hexadecimal characters")
    if not ARCHIVE_ID_RE.fullmatch(archive_id):
        _fail("INVALID_ARCHIVE_ID", "archive ID must be 4..64 safe ASCII characters")

    queue = _ensure_dir(root, "review/00_TO_UPLOAD")
    archive_dir = _ensure_dir(root, f"review/90_UPLOADED_ARCHIVE/{archive_id}")
    source = queue / name
    destination = archive_dir / name
    receipt_path = archive_dir / "ARCHIVE_RECEIPT.json"

    if source.exists() and destination.exists():
        _fail("ARCHIVE_DESTINATION_COLLISION", "source and archive destination both exist")
    if not source.exists() and destination.exists():
        if sha256(destination) != expected_sha256:
            _fail("ARCHIVED_HASH_MISMATCH", "archived copy has a different SHA-256")
        validate_queue_artifact(
            destination,
            require_manifest=False,
            require_sensitive_clean=False,
            require_no_nested_zip=False,
            allow_legacy_status_only_exact_ack=True,
        )
        record_id = f"{archive_id}:{source.name}:{expected_sha256}"
        existing = _receipt_record_by_id(receipt_path, record_id)
        if existing is not None:
            return {"status": "ALREADY_ARCHIVED", "record": existing}
        record = _receipt_record(
            root, source, destination, expected_sha256, archive_id, True, acknowledged_filenames
        )
        _append_receipt(receipt_path, record)
        _append_global_ledger(root, record)
        return {"status": "RECOVERED_AFTER_COMPLETED_MOVE", "record": record}
    if not source.exists():
        _fail("QUEUE_ITEM_MISSING", f"queue item does not exist: {name}")
    if source.is_symlink() or not source.is_file():
        _fail("QUEUE_ITEM_NOT_REGULAR", "queue item must be a regular file")
    validate_queue_artifact(
        source,
        require_manifest=False,
        require_sensitive_clean=False,
        require_no_nested_zip=False,
        allow_legacy_status_only_exact_ack=True,
    )
    actual = sha256(source)
    if actual != expected_sha256:
        _fail("ACK_SHA256_MISMATCH", "acknowledged SHA-256 does not match queue copy")
    if destination.exists():
        _fail("ARCHIVE_DESTINATION_COLLISION", "archive destination already exists")

    os.replace(source, destination)
    if sha256(destination) != expected_sha256:
        _fail("POST_MOVE_SHA256_MISMATCH", "archived copy failed post-move SHA-256 readback")
    record = _receipt_record(
        root, source, destination, expected_sha256, archive_id, False, acknowledged_filenames
    )
    _append_receipt(receipt_path, record)
    _append_global_ledger(root, record)
    return {"status": "ARCHIVED", "record": record}


def archive_queue_item(
    root: Path,
    name: str,
    expected_sha256: str,
    archive_id: str,
    acknowledged: bool,
    acknowledged_filenames: list[str] | None = None,
) -> dict:
    root = _root(root)
    locks = _ensure_dir(root, "review/E02/locks")
    with _QueueLock(locks / "flat_queue.lock") as lock:
        result = _archive_queue_item_locked(
            root,
            name,
            expected_sha256,
            archive_id,
            acknowledged,
            acknowledged_filenames,
        )
        result["stale_lock_recovered"] = lock.recovered_stale_lock
        return result


def _ack_records(root: Path, ack_file: Path) -> list[dict]:
    candidate = ack_file if ack_file.is_absolute() else root / ack_file
    path = _inside(root, candidate, must_exist=True)
    if path.is_symlink() or not path.is_file() or path.suffix.casefold() != ".json":
        _fail("INVALID_ACK_FILE", "ACK input must be a regular JSON file inside the project root")
    if path.stat().st_size > MAX_ACK_FILE_BYTES:
        _fail("ACK_FILE_TOO_LARGE", "ACK input exceeds 1 MiB")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail("INVALID_ACK_FILE", f"cannot decode ACK input: {type(exc).__name__}")
    if not isinstance(payload, dict) or payload.get("schema") != "CDH-EXACT-ACK-1":
        _fail("INVALID_ACK_SCHEMA", "ACK input schema must be CDH-EXACT-ACK-1")
    records = payload.get("acks")
    if not isinstance(records, list) or not records or len(records) > 100:
        _fail("INVALID_ACK_SET", "ACK input requires 1..100 records")
    parsed: list[dict] = []
    keys: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            _fail("INVALID_ACK_RECORD", f"ACK record {index} must be an object")
        name = record.get("filename")
        digest = record.get("sha256")
        aliases = record.get("central_ack_filenames", [name])
        if not isinstance(name, str) or not (_delivery_name(name) or BATCH_RE.fullmatch(name)):
            _fail("INVALID_ACK_RECORD", f"ACK record {index} has an invalid filename")
        if not isinstance(digest, str) or not HEX_RE.fullmatch(digest):
            _fail("INVALID_ACK_RECORD", f"ACK record {index} has an invalid SHA-256")
        if not isinstance(aliases, list) or not aliases or not all(
            isinstance(alias, str) and alias for alias in aliases
        ):
            _fail("INVALID_ACK_RECORD", f"ACK record {index} has invalid central aliases")
        key = unicodedata.normalize("NFC", name).casefold()
        if key in keys:
            _fail("ACK_FILENAME_CASE_COLLISION", f"duplicate Windows ACK filename: {name}")
        keys.add(key)
        parsed.append(
            {
                "filename": name,
                "sha256": digest,
                "central_ack_filenames": sorted(set(aliases)),
            }
        )
    return parsed


def archive_ack_file(
    root: Path,
    ack_file: Path,
    archive_id: str,
    acknowledged: bool,
) -> dict:
    root = _root(root)
    if not acknowledged:
        _fail("ACKNOWLEDGEMENT_REQUIRED", "batch archive requires explicit central acknowledgement")
    if not ARCHIVE_ID_RE.fullmatch(archive_id):
        _fail("INVALID_ARCHIVE_ID", "archive ID must be 4..64 safe ASCII characters")
    records = _ack_records(root, ack_file)
    locks = _ensure_dir(root, "review/E02/locks")
    results: list[dict] = []
    with _QueueLock(locks / "flat_queue.lock") as lock:
        for record in records:
            try:
                outcome = _archive_queue_item_locked(
                    root,
                    record["filename"],
                    record["sha256"],
                    archive_id,
                    True,
                    record["central_ack_filenames"],
                )
                results.append(
                    {
                        "filename": record["filename"],
                        "sha256": record["sha256"],
                        "status": outcome["status"],
                    }
                )
            except HandoffError as exc:
                results.append(
                    {
                        "filename": record["filename"],
                        "sha256": record["sha256"],
                        "status": "FAILED",
                        "error": exc.code,
                        "detail": exc.detail,
                    }
                )
    counts = {
        status: sum(1 for item in results if item["status"] == status)
        for status in (
            "ARCHIVED",
            "ALREADY_ARCHIVED",
            "RECOVERED_AFTER_COMPLETED_MOVE",
            "FAILED",
        )
    }
    return {
        "schema": "CDH-ACK-IMPORT-RESULT-1",
        "archive_id": archive_id,
        "ack_count": len(records),
        "archived_count": counts["ARCHIVED"],
        "already_archived_count": counts["ALREADY_ARCHIVED"],
        "recovered_count": counts["RECOVERED_AFTER_COMPLETED_MOVE"],
        "failure_count": counts["FAILED"],
        "stale_lock_recovered": lock.recovered_stale_lock,
        "pending_count": len(_queue_files(root)),
        "results": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    enqueue = sub.add_parser("enqueue", help="copy named immutable releases into the flat queue")
    enqueue.add_argument("--files", nargs="+", required=True)
    sub.add_parser("list", help="validate and list all pending flat queue ZIPs")
    archive = sub.add_parser("archive", help="archive one exact-name, exact-hash acknowledged queue copy")
    archive.add_argument("--name", required=True)
    archive.add_argument("--sha256", required=True)
    archive.add_argument("--archive-id", required=True)
    archive.add_argument("--acknowledged", action="store_true")
    archive.add_argument("--ack-filename", action="append", default=[])
    archive_acks = sub.add_parser(
        "archive-acks", help="import an exact-ACK JSON file and archive only matching queue copies"
    )
    archive_acks.add_argument("--ack-file", required=True, type=Path)
    archive_acks.add_argument("--archive-id", required=True)
    archive_acks.add_argument("--acknowledged", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action == "enqueue":
        result = enqueue_releases(args.project_root, args.files)
    elif args.action == "list":
        result = list_queue(args.project_root)
    elif args.action == "archive":
        result = archive_queue_item(
            args.project_root,
            args.name,
            args.sha256,
            args.archive_id,
            args.acknowledged,
            args.ack_filename or [args.name],
        )
    else:
        result = archive_ack_file(
            args.project_root,
            args.ack_file,
            args.archive_id,
            args.acknowledged,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 2 if result.get("failure_count", 0) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HandoffError as exc:
        print(json.dumps({"error": exc.code, "detail": exc.detail}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(json.dumps({"error": "UNEXPECTED_FAILURE", "detail": type(exc).__name__}, sort_keys=True), file=sys.stderr)
        sys.exit(3)
